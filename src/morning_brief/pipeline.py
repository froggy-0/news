from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from morning_brief.analysis.sentiment_join.intelligence import load_sentiment_intelligence
from morning_brief.analysis.sentiment_join.risk_overlay import RiskOverlay, compute_risk_overlay
from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.data_quality import (
    MIN_NEWS_ITEMS,
    MIN_PREFERRED_NEWS_ITEMS,
    MIN_TIER_1_NEWS_ITEMS,
    assess_data_quality,
)
from morning_brief.data.market import (
    build_market_packet,
    fetch_newsletter_display_data,
    reset_market_warned_state,
)
from morning_brief.data.market_keywords import build_search_keywords, extract_market_keywords
from morning_brief.data.news import PUBLIC_FEATURED_NEWS_ITEMS, build_news_packet
from morning_brief.data.news_packet import NewsPacketItem
from morning_brief.data.sources.provider_runtime import (
    provider_stats_snapshot,
    reset_provider_runtime_state,
)
from morning_brief.emailer import SesSender
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.llm_provider_policy import provider_role_snapshot
from morning_brief.logging_utils import log_structured
from morning_brief.observability import PipelineObserver
from morning_brief.public_site import publish_public_brief
from morning_brief.raw_capture import try_raw_capture
from morning_brief.research_backfill import (
    _needs_web_search_backfill,
    backfill_news_with_web_search,
)

logger = logging.getLogger(__name__)

_assess_data_quality = assess_data_quality


def _load_sentiment_intelligence_packet() -> dict | None:
    output_dir = Path(os.getenv("SENTIMENT_JOIN_OUTPUT_DIR", "data/sentiment_join")).resolve()
    return load_sentiment_intelligence(output_dir)


def _load_risk_overlay() -> RiskOverlay | None:
    """Risk Overlay 산출. 두 가지 경로를 순서대로 시도한다.

    경로 1 (선호): latest.json의 riskOverlay 필드 직접 읽기.
                   sentiment-join이 먼저 실행된 환경(CI 정상 순서)에서 동작.
    경로 2 (로컬 fallback): parquet을 직접 읽어 산출.
                            로컬 개발 환경에서 동작.
    """
    import json

    output_dir = Path(os.getenv("SENTIMENT_JOIN_OUTPUT_DIR", "data/sentiment_join")).resolve()
    artifact_path = output_dir / "latest.json"

    # 경로 1: latest.json → riskOverlay 필드
    if artifact_path.exists():
        try:
            with artifact_path.open() as fp:
                artifact = json.load(fp)

            ro_dict = artifact.get("riskOverlay")
            if ro_dict and isinstance(ro_dict, dict):
                from morning_brief.analysis.sentiment_join.risk_overlay import (
                    RegimeState,
                    SignalConfidence,
                    VolEnvironment,
                )

                return RiskOverlay(
                    regime=RegimeState(
                        label=ro_dict.get("regimeState", "Choppy"),
                        description=ro_dict.get("regimeDescription", ""),
                        raw=ro_dict.get("regimeRaw") or {},
                    ),
                    vol=VolEnvironment(
                        level=ro_dict.get("volLevel", "Mid"),
                        trend=ro_dict.get("volTrend", "stable"),
                        description=ro_dict.get("volDescription", ""),
                    ),
                    confidence=SignalConfidence(
                        level=ro_dict.get("signalConfidence"),
                        reasons=ro_dict.get("signalReasons") or [],
                        reason_labels=ro_dict.get("signalReasonLabels") or [],
                    ),
                    overlay_gate_decision=ro_dict.get("overlayGateDecision", "research_only"),
                )
        except Exception as exc:
            log_structured(
                logger,
                event="risk_overlay.json_read_failed",
                level=logging.WARNING,
                message="latest.json riskOverlay 읽기 실패 — parquet fallback 시도",
                reason=str(exc),
            )

    # 경로 2: parquet 직접 산출 (로컬 fallback)
    try:
        import pandas as pd

        parquets = sorted(output_dir.glob("sentiment_join_master_*.parquet"))
        if not parquets:
            return None
        df = pd.read_parquet(parquets[-1])

        overlay_decision = "research_only"
        if artifact_path.exists():
            with artifact_path.open() as fp:
                artifact = json.load(fp)
            overlay_decision = (
                artifact.get("alpha", {})
                .get("promotionGate", {})
                .get("volRegimeV2Overlay", {})
                .get("decision", "research_only")
            )

        return compute_risk_overlay(df, overlay_decision)
    except Exception as exc:
        log_structured(
            logger,
            event="risk_overlay.failed",
            level=logging.WARNING,
            message="risk overlay 산출에 실패했지만 파이프라인을 계속합니다.",
            reason=str(exc),
        )
        return None


def _needs_public_news_backfill(public_context: dict) -> bool:
    counts = public_context.get("source_counts", {})
    if not isinstance(counts, dict):
        return True
    try:
        return int(counts.get("newsFeatured", 0)) < PUBLIC_FEATURED_NEWS_ITEMS
    except (TypeError, ValueError):
        return True


def _needs_email_news_backfill(quality: dict) -> bool:
    if not isinstance(quality, dict):
        return True

    def _count(key: str) -> int:
        try:
            return int(quality.get(key, 0))
        except (TypeError, ValueError):
            return 0

    news_count = _count("news_count")
    preferred_signal_count = _count("preferred_news_count") + _count("official_signal_count")
    authoritative_signal_count = _count("tier_1_news_count") + _count("official_signal_count")
    return (
        news_count < MIN_NEWS_ITEMS
        or preferred_signal_count < MIN_PREFERRED_NEWS_ITEMS
        or authoritative_signal_count < MIN_TIER_1_NEWS_ITEMS
    )


def run_pipeline(settings: Settings) -> str:
    reset_provider_runtime_state()
    reset_market_warned_state()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    observer = PipelineObserver(output_dir=settings.output_dir)
    observer.record_cache_status_from_env()
    observer.log_event("provider_role_policy", policies=provider_role_snapshot())
    log_structured(
        logger,
        event="run.start",
        message="브리핑 파이프라인을 시작할게요.",
        phase="run",
    )
    pipeline_started_at = time.perf_counter()
    market_packet: dict = {}
    news_packet: list[NewsPacketItem] = []
    public_context: dict = {}
    packet: dict = {}
    briefing = ""
    output_path = None
    status = "ok"
    brief_fallback_used = False
    failure_message = ""
    failure_exc: Exception | None = None

    try:
        with observer.phase("market"):
            market_packet = build_market_packet(
                fred_api_key=settings.fred_api_key,
                perplexity_api_key=settings.perplexity_api_key,
                cache_dir=settings.cache_dir,
                observer=observer,
                cache_max_age_hours=settings.market_point_cache_max_age_hours,
            )
        with observer.phase("news"):
            market_keywords = extract_market_keywords(market_packet)
            keywords_by_topic = build_search_keywords(market_keywords)
            if market_keywords and observer is not None:
                observer.log_event(
                    "market_keywords_extracted",
                    keywords=market_keywords,
                )
            news_packet, topic_summaries, x_signals, public_context = build_news_packet(
                settings=settings,
                observer=observer,
                keywords_by_topic=keywords_by_topic,
            )
        log_structured(
            logger,
            event="data.collect.complete",
            message="시장 지표와 뉴스 묶음을 준비했어요.",
            phase="news",
            news_count=len(news_packet),
        )

        # raw capture: 시장/뉴스 수집 경계 payload 저장
        run_date = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d")
        try_raw_capture(
            settings=settings,
            run_date=run_date,
            market_packet=market_packet,
            news_packet=news_packet,
            public_context=public_context,
        )

        # ── FinBERT sentiment enrichment ──
        from morning_brief.data.finbert_sentiment import (
            build_public_news_sentiment_text as _build_public_news_text,
        )
        from morning_brief.data.finbert_sentiment import enrich_news_packet as _enrich_news
        from morning_brief.data.finbert_sentiment import (
            enrich_public_signal_items as _enrich_public_signals,
        )
        from morning_brief.data.finbert_sentiment import enrich_x_signals as _enrich_signals

        _enrich_news(news_packet, settings, observer)
        _enrich_signals(x_signals, settings, observer)
        raw_public_news = public_context.get("all_news", [])
        if isinstance(raw_public_news, list):
            public_news = raw_public_news
            if any(not isinstance(item, dict) for item in public_news):
                public_news = [item for item in public_news if isinstance(item, dict)]
                public_context["all_news"] = public_news
        else:
            public_news = []
        public_context["sentiment_status"] = _enrich_news(
            public_news,
            settings,
            observer,
            text_builder=_build_public_news_text,
        )
        raw_all_public_signals = public_context.get("all_x_signals", [])
        if isinstance(raw_all_public_signals, list):
            public_signal_items = raw_all_public_signals
            if any(not isinstance(item, dict) for item in public_signal_items):
                public_signal_items = [
                    item for item in public_signal_items if isinstance(item, dict)
                ]
                public_context["all_x_signals"] = public_signal_items
        else:
            public_signal_items = []
        raw_featured_public_signals = public_context.get("featured_x_signals", [])
        if isinstance(raw_featured_public_signals, list):
            featured_public_signal_items = raw_featured_public_signals
            if any(not isinstance(item, dict) for item in featured_public_signal_items):
                featured_public_signal_items = [
                    item for item in featured_public_signal_items if isinstance(item, dict)
                ]
                public_context["featured_x_signals"] = featured_public_signal_items
        else:
            featured_public_signal_items = []
        public_context["signal_sentiment_status"] = _enrich_public_signals(
            public_signal_items,
            settings,
            observer,
        )
        _enrich_public_signals(
            featured_public_signal_items,
            settings,
            observer,
        )

        packet = {
            **market_packet,
            "news": news_packet,
        }
        try:
            sentiment_intelligence = _load_sentiment_intelligence_packet()
        except Exception as exc:
            sentiment_intelligence = None
            log_structured(
                logger,
                event="source.failed",
                message="sentiment intelligence를 읽지 못했지만 브리핑은 계속 생성합니다.",
                level=logging.WARNING,
                source="sentiment_join",
                reason=str(exc),
            )
        if sentiment_intelligence is not None:
            packet["sentiment_intelligence"] = sentiment_intelligence

        risk_overlay = _load_risk_overlay()
        if risk_overlay is not None:
            packet["risk_overlay"] = risk_overlay.to_dict()

        # 트랙레코드 조회 (Supabase 미설정 환경에서는 빈값으로 graceful 처리)
        if settings.supabase_url and settings.supabase_service_role_key:
            try:
                from morning_brief.signal_logger import fetch_track_record

                packet["signal_track_record"] = fetch_track_record(
                    supabase_url=settings.supabase_url,
                    service_role_key=settings.supabase_service_role_key,
                    days=90,
                )
            except Exception as _tr_exc:
                log_structured(
                    logger,
                    event="track_record.failed",
                    level=logging.WARNING,
                    message="트랙레코드 조회 실패 — 파이프라인에는 영향 없음",
                    reason=str(_tr_exc),
                )

        # 신규 데이터 소스를 packet에 추가 (브리핑 프롬프트에서 활용)
        if topic_summaries:
            from morning_brief.data.sources.perplexity_sonar import topic_summaries_to_dict

            packet["topic_summaries"] = topic_summaries_to_dict(topic_summaries)
        if x_signals:
            from morning_brief.data.sources.grok_x_keyword import x_signals_to_dict

            packet["x_market_signals"] = x_signals_to_dict(x_signals)

        # Phase 3: Sonar 맥락 보강
        if news_packet and settings.perplexity_use_sonar and settings.perplexity_api_key:
            from morning_brief.data.sources.perplexity_sonar import fetch_sonar_context

            context_articles = [
                {
                    "topic": n.get("topic", ""),
                    "title": n.get("title", ""),
                    "summary": n.get("summary", ""),
                }
                for n in news_packet[:12]
                if n.get("title")
            ]
            sonar_context = fetch_sonar_context(
                api_key=settings.perplexity_api_key,
                articles=context_articles,
                observer=observer,
            )
            if sonar_context:
                packet["sonar_context"] = {
                    "analyses": sonar_context.analyses,
                    "key_narrative": sonar_context.key_narrative,
                }

        quality = _assess_data_quality(packet=packet, news_packet=news_packet)
        with observer.phase("backfill"):
            public_needs_backfill = _needs_public_news_backfill(public_context)
            email_needs_backfill = _needs_email_news_backfill(quality)
            if not settings.openai_web_search_enabled:
                observer.log_event(
                    "backfill_skipped",
                    reason="OpenAI web_search 백필 설정이 꺼져 있어 현재 뉴스 묶음을 유지할게요.",
                )
            elif not _needs_web_search_backfill(quality):
                observer.log_event(
                    "backfill_skipped",
                    reason="현재 뉴스 품질이 백필 기준을 넘겨 OpenAI web_search는 건너뛸게요.",
                )
            elif not email_needs_backfill:
                observer.log_event(
                    "backfill_skipped",
                    reason="이메일 기준 신뢰 출처 뉴스와 공식 시그널이 이미 충분해 OpenAI web_search는 건너뛸게요.",
                )
            elif not public_needs_backfill:
                observer.log_event(
                    "backfill_skipped",
                    reason="공개 홈 기준 featured 뉴스가 이미 충분해 OpenAI web_search는 건너뛸게요.",
                )
            else:
                merged_news, references = backfill_news_with_web_search(
                    packet=packet,
                    quality=quality,
                    settings=settings,
                    observer=observer,
                )
                news_packet = merged_news
                packet["news"] = merged_news
                packet["web_search_references"] = references
                quality = _assess_data_quality(packet=packet, news_packet=news_packet)

        packet["data_quality"] = quality
        if quality["status"] == "critical":
            status = "degraded"
            log_structured(
                logger,
                event="quality.degraded",
                message="데이터 품질이 critical이어서 실행 상태를 degraded로 남길게요.",
                level=logging.WARNING,
                quality_status=quality["status"],
                reason="; ".join(quality["warnings"]),
            )
        elif quality["status"] != "ok":
            log_structured(
                logger,
                event="quality.warning",
                message="데이터 품질 경고가 있어 확인이 필요해요.",
                level=logging.WARNING,
                quality_status=quality["status"],
                reason="; ".join(quality["warnings"]),
            )

        briefing = generate_briefing(packet=packet, settings=settings, observer=observer)

        # unified-pipeline: 공통 레이어 생성 (Phase 1 — 채널 분기 전 SSOT 확립)
        # 기존 packet / briefing 변수는 그대로 유지 (하위 호환 참조)
        try:
            from morning_brief.unified_output import (
                MetaLayer,
                UnifiedOutput,
                briefing_to_narrative,
                packet_to_quantitative,
            )

            unified = UnifiedOutput(
                quantitative=packet_to_quantitative(packet),
                narrative=briefing_to_narrative(briefing, packet, public_context),
                meta=MetaLayer(
                    run_at=datetime.now(ZoneInfo(settings.timezone)).isoformat(),
                    pipeline_version="2.0",
                    source_counts=packet.get("data_quality") or {},
                    translation_status="skipped",  # Phase 2에서 갱신
                ),
            )
            observer.log_event(
                "unified_output_created",
                quantitative_keys=list(unified.quantitative.sparkline_data.keys()),
                narrative_optional_present=[
                    f
                    for f in (
                        "sector_mapping",
                        "event_calendar",
                        "issue_briefings",
                        "weekly_context",
                        "sonar_analyses",
                    )
                    if getattr(unified.narrative, f) is not None
                ],
            )
        except Exception as unified_exc:
            observer.log_event(
                "unified_output_failed",
                level=logging.ERROR,
                message="unified_output 생성에 실패해 기존 경로로 계속 진행할게요.",
                reason=str(unified_exc),
                error_type=type(unified_exc).__name__,
            )
            unified = None

        brief_fallback_used = any(
            str(event.get("event", "")).strip() == "brief_fallback_used"
            for event in observer.events
        )
        if brief_fallback_used and status == "ok":
            status = "brief_fallback"
            log_structured(
                logger,
                event="fallback.used",
                message="최종 브리핑이 안전한 기본 브리핑으로 대체돼 brief_fallback으로 남길게요.",
                level=logging.WARNING,
                reason="brief_fallback_used",
            )

        now = datetime.now(ZoneInfo(settings.timezone))
        file_name = now.strftime("brief_%Y%m%d_%H%M.md")
        output_path = settings.output_dir / file_name
        output_path.write_text(briefing, encoding="utf-8")
        log_structured(
            logger,
            event="artifact.created",
            message="브리핑 파일을 저장했어요.",
            artifact_type="brief_markdown",
            path=str(output_path),
        )

        # 뉴스레터 렌더링 직전 — 표시 전용 데이터 주입 (감성 파이프라인 제외 항목)
        display_data = fetch_newsletter_display_data(
            cache_dir=settings.cache_dir,
            observer=observer,
        )
        render_packet = {
            **packet,
            "korea_watch": display_data["korea_watch"],
            "korea_indices": display_data["korea_indices"],
            "tech_stocks": display_data["tech_stocks"],
        }
        render_packet["bitcoin"] = {
            **render_packet.get("bitcoin", {}),
            "etf_points": display_data["btc_etf_points"],
        }

        publish_public_brief(
            packet=render_packet,
            briefing=briefing,
            run_at=now,
            settings=settings,
            observer=observer,
            public_context=public_context,
            unified=unified,
        )

        subject = f"SOVEREIGN BRIEF ({now.strftime('%Y-%m-%d')})"
        if quality["status"] == "critical":
            subject = f"[데이터 부족] {subject}"

        brief_review_failed = any(
            str(event.get("event", "")).strip() == "brief_review_failed"
            for event in observer.events
        )
        if quality["status"] == "critical" and brief_review_failed:
            status = "skipped"
            observer.log_event(
                "email_skipped",
                level=logging.WARNING,
                message="데이터 품질 critical + 검수 미통과 조합으로 이메일 발송을 건너뛸게요.",
                reason="데이터 품질 critical + 검수 미통과 조합으로 발송을 건너뛸게요.",
            )
        else:
            try:
                with observer.phase("email"):
                    SesSender(settings).send(subject=subject, body=briefing, packet=render_packet)
            except Exception as exc:
                if status == "ok":
                    status = "degraded"
                failure_message = str(exc)
                observer.log_event(
                    "email_send_failed",
                    level=logging.WARNING,
                    message="이메일 발송은 실패했지만 공개 산출물은 유지하고 다음 단계를 계속할게요.",
                    reason=failure_message,
                    error_type=type(exc).__name__,
                )

            # 이메일 발송 시도 후 신호를 기록 (발송 성공/실패 무관하게 기록)
            if (
                risk_overlay is not None
                and settings.supabase_url
                and settings.supabase_service_role_key
            ):
                try:
                    from morning_brief.signal_logger import log_signal

                    btc_spot_raw = render_packet.get("bitcoin", {}).get("spot", {}) or {}
                    btc_price_open = btc_spot_raw.get("resolved_value") or btc_spot_raw.get("price")
                    log_signal(
                        supabase_url=settings.supabase_url,
                        service_role_key=settings.supabase_service_role_key,
                        signal_date=now.date(),
                        regime_state=risk_overlay.regime.label,
                        vol_level=risk_overlay.vol.level,
                        vol_trend=risk_overlay.vol.trend,
                        overlay_decision=risk_overlay.overlay_gate_decision,
                        confidence=risk_overlay.confidence.level,
                        reasons=risk_overlay.confidence.reasons,
                        btc_price_open=float(btc_price_open)
                        if btc_price_open is not None
                        else None,
                    )
                except Exception as log_exc:
                    log_structured(
                        logger,
                        event="signal_log.failed",
                        level=logging.WARNING,
                        message="signal_log 기록 실패 — 파이프라인에는 영향 없음",
                        reason=str(log_exc),
                    )

    except BriefGenerationError as exc:
        status = "openai_failed"
        failure_message = str(exc)
        failure_exc = exc
        observer.log_event(
            "openai_alert",
            level=logging.ERROR,
            message="OpenAI 브리핑 생성이 중단돼 메일 발송을 건너뛸게요.",
            action="skip_email",
            reason=failure_message,
        )
    except Exception as exc:
        status = "failed"
        failure_message = str(exc)
        failure_exc = exc
        observer.log_event(
            "pipeline_error",
            level=logging.ERROR,
            message="브리핑 파이프라인 실행 중 예외가 발생했어요.",
            reason=failure_message,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        total_duration_ms = int(round((time.perf_counter() - pipeline_started_at) * 1000))
        provider_stats = provider_stats_snapshot()
        observer.write_outputs(
            status=status,
            provider_stats=provider_stats,
            extra={
                "total_duration_ms": total_duration_ms,
                "news_count": len(news_packet),
                "brief_path": str(output_path) if output_path else None,
                "brief_fallback_used": brief_fallback_used,
                "failure_message": failure_message or None,
            },
        )

    if failure_exc is not None:
        raise failure_exc

    return briefing
