"""아레나 서버 진입점. systemd: python -m arena.server"""

from __future__ import annotations

import asyncio
import logging
import signal

from . import liquidation_stream, positions, realtime_market, scheduler, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _main() -> None:
    await positions.init()
    await positions.refresh_open_positions()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    tasks = [
        asyncio.create_task(scheduler.run(), name="scheduler"),
        asyncio.create_task(stream.run(), name="stream"),
        asyncio.create_task(realtime_market.run(), name="realtime_market"),
        # WI-9: 선물 강제청산 수집(플래그 off 시 즉시 반환). 트레이딩과 분리 — 죽어도 무영향.
        asyncio.create_task(liquidation_stream.run(), name="liquidation_stream"),
        asyncio.create_task(stop_event.wait(), name="stop"),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    for task in done:
        if exc := task.exception() if not task.cancelled() else None:
            logger.error("Task %s raised: %s", task.get_name(), exc)

    logger.info("Arena stopped")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
