from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from openai import OpenAI

from morning_brief.config import Settings
from morning_brief.logging_utils import log_structured
from morning_brief.observability import PipelineObserver
from morning_brief.openai_utils import usage_snapshot
from morning_brief.prompting import build_prompt_cache_key, render_public_news_analysis_prompts

logger = logging.getLogger(__name__)

_PUBLIC_NEWS_ANALYSIS_BATCH_ITEMS = 4
_PUBLIC_NEWS_ANALYSIS_BATCH_CHARS = 2200
_PUBLIC_NEWS_ANALYSIS_MAX_SUMMARY_LEN = 240
_PUBLIC_NEWS_ANALYSIS_MAX_INTERPRETATION_LEN = 120
_PLACEHOLDER_TEXTS = frozenset(
    {
        "",
        "없음",
        "없음.",
        "없음,",
        "해당없음",
        "해당 없음",
        "해당없음.",
        "해당 없음.",
        "해당없음,",
        "해당 없음,",
        "n/a",
        "null",
    }
)


@dataclass(frozen=True)
class PublicNewsAnalysisInput:
    id: str
    title: str
    url: str
    source: str
    topic: str | None
    published_at: str | None
    summary: str | None
    why_it_matters: str | None
    citations: list[str]


@dataclass(frozen=True)
class PublicNewsAnalysisOutput:
    id: str
    summary_ko: str
    interpretation_ko: str


@dataclass(frozen=True)
class PublicNewsAnalysisAudit:
    candidate_count: int
    requested_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    status: str


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _contains_korean(value: str) -> bool:
    return any("가" <= ch <= "힣" for ch in value)


def _is_meaningless_text(value: str) -> bool:
    normalized = _normalize_text(value).lower()
    return normalized in _PLACEHOLDER_TEXTS


def _is_valid_generated_text(value: str, *, max_len: int) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    if len(normalized) > max_len:
        return False
    if _is_meaningless_text(normalized):
        return False
    return _contains_korean(normalized)


def _analysis_input_from_item(item: dict[str, Any], index: int) -> PublicNewsAnalysisInput | None:
    title = _normalize_text(str(item.get("title", "")).strip())
    url = _normalize_text(str(item.get("url", "")).strip())
    summary = _normalize_text(str(item.get("summary", "")).strip())
    why_it_matters = _normalize_text(str(item.get("why_it_matters", "")).strip())
    if not title or not url:
        return None
    if not summary and not why_it_matters:
        return None
    return PublicNewsAnalysisInput(
        id=f"news-{index}",
        title=title,
        url=url,
        source=_normalize_text(str(item.get("source", "")).strip()),
        topic=_normalize_text(str(item.get("topic", "")).strip()) or None,
        published_at=_normalize_text(str(item.get("published_at", "")).strip()) or None,
        summary=summary or None,
        why_it_matters=why_it_matters or None,
        citations=[
            _normalize_text(str(citation).strip())
            for citation in item.get("citations", [])
            if _normalize_text(str(citation).strip())
        ]
        if isinstance(item.get("citations", []), list)
        else [],
    )


def _analysis_batches(
    items: list[PublicNewsAnalysisInput],
) -> list[list[PublicNewsAnalysisInput]]:
    batches: list[list[PublicNewsAnalysisInput]] = []
    current: list[PublicNewsAnalysisInput] = []
    current_chars = 0

    for item in items:
        item_json = json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":"))
        item_chars = len(item_json)
        if current and (
            len(current) >= _PUBLIC_NEWS_ANALYSIS_BATCH_ITEMS
            or current_chars + item_chars > _PUBLIC_NEWS_ANALYSIS_BATCH_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars

    if current:
        batches.append(current)
    return batches


def _status_for_counts(*, requested_count: int, success_count: int) -> str:
    if requested_count == 0:
        return "skipped"
    if success_count == requested_count:
        return "ok"
    if success_count == 0:
        return "failed"
    return "partial"


def _log_event(
    *,
    observer: PipelineObserver | None,
    event: str,
    message: str,
    level: int = logging.INFO,
    **attributes: Any,
) -> None:
    if observer is not None:
        observer.log_event(event, level=level, message=message, **attributes)
        return
    log_structured(logger, event=event, message=message, level=level, **attributes)


def enrich_public_news_packet(
    *,
    items: list[dict[str, Any]],
    settings: Settings,
    observer: PipelineObserver | None = None,
) -> tuple[list[dict[str, Any]], PublicNewsAnalysisAudit]:
    candidate_count = len(items)
    enriched_items = [dict(item) for item in items]

    if not items:
        return enriched_items, PublicNewsAnalysisAudit(
            candidate_count=0,
            requested_count=0,
            success_count=0,
            skipped_count=0,
            failed_count=0,
            status="skipped",
        )

    if not settings.openai_public_news_analysis_enabled:
        _log_event(
            observer=observer,
            event="public_news_analysis_skipped",
            message="공개 뉴스 해설 생성이 비활성화되어 기존 기사 packet을 유지할게요.",
            reason="disabled",
            candidate_count=candidate_count,
        )
        return enriched_items, PublicNewsAnalysisAudit(
            candidate_count=candidate_count,
            requested_count=0,
            success_count=0,
            skipped_count=candidate_count,
            failed_count=0,
            status="skipped",
        )

    if not settings.openai_api_key:
        _log_event(
            observer=observer,
            event="public_news_analysis_skipped",
            message="OpenAI API 키가 없어 공개 뉴스 해설 생성을 건너뛸게요.",
            level=logging.WARNING,
            reason="missing_api_key",
            candidate_count=candidate_count,
        )
        return enriched_items, PublicNewsAnalysisAudit(
            candidate_count=candidate_count,
            requested_count=0,
            success_count=0,
            skipped_count=candidate_count,
            failed_count=0,
            status="skipped",
        )

    analysis_inputs: list[PublicNewsAnalysisInput] = []
    item_indexes: dict[str, int] = {}
    skipped_count = 0
    for index, item in enumerate(items, start=1):
        analysis_input = _analysis_input_from_item(item, index)
        if analysis_input is None:
            skipped_count += 1
            continue
        analysis_inputs.append(analysis_input)
        item_indexes[analysis_input.id] = index - 1

    requested_count = len(analysis_inputs)
    if requested_count == 0:
        return enriched_items, PublicNewsAnalysisAudit(
            candidate_count=candidate_count,
            requested_count=0,
            success_count=0,
            skipped_count=skipped_count,
            failed_count=0,
            status="skipped",
        )

    client = OpenAI(api_key=settings.openai_api_key)
    merged_count = 0
    outputs_by_id: dict[str, PublicNewsAnalysisOutput] = {}

    for batch in _analysis_batches(analysis_inputs):
        items_json = json.dumps(
            {"items": [asdict(item) for item in batch]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        instructions, user_prompt = render_public_news_analysis_prompts(
            items_json=items_json,
            settings=settings,
        )
        prompt_cache_key = build_prompt_cache_key(
            settings=settings,
            instructions=instructions,
            model_name=settings.openai_public_news_analysis_model,
        )
        try:
            response = client.responses.create(
                model=settings.openai_public_news_analysis_model,
                instructions=instructions,
                input=user_prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "public_news_analysis_batch",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "summary_ko": {"type": "string"},
                                            "interpretation_ko": {"type": "string"},
                                        },
                                        "required": ["id", "summary_ko", "interpretation_ko"],
                                        "additionalProperties": False,
                                    },
                                }
                            },
                            "required": ["items"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    }
                },
                reasoning={"effort": "minimal"},
                max_output_tokens=min(3200, max(900, 320 * len(batch))),
                prompt_cache_key=prompt_cache_key,
            )
        except Exception as exc:
            _log_event(
                observer=observer,
                event="public_news_analysis_failed",
                message="공개 뉴스 해설 생성 중 오류가 있어 원본 기사 packet을 유지할게요.",
                level=logging.WARNING,
                reason=str(exc),
                error_type=type(exc).__name__,
                batch_size=len(batch),
            )
            continue

        if observer is not None:
            observer.record_provider_usage(
                "openai",
                phase="public_news_analysis",
                requests=1,
                **usage_snapshot(response),
            )

        try:
            payload = json.loads((response.output_text or "").strip())
        except json.JSONDecodeError:
            _log_event(
                observer=observer,
                event="public_news_analysis_failed",
                message="공개 뉴스 해설 생성 응답을 JSON으로 읽지 못해 원본 기사 packet을 유지할게요.",
                level=logging.WARNING,
                reason="invalid_json",
                batch_size=len(batch),
                preview=(response.output_text or "")[:200],
            )
            continue

        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            _log_event(
                observer=observer,
                event="public_news_analysis_failed",
                message="공개 뉴스 해설 생성 응답 스키마가 맞지 않아 원본 기사 packet을 유지할게요.",
                level=logging.WARNING,
                reason="invalid_schema",
                batch_size=len(batch),
            )
            continue

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item_id = _normalize_text(str(raw_item.get("id", "")).strip())
            summary_ko = _normalize_text(str(raw_item.get("summary_ko", "")).strip())
            interpretation_ko = _normalize_text(str(raw_item.get("interpretation_ko", "")).strip())
            if item_id not in item_indexes:
                continue
            if not _is_valid_generated_text(
                summary_ko,
                max_len=_PUBLIC_NEWS_ANALYSIS_MAX_SUMMARY_LEN,
            ):
                continue
            if not _is_valid_generated_text(
                interpretation_ko,
                max_len=_PUBLIC_NEWS_ANALYSIS_MAX_INTERPRETATION_LEN,
            ):
                continue
            outputs_by_id[item_id] = PublicNewsAnalysisOutput(
                id=item_id,
                summary_ko=summary_ko,
                interpretation_ko=interpretation_ko,
            )

    for item_id, output in outputs_by_id.items():
        enriched_items[item_indexes[item_id]]["summary_ko"] = output.summary_ko
        enriched_items[item_indexes[item_id]]["interpretation_ko"] = output.interpretation_ko
        merged_count += 1

    failed_count = max(requested_count - merged_count, 0)
    status = _status_for_counts(requested_count=requested_count, success_count=merged_count)
    _log_event(
        observer=observer,
        event="public_news_analysis_complete",
        message="공개 뉴스 해설 생성 결과를 정리했어요.",
        candidate_count=candidate_count,
        requested_count=requested_count,
        success_count=merged_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        status=status,
    )

    return enriched_items, PublicNewsAnalysisAudit(
        candidate_count=candidate_count,
        requested_count=requested_count,
        success_count=merged_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        status=status,
    )
