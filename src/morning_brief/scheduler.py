from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from morning_brief.config import Settings
from morning_brief.pipeline import run_pipeline



def run_once(settings: Settings) -> str:
    return run_pipeline(settings=settings)



def run_daily(settings: Settings, hour: int = 8, minute: int = 0) -> None:
    scheduler = BlockingScheduler(timezone=settings.timezone)

    scheduler.add_job(
        func=lambda: run_pipeline(settings=settings),
        trigger="cron",
        hour=hour,
        minute=minute,
        id="morning_market_brief",
        replace_existing=True,
    )

    print(f"Scheduler started: daily {hour:02d}:{minute:02d} ({settings.timezone})")
    scheduler.start()
