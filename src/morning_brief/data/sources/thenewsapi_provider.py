from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from morning_brief.data import providers
from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

THENEWSAPI_PROVIDER = "thenewsapi"
BASE_URL = "https://api.thenewsapi.net/crypto"
FREE_PLAN_MAX_PAGE_SIZE = 10

_BITCOIN_HINTS = (
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "crypto",
    "stablecoin",
    "etf",
    "blockchain",
    "defi",
    "web3",
)


@dataclass(frozen=True)
class TheNewsApiPage:
    items: list[NewsItem]
    has_next: bool
    requested_size: int
    page: int


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_csv(raw: str) -> str:
    return ",".join(part.strip().lower() for part in raw.split(",") if part.strip())


def _published_at(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _topic_for_article(title: str, body: str, category: str) -> str:
    text = f"{title} {body} {category}".lower()
    if any(hint in text for hint in _BITCOIN_HINTS):
        return "bitcoin"
    return "bitcoin"


def _why_it_matters(title: str, summary: str) -> str:
    source = summary or title
    if not source:
        return "TheNewsAPI 보도라 크립토 시장 흐름을 빠르게 훑는 데 도움이 돼요."
    return f"TheNewsAPI 보도라 크립토 시장 흐름을 빠르게 훑는 데 도움이 돼요: {source[:180]}"


def _source_name(raw_source: object) -> str:
    if isinstance(raw_source, dict):
        name = str(raw_source.get("name", "")).strip()
        if name:
            return name
        domain = str(raw_source.get("domain", "")).strip()
        if domain:
            return domain
    name = str(raw_source or "").strip()
    return name or "Unknown"


def _article_to_news_item(raw: dict[str, Any]) -> NewsItem | None:
    title = str(raw.get("title", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not title or not url:
        return None

    summary = str(raw.get("summary", "")).strip()
    description = str(raw.get("description", "")).strip()
    category = str(raw.get("category", "")).strip().lower()
    body = summary or description

    return NewsItem(
        title=title,
        url=url,
        source=_source_name(raw.get("source")),
        published_at=_published_at(raw.get("published_at")),
        topic=_topic_for_article(title, body, category),
        provider=providers.THENEWSAPI,
        summary=summary,
        why_it_matters=_why_it_matters(title, body),
        citations=[url],
    )


def fetch_thenewsapi_page(
    *,
    api_key: str,
    max_items: int,
    lookback_hours: int,
    langs: str,
    categories: str,
    query: str,
    page: int = 1,
    observer: PipelineObserver | None = None,
    now: datetime | None = None,
) -> TheNewsApiPage:
    if not api_key or max_items <= 0 or lookback_hours <= 0:
        return TheNewsApiPage(items=[], has_next=False, requested_size=0, page=page)

    run_now = now or _now_utc()
    if run_now.tzinfo is None:
        run_now = run_now.replace(tzinfo=timezone.utc)
    run_now = run_now.astimezone(timezone.utc)
    start_at = run_now - timedelta(hours=lookback_hours)
    requested_size = min(max_items, FREE_PLAN_MAX_PAGE_SIZE)

    payload = get_json_with_retry(
        BASE_URL,
        params={
            "apikey": api_key,
            "q": query,
            "from": start_at.isoformat().replace("+00:00", "Z"),
            "to": run_now.isoformat().replace("+00:00", "Z"),
            "categories": _normalize_csv(categories),
            "langs": _normalize_csv(langs),
            "page": page,
            "size": requested_size,
        },
        provider=THENEWSAPI_PROVIDER,
        timeout=20,
    )

    if payload.get("success") is False:
        error = payload.get("error")
        raise HttpFetchError(
            f"TheNewsAPI 응답이 실패로 표시됐어요: {error!r}",
            provider=THENEWSAPI_PROVIDER,
        )

    data = payload.get("data", {})
    if not isinstance(data, dict):
        raise HttpFetchError(
            "TheNewsAPI data 필드 구조가 예상과 달라요.", provider=THENEWSAPI_PROVIDER
        )

    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        raise HttpFetchError(
            "TheNewsAPI results 필드 구조가 예상과 달라요.",
            provider=THENEWSAPI_PROVIDER,
        )

    items = [
        item for raw in raw_results if isinstance(raw, dict) if (item := _article_to_news_item(raw))
    ]
    has_next = bool(data.get("next"))

    log_structured(
        logger,
        event="selection.complete",
        message="TheNewsAPI에서 크립토 뉴스를 수집했어요.",
        provider=THENEWSAPI_PROVIDER,
        candidate_count=len(raw_results),
        kept_count=len(items),
        requested_size=requested_size,
        page=page,
        has_next=has_next,
    )
    if observer is not None:
        observer.log_event(
            "thenewsapi_news_collected",
            provider=THENEWSAPI_PROVIDER,
            candidate_count=len(raw_results),
            kept_count=len(items),
            requested_size=requested_size,
            page=page,
            has_next=has_next,
        )

    return TheNewsApiPage(
        items=items,
        has_next=has_next,
        requested_size=requested_size,
        page=page,
    )
