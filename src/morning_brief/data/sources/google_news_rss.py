from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote_plus

import feedparser

from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)


def _parse_published(entry: dict) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _google_news_rss(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def fetch_news_from_google_rss(
    *,
    queries: list[str],
    max_items: int,
    recency_hours: int,
    preferred_only: bool,
    is_preferred_domain_fn: Callable[[str], bool],
    extract_domain_fn: Callable[[str], str],
) -> list[NewsItem]:
    candidates: list[NewsItem] = []

    for query in queries:
        feed = feedparser.parse(_google_news_rss(query))
        if getattr(feed, "bozo", 0):
            log_structured(
                logger,
                event="error.raised",
                message="RSS를 읽는 중 경고가 있었어요.",
                level=logging.WARNING,
                provider="google_news_rss",
                query=query,
                reason=str(getattr(feed, "bozo_exception", "unknown")),
            )

        for entry in feed.entries:
            source = ""
            source_url = ""
            source_data = entry.get("source")
            if isinstance(source_data, dict):
                source = source_data.get("title", "").strip()
                source_url = source_data.get("href", "").strip()

            link = entry.get("link", "").strip() or source_url
            if not link:
                continue

            if preferred_only and not is_preferred_domain_fn(link):
                continue

            candidates.append(
                NewsItem(
                    title=entry.get("title", "").strip(),
                    url=link,
                    source=source or extract_domain_fn(link),
                    published_at=_parse_published(entry),
                    provider="legacy_rss",
                )
            )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=recency_hours)
    filtered = [
        item for item in candidates if item.published_at is None or item.published_at >= cutoff
    ]
    return filtered[:max_items]
