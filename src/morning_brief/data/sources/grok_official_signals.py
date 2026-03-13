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
    record_failure,
    record_request,
    record_success,
)
from morning_brief.models import NewsItem

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
) -> list[NewsItem]:
    unavailable_reason = disabled_reason(GROK_PROVIDER)
    if unavailable_reason:
        raise HttpFetchError(f"Grok은 이번 실행에서 더 이상 쓰지 않을게요: {unavailable_reason}")

    handles = [
        str(entity.get("x_handle", "")).strip().lstrip("@")
        for entity in entities
        if entity.get("x_handle")
    ]
    if not handles:
        return []

    client = _build_client(api_key)
    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(hours=lookback_hours)

    record_request(GROK_PROVIDER)
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
        record_failure(GROK_PROVIDER)
        raise HttpFetchError(f"Grok X Search를 호출하지 못했어요: {exc}") from exc

    payload_items = _parse_response_items(_normalize_text(getattr(response, "content", "")))
    record_success(GROK_PROVIDER)
    fallback_citations = _normalize_citations(getattr(response, "citations", []))
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
                )
            )
        except HttpFetchError as exc:
            logger.warning("Grok에서 %s 그룹 공식 X를 확인하는 중 문제가 있었어요: %s", group, exc)

    collected.sort(
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return collected[:max_items]
