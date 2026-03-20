from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.data_quality import assess_data_quality
from morning_brief.data.market import build_market_packet, reset_market_warned_state
from morning_brief.data.market_keywords import build_search_keywords, extract_market_keywords
from morning_brief.data.news import build_news_packet
from morning_brief.data.sources.provider_runtime import (
    provider_stats_snapshot,
    reset_provider_runtime_state,
)
from morning_brief.emailer import GmailSender
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.llm_provider_policy import provider_role_snapshot
from morning_brief.observability import PipelineObserver
from morning_brief.research_backfill import (
    _needs_web_search_backfill,
    backfill_news_with_web_search,
)

logger = logging.getLogger(__name__)

_assess_data_quality = assess_data_quality


def run_pipeline(settings: Settings) -> str:
    reset_provider_runtime_state()
    reset_market_warned_state()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    observer = PipelineObserver(output_dir=settings.output_dir)
    observer.record_cache_status_from_env()
    observer.log_event("provider_role_policy", policies=provider_role_snapshot())
    logger.info("브리핑 파이프라인을 시작할게요.")
    pipeline_started_at = time.perf_counter()
    market_packet: dict = {}
    news_packet: list[dict] = []
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
            )
        with observer.phase("news"):
            market_keywords = extract_market_keywords(market_packet)
            keywords_by_topic = build_search_keywords(market_keywords)
            if market_keywords and observer is not None:
                observer.log_event(
                    "market_keywords_extracted",
                    keywords=market_keywords,
                )
            news_packet, topic_summaries, x_signals = build_news_packet(
                settings=settings,
                observer=observer,
                keywords_by_topic=keywords_by_topic,
            )
        logger.info("시장 지표와 뉴스 %s건을 모았어요.", len(news_packet))

        packet = {
            **market_packet,
            "news": news_packet,
        }
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
            logger.warning(
                "데이터 품질이 critical이어서 실행 상태를 degraded로 남길게요. 확인할 점은 %s",
                "; ".join(quality["warnings"]),
            )
        elif quality["status"] != "ok":
            logger.warning(
                "데이터 품질 상태는 %s예요. 확인할 점은 %s",
                quality["status"],
                "; ".join(quality["warnings"]),
            )

        briefing = generate_briefing(packet=packet, settings=settings, observer=observer)
        brief_fallback_used = any(
            str(event.get("event", "")).strip() == "brief_fallback_used"
            for event in observer.events
        )
        if brief_fallback_used and status == "ok":
            status = "brief_fallback"
            logger.warning(
                "최종 브리핑이 안전한 기본 브리핑으로 대체돼 실행 상태를 brief_fallback으로 남길게요."
            )

        now = datetime.now(ZoneInfo(settings.timezone))
        file_name = now.strftime("brief_%Y%m%d_%H%M.md")
        output_path = settings.output_dir / file_name
        output_path.write_text(briefing, encoding="utf-8")
        logger.info("브리핑을 저장했어요: %s", output_path)

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
                reason="데이터 품질 critical + 검수 미통과 조합으로 발송을 건너뛸게요.",
            )
            logger.warning("데이터 품질 critical + 검수 미통과로 이메일 발송을 건너뛸게요.")
        else:
            with observer.phase("email"):
                GmailSender(settings).send(subject=subject, body=briefing, packet=packet)
    except BriefGenerationError as exc:
        status = "openai_failed"
        failure_message = str(exc)
        failure_exc = exc
        observer.log_event(
            "openai_alert",
            action="skip_email",
            reason=failure_message,
        )
        logger.error("OpenAI 브리핑 생성이 중단돼 메일 발송을 건너뛸게요: %s", exc)
    except Exception as exc:
        status = "failed"
        failure_message = str(exc)
        failure_exc = exc
        observer.log_event("pipeline_error", reason=failure_message)
        raise
    finally:
        total_duration_ms = int(round((time.perf_counter() - pipeline_started_at) * 1000))
        provider_stats = provider_stats_snapshot()
        summary = observer.write_outputs(
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
        if provider_stats:
            logger.info("이번 실행의 수집 공급자 상태는 %s", provider_stats)
        logger.info("브리핑 파이프라인을 마쳤어요. status=%s", summary["status"])
        provider_usage_line = str(summary.get("provider_usage_line") or "").strip()
        if provider_usage_line:
            logger.info("이번 실행의 LLM 토큰 사용량은 %s", provider_usage_line)

    if failure_exc is not None:
        raise failure_exc

    return briefing
