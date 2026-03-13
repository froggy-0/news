from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from morning_brief.data.sources.domain_utils import domain_matches, normalize_domain
from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMESPAN_HOURS = 36


def _parse_gdelt_time(raw: str) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _normalize_domain(url: str) -> str:
    return normalize_domain(url)


def _build_query(topics: list[str]) -> str:
    if not topics:
        return "market OR stocks OR bitcoin"
    return " OR ".join(topics)


def fetch_news_from_gdelt(
    *,
    topics: list[str],
    max_items: int,
    recency_hours: int = DEFAULT_TIMESPAN_HOURS,
    preferred_domains: set[str] | None = None,
    preferred_only: bool = True,
) -> list[NewsItem]:
    payload = get_json_with_retry(
        GDELT_DOC_URL,
        params={
            "query": _build_query(topics),
            "mode": "artlist",
            "maxrecords": max(max_items * 3, 20),
            "timespan": f"{recency_hours}h",
            "sort": "datedesc",
            "format": "json",
        },
        provider="gdelt",
        timeout=25,
    )

    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        raise ValueError("GDELT 응답 구조가 예상과 달라요.")

    preferred_domains = preferred_domains or set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=recency_hours)

    items: list[NewsItem] = []
    seen_titles: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            continue

        title = str(article.get("title", "")).strip()
        link = str(article.get("url", "")).strip()
        if not title or not link:
            continue

        domain = _normalize_domain(link)
        if (
            preferred_only
            and preferred_domains
            and not any(
                domain_matches(domain, preferred_domain) for preferred_domain in preferred_domains
            )
        ):
            continue

        published_at = _parse_gdelt_time(str(article.get("seendate", "")))
        if published_at and published_at < cutoff:
            continue

        dedup_key = title.lower()
        if dedup_key in seen_titles:
            continue
        seen_titles.add(dedup_key)

        items.append(
            NewsItem(
                title=title,
                url=link,
                source=domain or "Unknown",
                published_at=published_at,
                provider="legacy_gdelt",
            )
        )

        if len(items) >= max_items:
            break

    return items


__all__ = [
    "HttpFetchError",
    "fetch_news_from_gdelt",
]
