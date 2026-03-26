from __future__ import annotations

import logging
from datetime import date
from functools import partial

from apscheduler.schedulers.blocking import BlockingScheduler

from morning_brief.config import Settings
from morning_brief.logging_utils import log_structured
from morning_brief.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def run_once(settings: Settings) -> str:
    return run_pipeline(settings=settings)


def _run_dynamic_registry_update(api_key: str) -> None:
    """Dynamic Signal Registry를 Grok API로 갱신한다 (스케줄러 잡용).

    Grok API 장애 시 Base Layer fallback — 기존 동작 보장.
    """
    from morning_brief.data.sources.dynamic_registry_updater import update_dynamic_registry

    log_structured(
        logger,
        event="run.start",
        message="Dynamic registry 자동 갱신을 시작할게요.",
        component=__name__,
        date=date.today().isoformat(),
    )
    try:
        success = update_dynamic_registry(api_key=api_key)
        if success:
            log_structured(
                logger,
                event="publish.complete",
                message="Dynamic registry 갱신을 완료했어요.",
                component=__name__,
            )
        else:
            log_structured(
                logger,
                event="fallback.used",
                message="Dynamic registry 갱신 실패로 Base Layer fallback으로 계속 운영할게요.",
                level=logging.WARNING,
                component=__name__,
                reason="update_failed",
            )
    except Exception as exc:
        log_structured(
            logger,
            event="error.raised",
            message="Dynamic registry 갱신 중 예외가 발생해 Base Layer fallback으로 이어갈게요.",
            level=logging.ERROR,
            component=__name__,
            reason=str(exc),
            error_type=type(exc).__name__,
        )


def run_daily(settings: Settings, hour: int = 8, minute: int = 0) -> None:
    scheduler = BlockingScheduler(timezone=settings.timezone)

    scheduler.add_job(
        func=partial(run_pipeline, settings=settings),
        trigger="cron",
        hour=hour,
        minute=minute,
        id="morning_market_brief",
        replace_existing=True,
    )

    # Dynamic Registry 자동 갱신: 매일 새벽 2시 (브리핑 실행 전)
    # Grok API 장애 시 Base Layer fallback으로 안전하게 운영
    if settings.grok_api_key:
        scheduler.add_job(
            func=partial(_run_dynamic_registry_update, api_key=settings.grok_api_key),
            trigger="cron",
            hour=2,
            minute=0,
            id="dynamic_registry_update",
            replace_existing=True,
            coalesce=True,  # 중복 실행 방지
            max_instances=1,
        )
        log_structured(
            logger,
            event="selection.complete",
            message="Dynamic registry 자동 갱신 스케줄러를 등록했어요.",
            timezone=settings.timezone,
            schedule="02:00",
        )

    log_structured(
        logger,
        event="run.start",
        message="스케줄러를 시작할게요.",
        schedule=f"{hour:02d}:{minute:02d}",
        timezone=settings.timezone,
    )
    scheduler.start()
