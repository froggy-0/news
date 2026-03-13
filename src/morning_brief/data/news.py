from __future__ import annotations

from datetime import datetime, timezone
import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from morning_brief.config import Settings
from morning_brief.data.data_quality import (
    assess_perplexity_fallback_need,
    summarize_news_packet_quality,
)
from morning_brief.data.news_packet import (
    OFFICIAL_SIGNAL_PROVIDER,
    merge_news_packets as _merge_news_packets,
    news_items_to_packet as _news_items_to_packet,
    packet_item_to_news_item as _packet_item_to_news_item,
)
from morning_brief.data.news_policy import (
    MAX_ITEMS_PER_DOMAIN,
    MIN_NEWS_ITEMS,
    NEWS_RECENCY_HOURS,
    PREFERRED_DOMAINS,
    RSS_QUERIES,
    TOPIC_KEYWORDS,
    TRACKING_QUERY_KEYS,
    TRACKING_QUERY_PREFIXES,
    domain_score,
    extract_domain,
    is_preferred_domain,
    keyword_score,
    recency_score,
)
from morning_brief.data.sources.gdelt import fetch_news_from_gdelt
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.google_news_rss import fetch_news_from_google_rss
from morning_brief.data.sources.newsapi_provider import fetch_news_from_newsapi
from morning_brief.data.sources.perplexity_search import fetch_news_from_perplexity
from morning_brief.data.sources.grok_official_signals import fetch_official_x_signals
from morning_brief.data.news_rollout import (
    record_news_rollout_run,
    should_reduce_legacy_broad_fallback,
)
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)
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



def _extract_domain(url: str) -> str:
    return extract_domain(url)



def _is_preferred_domain(url: str) -> bool:
    return is_preferred_domain(url)



def _recency_score(published_at: datetime | None) -> float:
    return recency_score(published_at)



def _domain_score(url: str) -> float:
    return domain_score(url)


def _keyword_score(title: str) -> float:
    return keyword_score(title)



def _item_score(item: NewsItem) -> float:
    provider_bonus = 4.2 if item.provider == OFFICIAL_SIGNAL_PROVIDER else 0.0
    return (
        _domain_score(item.url)
        + _recency_score(item.published_at)
        + _keyword_score(item.title)
        + provider_bonus
    )



def _sort_by_score(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(
        items,
        key=lambda x: (
            _item_score(x),
            x.published_at or datetime.min.replace(tzinfo=timezone.utc),
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
            else _extract_domain(item.url)
        )
        count = per_domain.get(domain, 0)
        if count >= MAX_ITEMS_PER_DOMAIN:
            continue
        selected.append(item)
        per_domain[domain] = count + 1
        if len(selected) >= max_items:
            break

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

        source_domain = _extract_domain(normalized_url)
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
        if existing is None:
            by_key[key] = normalized_item
            continue

        if _item_score(normalized_item) > _item_score(existing):
            by_key[key] = normalized_item

    ranked = _sort_by_score(list(by_key.values()))
    return _apply_domain_diversity_limit(ranked, max_items=max_items)



def _collect_from_gdelt(max_items: int, preferred_only: bool = True) -> list[NewsItem]:
    try:
        return fetch_news_from_gdelt(
            topics=list(TOPIC_KEYWORDS.keys()),
            max_items=max_items,
            recency_hours=NEWS_RECENCY_HOURS,
            preferred_domains=PREFERRED_DOMAINS,
            preferred_only=preferred_only,
        )
    except (HttpFetchError, ValueError) as exc:
        logger.warning("GDELT에서 뉴스를 가져오지 못했어요: %s", exc)
        return []



def _collect_from_rss(max_items: int, preferred_only: bool = True) -> list[NewsItem]:
    candidates = fetch_news_from_google_rss(
        queries=RSS_QUERIES,
        max_items=max_items,
        recency_hours=NEWS_RECENCY_HOURS,
        preferred_only=preferred_only,
        is_preferred_domain_fn=_is_preferred_domain,
        extract_domain_fn=_extract_domain,
    )
    return _dedup_and_rank(candidates, max_items=max_items)



def _collect_from_newsapi(api_key: str, max_items: int) -> list[NewsItem]:
    items = fetch_news_from_newsapi(
        api_key=api_key,
        max_items=max_items,
        domains=sorted(PREFERRED_DOMAINS),
        query="(Fed OR Treasury OR Nasdaq OR S&P 500 OR semiconductor OR Bitcoin ETF OR Nvidia OR Apple OR Microsoft)",
    )
    return _dedup_and_rank(items, max_items=max_items)



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
    packet = _news_items_to_packet(items)
    return packet, summarize_news_packet_quality(packet)


def _needs_full_legacy_backfill(fallback_review: dict) -> bool:
    return any(
        [
            int(fallback_review.get("count", 0)) == 0,
            int(fallback_review.get("fresh_count", 0)) == 0,
            int(fallback_review.get("unique_domains", 0)) < 2,
            int(fallback_review.get("citation_backed_count", 0)) == 0,
        ]
    )


def _collect_official_signal_items(settings: Settings) -> list[NewsItem]:
    if not settings.enable_official_x_signals or not settings.grok_api_key:
        return []

    items = fetch_official_x_signals(
        api_key=settings.grok_api_key,
        model=settings.grok_model,
        lookback_hours=settings.official_x_lookback_hours,
        max_items=settings.official_x_max_items,
    )
    if items:
        logger.info("검증된 공식 X 시그널 %s건을 함께 반영했어요.", len(items))
    return items



def fetch_news(
    max_items: int,
    newsapi_key: str = "",
    *,
    allow_broad_fallback: bool = True,
) -> list[NewsItem]:
    # Collect a wider candidate pool, then rank down to target size.
    candidate_limit = max(max_items * 3, 15)

    items = _collect_from_gdelt(max_items=candidate_limit, preferred_only=True)
    if items:
        logger.info("뉴스 수집은 GDELT 우선 결과를 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS and newsapi_key:
        try:
            newsapi_items = _collect_from_newsapi(newsapi_key, max_items=candidate_limit)
            items = _merge_rank(items, newsapi_items, max_items=candidate_limit)
            if newsapi_items:
                logger.info("뉴스 보강에는 NewsAPI를 함께 사용했어요.")
        except (HttpFetchError, ValueError) as exc:
            logger.warning("NewsAPI에서 뉴스를 가져오지 못했어요: %s", exc)

    if len(items) < MIN_NEWS_ITEMS:
        rss_items = _collect_from_rss(max_items=candidate_limit, preferred_only=True)
        items = _merge_rank(items, rss_items, max_items=candidate_limit)
        if rss_items:
            logger.info("뉴스 보강에는 Google News RSS 우선 도메인을 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS and allow_broad_fallback:
        logger.info(
            "우선 신뢰 출처가 %s건이라 범위를 넓혀 GDELT와 RSS를 한 번 더 살펴봤어요.",
            len(items),
        )
        gdelt_broad = _collect_from_gdelt(max_items=candidate_limit, preferred_only=False)
        rss_broad = _collect_from_rss(max_items=candidate_limit, preferred_only=False)
        items = _merge_rank(items, gdelt_broad + rss_broad, max_items=candidate_limit)
    elif len(items) < MIN_NEWS_ITEMS and not allow_broad_fallback:
        logger.info("최근 운영 이력이 안정적이라 broad legacy fallback은 이번엔 건너뛸게요.")

    final_items = _dedup_and_rank(items, max_items=max_items)
    if final_items:
        logger.info("legacy 뉴스 provider 비중은 %s였어요.", _provider_breakdown(final_items))
    return final_items


def packet_item_to_news_item(item: dict) -> NewsItem | None:
    return _packet_item_to_news_item(item)


def news_items_to_packet(items: list[NewsItem]) -> list[dict]:
    return _news_items_to_packet(items)


def merge_news_packets(existing_packet: list[dict], extra_items: list[NewsItem], max_items: int) -> list[dict]:
    return _merge_news_packets(
        existing_packet=existing_packet,
        extra_items=extra_items,
        max_items=max_items,
        merge_rank_fn=_merge_rank,
    )


def build_news_packet(*, settings: Settings) -> list[dict]:
    items: list[NewsItem] = []
    legacy_items: list[NewsItem] = []
    official_signal_items = _collect_official_signal_items(settings)
    allow_broad_fallback = True
    fallback_review: dict | None = None

    if settings.research_provider == "perplexity":
        items = fetch_news_from_perplexity(
            max_items=settings.max_news_items,
            api_key=settings.perplexity_api_key,
        )
        if official_signal_items:
            items = _merge_rank(items, official_signal_items, max_items=settings.max_news_items)
        items = _dedup_and_rank(items, max_items=settings.max_news_items)
        packet, _ = _packet_summary(items)
        fallback_review = assess_perplexity_fallback_need(packet)
        if fallback_review["needs_legacy_fallback"] and settings.enable_legacy_news_fallback:
            reduce_broad_fallback = should_reduce_legacy_broad_fallback(settings.cache_dir)
            allow_broad_fallback = not (
                reduce_broad_fallback and not _needs_full_legacy_backfill(fallback_review)
            )
            logger.info(
                "Perplexity와 공식 시그널 결과를 살펴보니 %s. legacy 뉴스로 빈 부분을 함께 채울게요.",
                "; ".join(fallback_review["reasons"]),
            )
            if reduce_broad_fallback and not allow_broad_fallback:
                logger.info(
                    "최근 Perplexity 결과가 안정적이어서 이번에는 선별된 legacy fallback만 사용할게요."
                )
            legacy_items = fetch_news(
                max_items=settings.max_news_items,
                newsapi_key=settings.newsapi_key,
                allow_broad_fallback=allow_broad_fallback,
            )
            items = _merge_rank(items, legacy_items, max_items=settings.max_news_items)
        elif not items:
            logger.warning(
                "Perplexity 연구 결과가 없고 legacy 뉴스 폴백도 꺼져 있어서 빈 뉴스 묶음을 그대로 사용할게요."
            )
        else:
            logger.info(
                "Perplexity와 공식 시그널만으로도 기사 %s건, 도메인 %s개, 토픽 %s개 기준을 채웠어요.",
                fallback_review["count"],
                fallback_review["unique_domains"],
                fallback_review["topic_coverage_count"],
            )
    else:
        legacy_items = fetch_news(
            max_items=settings.max_news_items,
            newsapi_key=settings.newsapi_key,
        )
        items = _merge_rank(legacy_items, official_signal_items, max_items=settings.max_news_items)

    if items:
        packet, final_summary = _packet_summary(items)
        perplexity_count, official_signal_count, legacy_count, provider_breakdown = _provider_counts(items)
        logger.info(
            "최종 뉴스 구성은 Perplexity %s건, 공식 시그널 %s건, legacy %s건이었고 도메인 %s개, 토픽 %s개, provider 비중 %s로 정리됐어요.",
            perplexity_count,
            official_signal_count,
            legacy_count,
            final_summary["unique_domains"],
            final_summary["topic_coverage_count"],
            provider_breakdown,
        )
        if settings.research_provider == "perplexity" and fallback_review is not None:
            record_news_rollout_run(
                cache_dir=settings.cache_dir,
                fallback_review=fallback_review,
                used_legacy=bool(legacy_items),
                allow_broad_fallback=allow_broad_fallback,
                provider_breakdown=provider_breakdown,
            )
        return packet

    return _news_items_to_packet(items)
