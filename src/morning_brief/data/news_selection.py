from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from morning_brief.data.news_packet import OFFICIAL_SIGNAL_PROVIDER, news_items_to_packet
from morning_brief.data.news_policy import (
    MAX_ITEMS_PER_DOMAIN,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    domain_score,
    extract_domain,
    keyword_score,
    recency_score,
)
from morning_brief.models import NewsItem

PERPLEXITY_PROVIDER = "perplexity_search"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        return url.strip()

    filtered_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l.startswith(TRACKING_QUERY_PREFIXES):
            continue
        if key_l in TRACKING_QUERY_KEYS:
            continue
        filtered_params.append((key, value))

    filtered_query = urlencode(filtered_params)

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            filtered_query,
            "",
        )
    )


def _item_score(item: NewsItem) -> float:
    provider_bonus = 4.2 if item.provider == OFFICIAL_SIGNAL_PROVIDER else 0.0
    return (
        domain_score(item.url)
        + recency_score(item.published_at)
        + keyword_score(item.title)
        + provider_bonus
    )


def _sort_by_score(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(
        items,
        key=lambda item: (
            _item_score(item),
            item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )


def _apply_domain_diversity_limit(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    selected: list[NewsItem] = []
    per_domain: dict[str, int] = {}

    for item in items:
        domain = (
            f"{OFFICIAL_SIGNAL_PROVIDER}:{item.source.lower()}"
            if item.provider == OFFICIAL_SIGNAL_PROVIDER
            else extract_domain(item.url)
        )
        count = per_domain.get(domain, 0)
        if count >= MAX_ITEMS_PER_DOMAIN:
            continue
        selected.append(item)
        per_domain[domain] = count + 1
        if len(selected) >= max_items:
            return selected

    for item in items:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= max_items:
            break

    return selected[:max_items]


def _dedup_and_rank(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}

    for item in items:
        title = item.title.strip()
        if not title:
            continue

        normalized_url = _normalize_url(item.url)
        if not normalized_url:
            continue

        source_domain = extract_domain(normalized_url)
        normalized_item = NewsItem(
            title=title,
            url=normalized_url,
            source=item.source if item.source and item.source != "Unknown" else source_domain,
            published_at=item.published_at,
            topic=item.topic,
            provider=item.provider,
            summary=item.summary,
            why_it_matters=item.why_it_matters,
            citations=list(item.citations),
        )

        key = normalized_url or title.lower()
        existing = by_key.get(key)
        if existing is None or _item_score(normalized_item) > _item_score(existing):
            by_key[key] = normalized_item

    ranked = _sort_by_score(list(by_key.values()))
    return _apply_domain_diversity_limit(ranked, max_items=max_items)


def _merge_rank(items: list[NewsItem], other: list[NewsItem], max_items: int) -> list[NewsItem]:
    return _dedup_and_rank(items + other, max_items=max_items)


def _provider_breakdown(items: list[NewsItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        provider = item.provider or "unknown"
        counts[provider] = counts.get(provider, 0) + 1
    return counts


def _provider_counts(items: list[NewsItem]) -> tuple[int, int, int, dict[str, int]]:
    breakdown = _provider_breakdown(items)
    perplexity_count = breakdown.get(PERPLEXITY_PROVIDER, 0)
    official_signal_count = breakdown.get(OFFICIAL_SIGNAL_PROVIDER, 0)
    legacy_count = sum(
        count
        for provider, count in breakdown.items()
        if provider not in {PERPLEXITY_PROVIDER, OFFICIAL_SIGNAL_PROVIDER}
    )
    return perplexity_count, official_signal_count, legacy_count, breakdown


def _packet_summary(items: list[NewsItem]) -> tuple[list[dict], dict]:
    packet = news_items_to_packet(items)
    from morning_brief.data.data_quality import summarize_news_packet_quality

    return packet, summarize_news_packet_quality(packet)
