from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from morning_brief.data.news_packet import OFFICIAL_SIGNAL_PROVIDER, news_items_to_packet
from morning_brief.data.news_policy import (
    MAX_ITEMS_PER_DOMAIN,
    MIN_NEWS_ITEMS,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    domain_score,
    extract_domain,
    is_preferred_domain,
    keyword_score,
    recency_score,
)
from morning_brief.models import NewsItem

PERPLEXITY_PROVIDER = "perplexity_search"
PERPLEXITY_SONAR_PROVIDER = "perplexity_sonar"
GROK_KEYWORD_PROVIDER = "grok_x_keyword"
GROK_WEB_PROVIDER = "grok_web_search"
_PERPLEXITY_PROVIDERS = {PERPLEXITY_PROVIDER, PERPLEXITY_SONAR_PROVIDER}
_GROK_PROVIDERS = {OFFICIAL_SIGNAL_PROVIDER, GROK_KEYWORD_PROVIDER, GROK_WEB_PROVIDER}
_PUBLISH_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(weak source item|example|sample|test item|placeholder)\b",
    re.IGNORECASE,
)
_PUBLISH_FILELIKE_TITLE_RE = re.compile(r"\.(?:pdf|html?|xml|json|txt|csv)(?:$|\s)", re.IGNORECASE)
_PUBLISH_BLOCKED_DOMAINS = {"example.com", "example.net", "example.org", "localhost"}
_PUBLIC_NEWS_BLOCKED_DOMAINS = {"x.com", "twitter.com"}
_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS = frozenset(
    {
        "",
        "없음",
        "없음.",
        "없음,",
        "해당없음",
        "해당 없음",
        "해당없음.",
        "해당 없음.",
        "해당없음,",
        "해당 없음,",
        "n/a",
        "null",
    }
)


def _normalized_publish_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _looks_like_publish_placeholder(title: str) -> bool:
    normalized = _normalized_publish_text(title)
    if not normalized:
        return True
    if normalized.startswith(("http://", "https://")):
        return True
    return bool(_PUBLISH_PLACEHOLDER_TITLE_RE.match(normalized))


def _looks_like_file_title(title: str) -> bool:
    normalized = title.strip()
    return bool(_PUBLISH_FILELIKE_TITLE_RE.search(normalized))


def _is_x_handle_source(item: NewsItem) -> bool:
    return item.source.strip().startswith("@")


def _is_x_domain_url(url: str) -> bool:
    domain = extract_domain(url)
    return any(
        domain == blocked_domain or domain.endswith(f".{blocked_domain}")
        for blocked_domain in _PUBLIC_NEWS_BLOCKED_DOMAINS
    )


def _has_meaningful_public_interpretation(item: NewsItem) -> bool:
    interpretation = item.why_it_matters.strip() or item.summary.strip()
    normalized = _normalized_publish_text(interpretation)
    return bool(normalized) and normalized not in _PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS


def _filter_news_items(
    items: list[NewsItem],
    *,
    min_items: int,
    public_article_only: bool = False,
) -> tuple[list[NewsItem], dict[str, Any]]:
    kept: list[NewsItem] = []
    dropped: dict[str, int] = {}

    for item in items:
        title = item.title.strip()
        url = item.url.strip()
        domain = extract_domain(url)
        interpretation = item.why_it_matters.strip() or item.summary.strip()
        is_official_signal = item.provider == OFFICIAL_SIGNAL_PROVIDER
        reason: str | None = None

        if public_article_only and _is_x_handle_source(item):
            reason = "x_handle_source"
        elif public_article_only and _is_x_domain_url(url):
            reason = "x_domain_url"
        elif public_article_only and not interpretation:
            reason = "missing_public_interpretation"
        elif public_article_only and not _has_meaningful_public_interpretation(item):
            reason = "placeholder_public_interpretation"
        elif not title or not url:
            reason = "missing_title_or_url"
        elif domain in _PUBLISH_BLOCKED_DOMAINS:
            reason = "blocked_domain"
        elif not is_official_signal and not is_preferred_domain(url):
            reason = "non_preferred_domain"
        elif _looks_like_publish_placeholder(title):
            reason = "placeholder_title"
        elif _looks_like_file_title(title):
            reason = "file_like_title"
        elif interpretation and _normalized_publish_text(
            interpretation
        ) == _normalized_publish_text(title):
            reason = "duplicate_interpretation"

        if reason is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        kept.append(item)

    below_minimum = len(kept) < min_items
    if below_minimum:
        dropped["below_minimum"] = dropped.get("below_minimum", 0) + len(kept)
        kept = []

    return kept, {
        "candidate_count": len(items),
        "kept_count": len(kept),
        "below_minimum": below_minimum,
        "dropped": dropped,
    }


def filter_publish_news(
    items: list[NewsItem],
    *,
    min_items: int = MIN_NEWS_ITEMS,
) -> tuple[list[NewsItem], dict[str, Any]]:
    return _filter_news_items(items, min_items=min_items)


def filter_publish_news_candidates(items: list[NewsItem]) -> tuple[list[NewsItem], dict[str, Any]]:
    return filter_publish_news(items, min_items=0)


def filter_public_article_news(
    items: list[NewsItem],
    *,
    min_items: int = 0,
) -> tuple[list[NewsItem], dict[str, Any]]:
    return _filter_news_items(items, min_items=min_items, public_article_only=True)


def filter_public_article_news_candidates(
    items: list[NewsItem],
) -> tuple[list[NewsItem], dict[str, Any]]:
    return filter_public_article_news(items, min_items=0)


def filter_publish_x_signals(
    signals: list[Any],
    *,
    min_items: int = 1,
) -> tuple[list[Any], dict[str, Any]]:
    kept: list[Any] = []
    dropped: dict[str, int] = {}

    for signal in signals:
        headline = str(getattr(signal, "headline", "") or "").strip()
        summary = str(getattr(signal, "summary", "") or "").strip()
        impact = str(getattr(signal, "why_it_matters", "") or "").strip()
        handle = str(getattr(signal, "source_handle", "") or "").strip()
        reason: str | None = None

        if not headline or not summary or not impact:
            reason = "missing_text"
        elif not handle:
            reason = "missing_handle"
        elif _looks_like_publish_placeholder(headline):
            reason = "placeholder_headline"

        if reason is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        kept.append(signal)

    below_minimum = len(kept) < min_items
    if below_minimum:
        dropped["below_minimum"] = dropped.get("below_minimum", 0) + len(kept)
        kept = []

    return kept, {
        "candidate_count": len(signals),
        "kept_count": len(kept),
        "below_minimum": below_minimum,
        "dropped": dropped,
    }


def filter_publish_x_signal_candidates(signals: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    return filter_publish_x_signals(signals, min_items=0)


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
    perplexity_count = sum(
        count for provider, count in breakdown.items() if provider in _PERPLEXITY_PROVIDERS
    )
    official_signal_count = sum(
        count for provider, count in breakdown.items() if provider in _GROK_PROVIDERS
    )
    legacy_count = sum(
        count
        for provider, count in breakdown.items()
        if provider not in _PERPLEXITY_PROVIDERS and provider not in _GROK_PROVIDERS
    )
    return perplexity_count, official_signal_count, legacy_count, breakdown


def _packet_summary(items: list[NewsItem]) -> tuple[list[dict], dict]:
    packet = news_items_to_packet(items)
    from morning_brief.data.data_quality import summarize_news_packet_quality

    return packet, summarize_news_packet_quality(packet)
