from __future__ import annotations

from datetime import datetime

from morning_brief.data.sources.http_client import get_json_with_retry
from morning_brief.models import NewsItem


def fetch_news_from_newsapi(
    *,
    api_key: str,
    max_items: int,
    domains: list[str],
    query: str,
) -> list[NewsItem]:
    if not api_key:
        return []

    payload = get_json_with_retry(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_items,
            "domains": ",".join(sorted(domains)),
        },
        headers={"X-Api-Key": api_key},
        provider="newsapi",
        timeout=20,
    )

    items: list[NewsItem] = []
    for article in payload.get("articles", []):
        if not isinstance(article, dict):
            continue

        title = str(article.get("title", "")).strip()
        link = str(article.get("url", "")).strip()
        if not title or not link:
            continue

        source = str(article.get("source", {}).get("name", "Unknown")).strip() or "Unknown"
        published_at = None
        published_raw = article.get("publishedAt")
        if isinstance(published_raw, str) and published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        items.append(
            NewsItem(
                title=title,
                url=link,
                source=source,
                published_at=published_at,
                provider="legacy_newsapi",
            )
        )

    return items
