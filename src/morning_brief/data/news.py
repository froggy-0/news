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
from morning_brief.data.sources.gemini_grounding import fetch_gemini_grounding
from morning_brief.data.sources.google_news_rss import fetch_news_from_google_rss
from morning_brief.data.sources.grok_official_signals import fetch_official_x_signals
from morning_brief.data.sources.grok_web_search import fetch_grok_web_news
from morning_brief.data.sources.grok_x_keyword import (
    XSignal,
    fetch_x_keyword_signals,
)
from morning_brief.data.sources.http_client import HttpFetchError
from morning_brief.data.sources.newsapi_provider import fetch_news_from_newsapi
from morning_brief.data.sources.perplexity_search import fetch_news_from_perplexity
from morning_brief.data.sources.perplexity_sonar import (
    TopicSummary,
    collect_sonar_news_items,
    fetch_sonar_summaries,
)
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

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


def _collect_official_signal_items(
    settings: Settings,
    *,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    if not settings.enable_official_x_signals or not settings.grok_api_key:
        return []

    try:
        items = fetch_official_x_signals(
            api_key=settings.grok_api_key,
            model=settings.grok_model,
            lookback_hours=settings.official_x_lookback_hours,
            max_items=settings.official_x_max_items,
            observer=observer,
        )
    except Exception as exc:
        logger.warning("Grok 공식 X 시그널을 가져오지 못해 해당 섹션은 생략할게요: %s", exc)
        if observer is not None:
            observer.log_event("grok_signal_omitted", reason=str(exc))
        return []
    if items:
        logger.info("검증된 공식 X 시그널 %s건을 함께 반영했어요.", len(items))
    return items


def _collect_sonar_summaries(
    settings: Settings,
    *,
    observer: PipelineObserver | None = None,
) -> tuple[dict[str, TopicSummary], list[NewsItem]]:
    """Perplexity Sonar 요약을 수집한다."""
    if not settings.perplexity_use_sonar or not settings.perplexity_api_key:
        return {}, []

    try:
        summaries = fetch_sonar_summaries(
            api_key=settings.perplexity_api_key,
            model=settings.perplexity_sonar_model,
            max_tokens=settings.perplexity_sonar_max_tokens,
            observer=observer,
        )
    except Exception as exc:
        logger.warning("Sonar 요약 수집 중 오류 발생, 건너뛸게요: %s", exc)
        return {}, []
    news_items = collect_sonar_news_items(summaries)
    if summaries:
        logger.info(
            "Sonar 요약 %d개 토픽 수집 완료, citations에서 NewsItem %d건 추출",
            len(summaries),
            len(news_items),
        )
    return summaries, news_items


def _collect_x_keyword_signals(
    settings: Settings,
    *,
    observer: PipelineObserver | None = None,
) -> tuple[list[XSignal], list[NewsItem], dict[str, list[str]]]:
    """Grok X 키워드 기반 시장 반응을 수집한다."""
    if not settings.grok_x_keyword_search_enabled or not settings.grok_api_key:
        return [], [], {}

    return fetch_x_keyword_signals(
        api_key=settings.grok_api_key,
        model=settings.grok_model,
        lookback_hours=settings.official_x_lookback_hours,
        max_items=settings.grok_x_search_max_items,
        observer=observer,
    )


def _collect_grok_web_news(
    settings: Settings,
    *,
    observer: PipelineObserver | None = None,
) -> list[NewsItem]:
    """Grok Web Search로 뉴스를 수집한다."""
    if not settings.grok_web_search_enabled or not settings.grok_api_key:
        return []

    return fetch_grok_web_news(
        api_key=settings.grok_api_key,
        model=settings.grok_model,
        max_items=settings.grok_web_search_max_items,
        observer=observer,
    )


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
        logger.debug("뉴스 수집은 Google News RSS 우선 결과를 사용했어요.")

    if len(items) < MIN_NEWS_ITEMS and newsapi_key:
        try:
            newsapi_items = _collect_from_newsapi(newsapi_key, max_items=candidate_limit)
            items = _merge_rank(items, newsapi_items, max_items=candidate_limit)
            if newsapi_items:
                logger.debug("뉴스 보강에는 NewsAPI를 함께 사용했어요.")
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
        logger.debug("최근 운영 이력이 안정적이라 broad legacy fallback은 이번엔 건너뛸게요.")

    final_items = _dedup_and_rank(items, max_items=max_items)
    if final_items:
        logger.debug("legacy 뉴스 provider 비중은 %s였어요.", _provider_breakdown(final_items))
    elif candidate_limit >= MIN_NEWS_ITEMS:
        logger.warning(
            "RSS와 NewsAPI까지 확인했지만 legacy 뉴스가 최소 기준(%s건)을 채우지 못했어요.",
            MIN_NEWS_ITEMS,
        )
    return final_items


def build_news_packet(
    *,
    settings: Settings,
    observer: PipelineObserver | None = None,
    keywords_by_topic: dict[str, list[str]] | None = None,
) -> tuple[list[dict], dict[str, TopicSummary], list[XSignal]]:
    """뉴스 패킷을 구성한다.

    Returns:
        (news_packet, topic_summaries, x_signals) 튜플.
        기존 호출자와의 하위 호환을 위해 news_packet은 list[dict] 유지.
    """
    items: list[NewsItem] = []
    legacy_items: list[NewsItem] = []
    official_signal_items = _collect_official_signal_items(settings, observer=observer)
    allow_broad_fallback = True
    fallback_review: dict | None = None

    # --- 신규: Sonar 요약 + Grok X 키워드 + Grok Web Search ---
    topic_summaries, sonar_news = _collect_sonar_summaries(settings, observer=observer)
    x_signals, x_news, grok_keywords = _collect_x_keyword_signals(settings, observer=observer)
    grok_web_news = _collect_grok_web_news(settings, observer=observer)

    # official signals와 keyword signals 간 source_handle 기반 dedup
    if x_news and official_signal_items:
        official_handles = {it.source.lstrip("@") for it in official_signal_items}
        x_news = [n for n in x_news if n.source.lstrip("@") not in official_handles]

    # Grok 키워드를 Perplexity 쿼리 키워드에 합산
    if grok_keywords:
        if keywords_by_topic is None:
            keywords_by_topic = {}
        for sector, kws in grok_keywords.items():
            keywords_by_topic.setdefault(sector, []).extend(kws)

    if settings.research_provider == "perplexity":
        # Sonar 모드가 켜져 있으면 Sonar citations에서 추출한 NewsItem을 우선 사용
        if settings.perplexity_use_sonar and sonar_news:
            items = sonar_news
        else:
            items = fetch_news_from_perplexity(
                max_items=settings.max_news_items,
                api_key=settings.perplexity_api_key,
                observer=observer,
                keywords_by_topic=keywords_by_topic,
            )
        if not items and observer is not None:
            observer.log_event(
                "perplexity_degraded",
                reason="Perplexity 결과가 비어 있어 legacy 뉴스와 Grok 보조 모드로 전환했어요.",
            )

        # Perplexity 0건 시 Gemini fallback
        if not items and settings.gemini_api_key:
            gemini_items = fetch_gemini_grounding(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                topics=["macro", "ai_bigtech", "bitcoin", "us_equity"],
                keywords_by_topic=keywords_by_topic,
                observer=observer,
            )
            if gemini_items:
                items = gemini_items
                logger.info("Gemini grounding fallback으로 %d건 수집", len(gemini_items))

        # Grok X 키워드 + Web Search 결과 병합
        if x_news:
            items = _merge_rank(items, x_news, max_items=settings.max_news_items * 2)
        if grok_web_news:
            items = _merge_rank(items, grok_web_news, max_items=settings.max_news_items * 2)

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
        # Grok 결과도 legacy 모드에서 병합
        if x_news:
            items = _merge_rank(items, x_news, max_items=settings.max_news_items)
        if grok_web_news:
            items = _merge_rank(items, grok_web_news, max_items=settings.max_news_items)

    if items:
        packet, final_summary = _packet_summary(items)
        if observer is not None:
            observer.record_perplexity_final_selection(packet)
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
        return packet, topic_summaries, x_signals

    return _news_items_to_packet(items), topic_summaries, x_signals
