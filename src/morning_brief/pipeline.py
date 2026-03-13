from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from morning_brief.briefing import generate_briefing
from morning_brief.config import Settings
from morning_brief.data.data_quality import assess_data_quality
from morning_brief.data.market import build_market_packet
from morning_brief.data.news import build_news_packet
from morning_brief.data.sources.provider_runtime import (
    provider_stats_snapshot,
    reset_provider_runtime_state,
)
from morning_brief.emailer import GmailSender
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.llm_provider_policy import provider_role_snapshot
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

_assess_data_quality = assess_data_quality


def run_pipeline(settings: Settings) -> str:
    reset_provider_runtime_state()
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
            news_packet = build_news_packet(settings=settings, observer=observer)
        logger.info("시장 지표와 뉴스 %s건을 모았어요.", len(news_packet))

        packet = {
            **market_packet,
            "news": news_packet,
        }
        quality = _assess_data_quality(packet=packet, news_packet=news_packet)
        with observer.phase("backfill"):
            observer.log_event(
                "backfill_skipped",
                reason="OpenAI는 브리핑 생성/검수 전용이라 수집 백필을 수행하지 않아요.",
            )

        packet["data_quality"] = quality
        if quality["status"] != "ok":
            logger.warning(
                "데이터 품질 상태는 %s예요. 확인할 점은 %s",
                quality["status"],
                "; ".join(quality["warnings"]),
            )

        briefing = generate_briefing(packet=packet, settings=settings, observer=observer)

        now = datetime.now(ZoneInfo(settings.timezone))
        file_name = now.strftime("brief_%Y%m%d_%H%M.md")
        output_path = settings.output_dir / file_name
        output_path.write_text(briefing, encoding="utf-8")
        logger.info("브리핑을 저장했어요: %s", output_path)

        subject = f"미국 기술주·비트코인 시장 브리핑 ({now.strftime('%Y-%m-%d')})"
        with observer.phase("email"):
            GmailSender(settings).send(subject=subject, body=briefing)
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
                "failure_message": failure_message or None,
            },
        )
        if provider_stats:
            logger.info("이번 실행의 수집 공급자 상태는 %s", provider_stats)
        logger.info("브리핑 파이프라인을 마쳤어요. status=%s", summary["status"])

    if failure_exc is not None:
        raise failure_exc

    return briefing
