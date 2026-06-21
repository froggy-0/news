"""Binance WebSocket 1m kline 스트림 — 실시간 현재가 갱신 + 스톱로스 감지."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from . import config, execution_rules, parameters, positions, state

logger = logging.getLogger(__name__)

# 알고별 마지막으로 DB에 persist한 손절가 — 매 틱이 아닌 임계 이동 시에만 쓰기.
_last_persisted_stop: dict[str, float] = {}


def _is_stop_triggered(pos: dict, price: float) -> bool:
    """ATR 기반 stop_loss_price 우선 사용. 미저장 시 고정 % fallback."""
    return execution_rules.stop_loss_triggered(
        direction=pos["direction"],
        open_price=pos["open_price"],
        current_price=price,
        stop_loss_price=pos.get("stop_loss_price"),
        fallback_stop_loss_pct=config.STOP_LOSS_PCT,
    )


async def _ratchet_trailing_stop(algo_id: str, pos: dict, price: float) -> None:
    """수익 방향으로 손절가를 단조 끌어올림. 인메모리 매 틱 갱신, DB는 임계 이동 시만 persist."""
    if not parameters.TRAILING_STOP_ENABLED:
        return
    current_stop = pos.get("stop_loss_price")
    trail_distance = pos.get("trail_distance")
    if current_stop is None or not trail_distance or trail_distance <= 0:
        return
    new_stop = execution_rules.ratchet_trailing_stop(
        direction=pos["direction"],
        current_price=price,
        current_stop=float(current_stop),
        trail_distance=float(trail_distance),
    )
    if new_stop == current_stop:
        return
    pos["stop_loss_price"] = new_stop  # 인메모리 즉시 반영 (다음 틱 트리거 체크에 사용)
    last_persisted = _last_persisted_stop.get(algo_id, float(current_stop))
    step_bps = abs(new_stop - last_persisted) / price * 10_000.0
    if step_bps >= parameters.TRAIL_PERSIST_STEP_BPS:
        pos_id = pos.get("id")
        if pos_id is not None:
            await positions.update_stop_loss(pos_id, new_stop)
            _last_persisted_stop[algo_id] = new_stop
            logger.info(
                "Trail ratchet persisted: %s %s  sl=%.2f  price=%.2f  open=%.2f",
                algo_id,
                pos["direction"],
                new_stop,
                price,
                pos["open_price"],
            )


async def _check_stop_loss(price: float) -> None:
    for algo_id, pos in list(state.open_positions.items()):
        if pos is None:
            continue
        await _ratchet_trailing_stop(algo_id, pos, price)
        if _is_stop_triggered(pos, price):
            sl = pos.get("stop_loss_price", "fallback")
            trailed = execution_rules.is_trailing_exit(
                direction=pos["direction"],
                open_price=pos["open_price"],
                stop_loss_price=float(sl) if isinstance(sl, (int, float)) else pos["open_price"],
                trail_distance=float(pos.get("trail_distance") or 0.0),
            )
            close_reason = "trailing_stop" if trailed else "stop_loss"
            logger.warning(
                "Stop-loss(%s): %s %s  now=%.2f  sl=%.2f  open=%.2f",
                close_reason,
                algo_id,
                pos["direction"],
                price,
                sl if isinstance(sl, float) else 0,
                pos["open_price"],
            )
            now = datetime.now(timezone.utc)
            await positions.close_position(
                pos["id"], now, price, is_stop_loss=True, close_reason=close_reason
            )
            state.open_positions[algo_id] = None
            _last_persisted_stop.pop(algo_id, None)


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
