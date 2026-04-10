from __future__ import annotations

import atexit
import contextvars
import json
import logging
import logging.config
import logging.handlers
import os
import queue
import re
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

THIRD_PARTY_LOGGERS = (
    "httpx",
    "openai._base_client",
    "urllib3.connectionpool",
    "perplexity",
    "google.genai",
    "google.auth",
)

LEGACY_EVENT_MAP = {
    "phase_duration": "phase.complete",
    "provider_usage_summary": "provider.usage",
    "pipeline_summary": "run.complete",
    "backfill_skipped": "phase.skip",
    "brief_review_failed": "error.raised",
    "pipeline_error": "error.raised",
    "cache_status": "cache.status",
    "public_brief_published": "publish.complete",
    "pipeline_log_file": "artifact.created",
    "perplexity_audit_file": "artifact.created",
}

SEVERITY_MAP = {
    logging.DEBUG: ("DEBUG", 5),
    logging.INFO: ("INFO", 9),
    logging.WARNING: ("WARN", 13),
    logging.ERROR: ("ERROR", 17),
    logging.CRITICAL: ("FATAL", 21),
}

ATTRIBUTE_STRING_LIMIT = 500
ATTRIBUTE_LIST_LIMIT = 10
ATTRIBUTE_DICT_LIMIT = 20
SUMMARY_ATTR_PRIORITY = (
    "status",
    "duration_ms",
    "total_duration_ms",
    "candidate_count",
    "kept_count",
    "dropped",
    "requests",
    "cost_usd",
    "total_cost_usd",
    "app_events_path",
    "pipeline_run_path",
    "perplexity_audit_path",
    "reason",
)

_RUN_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar("log_run_id", default=None)
_PHASE_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar("log_phase", default=None)
_PROVIDER_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_provider", default=None
)
_ATTEMPT_CTX: contextvars.ContextVar[int | str | None] = contextvars.ContextVar(
    "log_attempt", default=None
)

_STANDARD_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
    "canonical_event",
}
_LOG_QUEUE: queue.Queue[logging.LogRecord] | None = None
_QUEUE_LISTENER: logging.handlers.QueueListener | None = None
_OUTPUT_DIR: Path | None = None
_QUEUE_FALLBACK_ACTIVE = False
_QUEUE_FALLBACK_WARNED = False

_REDACTION_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9]{10,})"),
)
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "token",
    "secret",
    "password",
    "credentials",
    "authorization",
    "bearer",
    "account_id",
)
_PROVIDER_HINTS = {
    "perplexity": "perplexity",
    "grok_official_signals": "grok_official",
    "grok_official": "grok_official",
    "grok_x_keyword": "grok_keyword",
    "grok_keyword": "grok_keyword",
    "grok_web_search": "grok_keyword",
    "gemini": "gemini",
    "fred": "fred",
    "ses": "ses",
    "openai": "openai",
}


def _ensure_queue() -> queue.Queue[logging.LogRecord]:
    global _LOG_QUEUE
    if _LOG_QUEUE is None:
        _LOG_QUEUE = queue.Queue()
    return _LOG_QUEUE


def _level_name() -> str:
    return os.getenv("LOG_LEVEL", "INFO").upper()


def _level_value() -> int:
    return getattr(logging, _level_name(), logging.INFO)


def _severity_for(levelno: int) -> tuple[str, int]:
    return SEVERITY_MAP.get(levelno, ("INFO", 9))


def severity_fields(levelno: int) -> tuple[str, int]:
    return _severity_for(levelno)


def _iso_utc_from_created(created: float) -> str:
    return datetime.fromtimestamp(created, tz=timezone.utc).isoformat()


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("***", redacted)
    if len(redacted) > ATTRIBUTE_STRING_LIMIT:
        omitted = len(redacted) - ATTRIBUTE_STRING_LIMIT
        redacted = f"{redacted[:ATTRIBUTE_STRING_LIMIT]}… [truncated {omitted} chars]"
    return redacted


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if key and _looks_sensitive_key(key):
        return "***"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return _redact_string(str(value))
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        items = list(value.items())
        sanitized: dict[str, Any] = {}
        for idx, (child_key, child_value) in enumerate(items):
            if idx >= ATTRIBUTE_DICT_LIMIT:
                sanitized["truncated_count"] = len(items) - ATTRIBUTE_DICT_LIMIT
                break
            sanitized[str(child_key)] = _sanitize_value(child_value, key=str(child_key))
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized_items = [_sanitize_value(item) for item in items[:ATTRIBUTE_LIST_LIMIT]]
        if len(items) > ATTRIBUTE_LIST_LIMIT:
            sanitized_items.append({"truncated_count": len(items) - ATTRIBUTE_LIST_LIMIT})
        return sanitized_items
    return _redact_string(repr(value))


def _infer_provider(component: str) -> str | None:
    lowered = component.lower()
    for marker, provider in _PROVIDER_HINTS.items():
        if marker in lowered:
            return provider
    return None


def _canonical_event_name(raw_event: str | None, component: str, levelno: int) -> str:
    if raw_event:
        normalized = LEGACY_EVENT_MAP.get(raw_event, raw_event)
        return normalized
    if not component.startswith("morning_brief"):
        return "third_party.log"
    if levelno >= logging.ERROR:
        return "error.raised"
    if levelno >= logging.WARNING:
        return "log.warning"
    if levelno == logging.DEBUG:
        return "log.debug"
    return "log.info"


def canonical_event_name(raw_event: str | None, component: str, levelno: int) -> str:
    return _canonical_event_name(raw_event, component, levelno)


def _extract_attributes(record: logging.LogRecord) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    record_attributes = getattr(record, "attributes", None)
    if isinstance(record_attributes, dict):
        attributes.update(record_attributes)
    for key, value in record.__dict__.items():
        if key in _STANDARD_RECORD_ATTRS:
            continue
        if key in {"run_id", "phase", "provider", "attempt", "component", "event"}:
            continue
        attributes.setdefault(key, value)
    if record.exc_info:
        error_type = ""
        error_message = ""
        if record.exc_info[0] is not None:
            error_type = record.exc_info[0].__name__
        if record.exc_info[1] is not None:
            error_message = str(record.exc_info[1])
        attributes.setdefault("error_type", error_type)
        attributes.setdefault("reason", error_message)
        attributes.setdefault("stacktrace", "".join(traceback.format_exception(*record.exc_info)))
    return _sanitize_value(attributes) or {}


def build_canonical_event(record: logging.LogRecord) -> dict[str, Any]:
    severity_text, severity_number = _severity_for(record.levelno)
    raw_event = getattr(record, "event", None)
    component = getattr(record, "component", record.name)
    event = _canonical_event_name(raw_event, component, record.levelno)
    attributes = _extract_attributes(record)
    if raw_event and raw_event != event:
        attributes.setdefault("legacy_event", raw_event)

    event_dict: dict[str, Any] = {
        "ts": _iso_utc_from_created(record.created),
        "level": record.levelname,
        "severity_text": severity_text,
        "severity_number": severity_number,
        "event": event,
        "message": _sanitize_value(record.getMessage()),
        "run_id": getattr(record, "run_id", None),
        "component": component,
        "attributes": attributes,
    }
    for field in ("phase", "provider", "attempt"):
        value = getattr(record, field, None)
        if value is not None:
            event_dict[field] = value
    return event_dict


def get_log_context() -> dict[str, Any]:
    return {
        "run_id": _RUN_ID_CTX.get(),
        "phase": _PHASE_CTX.get(),
        "provider": _PROVIDER_CTX.get(),
        "attempt": _ATTEMPT_CTX.get(),
    }


def set_run_context(run_id: str | None) -> None:
    _RUN_ID_CTX.set(run_id)


@contextmanager
def bind_phase(phase: str | None) -> Iterator[None]:
    token = _PHASE_CTX.set(phase)
    try:
        yield
    finally:
        _PHASE_CTX.reset(token)


@contextmanager
def bind_provider(provider: str | None) -> Iterator[None]:
    token = _PROVIDER_CTX.set(provider)
    try:
        yield
    finally:
        _PROVIDER_CTX.reset(token)


@contextmanager
def bind_attempt(attempt: int | str | None) -> Iterator[None]:
    token = _ATTEMPT_CTX.set(attempt)
    try:
        yield
    finally:
        _ATTEMPT_CTX.reset(token)


def get_app_events_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / "observability" / f"app-events-{run_id}.jsonl"


class ContextInjectionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.component = getattr(record, "component", record.name)
        record.run_id = getattr(record, "run_id", None) or _RUN_ID_CTX.get()
        record.phase = getattr(record, "phase", None) or _PHASE_CTX.get()
        record.provider = (
            getattr(record, "provider", None) or _PROVIDER_CTX.get() or _infer_provider(record.name)
        )
        record.attempt = getattr(record, "attempt", None) or _ATTEMPT_CTX.get()
        return True


class CanonicalEventFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.canonical_event = build_canonical_event(record)
        return True


class HumanConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_dict = getattr(record, "canonical_event", None) or build_canonical_event(record)
        created_at = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        parts = [created_at, event_dict["level"]]
        run_id = event_dict.get("run_id")
        if run_id:
            parts.append(f"run={run_id}")
        phase = event_dict.get("phase")
        if phase:
            parts.append(f"phase={phase}")
        provider = event_dict.get("provider")
        if provider:
            parts.append(f"provider={provider}")
        parts.append(f"event={event_dict['event']}")

        attributes = event_dict.get("attributes", {})
        if isinstance(attributes, dict):
            for key in SUMMARY_ATTR_PRIORITY:
                if key in attributes:
                    parts.append(f"{key}={attributes[key]}")
        message = str(event_dict.get("message") or "").strip()
        if message:
            parts.append(message)
        return " | ".join(parts)


class JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_dict = getattr(record, "canonical_event", None) or build_canonical_event(record)
        return json.dumps(event_dict, ensure_ascii=False, sort_keys=True)


class AppJsonlFileHandler(logging.Handler):
    def __init__(self, output_dir: Path) -> None:
        super().__init__(level=logging.DEBUG)
        self.output_dir = output_dir
        self._files: dict[Path, Any] = {}

    def emit(self, record: logging.LogRecord) -> None:
        event_dict = getattr(record, "canonical_event", None) or build_canonical_event(record)
        run_id = event_dict.get("run_id")
        if not run_id:
            return
        path = get_app_events_path(self.output_dir, str(run_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._files.get(path)
        if handle is None:
            handle = path.open("a", encoding="utf-8")
            self._files[path] = handle
        payload = self.format(record)
        handle.write(f"{payload}\n")
        handle.flush()

    def close(self) -> None:
        for handle in self._files.values():
            handle.close()
        self._files.clear()
        super().close()


def _build_queue_handler() -> logging.Handler:
    return logging.handlers.QueueHandler(_ensure_queue())


def _build_console_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(_level_value())
    handler.setFormatter(HumanConsoleFormatter())
    return handler


def _build_jsonl_handler() -> logging.Handler:
    output_dir = _OUTPUT_DIR or Path("outputs").resolve()
    handler = AppJsonlFileHandler(output_dir=output_dir)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonlFormatter())
    return handler


def build_logging_config() -> dict[str, Any]:
    level_name = _level_name()
    logger_overrides = {
        logger_name: {
            "level": "WARNING",
            "handlers": [],
            "propagate": True,
        }
        for logger_name in THIRD_PARTY_LOGGERS
    }
    logger_overrides["morning_brief"] = {
        "level": level_name,
        "handlers": [],
        "propagate": True,
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {"()": "morning_brief.logging_utils.ContextInjectionFilter"},
            "canonical": {"()": "morning_brief.logging_utils.CanonicalEventFilter"},
        },
        "handlers": {
            "queue": {
                "()": "morning_brief.logging_utils._build_queue_handler",
                "filters": ["context", "canonical"],
            }
        },
        "root": {
            "level": level_name,
            "handlers": ["queue"],
        },
        "loggers": logger_overrides,
    }


def _start_queue_listener() -> None:
    global _QUEUE_LISTENER, _QUEUE_FALLBACK_ACTIVE, _QUEUE_FALLBACK_WARNED
    if _QUEUE_LISTENER is not None:
        _QUEUE_LISTENER.stop()
        _QUEUE_LISTENER = None

    try:
        _QUEUE_LISTENER = logging.handlers.QueueListener(
            _ensure_queue(),
            _build_console_handler(),
            _build_jsonl_handler(),
            respect_handler_level=True,
        )
        _QUEUE_LISTENER.start()
        _QUEUE_FALLBACK_ACTIVE = False
        return
    except Exception:
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        fallback_handler = _build_console_handler()
        fallback_handler.addFilter(ContextInjectionFilter())
        fallback_handler.addFilter(CanonicalEventFilter())
        root_logger.addHandler(fallback_handler)
        root_logger.setLevel(_level_value())
        _QUEUE_FALLBACK_ACTIVE = True
        if not _QUEUE_FALLBACK_WARNED:
            _QUEUE_FALLBACK_WARNED = True
            log_structured(
                logging.getLogger(__name__),
                event="logging.fallback",
                message="Queue listener 초기화에 실패해 console-only fallback으로 계속할게요.",
                level=logging.WARNING,
                queue_fallback=True,
            )


def shutdown_logging() -> None:
    global _QUEUE_LISTENER
    if _QUEUE_LISTENER is not None:
        _QUEUE_LISTENER.stop()
        _QUEUE_LISTENER = None
    logging.shutdown()


def queue_fallback_active() -> bool:
    return _QUEUE_FALLBACK_ACTIVE


def setup_logging(*, output_dir: Path | None = None) -> None:
    global _OUTPUT_DIR
    _OUTPUT_DIR = output_dir.resolve() if output_dir is not None else Path("outputs").resolve()
    logging.config.dictConfig(build_logging_config())
    _start_queue_listener()


def log_structured(
    logger: logging.Logger,
    *,
    event: str,
    message: str,
    level: int = logging.INFO,
    **attributes: Any,
) -> None:
    extra: dict[str, Any] = {"event": event}
    payload = dict(attributes)
    for field in ("run_id", "phase", "provider", "attempt", "component"):
        if field in payload:
            extra[field] = payload.pop(field)
    extra["attributes"] = payload
    logger.log(level, message, extra=extra)


atexit.register(shutdown_logging)
