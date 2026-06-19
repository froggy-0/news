"""4H APScheduler 사이클 — Binance 4H OHLCV + R2 매크로 → 알고리즘 실행 → 포지션 관리."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import NamedTuple

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import (
    allocator,
    config,
    data_lake,
    execution_rules,
    indicators,
    market_structure,
    parameters,
    positions,
    risk,
    sleeves,
    state,
)
from .algorithms import ALGORITHMS

logger = logging.getLogger(__name__)


class OHLCV(NamedTuple):
    highs: list[float]
    lows: list[float]
    closes: list[float]
    last_close_time: datetime | None
    raw_klines: list[list]


class MacroData(NamedTuple):
    signal: dict
    payload: dict
    fetched_at: datetime | None
    source_url: str


async def _fetch_ohlcv() -> OHLCV:
    """Binance 4H OHLCV 수집. 미확정 오픈 캔들 제거."""
    url = (
        f"{config.BINANCE_REST_URL}"
        f"?symbol={config.SYMBOL}&interval={parameters.BINANCE_KLINE_INTERVAL}"
        f"&limit={config.KLINES_LIMIT}"
    )
    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        res = await client.get(url)
        res.raise_for_status()
    klines = res.json()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if klines and int(klines[-1][6]) > now_ms:
        klines = klines[:-1]
    return OHLCV(
        highs=[float(k[2]) for k in klines],
        lows=[float(k[3]) for k in klines],
        closes=[float(k[4]) for k in klines],
        last_close_time=(
            datetime.fromtimestamp(int(klines[-1][6]) / 1000, tz=timezone.utc) if klines else None
        ),
        raw_klines=klines,
    )


async def _fetch_macro() -> MacroData:
    """R2 latest.json 수집. stale 데이터는 거시 신호로 사용하지 않음."""
    if not config.LATEST_JSON_URL:
        logger.warning("LATEST_JSON_URL 미설정 — 빈 매크로 사용")
        return MacroData({}, {}, None, "")
    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        res = await client.get(config.LATEST_JSON_URL)
        res.raise_for_status()
    data = res.json()
    fetched_at = datetime.now(timezone.utc)

    # 신선도 검증: referenceDate 기준 경과 시간 확인
    ref_date = data.get("referenceDate", "")
    stale_h: float | None = None
    if ref_date:
        try:
            ref_dt = datetime.fromisoformat(ref_date.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            else:
                ref_dt = ref_dt.astimezone(timezone.utc)
            stale_h = (datetime.now(timezone.utc) - ref_dt).total_seconds() / 3600
            if stale_h > config.MACRO_STALE_HOURS:
                logger.warning(
                    "Macro data stale: %.0fh (ref=%s, threshold=%.0fh) — macro signals disabled",
                    stale_h,
                    ref_date,
                    config.MACRO_STALE_HOURS,
                )
                return MacroData({}, data, fetched_at, config.LATEST_JSON_URL)
        except ValueError:
            logger.warning(
                "Macro referenceDate parse failed: %s — macro signals disabled", ref_date
            )
            return MacroData({}, data, fetched_at, config.LATEST_JSON_URL)

    overlay = data.get("riskOverlay", {})
    raw = overlay.get("regimeRaw", {})
    return MacroData(
        {
            "regime_state": overlay.get("regimeState", ""),
            "fng": raw.get("fng"),
            "vix_now": raw.get("vix_now"),
            "vix_q40": raw.get("vix_q40"),
            "reference_date": ref_date or None,
            "stale_hours": round(stale_h, 2) if stale_h is not None else None,
        },
        data,
        fetched_at,
        config.LATEST_JSON_URL,
    )


def _params_snapshot(algo_id: str) -> dict:
    return execution_rules.build_params_snapshot(
        base_snapshot=parameters.base_params_snapshot(),
        algo_id=algo_id,
        stop_loss_fallback_pct=config.STOP_LOSS_PCT,
        fee_bps=config.FEE_BPS,
        atr_multiple=config.ATR_MULTIPLE,
        stop_loss_min_pct=config.STOP_LOSS_MIN_PCT,
        stop_loss_max_pct=config.STOP_LOSS_MAX_PCT,
        macro_stale_hours=config.MACRO_STALE_HOURS,
        portfolio_risk=risk.policy_snapshot(_risk_policy()),
    )


def _risk_policy() -> risk.PortfolioRiskPolicy:
    return risk.PortfolioRiskPolicy(
        position_unit=config.POSITION_UNIT,
        max_open_positions_total=config.MAX_OPEN_POSITIONS_TOTAL,
        max_long_positions=config.MAX_LONG_POSITIONS,
        max_short_positions=config.MAX_SHORT_POSITIONS,
        max_net_long_exposure=config.MAX_NET_LONG_EXPOSURE,
        max_net_short_exposure=config.MAX_NET_SHORT_EXPOSURE,
        daily_loss_limit_pct=config.DAILY_LOSS_LIMIT_PCT,
        algo_max_drawdown_kill_pct=config.ALGO_MAX_DRAWDOWN_KILL_PCT,
        cooldown_after_kill_hours=config.COOLDOWN_AFTER_KILL_HOURS,
    )


async def _risk_state(now: datetime) -> risk.PortfolioRiskState:
    metrics = await positions.risk_metrics(now)
    return risk.PortfolioRiskState(
        daily_realized_ret_pct=metrics["daily_realized_ret_pct"],
        algo_drawdown_pct=metrics["algo_drawdown_pct"],
    )


def _data_timestamp(ohlcv: OHLCV, now: datetime) -> datetime:
    return ohlcv.last_close_time or now


def _market_snapshot(price: float, ohlcv: OHLCV, data_timestamp: datetime) -> dict:
    return execution_rules.build_market_snapshot(
        symbol=config.SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        klines_limit=config.KLINES_LIMIT,
        price=price,
        high=ohlcv.highs[-1] if ohlcv.highs else None,
        low=ohlcv.lows[-1] if ohlcv.lows else None,
        closes_count=len(ohlcv.closes),
        data_timestamp=data_timestamp,
    )


def _signal_reason(algo_id: str, signal: str | None, ind: dict, macro: dict) -> dict:
    return execution_rules.build_signal_reason(
        algo_id=algo_id,
        signal=signal,
        indicators=ind,
        macro=macro,
    )


async def _run_shadow_vnext(
    *,
    run_id: str,
    data_timestamp: datetime,
    price: float,
    ind: dict,
    macro: dict,
    policy: risk.PortfolioRiskPolicy,
    portfolio_risk_state: risk.PortfolioRiskState,
) -> list[data_lake.CaptureWriteResult]:
    if not config.ENABLE_ARENA_SHADOW_VNEXT:
        return []
    results: list[data_lake.CaptureWriteResult] = []
    try:
        snapshot = await market_structure.fetch_market_structure_snapshot(
            symbol=config.SYMBOL,
            interval=parameters.BINANCE_KLINE_INTERVAL,
            data_timestamp=data_timestamp,
            spot_close=price,
            limit=config.KLINES_LIMIT,
        )
        results.extend(
            await data_lake.record_market_structure_snapshot(
                run_id=run_id,
                snapshot=snapshot,
            )
        )
        risk_snapshot = {
            "policy": risk.policy_snapshot(policy),
            "state": {
                "daily_realized_ret_pct": portfolio_risk_state.daily_realized_ret_pct,
                "algo_drawdown_pct": dict(portfolio_risk_state.algo_drawdown_pct),
                "killed_algos": dict(portfolio_risk_state.killed_algos),
            },
        }
        for sleeve_signal, regime_decision in sleeves.evaluate_shadow_sleeves(
            ind,
            snapshot.features,
            macro,
        ):
            allocation = allocator.allocate_shadow(
                sleeve_signal,
                regime_snapshot=regime_decision.as_dict(),
                risk_snapshot=risk_snapshot,
            )
            results.append(
                await data_lake.record_shadow_decision(
                    run_id=run_id,
                    signal=sleeve_signal,
                    allocation=allocation,
                )
            )
    except Exception as exc:
        logger.warning("Arena shadow vNext failed: %s", exc)
        results.append(
            data_lake.CaptureWriteResult(
                label="arena_shadow_vnext",
                ok=False,
                error=str(exc),
            )
        )
    return results


async def _run_cycle() -> None:
    run_id = data_lake.new_run_id()
    started_at = datetime.now(timezone.utc)
    capture_results: list[data_lake.CaptureWriteResult] = []
    base_params_snapshot = parameters.base_params_snapshot()
    logger.info("4H cycle start")
    capture_results.extend(
        await data_lake.record_strategy_metadata(params_snapshot=base_params_snapshot)
    )
    capture_results.append(
        await data_lake.record_run_started(
            run_id=run_id,
            started_at=started_at,
            params_snapshot=base_params_snapshot,
        )
    )
    try:
        ohlcv, macro_data = await asyncio.gather(_fetch_ohlcv(), _fetch_macro())
    except Exception as exc:
        logger.error("데이터 수집 실패: %s", exc)
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message=str(exc),
            capture_results=capture_results,
        )
        return

    if not ohlcv.closes:
        logger.error("closes 비어있음 — 사이클 스킵")
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message="empty_closes",
            capture_results=capture_results,
        )
        return

    ind = indicators.compute(ohlcv.highs, ohlcv.lows, ohlcv.closes)
    now = datetime.now(timezone.utc)
    data_timestamp = _data_timestamp(ohlcv, now)
    macro = macro_data.signal
    price = ohlcv.closes[-1]
    capture_results.extend(
        await data_lake.record_ohlcv_bars(
            run_id=run_id,
            raw_klines=ohlcv.raw_klines,
            fetched_at=now,
        )
    )
    capture_results.append(
        await data_lake.record_macro_snapshot(
            run_id=run_id,
            fetched_at=macro_data.fetched_at or now,
            source_url=macro_data.source_url,
            payload=macro_data.payload,
            signal=macro,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_snapshot(
            run_id=run_id,
            data_timestamp=data_timestamp,
            indicators=ind,
        )
    )
    logger.info(
        "price=%.2f  rsi=%.1f  macd_hist=%.4f  atr=%.2f  macro=%s",
        price,
        ind["rsi"],
        ind["macd_hist"],
        ind["atr"],
        macro,
    )

    had_algo_error = False
    policy = _risk_policy()
    portfolio_risk_state = await _risk_state(now)
    for algo_id, fn in ALGORITHMS.items():
        signal: str | None = None
        action = "flat_skip"
        skipped_reason: str | None = None
        resulting_position_id: int | None = None
        risk_decision: risk.RiskDecision | None = None
        current = state.open_positions.get(algo_id)
        current_position_id = current["id"] if current else None
        try:
            signal = fn(macro, ind)

            if signal is None:
                if current is not None:
                    if not execution_rules.min_hold_ok(
                        current,
                        now,
                        algo_id,
                        parameters.MIN_HOLD_HOURS,
                        parameters.MIN_HOLD_FALLBACK_HOURS,
                    ):
                        action = "min_hold_skip"
                        skipped_reason = "flat_signal_before_min_hold"
                        continue
                    await positions.close_position(current["id"], now, price)
                    state.open_positions[algo_id] = None
                    portfolio_risk_state = await _risk_state(now)
                    action = "close_flat"
                continue

            if current is not None:
                if current["direction"] == signal:
                    action = "hold"
                    continue  # HOLD — 방향 동일
                if not execution_rules.min_hold_ok(
                    current,
                    now,
                    algo_id,
                    parameters.MIN_HOLD_HOURS,
                    parameters.MIN_HOLD_FALLBACK_HOURS,
                ):
                    logger.debug("%s: 최소 보유 시간 미경과 — 반전 스킵", algo_id)
                    action = "min_hold_skip"
                    skipped_reason = "reverse_signal_before_min_hold"
                    continue
                await positions.close_position(current["id"], now, price)
                state.open_positions[algo_id] = None
                portfolio_risk_state = await _risk_state(now)
                action = "reverse"
            else:
                action = "open"

            risk_decision = risk.evaluate_open(
                algo_id=algo_id,
                direction=signal,
                open_positions=state.open_positions,
                state=portfolio_risk_state,
                evaluated_at=now,
                policy=policy,
            )
            if not risk_decision.allowed:
                action = "risk_blocked"
                skipped_reason = risk_decision.reason
                capture_results.append(
                    await data_lake.record_risk_event(
                        run_id=run_id,
                        algo_id=algo_id,
                        event_type=risk_decision.reason,
                        risk_decision=risk_decision.as_dict(),
                        risk_snapshot=risk_decision.as_dict(),
                        position_id=current_position_id,
                    )
                )
                continue

            sl_price = execution_rules.calc_stop_loss_price(
                signal,
                price,
                ind["atr"],
                atr_multiple=config.ATR_MULTIPLE,
                stop_loss_min_pct=config.STOP_LOSS_MIN_PCT,
                stop_loss_max_pct=config.STOP_LOSS_MAX_PCT,
            )
            new_pos = await positions.open_position(
                algo_id,
                signal,
                now,
                price,
                sl_price,
                data_timestamp=data_timestamp,
                strategy_version=parameters.STRATEGY_VERSION,
                params_version=parameters.PARAMS_VERSION,
                params_snapshot=_params_snapshot(algo_id),
                indicator_snapshot=ind,
                macro_snapshot=macro,
                market_snapshot=_market_snapshot(price, ohlcv, data_timestamp),
                signal_reason=_signal_reason(algo_id, signal, ind, macro),
                risk_snapshot=risk_decision.as_dict(),
            )
            state.open_positions[algo_id] = new_pos
            resulting_position_id = new_pos.get("id")

        except Exception as exc:
            had_algo_error = True
            action = "error"
            skipped_reason = str(exc)
            logger.error("알고 %s 오류: %s", algo_id, exc)
        finally:
            capture_results.append(
                await data_lake.record_decision(
                    run_id=run_id,
                    algo_id=algo_id,
                    signal=signal,
                    action=action,
                    reason=_signal_reason(algo_id, signal, ind, macro),
                    current_position_id=current_position_id,
                    resulting_position_id=resulting_position_id,
                    skipped_reason=skipped_reason,
                    risk_decision=risk_decision.as_dict() if risk_decision else None,
                    risk_snapshot=risk_decision.as_dict() if risk_decision else None,
                )
            )

    capture_results.extend(
        await _run_shadow_vnext(
            run_id=run_id,
            data_timestamp=data_timestamp,
            price=price,
            ind=ind,
            macro=macro,
            policy=policy,
            portfolio_risk_state=portfolio_risk_state,
        )
    )

    await data_lake.record_run_completed(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc),
        status="partial_failed" if had_algo_error else "completed",
        data_timestamp=data_timestamp,
        capture_results=capture_results,
    )


async def run() -> None:
    """APScheduler 시작 + 즉시 1회 실행. server.py에서 asyncio.gather()로 호출."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_cycle,
        "cron",
        hour=parameters.SCHEDULER_CRON_HOUR,
        minute=parameters.SCHEDULER_CRON_MINUTE,
    )
    scheduler.start()
    logger.info("Scheduler started (cron every 4H at :%02d)", parameters.SCHEDULER_CRON_MINUTE)

    await _run_cycle()

    try:
        while True:
            await asyncio.sleep(parameters.SERVER_IDLE_SLEEP_SECONDS)
    finally:
        scheduler.shutdown()
