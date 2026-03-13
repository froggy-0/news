from __future__ import annotations

import logging

from morning_brief.config import Settings
from morning_brief.data import data_quality, news_policy, news_selection
from morning_brief.data.data_quality import (
    assess_perplexity_fallback_need,
)
from morning_brief.data.news_packet import (
    news_items_to_packet as _news_items_to_packet,
)
from morning_brief.data.news_policy import (
    MIN_NEWS_ITEMS,
    NEWS_RECENCY_HOURS,
    PREFERRED_DOMAINS,
    RSS_QUERIES,
)
from morning_brief.data.news_rollout import (
    record_news_rollout_run,
    should_reduce_legacy_broad_fallback,
)
from morning_brief.data.sources.google_news_rss import fetch_news_from_google_rss
from morning_brief.data.sources.grok_official_signals import fetch_official_x_signals
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.newsapi_provider import fetch_news_from_newsapi
from morning_brief.data.sources.perplexity_search import fetch_news_from_perplexity
from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)

# Re-export ranking helpers for tests and adjacent modules while keeping
# ranking/selection responsibilities in news_selection.py.
_dedup_and_rank = news_selection._dedup_and_rank
_domain_score = news_policy.domain_score
_extract_domain = news_policy.extract_domain
_is_preferred_domain = news_policy.is_preferred_domain
_item_score = news_selection._item_score
_merge_rank = news_selection._merge_rank
_normalize_url = news_selection._normalize_url
_packet_summary = news_selection._packet_summary
_provider_breakdown = news_selection._provider_breakdown
_provider_counts = news_selection._provider_counts
summarize_news_packet_quality = data_quality.summarize_news_packet_quality


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

    items = _collect_from_rss(max_items=candidate_limit, preferred_only=True)
    if items:
        logger.info("뉴스 수집은 Google News RSS 우선 결과를 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS and newsapi_key:
        try:
            newsapi_items = _collect_from_newsapi(newsapi_key, max_items=candidate_limit)
            items = _merge_rank(items, newsapi_items, max_items=candidate_limit)
            if newsapi_items:
                logger.info("뉴스 보강에는 NewsAPI를 함께 사용했어요.")
        except (HttpFetchError, ValueError) as exc:
            logger.warning("NewsAPI에서 뉴스를 가져오지 못했어요: %s", exc)

    if len(items) < MIN_NEWS_ITEMS and allow_broad_fallback:
        logger.info(
            "우선 신뢰 출처가 %s건이라 범위를 넓혀 RSS를 한 번 더 살펴봤어요.",
            len(items),
        )
        rss_broad = _collect_from_rss(max_items=candidate_limit, preferred_only=False)
        items = _merge_rank(items, rss_broad, max_items=candidate_limit)
    elif len(items) < MIN_NEWS_ITEMS and not allow_broad_fallback:
        logger.info("최근 운영 이력이 안정적이라 broad legacy fallback은 이번엔 건너뛸게요.")

    final_items = _dedup_and_rank(items, max_items=max_items)
    if final_items:
        logger.info("legacy 뉴스 provider 비중은 %s였어요.", _provider_breakdown(final_items))
    elif candidate_limit >= MIN_NEWS_ITEMS:
        logger.warning(
            "RSS와 NewsAPI까지 확인했지만 legacy 뉴스가 최소 기준(%s건)을 채우지 못했어요.",
            MIN_NEWS_ITEMS,
        )
    return final_items


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
        perplexity_count, official_signal_count, legacy_count, provider_breakdown = (
            _provider_counts(items)
        )
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
