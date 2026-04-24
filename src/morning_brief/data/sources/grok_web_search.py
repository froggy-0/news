"""Grok Web Search 기반 실시간 뉴스 기사 수집.

Grok API의 web_search 도구를 활용하여 최신 금융 뉴스 기사를 수집한다.
Perplexity Sonar와 독립적인 뉴스 소스로 기능한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search

from morning_brief.data.sources.grok_official_signals import GROK_PROVIDER
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.provider_runtime import (
    disabled_reason,
    execute_with_provider_retry,
    open_circuit,
    record_skip,
)
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

WEB_SEARCH_PROMPT = """Search the web for the most important financial news articles
from the last 24 hours covering:
1. US macro economy (Fed, rates, inflation, employment)
2. US equity markets (S&P 500, Nasdaq, sector moves)
3. Bitcoin and crypto (ETF flows, regulation, price)

Return the top {max_items} most market-moving articles as JSON.
For each: title, url, source, published_at (ISO8601), topic (macro/us_equity/bitcoin), summary (one sentence).
Prefer Reuters, Bloomberg, WSJ, FT, CNBC.
Exclude data pages, stock quote pages, and non-English articles.
Output format: {{"articles": [...]}}"""

EXCLUDED_DOMAINS = [
    "markets.ft.com",
    "data.coindesk.com",
    "downloads.coindesk.com",
    "sponsored.bloomberg.com",
    "cn.wsj.com",
    "jp.reuters.com",
]


def _build_client(api_key: str) -> Client:
    return Client(api_key=api_key)


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
        "cost_in_usd_ticks": _usage_int(usage, "cost_in_usd_ticks"),
        "num_sources_used": _usage_int(usage, "num_sources_used"),
    }


def _to_http_fetch_error(exc: Exception) -> HttpFetchError:
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status_code == 429:
        msg = f"Grok Web Search 호출 한도에 걸렸어요: {exc}"
        open_circuit(GROK_PROVIDER, msg)
        return HttpFetchError(msg, provider=GROK_PROVIDER, retryable=False, rate_limited=True)
    retryable = status_code in {500, 502, 503, 504} if status_code else False
    return HttpFetchError(
        f"Grok Web Search 호출 실패: {exc}", provider=GROK_PROVIDER, retryable=retryable
    )


def _parse_datetime(value: object) -> datetime | None:
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


def _source_from_url(url: str) -> str:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "Unknown"
    host = host.removeprefix("www.")
    parts = host.split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else host or "Unknown"


def _perform_web_search(
    *, api_key: str, model: str, max_items: int
) -> tuple[list[dict[str, Any]], dict[str, int | None]]:
    client = _build_client(api_key)
    prompt = WEB_SEARCH_PROMPT.format(max_items=max_items)

    try:
        chat = client.chat.create(
            model=model,
            tools=[web_search(excluded_domains=EXCLUDED_DOMAINS)],
            tool_choice="required",
            response_format="json_object",
        )
        chat.append(user(prompt))
        response = chat.sample()
    except Exception as exc:
        raise _to_http_fetch_error(exc) from exc

    content = getattr(response, "content", "") or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        log_structured(
            logger,
            event="error.raised",
            message="Grok Web Search 응답 JSON 파싱이 실패했어요.",
            level=logging.WARNING,
            provider=GROK_PROVIDER,
            preview=content[:200],
            reason="invalid_json",
        )
        return [], _usage_snapshot(response)

    articles = data.get("articles", []) if isinstance(data, dict) else []
    return articles, _usage_snapshot(response)


def _article_to_news_item(article: dict[str, Any]) -> NewsItem | None:
    title = str(article.get("title", "")).strip()
    url = str(article.get("url", "")).strip()
    if not title or not url:
        return None
    source = str(article.get("source", "")).strip() or _source_from_url(url)
    return NewsItem(
        title=title,
        url=url,
        source=source,
        published_at=_parse_datetime(article.get("published_at")),
        topic=str(article.get("topic", "")).strip(),
        provider="grok_web_search",
        summary=str(article.get("summary", "")).strip(),
    )


def _record_usage(observer: PipelineObserver | None, usage: dict[str, int | None]) -> None:
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
        cost_in_usd_ticks=usage.get("cost_in_usd_ticks"),
        num_sources_used=usage.get("num_sources_used"),
        usage_parse_failures=failures,
    )


def fetch_grok_web_news(
    *,
    api_key: str,
    model: str,
    max_items: int = 8,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    """Grok Web Search로 최신 뉴스 기사를 수집한다."""
    if not api_key.strip():
        log_structured(
            logger,
            event="phase.skip",
            message="Grok API 키가 없어서 Web Search를 건너뛸게요.",
            level=logging.WARNING,
            provider=GROK_PROVIDER,
            reason="missing_api_key",
        )
        return []

    reason = disabled_reason(GROK_PROVIDER)
    if reason:
        record_skip(GROK_PROVIDER)
        log_structured(
            logger,
            event="phase.skip",
            message="Grok은 이번 실행에서 더 이상 쓰지 않을게요.",
            level=logging.WARNING,
            provider=GROK_PROVIDER,
            reason=reason,
        )
        return []

    try:
        raw_articles, usage = execute_with_provider_retry(
            provider=GROK_PROVIDER,
            operation=lambda: _perform_web_search(
                api_key=api_key, model=model, max_items=max_items
            ),
            should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
            on_retry=lambda exc, attempt, max_attempts, delay: log_structured(
                logger,
                event="provider.retry",
                message="Grok Web Search를 다시 시도하는 중이에요.",
                level=logging.WARNING,
                provider=GROK_PROVIDER,
                attempt=attempt,
                max_attempts=max_attempts,
                reason=str(exc),
                retryable=True,
                delay_seconds=delay,
            ),
            retry_after_seconds_for_error=lambda exc: (
                exc.retry_after_seconds if isinstance(exc, HttpFetchError) else None
            ),
        )
        _record_usage(observer, usage)
    except HttpFetchError as exc:
        if observer:
            observer.log_event(
                "grok_web_search_failed",
                level=logging.WARNING,
                message="Grok Web Search가 실패했어요.",
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        else:
            log_structured(
                logger,
                event="error.raised",
                message="Grok Web Search가 실패했어요.",
                level=logging.WARNING,
                provider=GROK_PROVIDER,
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        return []

    items: list[NewsItem] = []
    for article in raw_articles[:max_items]:
        news_item = _article_to_news_item(article)
        if news_item:
            items.append(news_item)

    log_structured(
        logger,
        event="selection.complete",
        message="Grok Web Search 뉴스 기사 수집을 마쳤어요.",
        provider=GROK_PROVIDER,
        kept_count=len(items),
    )
    return items
