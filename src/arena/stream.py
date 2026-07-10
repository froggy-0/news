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
        # 역발산(평균회귀) 계열: 가격/트레일 손절 제외 — 대신 1m 틱마다 가격 기준 물타기를
        # 실시간 평가(공포 딥에 한계가 체결). 시간 손절은 4h 루프가 담당.
        if algo_id in parameters.PRICE_STOP_DISABLED_ALGOS:
            if parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED and algo_id == "fng_contrarian":
                updated = await positions.maybe_scale_in_fng_price(pos, price)
                if updated:
                    state.open_positions[algo_id] = updated  # 인메모리 반영(4h 루프 공유)
                    pos = updated
            # P-A: fng 이익 포착 익절 — 평단×(1+target_pct) 도달 시 청산(물타기 후 평단 기준).
            #   익절이므로 min_hold 무시(손절과 비대칭). 하방 스톱은 없음(가격손절 금지 유지).
            if parameters.FNG_TARGET_EXIT_ENABLED and algo_id == "fng_contrarian":
                tp = (pos.get("signal_reason") or {}).get("fng_target_pct")
                if tp is not None:
                    target = float(pos["open_price"]) * (1.0 + float(tp))
                    if execution_rules.target_exit_triggered(
                        direction=pos["direction"], current_price=price, target_price=target
                    ):
                        logger.info(
                            "Target-exit(fng): now=%.2f  target=%.2f  avg_open=%.2f",
                            price,
                            target,
                            pos["open_price"],
                        )
                        now = datetime.now(timezone.utc)
                        await positions.close_position(
                            pos["id"], now, price, close_reason="target_exit"
                        )
                        state.open_positions[algo_id] = None
            continue
        # WI-7: omnibus 평균회귀(RANGE/REBOUND) 익절 목표가 도달 시 청산(1m 틱 감시).
        #   목표가는 진입 시점 signal_reason.omni_target_price에 고정. 익절이므로 min_hold
        #   보다 우선(손절과 비대칭). UP_TREND은 목표가 없음(None) → 트레일링이 담당.
        if parameters.OMNIBUS_TARGET_EXIT_ENABLED and algo_id == "omnibus":
            _reason = pos.get("signal_reason") or {}
            _target = _reason.get("omni_target_price")
            if execution_rules.target_exit_triggered(
                direction=pos["direction"], current_price=price, target_price=_target
            ):
                logger.info(
                    "Target-exit(omnibus): long now=%.2f  target=%.2f  open=%.2f",
                    price,
                    float(_target),
                    pos["open_price"],
                )
                now = datetime.now(timezone.utc)
                await positions.close_position(pos["id"], now, price, close_reason="target_exit")
                state.open_positions[algo_id] = None
                _last_persisted_stop.pop(algo_id, None)
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
