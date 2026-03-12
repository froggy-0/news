from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from morning_brief.models import NewsItem


PREFERRED_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "coindesk.com",
}

PREFERRED_SOURCE_NAMES = {
    "reuters",
    "bloomberg",
    "wall street journal",
    "financial times",
    "cnbc",
    "coindesk",
}


QUERIES = [
    "Fed interest rates US Treasury yields",
    "US stock market Nasdaq S&P 500 semiconductor",
    "NVIDIA Microsoft Apple Amazon Google Meta AMD TSM ASML AVGO",
    "Bitcoin ETF flows regulation",
]



def _is_preferred_domain(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(domain in host for domain in PREFERRED_DOMAINS)


def _is_preferred_source(source_name: str, source_url: str) -> bool:
    source_name_l = source_name.strip().lower()
    if any(name in source_name_l for name in PREFERRED_SOURCE_NAMES):
        return True
    return _is_preferred_domain(source_url)



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



def _dedup_key(item: NewsItem) -> str:
    return item.title.strip().lower()



def _google_news_rss(query: str) -> str:
    encoded = quote_plus(query)
    return (
        "https://news.google.com/rss/search?"
        f"q={encoded}&hl=en-US&gl=US&ceid=US:en"
    )



def _collect_from_rss(max_items: int) -> list[NewsItem]:
    candidates: list[NewsItem] = []
    for query in QUERIES:
        feed = feedparser.parse(_google_news_rss(query))
        for entry in feed.entries:
            source = ""
            source_url = ""
            source_data = entry.get("source")
            if isinstance(source_data, dict):
                source = source_data.get("title", "").strip()
                source_url = source_data.get("href", "").strip()

            if not _is_preferred_source(source, source_url):
                continue

            link = entry.get("link", "").strip() or source_url
            if not link:
                continue
            if not source:
                source = "Unknown"

            candidates.append(
                NewsItem(
                    title=entry.get("title", "").strip(),
                    url=link,
                    source=source,
                    published_at=_parse_published(entry),
                )
            )

    unique: dict[str, NewsItem] = {}
    for item in candidates:
        key = _dedup_key(item)
        if key and key not in unique:
            unique[key] = item

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    filtered = [
        item
        for item in unique.values()
        if item.published_at is None or item.published_at >= cutoff
    ]
    filtered.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return filtered[:max_items]



def _collect_from_newsapi(api_key: str, max_items: int) -> list[NewsItem]:
    url = "https://newsapi.org/v2/everything"
    query = "(Fed OR Treasury OR Nasdaq OR S&P 500 OR semiconductor OR Bitcoin ETF OR Nvidia OR Apple OR Microsoft)"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_items * 3,
        "domains": ",".join(sorted(PREFERRED_DOMAINS)),
    }
    headers = {"X-Api-Key": api_key}

    response = requests.get(url, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()

    items: list[NewsItem] = []
    for article in payload.get("articles", []):
        title = article.get("title", "").strip()
        link = article.get("url", "").strip()
        source = article.get("source", {}).get("name", "Unknown")
        if not title or not link:
            continue
        published_raw = article.get("publishedAt")
        published_at = None
        if published_raw:
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
            )
        )

    unique: dict[str, NewsItem] = {}
    for item in items:
        key = _dedup_key(item)
        if key and key not in unique:
            unique[key] = item

    ordered = sorted(
        unique.values(),
        key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return ordered[:max_items]



def fetch_news(max_items: int, newsapi_key: str = "") -> list[NewsItem]:
    if newsapi_key:
        try:
            return _collect_from_newsapi(newsapi_key, max_items)
        except requests.RequestException:
            pass

    return _collect_from_rss(max_items)



def build_news_packet(max_items: int, newsapi_key: str = "") -> list[dict]:
    items = fetch_news(max_items=max_items, newsapi_key=newsapi_key)
    result: list[dict] = []
    for item in items:
        result.append(
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
        )
    return result
