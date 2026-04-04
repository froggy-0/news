from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from morning_brief.data import providers
from morning_brief.data.news_packet import news_items_to_packet
from morning_brief.data.news_policy import (
    MAX_ITEMS_PER_DOMAIN,
    MIN_NEWS_ITEMS,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    domain_score,
    extract_domain,
    keyword_score,
    recency_score,
)
from morning_brief.models import NewsItem

_PERPLEXITY_PROVIDERS = providers.PERPLEXITY_PROVIDERS
_GROK_PROVIDERS = providers.GROK_PROVIDERS
_PUBLISH_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(weak source item|example|sample|test item|placeholder)\b",
    re.IGNORECASE,
)
_PUBLISH_FILELIKE_TITLE_RE = re.compile(r"\.(?:pdf|html?|xml|json|txt|csv)(?:$|\s)", re.IGNORECASE)
_PUBLISH_BLOCKED_DOMAINS = {"example.com", "example.net", "example.org", "localhost"}
_PUBLIC_NEWS_BLOCKED_DOMAINS = {"x.com", "twitter.com"}
_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS = frozenset(
    {
        # 한국어 패턴
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
        # 영어 패턴
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "no information",
        "no comment",
        "not available",
        "no information available",
        "no details available",
        # 기호
        "–",
        "-",
        "...",
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
    if not normalized or normalized in _PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS:
        return False
    # 30자 미만이면 구두점 제거 후 재체크 (예: "N/A." → "n/a")
    if len(normalized) < 30:
        stripped = normalized.rstrip(".,;:")
        if stripped in _PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS:
            return False
    return True


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
    provider_bonus = 4.2 if item.provider == providers.GROK_OFFICIAL_X else 0.0
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
            f"{providers.GROK_OFFICIAL_X}:{item.source.lower()}"
            if item.provider == providers.GROK_OFFICIAL_X
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


def _title_dedup_key(title: str) -> str:
    """보조 title dedup 키를 반환한다.

    소문자·공백 정규화 후 앞 40자를 반환한다.
    10자 미만이면 빈 문자열을 반환하여 보조 dedup을 비활성화한다.
    """
    normalized = " ".join(title.strip().lower().split())
    if len(normalized) < 10:
        return ""
    return normalized[:40]


def _dedup_and_rank(
    items: list[NewsItem],
    max_items: int,
    *,
    min_output: int = 0,
) -> list[NewsItem]:
    by_url: dict[str, NewsItem] = {}
    by_title: dict[str, str] = {}  # title_key → url_key

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

        url_key = normalized_url
        title_key = _title_dedup_key(title)

        # Step 1: URL dedup (우선 적용)
        existing_url = by_url.get(url_key)
        if existing_url is not None:
            if _item_score(normalized_item) > _item_score(existing_url):
                by_url[url_key] = normalized_item
                if title_key:
                    by_title[title_key] = url_key
            continue

        # Step 2: Title dedup (새 URL에 대해서만 적용)
        if title_key:
            existing_url_key = by_title.get(title_key)
            if existing_url_key is not None:
                # 같은 title이 이미 다른 URL로 등록됨 — 점수 높은 것 유지
                if _item_score(normalized_item) > _item_score(by_url[existing_url_key]):
                    del by_url[existing_url_key]
                    by_url[url_key] = normalized_item
                    by_title[title_key] = url_key
                continue

        by_url[url_key] = normalized_item
        if title_key:
            by_title[title_key] = url_key

    ranked = _sort_by_score(list(by_url.values()))
    result = _apply_domain_diversity_limit(ranked, max_items=max_items)

    # 최소 출력 보장: 도메인 다양성 제한이 min_output을 만족하지 못하면 완화
    if min_output > 0 and len(result) < min_output and len(ranked) >= min_output:
        return ranked[:min_output]

    return result


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
