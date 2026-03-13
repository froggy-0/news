from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from morning_brief.data.news_policy import extract_domain, is_preferred_domain, source_tier
from morning_brief.models import NewsItem

OFFICIAL_SIGNAL_PROVIDER = "grok_official_x"


def packet_item_to_news_item(item: dict) -> NewsItem | None:
    if not isinstance(item, dict):
        return None

    title = str(item.get("title", "")).strip()
    url = str(item.get("url", "")).strip()
    if not title or not url:
        return None

    published_at = None
    published_raw = item.get("published_at")
    if isinstance(published_raw, str) and published_raw.strip():
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    source = str(item.get("source", "")).strip() or extract_domain(url) or "Unknown"
    return NewsItem(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        topic=str(item.get("topic", "")).strip(),
        provider=str(item.get("provider", "")).strip(),
        summary=str(item.get("summary", "")).strip(),
        why_it_matters=str(item.get("why_it_matters", "")).strip(),
        citations=[
            str(citation).strip()
            for citation in item.get("citations", [])
            if str(citation).strip()
        ]
        if isinstance(item.get("citations", []), list)
        else [],
    )


def news_items_to_packet(items: list[NewsItem]) -> list[dict]:
    result: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    for item in items:
        age_hours = None
        if item.published_at is not None:
            age_hours = round(
                (now_utc - item.published_at).total_seconds() / 3600,
                2,
            )
        result.append(
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "domain": extract_domain(item.url),
                "source_tier": source_tier(item.url),
                "preferred_source": is_preferred_domain(item.url),
                "age_hours": age_hours,
                "topic": item.topic or None,
                "provider": item.provider or None,
                "summary": item.summary or None,
                "why_it_matters": item.why_it_matters or None,
                "citations": list(item.citations),
                "official_source": item.provider == OFFICIAL_SIGNAL_PROVIDER,
            }
        )

    return result


def merge_news_packets(
    *,
    existing_packet: list[dict],
    extra_items: list[NewsItem],
    max_items: int,
    merge_rank_fn: Callable[[list[NewsItem], list[NewsItem], int], list[NewsItem]],
) -> list[dict]:
    existing_items = [
        item
        for item in (packet_item_to_news_item(entry) for entry in existing_packet)
        if item is not None
    ]
    merged = merge_rank_fn(existing_items, extra_items, max_items)
    return news_items_to_packet(merged)
