"""Binance WebSocket 1m kline 스트림 — 실시간 현재가 갱신 + 스톱로스 감지."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from . import config, execution_rules, parameters, positions, state

logger = logging.getLogger(__name__)


def _is_stop_triggered(pos: dict, price: float) -> bool:
    """ATR 기반 stop_loss_price 우선 사용. 미저장 시 고정 % fallback."""
    return execution_rules.stop_loss_triggered(
        direction=pos["direction"],
        open_price=pos["open_price"],
        current_price=price,
        stop_loss_price=pos.get("stop_loss_price"),
        fallback_stop_loss_pct=config.STOP_LOSS_PCT,
    )


async def _check_stop_loss(price: float) -> None:
    for algo_id, pos in list(state.open_positions.items()):
        if pos is None:
            continue
        if _is_stop_triggered(pos, price):
            sl = pos.get("stop_loss_price", "fallback")
            logger.warning(
                "Stop-loss: %s %s  now=%.2f  sl=%.2f  open=%.2f",
                algo_id,
                pos["direction"],
                price,
                sl if isinstance(sl, float) else 0,
                pos["open_price"],
            )
            now = datetime.now(timezone.utc)
            await positions.close_position(pos["id"], now, price, is_stop_loss=True)
            state.open_positions[algo_id] = None


async def run() -> None:
    """무한 재접속 루프. 외부에서 asyncio.gather()로 실행."""
    while True:
        try:
            async with websockets.connect(
                config.BINANCE_WS_URL,
                ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
            ) as ws:
                logger.info("Binance WebSocket connected")
                async for raw in ws:
                    data = json.loads(raw)
                    k = data.get("k", {})
                    price = float(k.get("c", 0))
                    if price > 0:
                        state.current_price = price
                        await _check_stop_loss(price)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "WebSocket error: %s — reconnecting in %ss",
                exc,
                parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS)
