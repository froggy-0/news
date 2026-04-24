from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from morning_brief.data import providers
from morning_brief.data.sources.http_client import get_json_with_retry
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

COINDESK_PROVIDER = "coindesk"
BASE_URL = "https://data-api.coindesk.com/news/v1/article/list"
DEFAULT_CATEGORIES = "BTC"
PAGE_LIMIT = 50


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _unix_ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


def _published_at(value: object) -> datetime | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _first_text(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split()).strip()
        if text:
            return text
    return ""


def _article_url(raw: dict[str, Any]) -> str:
    return _first_text(raw, ("URL", "url", "LINK", "link"))


def _article_id(raw: dict[str, Any]) -> str:
    return _first_text(raw, ("ID", "id", "GUID", "guid"))


def _article_topic(title: str, body: str) -> str:
    text = f"{title} {body}".lower()
    if any(keyword in text for keyword in ("bitcoin", "btc", "crypto", "ether", "ethereum")):
        return "bitcoin"
    return "bitcoin"


def _why_it_matters(title: str, body: str) -> str:
    source = body or title
    if not source:
        return "CoinDesk 보도라 비트코인과 크립토 시장 흐름을 확인하는 데 도움이 돼요."
    return f"CoinDesk 보도라 비트코인과 크립토 시장 흐름을 확인하는 데 도움이 돼요: {source[:180]}"


def _article_to_news_item(raw: dict[str, Any]) -> NewsItem | None:
    title = _first_text(raw, ("TITLE", "title"))
    url = _article_url(raw)
    if not title or not url:
        return None

    body = _first_text(raw, ("BODY", "body", "SUBTITLE", "subtitle", "EXCERPT", "excerpt"))
    published_at = _published_at(raw.get("PUBLISHED_ON") or raw.get("published_on"))
    return NewsItem(
        title=title,
        url=url,
        source="CoinDesk",
        published_at=published_at,
        topic=_article_topic(title, body),
        provider=providers.COINDESK_API,
        summary=body,
        why_it_matters=_why_it_matters(title, body),
        citations=[url],
    )


def _dedup_latest(items: list[NewsItem]) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}
    for item in items:
        url_key = item.url.strip().lower().rstrip("/")
        title_key = " ".join(item.title.lower().split())
        key = url_key or title_key
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            continue
        if (item.published_at or datetime.min.replace(tzinfo=timezone.utc)) > (
            existing.published_at or datetime.min.replace(tzinfo=timezone.utc)
        ):
            by_key[key] = item
    return sorted(
        by_key.values(),
        key=lambda item: (
            item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            item.title,
        ),
        reverse=True,
    )


def fetch_coindesk_news(
    *,
    max_items: int,
    lookback_hours: int,
    categories: str = DEFAULT_CATEGORIES,
    observer: PipelineObserver | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    if max_items <= 0 or lookback_hours <= 0:
        return []

    run_now = now or _now_utc()
    if run_now.tzinfo is None:
        run_now = run_now.replace(tzinfo=timezone.utc)
    run_now = run_now.astimezone(timezone.utc)
    start_at = run_now - timedelta(hours=lookback_hours)
    start_ts = _unix_ts(start_at)
    cursor = _unix_ts(run_now)
    collected: list[NewsItem] = []
    seen_ids: set[str] = set()
    pages_fetched = 0

    while len(collected) < max(max_items * 3, PAGE_LIMIT):
        payload = get_json_with_retry(
            BASE_URL,
            params={
                "lang": "EN",
                "categories": categories,
                "limit": PAGE_LIMIT,
                "to_ts": cursor,
            },
            provider=COINDESK_PROVIDER,
            timeout=20,
        )
        raw_articles = payload.get("Data", [])
        if not isinstance(raw_articles, list) or not raw_articles:
            break

        pages_fetched += 1
        oldest_seen = cursor
        reached_lookback_start = False
        for raw in raw_articles:
            if not isinstance(raw, dict):
                continue
            published_at = _published_at(raw.get("PUBLISHED_ON") or raw.get("published_on"))
            if published_at is None:
                continue
            published_ts = _unix_ts(published_at)
            oldest_seen = min(oldest_seen, published_ts)
            if published_ts < start_ts:
                reached_lookback_start = True
                continue

            article_id = _article_id(raw)
            if article_id and article_id in seen_ids:
                continue
            if article_id:
                seen_ids.add(article_id)

            item = _article_to_news_item(raw)
            if item is not None:
                collected.append(item)

        if reached_lookback_start:
            break
        cursor = oldest_seen - 1

    items = _dedup_latest(collected)[:max_items]
    log_structured(
        logger,
        event="selection.complete",
        message="CoinDesk API에서 최신 크립토 뉴스를 수집했어요.",
        provider=COINDESK_PROVIDER,
        candidate_count=len(collected),
        kept_count=len(items),
        pages_fetched=pages_fetched,
        lookback_hours=lookback_hours,
    )
    if observer is not None:
        observer.log_event(
            "coindesk_news_collected",
            provider=COINDESK_PROVIDER,
            candidate_count=len(collected),
            kept_count=len(items),
            pages_fetched=pages_fetched,
            lookback_hours=lookback_hours,
        )
    return items
