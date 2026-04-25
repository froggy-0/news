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

MARKETAUX_PROVIDER = "marketaux"
BASE_URL = "https://api.marketaux.com/v1/news/all"
FREE_PLAN_MAX_LIMIT = 3

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
class MarketauxPage:
    items: list[NewsItem]
    has_next: bool
    requested_limit: int
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


def _topic_for_article(title: str, body: str) -> str:
    text = f"{title} {body}".lower()
    if any(hint in text for hint in _BITCOIN_HINTS):
        return "bitcoin"
    return "bitcoin"


def _why_it_matters(title: str, snippet: str) -> str:
    source = snippet or title
    if not source:
        return "Marketaux 기사라 크립토 시장의 주요 흐름을 빠르게 확인하는 데 도움이 돼요."
    return (
        f"Marketaux 기사라 크립토 시장의 주요 흐름을 빠르게 확인하는 데 도움이 돼요: {source[:180]}"
    )


def _article_to_news_item(raw: dict[str, Any]) -> NewsItem | None:
    title = str(raw.get("title", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not title or not url:
        return None

    description = str(raw.get("description", "")).strip()
    snippet = str(raw.get("snippet", "")).strip()

    return NewsItem(
        title=title,
        url=url,
        source=str(raw.get("source", "")).strip() or "Unknown",
        published_at=_published_at(raw.get("published_at")),
        topic=_topic_for_article(title, snippet or description),
        provider=providers.MARKETAUX,
        summary=description or snippet,
        why_it_matters=_why_it_matters(title, snippet or description),
        citations=[url],
    )


def fetch_marketaux_page(
    *,
    api_key: str,
    max_items: int,
    lookback_hours: int,
    language: str,
    domains: str,
    search: str,
    page: int = 1,
    observer: PipelineObserver | None = None,
    now: datetime | None = None,
) -> MarketauxPage:
    if not api_key or max_items <= 0 or lookback_hours <= 0:
        return MarketauxPage(items=[], has_next=False, requested_limit=0, page=page)

    run_now = now or _now_utc()
    if run_now.tzinfo is None:
        run_now = run_now.replace(tzinfo=timezone.utc)
    run_now = run_now.astimezone(timezone.utc)
    start_at = run_now - timedelta(hours=lookback_hours)
    requested_limit = min(max_items, FREE_PLAN_MAX_LIMIT)

    payload = get_json_with_retry(
        BASE_URL,
        params={
            "api_token": api_key,
            "search": search,
            "domains": _normalize_csv(domains),
            "language": _normalize_csv(language),
            "published_after": start_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sort": "published_at",
            "limit": requested_limit,
            "page": page,
        },
        provider=MARKETAUX_PROVIDER,
        timeout=20,
    )

    error = payload.get("error")
    if isinstance(error, dict) and error:
        raise HttpFetchError(
            f"Marketaux 응답이 실패로 표시됐어요: {error!r}",
            provider=MARKETAUX_PROVIDER,
        )

    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        raise HttpFetchError(
            "Marketaux meta 필드 구조가 예상과 달라요.", provider=MARKETAUX_PROVIDER
        )

    raw_results = payload.get("data", [])
    if not isinstance(raw_results, list):
        raise HttpFetchError(
            "Marketaux data 필드 구조가 예상과 달라요.", provider=MARKETAUX_PROVIDER
        )

    items = [
        item for raw in raw_results if isinstance(raw, dict) if (item := _article_to_news_item(raw))
    ]
    returned = int(meta.get("returned", len(raw_results)) or 0)
    found = int(meta.get("found", returned) or 0)
    limit = int(meta.get("limit", requested_limit) or requested_limit)
    current_page = int(meta.get("page", page) or page)
    has_next = returned >= limit and found > (current_page * limit)

    log_structured(
        logger,
        event="selection.complete",
        message="Marketaux에서 크립토 관련 뉴스를 수집했어요.",
        provider=MARKETAUX_PROVIDER,
        candidate_count=len(raw_results),
        kept_count=len(items),
        requested_limit=requested_limit,
        page=current_page,
        has_next=has_next,
    )
    if observer is not None:
        observer.log_event(
            "marketaux_news_collected",
            provider=MARKETAUX_PROVIDER,
            candidate_count=len(raw_results),
            kept_count=len(items),
            requested_limit=requested_limit,
            page=current_page,
            has_next=has_next,
        )

    return MarketauxPage(
        items=items,
        has_next=has_next,
        requested_limit=requested_limit,
        page=current_page,
    )
