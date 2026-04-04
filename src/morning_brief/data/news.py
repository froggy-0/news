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
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver
from morning_brief.public_news_analysis import enrich_public_news_packet

logger = logging.getLogger(__name__)

PUBLIC_FEATURED_NEWS_ITEMS = 5
PUBLIC_ALL_NEWS_ITEMS = 12
PUBLIC_FEATURED_X_SIGNALS = 6
PUBLIC_ALL_X_SIGNALS = 12

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
filter_publish_news = news_selection.filter_publish_news
filter_publish_news_candidates = news_selection.filter_publish_news_candidates
filter_public_article_news = news_selection.filter_public_article_news
filter_public_article_news_candidates = news_selection.filter_public_article_news_candidates
filter_publish_x_signals = news_selection.filter_publish_x_signals
filter_publish_x_signal_candidates = news_selection.filter_publish_x_signal_candidates
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
        if observer is not None:
            observer.log_event(
                "grok_signal_omitted",
                level=logging.WARNING,
                message="Grok 공식 X 시그널을 가져오지 못해 해당 섹션은 생략할게요.",
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        else:
            log_structured(
                logger,
                event="fallback.used",
                message="Grok 공식 X 시그널을 가져오지 못해 해당 섹션은 생략할게요.",
                level=logging.WARNING,
                provider="grok_official",
                reason=str(exc),
                error_type=type(exc).__name__,
            )
        return []
    if items:
        log_structured(
            logger,
            event="selection.complete",
            message="검증된 공식 X 시그널을 함께 반영했어요.",
            provider="grok_official",
            kept_count=len(items),
        )
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
        log_structured(
            logger,
            event="error.raised",
            message="Sonar 요약 수집 중 오류가 발생해 건너뛸게요.",
            level=logging.WARNING,
            provider="perplexity",
            reason=str(exc),
            error_type=type(exc).__name__,
        )
        return {}, []
    news_items = collect_sonar_news_items(summaries)
    if summaries:
        log_structured(
            logger,
            event="selection.complete",
            message="Sonar 요약과 citations 기반 NewsItem을 정리했어요.",
            provider="perplexity",
            candidate_count=len(summaries),
            kept_count=len(news_items),
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
        log_structured(
            logger,
            event="selection.complete",
            message="뉴스 수집은 Google News RSS 우선 결과를 사용했어요.",
            level=logging.DEBUG,
            provider="google_news_rss",
            kept_count=len(items),
        )

    if len(items) < MIN_NEWS_ITEMS and newsapi_key:
        try:
            newsapi_items = _collect_from_newsapi(newsapi_key, max_items=candidate_limit)
            items = _merge_rank(items, newsapi_items, max_items=candidate_limit)
            if newsapi_items:
                log_structured(
                    logger,
                    event="fallback.used",
                    message="뉴스 보강에는 NewsAPI를 함께 사용했어요.",
                    level=logging.DEBUG,
                    provider="newsapi",
                    kept_count=len(newsapi_items),
                )
        except (HttpFetchError, ValueError) as exc:
            log_structured(
                logger,
                event="error.raised",
                message="NewsAPI에서 뉴스를 가져오지 못했어요.",
                level=logging.WARNING,
                provider="newsapi",
                reason=str(exc),
                error_type=type(exc).__name__,
            )

    if len(items) < MIN_NEWS_ITEMS and allow_broad_fallback:
        log_structured(
            logger,
            event="fallback.used",
            message="우선 신뢰 출처가 부족해 범위를 넓혀 RSS를 한 번 더 살펴봤어요.",
            provider="google_news_rss",
            candidate_count=len(items),
        )
        rss_broad = _collect_from_rss(max_items=candidate_limit, preferred_only=False)
        items = _merge_rank(items, rss_broad, max_items=candidate_limit)
    elif len(items) < MIN_NEWS_ITEMS and not allow_broad_fallback:
        log_structured(
            logger,
            event="phase.skip",
            message="최근 운영 이력이 안정적이라 broad legacy fallback은 이번엔 건너뛸게요.",
            level=logging.DEBUG,
            reason="legacy_broad_disabled",
        )

    final_items = _dedup_and_rank(items, max_items=max_items)
    if final_items:
        log_structured(
            logger,
            event="selection.complete",
            message="legacy 뉴스 provider 비중을 정리했어요.",
            level=logging.DEBUG,
            provider_breakdown=_provider_breakdown(final_items),
            kept_count=len(final_items),
        )
    elif candidate_limit >= MIN_NEWS_ITEMS:
        log_structured(
            logger,
            event="selection.complete",
            message="RSS와 NewsAPI까지 확인했지만 legacy 뉴스가 최소 기준을 채우지 못했어요.",
            level=logging.WARNING,
            candidate_count=candidate_limit,
            kept_count=0,
            reason=f"minimum={MIN_NEWS_ITEMS}",
        )
    return final_items


def _dedup_x_signals(signals: list[XSignal]) -> list[XSignal]:
    """source_handle + headline[:30] 복합 키로 중복 XSignal을 제거한다.

    충돌 시 posted_at 최신 것을 유지한다. 동일하거나 None이면 기존 항목 유지.
    """
    seen: dict[str, XSignal] = {}
    for signal in signals:
        key = f"{signal.source_handle.lower()}:{signal.headline[:30].lower().strip()}"
        existing = seen.get(key)
        if existing is None:
            seen[key] = signal
        elif signal.posted_at is not None and (
            existing.posted_at is None or signal.posted_at > existing.posted_at
        ):
            seen[key] = signal

    removed = len(signals) - len(seen)
    if removed > 0:
        log_structured(
            logger,
            event="dedup.applied",
            message=f"XSignal 중복 {removed}건 제거됨",
            level=logging.DEBUG,
            provider="x_signal",
            removed_count=removed,
        )
    return list(seen.values())


def _cap_signals_by_topic(
    signals: list[XSignal],
    *,
    total_max: int,
    per_topic_max: int,
    sentiment_diversity: bool = False,
) -> list[XSignal]:
    """topic별 per_topic_max개로 제한하면서 최대 total_max개를 반환.

    sentiment_diversity=True이면 동일 topic 내 두 번째 선택 시
    이미 선택된 sentiment와 다른 sentiment를 우선한다.
    """
    topic_counts: dict[str, int] = {}
    topic_sentiments: dict[str, set[str]] = {}
    result: list[XSignal] = []
    deferred: list[XSignal] = []

    for signal in signals:
        topic = signal.topic or "unknown"
        count = topic_counts.get(topic, 0)
        if count >= per_topic_max:
            continue
        if sentiment_diversity and count >= 1:
            chosen = topic_sentiments.get(topic, set())
            if signal.sentiment in chosen:
                deferred.append(signal)
                continue
        result.append(signal)
        topic_counts[topic] = count + 1
        topic_sentiments.setdefault(topic, set()).add(signal.sentiment)
        if len(result) >= total_max:
            return result

    # 2차 패스: sentiment 제한 없이 deferred 항목으로 채움
    for signal in deferred:
        topic = signal.topic or "unknown"
        if topic_counts.get(topic, 0) >= per_topic_max:
            continue
        result.append(signal)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(result) >= total_max:
            break

    return result


def build_news_packet(
    *,
    settings: Settings,
    observer: PipelineObserver | None = None,
    keywords_by_topic: dict[str, list[str]] | None = None,
) -> tuple[list[dict], dict[str, TopicSummary], list[XSignal], dict[str, object]]:
    """뉴스 패킷을 구성한다.

    Returns:
        (news_packet, topic_summaries, x_signals, public_context) 튜플.
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

    public_merge_limit = max(PUBLIC_ALL_NEWS_ITEMS * 2, settings.max_news_items * 2)
    public_fetch_limit = max(PUBLIC_ALL_NEWS_ITEMS, settings.max_news_items)

    if settings.research_provider == "perplexity":
        items = fetch_news_from_perplexity(
            max_items=public_fetch_limit,
            api_key=settings.perplexity_api_key,
            observer=observer,
            keywords_by_topic=keywords_by_topic,
        )
        if not items and settings.perplexity_use_sonar and sonar_news:
            items = sonar_news
            log_structured(
                logger,
                event="fallback.used",
                message="Perplexity Search 결과가 비어 Sonar citations를 보조 뉴스로 사용할게요.",
                provider="perplexity",
                candidate_count=len(sonar_news),
                reason="search_empty",
            )
            if observer is not None:
                observer.log_event(
                    "perplexity_sonar_degraded",
                    reason="search_empty",
                    count=len(sonar_news),
                )
        elif items and settings.perplexity_use_sonar and sonar_news:
            log_structured(
                logger,
                event="selection.complete",
                message="Sonar 요약은 맥락 보강에만 쓰고 실제 뉴스 본문은 Perplexity Search 결과를 우선 사용할게요.",
                provider="perplexity",
                candidate_count=len(sonar_news),
                kept_count=len(items),
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
                log_structured(
                    logger,
                    event="fallback.used",
                    message="Gemini grounding fallback으로 뉴스를 수집했어요.",
                    provider="gemini",
                    kept_count=len(gemini_items),
                )

        # Grok X 키워드 + Web Search 결과 병합
        if x_news:
            items = _merge_rank(items, x_news, max_items=public_merge_limit)
        if grok_web_news:
            items = _merge_rank(items, grok_web_news, max_items=public_merge_limit)

        if official_signal_items:
            items = _merge_rank(items, official_signal_items, max_items=public_merge_limit)
        items = _dedup_and_rank(items, max_items=public_merge_limit)
        public_candidate_items, publish_candidate_audit = filter_publish_news_candidates(items)
        packet, _ = _packet_summary(public_candidate_items)
        fallback_review = assess_perplexity_fallback_need(packet)
        assert fallback_review is not None
        needs_legacy_fallback = bool(fallback_review.get("needs_legacy_fallback", False))
        fallback_reasons = [
            str(reason).strip()
            for reason in fallback_review.get("reasons", [])
            if str(reason).strip()
        ]
        fallback_count = int(fallback_review.get("count", 0))
        fallback_unique_domains = int(fallback_review.get("unique_domains", 0))
        fallback_topic_coverage_count = int(fallback_review.get("topic_coverage_count", 0))
        if observer is not None:
            observer.log_event(
                "public_publish_news_candidates",
                candidate_count=publish_candidate_audit["candidate_count"],
                kept_count=publish_candidate_audit["kept_count"],
                dropped=publish_candidate_audit["dropped"],
            )
        if needs_legacy_fallback and settings.enable_legacy_news_fallback:
            reduce_broad_fallback = should_reduce_legacy_broad_fallback(settings.cache_dir)
            allow_broad_fallback = not (
                reduce_broad_fallback and not _needs_full_legacy_backfill(fallback_review)
            )
            log_structured(
                logger,
                event="fallback.used",
                message="Perplexity와 공식 시그널 결과를 살펴보니 legacy 뉴스로 빈 부분을 함께 채울게요.",
                provider="perplexity",
                reason="; ".join(fallback_reasons),
            )
            if reduce_broad_fallback and not allow_broad_fallback:
                log_structured(
                    logger,
                    event="fallback.used",
                    message="최근 Perplexity 결과가 안정적이어서 이번에는 선별된 legacy fallback만 사용할게요.",
                    provider="perplexity",
                    reason="reduced_legacy_broad_fallback",
                )
            legacy_items = fetch_news(
                max_items=PUBLIC_ALL_NEWS_ITEMS,
                newsapi_key=settings.newsapi_key,
                allow_broad_fallback=allow_broad_fallback,
            )
            items = _merge_rank(items, legacy_items, max_items=public_merge_limit)
        elif not items:
            log_structured(
                logger,
                event="selection.complete",
                message="Perplexity 연구 결과가 없고 legacy 뉴스 폴백도 꺼져 있어서 빈 뉴스 묶음을 유지할게요.",
                level=logging.WARNING,
                kept_count=0,
                reason="empty_without_legacy_fallback",
            )
        else:
            log_structured(
                logger,
                event="selection.complete",
                message="Perplexity와 공식 시그널만으로도 기사/도메인/토픽 기준을 채웠어요.",
                provider="perplexity",
                kept_count=fallback_count,
                unique_domains=fallback_unique_domains,
                topic_coverage_count=fallback_topic_coverage_count,
            )
    else:
        legacy_items = fetch_news(
            max_items=PUBLIC_ALL_NEWS_ITEMS,
            newsapi_key=settings.newsapi_key,
        )
        items = _merge_rank(legacy_items, official_signal_items, max_items=public_merge_limit)
        # Grok 결과도 legacy 모드에서 병합
        if x_news:
            items = _merge_rank(items, x_news, max_items=public_merge_limit)
        if grok_web_news:
            items = _merge_rank(items, grok_web_news, max_items=public_merge_limit)

    public_candidate_items, publish_candidate_audit = filter_public_article_news_candidates(items)
    public_ranked_items = _dedup_and_rank(
        public_candidate_items,
        max_items=PUBLIC_ALL_NEWS_ITEMS,
        min_output=3,
    )
    publish_news_items, publish_news_audit = filter_public_article_news(public_ranked_items)
    email_ranked_items = _dedup_and_rank(items, max_items=settings.max_news_items)
    public_ranked_signals = _cap_signals_by_topic(
        _dedup_x_signals(x_signals),
        total_max=PUBLIC_ALL_X_SIGNALS,
        per_topic_max=4,
    )
    public_candidate_signals, publish_signal_candidate_audit = filter_publish_x_signal_candidates(
        public_ranked_signals
    )
    publish_signals, publish_signal_audit = filter_publish_x_signals(public_candidate_signals)
    featured_publish_signals = _cap_signals_by_topic(
        publish_signals,
        total_max=PUBLIC_FEATURED_X_SIGNALS,
        per_topic_max=2,
        sentiment_diversity=True,
    )

    if observer is not None:
        observer.log_event(
            "public_publish_news_selection",
            candidate_count=publish_news_audit["candidate_count"],
            kept_count=publish_news_audit["kept_count"],
            below_minimum=publish_news_audit["below_minimum"],
            dropped=publish_news_audit["dropped"],
        )
        observer.log_event(
            "public_publish_x_candidates",
            candidate_count=publish_signal_candidate_audit["candidate_count"],
            kept_count=publish_signal_candidate_audit["kept_count"],
            dropped=publish_signal_candidate_audit["dropped"],
        )
        observer.log_event(
            "public_publish_x_selection",
            candidate_count=publish_signal_audit["candidate_count"],
            kept_count=publish_signal_audit["kept_count"],
            below_minimum=publish_signal_audit["below_minimum"],
            dropped=publish_signal_audit["dropped"],
        )

    public_news_packet = _news_items_to_packet(publish_news_items)
    public_news_packet, public_news_analysis_audit = enrich_public_news_packet(
        items=public_news_packet,
        settings=settings,
        observer=observer,
    )

    if observer is not None:
        observer.log_event(
            "public_news_analysis_selection",
            candidate_count=public_news_analysis_audit.candidate_count,
            requested_count=public_news_analysis_audit.requested_count,
            success_count=public_news_analysis_audit.success_count,
            skipped_count=public_news_analysis_audit.skipped_count,
            failed_count=public_news_analysis_audit.failed_count,
            status=public_news_analysis_audit.status,
        )

    public_context: dict[str, object] = {
        "featured_news": public_news_packet[:PUBLIC_FEATURED_NEWS_ITEMS],
        "all_news": public_news_packet,
        "featured_x_signals": [
            {
                "headline": signal.headline,
                "summary": signal.summary,
                "why_it_matters": signal.why_it_matters,
                "sentiment": signal.sentiment,
                "source_handle": signal.source_handle,
                "posted_at": signal.posted_at.isoformat() if signal.posted_at else None,
                "topic": signal.topic,
                "citations": signal.citations,
            }
            for signal in featured_publish_signals
        ],
        "all_x_signals": [
            {
                "headline": signal.headline,
                "summary": signal.summary,
                "why_it_matters": signal.why_it_matters,
                "sentiment": signal.sentiment,
                "source_handle": signal.source_handle,
                "posted_at": signal.posted_at.isoformat() if signal.posted_at else None,
                "topic": signal.topic,
                "citations": signal.citations,
            }
            for signal in publish_signals
        ],
        "source_counts": {
            "newsCandidates": len(items),
            "newsRanked": len(public_ranked_items),
            "newsFeatured": min(len(publish_news_items), PUBLIC_FEATURED_NEWS_ITEMS),
            "newsAll": len(publish_news_items),
            "xSignalCandidates": len(x_signals),
            "xSignalRanked": len(public_candidate_signals),
            "xSignalFeatured": len(featured_publish_signals),
            "xSignalAll": len(publish_signals),
        },
        "public_news_analysis": {
            "candidateCount": public_news_analysis_audit.candidate_count,
            "requestedCount": public_news_analysis_audit.requested_count,
            "successCount": public_news_analysis_audit.success_count,
            "failedCount": public_news_analysis_audit.failed_count,
            "skippedCount": public_news_analysis_audit.skipped_count,
            "status": public_news_analysis_audit.status,
        },
    }

    if email_ranked_items:
        packet, final_summary = _packet_summary(email_ranked_items)
        if observer is not None:
            observer.record_perplexity_final_selection(packet)
        perplexity_count, official_signal_count, legacy_count, provider_breakdown = (
            _provider_counts(email_ranked_items)
        )
        log_structured(
            logger,
            event="selection.complete",
            message="최종 뉴스 구성을 정리했어요.",
            candidate_count=len(items),
            kept_count=len(email_ranked_items),
            provider_breakdown=provider_breakdown,
            unique_domains=final_summary["unique_domains"],
            topic_coverage_count=final_summary["topic_coverage_count"],
            perplexity_count=perplexity_count,
            official_signal_count=official_signal_count,
            legacy_count=legacy_count,
        )
        if settings.research_provider == "perplexity" and fallback_review is not None:
            record_news_rollout_run(
                cache_dir=settings.cache_dir,
                fallback_review=fallback_review,
                used_legacy=bool(legacy_items),
                allow_broad_fallback=allow_broad_fallback,
                provider_breakdown=provider_breakdown,
            )
        return packet, topic_summaries, x_signals, public_context

    return _news_items_to_packet(email_ranked_items), topic_summaries, x_signals, public_context
