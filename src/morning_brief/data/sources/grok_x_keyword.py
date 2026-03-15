"""Grok X Search 키워드 기반 시장 반응 수집.

기존 핸들 기반 공식 시그널 검색과 별도로, 금융 전문가/속보 계정 티어를
기반으로 키워드 검색을 수행하여 실시간 시장 반응을 수집한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import x_search

from morning_brief.data.official_signal_registry import grouped_verified_x_handles
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    open_circuit,
    record_skip,
)
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)
GROK_PROVIDER = "grok"

MACRO_EQUITY_GROUP = "macro_and_equity"
CRYPTO_ETF_GROUP = "crypto_and_etf"

MACRO_EQUITY_PROMPT = """Search X for the most significant market-moving posts from the last {lookback_hours} hours.
Focus on:
1. Fed policy signals, interest rate expectations, Treasury yield moves
2. S&P 500, Nasdaq market reaction and trader sentiment
3. Breaking economic data (CPI, PCE, jobs, GDP)
4. Notable analyst calls or market-moving commentary

For each post, extract as JSON array "signals":
- headline: one-line summary
- summary: core market insight in 1-2 sentences
- why_it_matters: market implication for investors
- sentiment: bullish / bearish / neutral
- source_handle: @handle of the poster
- posted_at: ISO8601 timestamp

Return the top {max_items} most impactful posts. Skip routine marketing and non-market posts.
Output format: {{"signals": [...]}}"""

CRYPTO_ETF_PROMPT = """Search X for the most significant Bitcoin and crypto market posts from the last {lookback_hours} hours.
Focus on:
1. Bitcoin ETF flow data (IBIT, BITB, GBTC inflows/outflows)
2. Crypto regulatory news (SEC, CFTC decisions)
3. BTC price action and market sentiment
4. Institutional Bitcoin adoption signals

Return the top {max_items} most impactful posts as JSON array "signals":
- headline: one-line summary
- summary: core insight in 1-2 sentences
- why_it_matters: market implication
- sentiment: bullish / bearish / neutral
- source_handle: @handle
- posted_at: ISO8601 timestamp

Prioritize posts with specific data points. Skip promotional content.
Output format: {{"signals": [...]}}"""

GROUP_PROMPTS = {
    MACRO_EQUITY_GROUP: MACRO_EQUITY_PROMPT,
    CRYPTO_ETF_GROUP: CRYPTO_ETF_PROMPT,
}

GROUP_TOPIC_MAP = {
    MACRO_EQUITY_GROUP: "macro",
    CRYPTO_ETF_GROUP: "bitcoin",
}


@dataclass
class XSignal:
    """X에서 수집한 시장 반응 시그널."""

    headline: str
    summary: str
    why_it_matters: str
    sentiment: str = "neutral"
    source_handle: str = ""
    posted_at: datetime | None = None
    topic: str = ""
    citations: list[str] = field(default_factory=list)


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
    return None


def _normalize_citations(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(c).strip() for c in value if str(c).strip()]
    return []


def _usage_field(container: object, *keys: str) -> object | None:
    current = container
    for key in keys:
        if current is None:
            return None
        current = getattr(current, key, None) if not isinstance(current, dict) else current.get(key)
    return current


def _usage_int(container: object, *keys: str) -> int | None:
    value = _usage_field(container, *keys)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usage_snapshot(response: object) -> dict[str, int | None]:
    usage = _usage_field(response, "usage")
    return {
        "input_tokens": _usage_int(usage, "prompt_tokens") or _usage_int(usage, "input_tokens"),
        "output_tokens": _usage_int(usage, "completion_tokens")
        or _usage_int(usage, "output_tokens"),
        "cached_input_tokens": None,
        "reasoning_tokens": None,
    }


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status_code == 429:
        msg = f"Grok X Search 호출 한도에 걸렸어요: {exc}"
        open_circuit(GROK_PROVIDER, msg)
        return HttpFetchError(msg, provider=GROK_PROVIDER, retryable=False, rate_limited=True)
    retryable = status_code in {500, 502, 503, 504} if status_code else False
    return HttpFetchError(
        f"Grok X Search 호출 실패: {exc}", provider=GROK_PROVIDER, retryable=retryable
    )


def _perform_keyword_search(
    *,
    api_key: str,
    model: str,
    group: str,
    handles: list[str],
    lookback_hours: int,
    max_items: int,
) -> tuple[list[dict[str, Any]], dict[str, int | None]]:
    client = _build_client(api_key)
    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(hours=lookback_hours)

    prompt_template = GROUP_PROMPTS.get(group, MACRO_EQUITY_PROMPT)
    prompt = prompt_template.format(lookback_hours=lookback_hours, max_items=max_items)

    try:
        tool_handles = handles[:10] if handles else None
        tools = (
            [x_search(allowed_x_handles=tool_handles, from_date=from_date, to_date=to_date)]
            if tool_handles
            else [x_search(from_date=from_date, to_date=to_date)]
        )
        chat = client.chat.create(
            model=model,
            tools=tools,
            tool_choice="required",
            response_format="json_object",
            include=["inline_citations"],
        )
        chat.append(user(prompt))
        response = chat.sample()
    except Exception as exc:
        raise _to_http_fetch_error(exc) from exc

    content = getattr(response, "content", "") or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Grok X Search %s 응답 JSON 파싱 실패: %.200s", group, content)
        return [], _usage_snapshot(response)

    signals = data.get("signals", []) if isinstance(data, dict) else []
    return signals, _usage_snapshot(response)


def _signal_to_x_signal(item: dict[str, Any], topic: str) -> XSignal | None:
    headline = str(item.get("headline", "")).strip()
    summary = str(item.get("summary", "")).strip()
    if not headline or not summary:
        return None
    return XSignal(
        headline=headline,
        summary=summary,
        why_it_matters=str(item.get("why_it_matters", "")).strip(),
        sentiment=str(item.get("sentiment", "neutral")).strip().lower(),
        source_handle=str(item.get("source_handle", "")).strip().lstrip("@"),
        posted_at=_normalize_datetime(item.get("posted_at")),
        topic=topic,
        citations=_normalize_citations(item.get("citations", [])),
    )


def _signal_to_news_item(signal: XSignal) -> NewsItem:
    handle = signal.source_handle
    return NewsItem(
        title=signal.headline,
        url=signal.citations[0] if signal.citations else f"https://x.com/{handle}",
        source=f"@{handle}" if handle else "X",
        published_at=signal.posted_at,
        topic=signal.topic,
        provider="grok_x_keyword",
        summary=signal.summary,
        why_it_matters=signal.why_it_matters,
        citations=signal.citations,
    )


def _record_usage(
    observer: PipelineObserver | None, group: str, usage: dict[str, int | None]
) -> None:
    if observer is None:
        return
    failures = 1 if all(v is None for v in usage.values()) else 0
    observer.record_provider_usage(
        GROK_PROVIDER,
        requests=1,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        usage_parse_failures=failures,
    )


def fetch_x_keyword_signals(
    *,
    api_key: str,
    model: str,
    lookback_hours: int = 24,
    max_items: int = 6,
    observer: PipelineObserver | None = None,
) -> tuple[list[XSignal], list[NewsItem]]:
    """키워드 기반 X Search로 시장 반응 시그널을 수집한다."""
    if not api_key.strip():
        logger.warning("Grok API 키가 없어서 X 키워드 검색을 건너뛸게요.")
        return [], []

    all_handles = grouped_verified_x_handles()
    search_groups = [MACRO_EQUITY_GROUP, CRYPTO_ETF_GROUP]

    all_signals: list[XSignal] = []
    all_news_items: list[NewsItem] = []

    for group in search_groups:
        reason = disabled_reason(GROK_PROVIDER)
        if reason:
            record_skip(GROK_PROVIDER)
            logger.warning("Grok은 이번 실행에서 더 이상 쓰지 않을게요: %s", reason)
            break

        handles = all_handles.get(group, [])
        topic = GROUP_TOPIC_MAP.get(group, "us_equity")

        try:
            raw_signals, usage = execute_with_provider_retry(
                provider=GROK_PROVIDER,
                operation=lambda: _perform_keyword_search(
                    api_key=api_key,
                    model=model,
                    group=group,
                    handles=handles,
                    lookback_hours=lookback_hours,
                    max_items=max_items,
                ),
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
            _record_usage(observer, group, usage)

            for item in raw_signals[:max_items]:
                signal = _signal_to_x_signal(item, topic)
                if signal:
                    all_signals.append(signal)
                    all_news_items.append(_signal_to_news_item(signal))

            logger.info("Grok X Search %s: %d건 시그널 수집", group, len(raw_signals))
        except HttpFetchError as exc:
            logger.warning("Grok X Search %s 실패: %s", group, exc)
            if observer:
                observer.log_event("grok_x_keyword_failed", group=group, reason=str(exc))

    return all_signals, all_news_items


def x_signals_to_dict(signals: list[XSignal]) -> list[dict[str, Any]]:
    """XSignal 리스트를 JSON 직렬화 가능한 dict 리스트로 변환한다."""
    return [
        {
            "headline": s.headline,
            "summary": s.summary,
            "why_it_matters": s.why_it_matters,
            "sentiment": s.sentiment,
            "source_handle": s.source_handle,
            "posted_at": s.posted_at.isoformat() if s.posted_at else None,
            "topic": s.topic,
            "citations": s.citations,
        }
        for s in signals
    ]
