from __future__ import annotations

import logging
from datetime import date
from functools import partial

from apscheduler.schedulers.blocking import BlockingScheduler

from morning_brief.config import Settings
from morning_brief.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def run_once(settings: Settings) -> str:
    return run_pipeline(settings=settings)


def _run_dynamic_registry_update(api_key: str) -> None:
    """Dynamic Signal Registry를 Grok API로 갱신한다 (스케줄러 잡용).

    Grok API 장애 시 Base Layer fallback — 기존 동작 보장.
    """
    from morning_brief.data.sources.dynamic_registry_updater import update_dynamic_registry

    logger.info("Dynamic registry 자동 갱신 시작 (%s)", date.today().isoformat())
    try:
        success = update_dynamic_registry(api_key=api_key)
        if success:
            logger.info("Dynamic registry 갱신 완료")
        else:
            logger.warning("Dynamic registry 갱신 실패 — Base Layer fallback으로 운영 계속")
    except Exception as exc:
        logger.error("Dynamic registry 갱신 중 예외 발생 — Base Layer fallback: %s", exc)


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
        logger.info("Dynamic registry 자동 갱신 스케줄러 등록: 매일 02:00 (%s)", settings.timezone)

    logger.info(
        "스케줄러를 시작할게요. 매일 %02d:%02d (%s)에 실행돼요.", hour, minute, settings.timezone
    )
    scheduler.start()
