from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import x_search

from morning_brief.data.official_signal_registry import grouped_verified_x_entities
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    open_circuit,
    parse_retry_after_seconds,
    policy_for,
    record_skip,
)
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)
GROK_PROVIDER = "grok"

GROUP_TOPIC_MAP = {
    "macro_regulator": "macro",
    "ai_bigtech_primary": "ai_bigtech",
    "btc_etf_primary": "bitcoin",
}

GROUP_MATERIALITY_RULES = {
    "macro_regulator": "연준, 재무부, SEC의 정책, 규제, 공식 일정, 시장에 직접 영향을 줄 수 있는 공지",
    "ai_bigtech_primary": "AI 투자, 제품 발표, 가이던스, 대형 계약, 설비 투자, 규제 대응, 공식 해명",
    "btc_etf_primary": "ETF 자금 흐름, 보유량, 수수료 변경, 규제 이슈, 공식 운용사 코멘트",
}

GROUP_IMPACT_LINES = {
    "macro": "공식 기관 시그널이라 거시 해석의 우선 근거로 볼 수 있어요.",
    "ai_bigtech": "기업이 직접 낸 메시지라 빅테크 뉴스 해석의 우선 근거로 볼 수 있어요.",
    "bitcoin": "ETF 운용사나 관련 주체의 직접 발신이라 비트코인 수급 해석에 바로 연결할 수 있어요.",
}

XAI_RESPONSE_MODEL = "json_object"


def _build_client(api_key: str) -> Client:
    return Client(api_key=api_key)


def _normalize_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_citations(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
            elif isinstance(item, dict):
                candidate = str(item.get("url", "")).strip()
            else:
                candidate = str(getattr(item, "url", "") or item).strip()
            if candidate.startswith("http") and candidate not in urls:
                urls.append(candidate)
    return urls


def _status_code_from_exception(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status

    return None


def _retry_after_seconds_from_exception(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        return parse_retry_after_seconds(headers.get("Retry-After") or headers.get("retry-after"))
    return None


def _is_retryable_transport_error(exc: Exception) -> bool:
    message = f"{exc.__class__.__name__} {exc}".lower()
    keywords = ("timeout", "timed out", "connection", "temporarily unavailable", "transport")
    return any(keyword in message for keyword in keywords)


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    status_code = _status_code_from_exception(exc)
    retry_after_seconds = _retry_after_seconds_from_exception(exc)
    if status_code == 429:
        message = f"Grok X Search 호출 한도에 걸렸어요: {exc}"
        open_circuit(GROK_PROVIDER, message)
        return HttpFetchError(
            message,
            provider=GROK_PROVIDER,
            retryable=False,
            rate_limited=True,
            retry_after_seconds=retry_after_seconds,
        )

    retryable = status_code in policy_for(GROK_PROVIDER).retryable_statuses
    retryable = retryable or _is_retryable_transport_error(exc)
    return HttpFetchError(
        f"Grok X Search를 호출하지 못했어요: {exc}",
        provider=GROK_PROVIDER,
        retryable=retryable,
        rate_limited=status_code == 429,
        retry_after_seconds=retry_after_seconds,
    )


def _build_prompt(
    *, group: str, lookback_hours: int, max_items: int, entities: list[dict[str, Any]]
) -> str:
    entity_lines = "\n".join(
        f"- {entity.get('entity_name', '')} ({entity.get('ticker', '')}) -> @{str(entity.get('x_handle', '')).strip().lstrip('@')}"
        for entity in entities
    )
    materiality = GROUP_MATERIALITY_RULES.get(group, "시장에 의미 있는 공식 업데이트")
    topic = GROUP_TOPIC_MAP.get(group, "us_equity")

    return (
        "You are reviewing verified official X posts from a constrained allowlist.\n"
        "Only consider materially important posts within the requested time window.\n"
        f"Target topic: {topic}.\n"
        f"Material updates to keep: {materiality}.\n"
        f"Maximum items: {max_items}.\n"
        f"Lookback window: last {lookback_hours} hours.\n"
        "Ignore reposts, routine marketing copy, short greetings, or low-signal brand content.\n"
        "Return strict JSON only with this shape:\n"
        '{"items":[{"entity_id":"","headline":"","summary":"","why_it_matters":"","posted_at":"","source_handle":"","citations":[""]}]}\n'
        'If nothing material is found, return {"items": []}.\n'
        "Verified entities in this group:\n"
        f"{entity_lines}"
    )


def _parse_response_items(payload_text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HttpFetchError("Grok 공식 X 응답을 JSON으로 읽지 못했어요.") from exc

    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise HttpFetchError("Grok 공식 X 응답 형식이 예상과 달라요.")
    return [item for item in items if isinstance(item, dict)]


def _search_group(
    *,
    api_key: str,
    model: str,
    group: str,
    entities: list[dict[str, Any]],
    lookback_hours: int,
    max_items: int,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    unavailable_reason = disabled_reason(GROK_PROVIDER)
    if unavailable_reason:
        record_skip(GROK_PROVIDER)
        raise HttpFetchError(f"Grok은 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}")

    handles = [
        str(entity.get("x_handle", "")).strip().lstrip("@")
        for entity in entities
        if entity.get("x_handle")
    ]
    if not handles:
        return []

    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(hours=lookback_hours)

    def perform_group_search() -> tuple[list[dict[str, Any]], list[str]]:
        client = _build_client(api_key)
        try:
            chat = client.chat.create(
                model=model,
                tools=[x_search(allowed_x_handles=handles, from_date=from_date, to_date=to_date)],
                tool_choice="required",
                response_format=XAI_RESPONSE_MODEL,
                include=["inline_citations"],
            )
            chat.append(
                user(
                    _build_prompt(
                        group=group,
                        lookback_hours=lookback_hours,
                        max_items=max_items,
                        entities=entities,
                    )
                )
            )
            response = chat.sample()
        except Exception as exc:
            raise _to_http_fetch_error(exc) from exc

        payload_items = _parse_response_items(_normalize_text(getattr(response, "content", "")))
        fallback_citations = _normalize_citations(getattr(response, "citations", []))
        return payload_items, fallback_citations

    payload_items, fallback_citations = execute_with_provider_retry(
        provider=GROK_PROVIDER,
        operation=perform_group_search,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=lambda exc, attempt, max_attempts, delay: logger.warning(
            "Grok X Search를 다시 시도하는 중이에요 (%s/%s). group=%s | %s | sleep=%.2fs",
            attempt,
            max_attempts,
            group,
            exc,
            delay,
        ),
        retry_after_seconds_for_error=lambda exc: exc.retry_after_seconds
        if isinstance(exc, HttpFetchError)
        else None,
    )
    if observer is not None:
        observer.record_provider_usage(GROK_PROVIDER, requests=1)

    can_apply_group_fallback = len(payload_items) == 1
    handle_map = {
        str(entity.get("x_handle", "")).strip().lstrip("@").lower(): entity
        for entity in entities
        if entity.get("x_handle")
    }

    topic = GROUP_TOPIC_MAP.get(group, "us_equity")
    items: list[NewsItem] = []
    for item in payload_items[:max_items]:
        source_handle = str(item.get("source_handle", "")).strip().lstrip("@")
        entity = handle_map.get(source_handle.lower())
        if entity is None:
            continue

        citations = _normalize_citations(item.get("citations", []))
        if not citations and can_apply_group_fallback:
            citations = fallback_citations
        title = _normalize_text(item.get("headline"))
        summary = _normalize_text(item.get("summary"))
        why_it_matters = _normalize_text(item.get("why_it_matters")) or GROUP_IMPACT_LINES.get(
            topic, "공식 시그널이라 직접적인 확인 근거가 돼요."
        )
        if not title or not summary:
            continue

        items.append(
            NewsItem(
                title=title,
                url=citations[0]
                if citations
                else str(entity.get("newsroom_or_ir_url", "")).strip(),
                source=f"@{source_handle}"
                if source_handle
                else str(entity.get("entity_name", "Official X")).strip(),
                published_at=_normalize_datetime(item.get("posted_at")),
                topic=topic,
                provider="grok_official_x",
                summary=summary,
                why_it_matters=why_it_matters,
                citations=citations,
            )
        )
    return items


def fetch_official_x_signals(
    *,
    api_key: str,
    model: str,
    lookback_hours: int,
    max_items: int,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    if not api_key.strip():
        return []

    grouped = grouped_verified_x_entities()
    if not grouped:
        return []

    collected: list[NewsItem] = []
    for group, entities in grouped.items():
        try:
            collected.extend(
                _search_group(
                    api_key=api_key,
                    model=model,
                    group=group,
                    entities=entities,
                    lookback_hours=lookback_hours,
                    max_items=max_items,
                    observer=observer,
                )
            )
        except HttpFetchError as exc:
            logger.warning("Grok에서 %s 그룹 공식 X를 확인하는 중 문제가 있었어요: %s", group, exc)

    collected.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return collected[:max_items]
