"""Binance WebSocket 1m kline 스트림 — 실시간 현재가 갱신 + 스톱로스 감지.

2026-08-06: BTC 단일 스트림에서 config.ARENA_LIVE_SYMBOLS(기본 BTC, 멀티자산
승격 시 +ETH/SOL) 콤바인드 스트림으로 확장. 심볼별 포지션·가격은 state.py의
심볼 네임스페이스 헬퍼로만 접근한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from . import config, execution_rules, parameters, positions, state

logger = logging.getLogger(__name__)

# 심볼×알고별 마지막으로 DB에 persist한 손절가 — 매 틱이 아닌 임계 이동 시에만 쓰기.
_last_persisted_stop: dict[tuple[str, str], float] = {}


def _combined_stream_url(symbols: tuple[str, ...]) -> str:
    streams = "/".join(f"{symbol.lower()}@kline_1m" for symbol in symbols)
    return f"{config.BINANCE_COMBINED_WS_URL}?streams={streams}"


def _is_stop_triggered(pos: dict, price: float) -> bool:
    """ATR 기반 stop_loss_price 우선 사용. 미저장 시 고정 % fallback."""
    return execution_rules.stop_loss_triggered(
        direction=pos["direction"],
        open_price=pos["open_price"],
        current_price=price,
        stop_loss_price=pos.get("stop_loss_price"),
        fallback_stop_loss_pct=config.STOP_LOSS_PCT,
    )


async def _ratchet_trailing_stop(symbol: str, algo_id: str, pos: dict, price: float) -> None:
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
    key = (symbol, algo_id)
    last_persisted = _last_persisted_stop.get(key, float(current_stop))
    step_bps = abs(new_stop - last_persisted) / price * 10_000.0
    if step_bps >= parameters.TRAIL_PERSIST_STEP_BPS:
        pos_id = pos.get("id")
        if pos_id is not None:
            await positions.update_stop_loss(pos_id, new_stop)
            _last_persisted_stop[key] = new_stop
            logger.info(
                "Trail ratchet persisted: %s %s %s  sl=%.2f  price=%.2f  open=%.2f",
                symbol,
                algo_id,
                pos["direction"],
                new_stop,
                price,
                pos["open_price"],
            )


async def _check_stop_loss(symbol: str, price: float) -> None:
    for algo_id, pos in list(state.positions_for(symbol).items()):
        if pos is None:
            continue
        # 역발산(평균회귀) 계열: 가격/트레일 손절 제외 — 대신 1m 틱마다 가격 기준 물타기를
        # 실시간 평가(공포 딥에 한계가 체결). 시간 손절은 4h 루프가 담당.
        if algo_id in parameters.PRICE_STOP_DISABLED_ALGOS:
            if parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED and algo_id == "fng_contrarian":
                updated = await positions.maybe_scale_in_fng_price(pos, price)
                if updated:
                    state.set_position(symbol, algo_id, updated)  # 인메모리 반영(4h 루프 공유)
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
                            "Target-exit(fng): %s now=%.2f  target=%.2f  avg_open=%.2f",
                            symbol,
                            price,
                            target,
                            pos["open_price"],
                        )
                        now = datetime.now(timezone.utc)
                        await positions.close_position(
                            pos["id"], now, price, close_reason="target_exit"
                        )
                        state.set_position(symbol, algo_id, None)
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
                    "Target-exit(omnibus): %s long now=%.2f  target=%.2f  open=%.2f",
                    symbol,
                    price,
                    float(_target),
                    pos["open_price"],
                )
                now = datetime.now(timezone.utc)
                await positions.close_position(pos["id"], now, price, close_reason="target_exit")
                state.set_position(symbol, algo_id, None)
                _last_persisted_stop.pop((symbol, algo_id), None)
                continue
        # Tier2: 범용 목표가 익절(vix_rsi/multi_factor 등, 진입 시 signal_reason.target_price
        #   고정). dict에 없는 알고는 target_price가 저장돼 있지 않아 항상 no-op.
        if (
            parameters.GENERIC_TARGET_EXIT_ENABLED
            and algo_id in parameters.TARGET_EXIT_ATR_MULT_BY_ALGO
        ):
            _reason = pos.get("signal_reason") or {}
            _target = _reason.get("target_price")
            if execution_rules.target_exit_triggered(
                direction=pos["direction"], current_price=price, target_price=_target
            ):
                logger.info(
                    "Target-exit(%s): %s now=%.2f  target=%.2f  open=%.2f",
                    algo_id,
                    symbol,
                    price,
                    float(_target),
                    pos["open_price"],
                )
                now = datetime.now(timezone.utc)
                await positions.close_position(pos["id"], now, price, close_reason="target_exit")
                state.set_position(symbol, algo_id, None)
                _last_persisted_stop.pop((symbol, algo_id), None)
                continue
        # P1 후속(2026-08-04): omnibus 레그별 가격손절 제외 — 진입 시점
        # signal_reason.diagnostics.factors.omni_regime으로 레그 판별(backtest.py
        # omnibus_regime_for()와 동일 원칙, live는 이미 저장된 값을 그대로 읽음).
        if algo_id == "omnibus" and parameters.OMNIBUS_PRICE_STOP_DISABLED_LEGS:
            _diag = (pos.get("signal_reason") or {}).get("diagnostics") or {}
            _leg = (_diag.get("factors") or {}).get("omni_regime")
            if _leg in parameters.OMNIBUS_PRICE_STOP_DISABLED_LEGS:
                continue
        await _ratchet_trailing_stop(symbol, algo_id, pos, price)
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
                "Stop-loss(%s): %s %s %s  now=%.2f  sl=%.2f  open=%.2f",
                close_reason,
                symbol,
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
            state.set_position(symbol, algo_id, None)
            _last_persisted_stop.pop((symbol, algo_id), None)


def _parse_tick(raw: str, symbols: tuple[str, ...]) -> tuple[str, float] | None:
    """콤바인드 스트림 메시지에서 (symbol, price)를 추출. 단일 심볼(BTC만)일 땐 단일
    스트림 포맷(wrapper 없음)도 함께 지원 — 하위호환."""
    data = json.loads(raw)
    if "stream" in data and "data" in data:
        stream_name = str(data["stream"])
        symbol = stream_name.split("@")[0].upper()
        k = data["data"].get("k", {})
    elif len(symbols) == 1:
        symbol = symbols[0]
        k = data.get("k", {})
    else:
        return None
    price = float(k.get("c", 0))
    return (symbol, price) if price > 0 else None


async def run() -> None:
    """무한 재접속 루프. 외부에서 asyncio.gather()로 실행.

    spot→perp Phase A2(2026-08-15): 구독은 실제 티커(config.ARENA_LIVE_REAL_SYMBOLS)
    하나뿐이다 — perp 트랙도 spot 가격 프록시를 쓰므로 새 WS 커넥션이 필요 없다. 틱
    하나가 도착하면 그 실제 티커에 매핑된 모든 트랙(config.ARENA_LIVE_TRACKS_BY_SYMBOL,
    perp 비활성 시 트랙이 1개뿐이라 기존과 동일)의 스탑로스를 전부 체크한다.
    """
    symbols = config.ARENA_LIVE_REAL_SYMBOLS
    url = _combined_stream_url(symbols)
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
            ) as ws:
                logger.info("Binance WebSocket connected (%s)", ", ".join(symbols))
                async for raw in ws:
                    tick = _parse_tick(raw, symbols)
                    if tick is None:
                        continue
                    real_symbol, price = tick
                    for track_symbol in config.ARENA_LIVE_TRACKS_BY_SYMBOL.get(
                        real_symbol, (real_symbol,)
                    ):
                        state.set_price(track_symbol, price)
                        await _check_stop_loss(track_symbol, price)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "WebSocket error: %s — reconnecting in %ss",
                exc,
                parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS)
