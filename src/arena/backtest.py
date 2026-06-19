"""Backtest replay engine for arena strategies.

The core replay path is intentionally pure: callers pass frames and algorithms,
and receive serializable results. Supabase I/O lives in thin async helpers at the
bottom so tests and future walk-forward jobs can reuse the same rule engine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from . import algorithms, execution_rules, indicators, market_structure, parameters, risk

StrategyFn = Callable[[dict[str, Any], dict[str, float]], str | None]


@dataclass(frozen=True)
class ReplayBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class ReplayFrame:
    bar: ReplayBar
    indicators: dict[str, float]
    macro: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)

    @property
    def data_timestamp(self) -> datetime:
        return self.bar.close_time


@dataclass(frozen=True)
class BacktestSettings:
    strategy_version: str = parameters.STRATEGY_VERSION
    params_version: str = parameters.PARAMS_VERSION
    feature_set_version: str = parameters.FEATURE_SET_VERSION
    risk_model_version: str = parameters.RISK_MODEL_VERSION
    symbol: str = parameters.BINANCE_SYMBOL
    interval: str = parameters.BINANCE_KLINE_INTERVAL
    fee_bps: float = parameters.FEE_BPS
    slippage_bps: float = 0.0
    atr_multiple: float = parameters.ATR_MULTIPLE
    stop_loss_min_pct: float = parameters.STOP_LOSS_MIN_PCT
    stop_loss_max_pct: float = parameters.STOP_LOSS_MAX_PCT
    stop_loss_fallback_pct: float = parameters.STOP_LOSS_FALLBACK_PCT
    macro_stale_hours: float = parameters.MACRO_STALE_HOURS
    min_hold_hours: dict[str, float] = field(
        default_factory=lambda: dict(parameters.MIN_HOLD_HOURS)
    )
    min_hold_fallback_hours: float = parameters.MIN_HOLD_FALLBACK_HOURS
    position_unit: float = parameters.POSITION_UNIT
    max_open_positions_total: int = parameters.MAX_OPEN_POSITIONS_TOTAL
    max_long_positions: int = parameters.MAX_LONG_POSITIONS
    max_short_positions: int = parameters.MAX_SHORT_POSITIONS
    max_net_long_exposure: float = parameters.MAX_NET_LONG_EXPOSURE
    max_net_short_exposure: float = parameters.MAX_NET_SHORT_EXPOSURE
    daily_loss_limit_pct: float = parameters.DAILY_LOSS_LIMIT_PCT
    algo_max_drawdown_kill_pct: float = parameters.ALGO_MAX_DRAWDOWN_KILL_PCT
    cooldown_after_kill_hours: float = parameters.COOLDOWN_AFTER_KILL_HOURS
    close_open_at_end: bool = True
    warmup_bars: int = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD


@dataclass
class SimPosition:
    algo_id: str
    direction: str
    open_time: datetime
    open_price: float
    stop_loss_price: float
    entry_data_timestamp: datetime
    params_snapshot: dict[str, Any]
    indicator_snapshot: dict[str, Any]
    macro_snapshot: dict[str, Any]
    risk_snapshot: dict[str, Any]

    def as_live_position(self) -> dict[str, Any]:
        return {
            "algo_id": self.algo_id,
            "direction": self.direction,
            "open_time": execution_rules.format_utc_timestamp(self.open_time),
            "open_price": self.open_price,
            "stop_loss_price": self.stop_loss_price,
            "risk_snapshot": self.risk_snapshot,
        }

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "algo_id": self.algo_id,
            "direction": self.direction,
            "open_time": execution_rules.format_utc_timestamp(self.open_time),
            "open_price": self.open_price,
            "stop_loss_price": self.stop_loss_price,
        }


@dataclass(frozen=True)
class BacktestTrade:
    algo_id: str
    direction: str
    open_time: datetime
    close_time: datetime
    entry_data_timestamp: datetime
    close_data_timestamp: datetime
    open_price: float
    close_price: float
    stop_loss_price: float
    ret_pct: float
    gross_ret_pct: float
    trading_cost_pct: float
    funding_ret_pct: float
    net_ret_pct: float
    hold_hours: float
    exit_reason: str
    params_snapshot: dict[str, Any]
    indicator_snapshot: dict[str, Any]
    macro_snapshot: dict[str, Any]
    risk_snapshot: dict[str, Any]


@dataclass(frozen=True)
class BacktestRiskEvent:
    algo_id: str
    data_timestamp: datetime
    signal: str
    event_type: str
    risk_decision: dict[str, Any]
    risk_snapshot: dict[str, Any]


@dataclass(frozen=True)
class FundingEvent:
    symbol: str
    funding_time: datetime
    funding_rate: float


@dataclass(frozen=True)
class EquityPoint:
    algo_id: str
    data_timestamp: datetime
    bar_open_time: datetime
    bar_close_time: datetime
    equity: float
    realized_ret_pct: float
    cumulative_ret_pct: float
    drawdown_pct: float
    open_position: dict[str, Any] | None


@dataclass(frozen=True)
class BacktestResult:
    backtest_run_id: str
    settings: BacktestSettings
    started_at: datetime
    completed_at: datetime
    frames: list[ReplayFrame]
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    risk_events: list[BacktestRiskEvent]
    metrics: dict[str, Any]
    params_snapshot: dict[str, Any]


def _clean_macro(
    macro: dict[str, Any], decision_time: datetime, settings: BacktestSettings
) -> dict[str, Any]:
    reference_date = macro.get("reference_date")
    stale_hours = macro.get("stale_hours")
    if reference_date:
        try:
            ref_dt = execution_rules.parse_utc_datetime(str(reference_date))
            stale_hours = (decision_time - ref_dt).total_seconds() / 3600.0
        except ValueError:
            return {}
    if stale_hours is not None and float(stale_hours) > settings.macro_stale_hours:
        return {}
    cleaned = dict(macro)
    if stale_hours is not None:
        cleaned["stale_hours"] = round(float(stale_hours), 2)
    return cleaned


def _params_snapshot(algo_id: str, settings: BacktestSettings) -> dict[str, Any]:
    return execution_rules.build_params_snapshot(
        base_snapshot=parameters.base_params_snapshot(),
        algo_id=algo_id,
        stop_loss_fallback_pct=settings.stop_loss_fallback_pct,
        fee_bps=settings.fee_bps,
        atr_multiple=settings.atr_multiple,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
        macro_stale_hours=settings.macro_stale_hours,
        slippage_bps=settings.slippage_bps,
        portfolio_risk=risk.policy_snapshot(_risk_policy(settings)),
    )


def _risk_policy(settings: BacktestSettings) -> risk.PortfolioRiskPolicy:
    return risk.PortfolioRiskPolicy(
        risk_model_version=settings.risk_model_version,
        position_unit=settings.position_unit,
        max_open_positions_total=settings.max_open_positions_total,
        max_long_positions=settings.max_long_positions,
        max_short_positions=settings.max_short_positions,
        max_net_long_exposure=settings.max_net_long_exposure,
        max_net_short_exposure=settings.max_net_short_exposure,
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        algo_max_drawdown_kill_pct=settings.algo_max_drawdown_kill_pct,
        cooldown_after_kill_hours=settings.cooldown_after_kill_hours,
    )


def _open_position(
    *,
    algo_id: str,
    direction: str,
    frame: ReplayFrame,
    macro: dict[str, Any],
    settings: BacktestSettings,
    risk_snapshot: dict[str, Any],
) -> SimPosition:
    stop_loss_price = execution_rules.calc_stop_loss_price(
        direction,
        frame.bar.close,
        frame.indicators["atr"],
        atr_multiple=settings.atr_multiple,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
    )
    return SimPosition(
        algo_id=algo_id,
        direction=direction,
        open_time=frame.bar.close_time,
        open_price=frame.bar.close,
        stop_loss_price=stop_loss_price,
        entry_data_timestamp=frame.data_timestamp,
        params_snapshot=_params_snapshot(algo_id, settings),
        indicator_snapshot=dict(frame.indicators),
        macro_snapshot=dict(macro),
        risk_snapshot=risk_snapshot,
    )


def _stop_fill_price(position: SimPosition, bar: ReplayBar) -> float | None:
    if position.direction == "long" and bar.low <= position.stop_loss_price:
        return min(bar.open, position.stop_loss_price)
    if position.direction == "short" and bar.high >= position.stop_loss_price:
        return max(bar.open, position.stop_loss_price)
    return None


def _close_position(
    position: SimPosition,
    *,
    close_time: datetime,
    close_data_timestamp: datetime,
    close_price: float,
    exit_reason: str,
    settings: BacktestSettings,
    funding_events: list[FundingEvent] | None = None,
) -> BacktestTrade:
    gross_ret = execution_rules.direction_sign(position.direction) * (
        close_price / position.open_price - 1.0
    )
    trading_cost = 2.0 * (settings.fee_bps + settings.slippage_bps) / 10_000.0
    funding_rows = [
        {
            "funding_time": execution_rules.format_utc_timestamp(event.funding_time),
            "funding_rate": event.funding_rate,
        }
        for event in (funding_events or [])
    ]
    funding_ret = market_structure.funding_return_pct(
        direction=position.direction,
        funding_rates=funding_rows,
        open_time=position.open_time,
        close_time=close_time,
    )
    net_ret = gross_ret - trading_cost + funding_ret
    return BacktestTrade(
        algo_id=position.algo_id,
        direction=position.direction,
        open_time=position.open_time,
        close_time=close_time,
        entry_data_timestamp=position.entry_data_timestamp,
        close_data_timestamp=close_data_timestamp,
        open_price=position.open_price,
        close_price=close_price,
        stop_loss_price=position.stop_loss_price,
        ret_pct=net_ret,
        gross_ret_pct=gross_ret,
        trading_cost_pct=trading_cost,
        funding_ret_pct=funding_ret,
        net_ret_pct=net_ret,
        hold_hours=execution_rules.hold_hours(position.open_time, close_time),
        exit_reason=exit_reason,
        params_snapshot=position.params_snapshot,
        indicator_snapshot=position.indicator_snapshot,
        macro_snapshot=position.macro_snapshot,
        risk_snapshot=position.risk_snapshot,
    )


def _metric_summary(
    *,
    algo_ids: list[str],
    trades: list[BacktestTrade],
    equity_by_algo: dict[str, float],
    max_drawdown_by_algo: dict[str, float],
) -> dict[str, Any]:
    by_algo: dict[str, Any] = {}
    for algo_id in algo_ids:
        algo_trades = [trade for trade in trades if trade.algo_id == algo_id]
        wins = [trade for trade in algo_trades if trade.ret_pct > 0]
        by_algo[algo_id] = {
            "trade_count": len(algo_trades),
            "win_rate": len(wins) / len(algo_trades) if algo_trades else None,
            "total_return_pct": equity_by_algo[algo_id] - 1.0,
            "avg_trade_ret_pct": (
                sum(trade.ret_pct for trade in algo_trades) / len(algo_trades)
                if algo_trades
                else None
            ),
            "max_drawdown_pct": max_drawdown_by_algo[algo_id],
        }
    return {"by_algo": by_algo}


def run_replay(
    frames: list[ReplayFrame],
    *,
    strategy_fns: dict[str, StrategyFn] | None = None,
    settings: BacktestSettings | None = None,
    backtest_run_id: str | None = None,
    funding_events: list[FundingEvent] | None = None,
) -> BacktestResult:
    settings = settings or BacktestSettings()
    strategy_fns = strategy_fns or algorithms.ALGORITHMS
    algo_ids = list(strategy_fns)
    sorted_frames = sorted(frames, key=lambda frame: frame.bar.close_time)

    positions_by_algo: dict[str, SimPosition | None] = {algo_id: None for algo_id in algo_ids}
    equity_by_algo = {algo_id: 1.0 for algo_id in algo_ids}
    peak_by_algo = {algo_id: 1.0 for algo_id in algo_ids}
    max_drawdown_by_algo = {algo_id: 0.0 for algo_id in algo_ids}
    # kill 시각 추적: kill 후 cooldown이 지나면 drawdown 카운터를 리셋하고 재진입 허용
    killed_at_by_algo: dict[str, datetime | None] = {algo_id: None for algo_id in algo_ids}
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    risk_events: list[BacktestRiskEvent] = []
    daily_realized_by_date: dict[str, float] = {}
    policy = _risk_policy(settings)
    funding_events = sorted(funding_events or [], key=lambda event: event.funding_time)
    started_at = datetime.now(timezone.utc)

    def _maybe_reset_drawdown(algo_id: str, now: datetime) -> None:
        """cooldown 종료 시 drawdown 카운터를 현재 equity 기준으로 리셋한다."""
        killed_at = killed_at_by_algo[algo_id]
        if killed_at is None:
            return
        elapsed_hours = (now - killed_at).total_seconds() / 3600.0
        if elapsed_hours >= settings.cooldown_after_kill_hours:
            peak_by_algo[algo_id] = equity_by_algo[algo_id]
            max_drawdown_by_algo[algo_id] = 0.0
            killed_at_by_algo[algo_id] = None

    def record_realized(algo_id: str, ret_pct: float, close_time: datetime) -> None:
        equity_by_algo[algo_id] *= 1.0 + ret_pct
        peak_by_algo[algo_id] = max(peak_by_algo[algo_id], equity_by_algo[algo_id])
        drawdown = equity_by_algo[algo_id] / peak_by_algo[algo_id] - 1.0
        max_drawdown_by_algo[algo_id] = min(max_drawdown_by_algo[algo_id], drawdown)
        day_key = close_time.date().isoformat()
        daily_realized_by_date[day_key] = daily_realized_by_date.get(day_key, 0.0) + ret_pct

    def risk_state_for(frame: ReplayFrame) -> risk.PortfolioRiskState:
        # cooldown 만료 여부를 먼저 확인해 drawdown 리셋
        for aid in algo_ids:
            _maybe_reset_drawdown(aid, frame.bar.close_time)
        return risk.PortfolioRiskState(
            daily_realized_ret_pct=daily_realized_by_date.get(
                frame.bar.close_time.date().isoformat(), 0.0
            ),
            algo_drawdown_pct=dict(max_drawdown_by_algo),
        )

    for frame in sorted_frames:
        frame_realized: dict[str, float] = {algo_id: 0.0 for algo_id in algo_ids}
        for algo_id, fn in strategy_fns.items():
            position = positions_by_algo[algo_id]
            stop_fill = _stop_fill_price(position, frame.bar) if position else None
            if position and stop_fill is not None:
                trade = _close_position(
                    position,
                    close_time=frame.bar.close_time,
                    close_data_timestamp=frame.data_timestamp,
                    close_price=stop_fill,
                    exit_reason="stop_loss",
                    settings=settings,
                    funding_events=funding_events,
                )
                trades.append(trade)
                record_realized(algo_id, trade.ret_pct, trade.close_time)
                frame_realized[algo_id] += trade.ret_pct
                positions_by_algo[algo_id] = None
                position = None

            macro = _clean_macro(frame.macro, frame.data_timestamp, settings)
            signal = fn(macro, frame.indicators)
            if signal is None:
                if position and execution_rules.min_hold_ok(
                    position.as_live_position(),
                    frame.bar.close_time,
                    algo_id,
                    settings.min_hold_hours,
                    settings.min_hold_fallback_hours,
                ):
                    trade = _close_position(
                        position,
                        close_time=frame.bar.close_time,
                        close_data_timestamp=frame.data_timestamp,
                        close_price=frame.bar.close,
                        exit_reason="signal_flat",
                        settings=settings,
                        funding_events=funding_events,
                    )
                    trades.append(trade)
                    record_realized(algo_id, trade.ret_pct, trade.close_time)
                    frame_realized[algo_id] += trade.ret_pct
                    positions_by_algo[algo_id] = None
                continue

            if position and position.direction == signal:
                continue

            if position:
                if not execution_rules.min_hold_ok(
                    position.as_live_position(),
                    frame.bar.close_time,
                    algo_id,
                    settings.min_hold_hours,
                    settings.min_hold_fallback_hours,
                ):
                    continue
                trade = _close_position(
                    position,
                    close_time=frame.bar.close_time,
                    close_data_timestamp=frame.data_timestamp,
                    close_price=frame.bar.close,
                    exit_reason="signal_reverse",
                    settings=settings,
                    funding_events=funding_events,
                )
                trades.append(trade)
                record_realized(algo_id, trade.ret_pct, trade.close_time)
                frame_realized[algo_id] += trade.ret_pct

            risk_decision = risk.evaluate_open(
                algo_id=algo_id,
                direction=signal,
                open_positions=positions_by_algo,
                state=risk_state_for(frame),
                evaluated_at=frame.bar.close_time,
                policy=policy,
            )
            if not risk_decision.allowed:
                risk_events.append(
                    BacktestRiskEvent(
                        algo_id=algo_id,
                        data_timestamp=frame.data_timestamp,
                        signal=signal,
                        event_type=risk_decision.reason,
                        risk_decision=risk_decision.as_dict(),
                        risk_snapshot=risk_decision.as_dict(),
                    )
                )
                # drawdown kill 최초 발생 시각만 기록 (이미 kill 중이면 갱신하지 않음)
                if (
                    risk_decision.reason == "algo_drawdown_kill"
                    and killed_at_by_algo[algo_id] is None
                ):
                    killed_at_by_algo[algo_id] = frame.bar.close_time
                continue

            positions_by_algo[algo_id] = _open_position(
                algo_id=algo_id,
                direction=signal,
                frame=frame,
                macro=macro,
                settings=settings,
                risk_snapshot=risk_decision.as_dict(),
            )

        for algo_id in algo_ids:
            peak_by_algo[algo_id] = max(peak_by_algo[algo_id], equity_by_algo[algo_id])
            drawdown = equity_by_algo[algo_id] / peak_by_algo[algo_id] - 1.0
            max_drawdown_by_algo[algo_id] = min(max_drawdown_by_algo[algo_id], drawdown)
            open_position = positions_by_algo[algo_id]
            equity_curve.append(
                EquityPoint(
                    algo_id=algo_id,
                    data_timestamp=frame.data_timestamp,
                    bar_open_time=frame.bar.open_time,
                    bar_close_time=frame.bar.close_time,
                    equity=equity_by_algo[algo_id],
                    realized_ret_pct=frame_realized[algo_id],
                    cumulative_ret_pct=equity_by_algo[algo_id] - 1.0,
                    drawdown_pct=drawdown,
                    open_position=open_position.as_snapshot() if open_position else None,
                )
            )

    if settings.close_open_at_end and sorted_frames:
        last_frame = sorted_frames[-1]
        for algo_id, position in list(positions_by_algo.items()):
            if not position:
                continue
            trade = _close_position(
                position,
                close_time=last_frame.bar.close_time,
                close_data_timestamp=last_frame.data_timestamp,
                close_price=last_frame.bar.close,
                exit_reason="end_of_data",
                settings=settings,
                funding_events=funding_events,
            )
            trades.append(trade)
            record_realized(algo_id, trade.ret_pct, trade.close_time)
            positions_by_algo[algo_id] = None
            drawdown = equity_by_algo[algo_id] / peak_by_algo[algo_id] - 1.0
            for index in range(len(equity_curve) - 1, -1, -1):
                point = equity_curve[index]
                if point.algo_id != algo_id:
                    continue
                equity_curve[index] = replace(
                    point,
                    equity=equity_by_algo[algo_id],
                    realized_ret_pct=point.realized_ret_pct + trade.ret_pct,
                    cumulative_ret_pct=equity_by_algo[algo_id] - 1.0,
                    drawdown_pct=drawdown,
                    open_position=None,
                )
                break

    return BacktestResult(
        backtest_run_id=backtest_run_id or str(uuid4()),
        settings=settings,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        frames=sorted_frames,
        trades=trades,
        equity_curve=equity_curve,
        risk_events=risk_events,
        metrics=_metric_summary(
            algo_ids=algo_ids,
            trades=trades,
            equity_by_algo=equity_by_algo,
            max_drawdown_by_algo=max_drawdown_by_algo,
        ),
        params_snapshot=parameters.base_params_snapshot(),
    )


def _row_ts(value: Any) -> datetime:
    return execution_rules.parse_utc_datetime(value)


def _macro_signal_from_snapshot(row: dict[str, Any], decision_time: datetime) -> dict[str, Any]:
    risk_overlay = row.get("risk_overlay") or {}
    raw = risk_overlay.get("regimeRaw") or {}
    macro = {
        "regime_state": risk_overlay.get("regimeState", ""),
        "fng": raw.get("fng"),
        "vix_now": raw.get("vix_now"),
        "vix_q40": raw.get("vix_q40"),
        "fetched_at": row.get("fetched_at"),
        "reference_date": row.get("reference_date"),
        "stale_hours": row.get("stale_hours"),
    }
    reference_date = macro.get("reference_date")
    if reference_date:
        try:
            ref_dt = execution_rules.parse_utc_datetime(str(reference_date))
            macro["stale_hours"] = round((decision_time - ref_dt).total_seconds() / 3600.0, 2)
        except ValueError:
            macro["stale_hours"] = None
    return macro


def _latest_macro_for_time(
    macros: list[dict[str, Any]],
    decision_time: datetime,
    start_index: int,
) -> tuple[dict[str, Any], int]:
    index = start_index
    selected: dict[str, Any] | None = None
    while index < len(macros) and _row_ts(macros[index]["fetched_at"]) <= decision_time:
        selected = macros[index]
        index += 1
    if selected is None and start_index > 0:
        selected = macros[start_index - 1]
    return (_macro_signal_from_snapshot(selected, decision_time) if selected else {}, index)


def _interval_hours(interval: str) -> int:
    """'4h' → 4, '1h' → 1, '1d' → 24."""
    if interval.endswith("d"):
        return int(interval[:-1]) * 24
    if interval.endswith("h"):
        return int(interval[:-1])
    return 4


async def load_frames_from_supabase(
    db: Any,
    *,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    limit: int = 1000,
    warmup_bars: int = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[ReplayFrame]:
    """Load replay frames from Supabase.

    When from_date / to_date are given, bars outside the window are fetched only
    for indicator warm-up and are not included in the returned frames.
    limit is ignored when a date range is specified.
    """
    from datetime import timedelta

    builder = (
        db.table("arena_ohlcv_bars")
        .select("open_time,close_time,open,high,low,close,volume")
        .eq("symbol", symbol)
        .eq("interval", interval)
    )

    if from_date is not None or to_date is not None:
        if from_date is not None:
            # fetch extra bars before from_date to warm up indicators
            pre_start = from_date - timedelta(hours=_interval_hours(interval) * (warmup_bars + 5))
            builder = builder.gte("open_time", _ts(pre_start))
        if to_date is not None:
            builder = builder.lte("close_time", _ts(to_date))
        builder = builder.order("open_time").limit(5000)
    else:
        builder = builder.order("open_time", desc=True).limit(limit)

    bars_res = await builder.execute()
    bar_rows = sorted(bars_res.data, key=lambda row: row["open_time"])

    macro_filter: dict[str, Any] = {}
    if from_date is not None:
        macro_filter["gte"] = (
            "fetched_at",
            _ts(from_date - timedelta(hours=_interval_hours(interval) * (warmup_bars + 5))),
        )
    macros_res = (
        await db.table("arena_macro_snapshots")
        .select("fetched_at,reference_date,stale_hours,risk_overlay")
        .order("fetched_at")
        .execute()
    )
    macro_rows = macros_res.data

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    frames: list[ReplayFrame] = []
    macro_index = 0
    for row in bar_rows:
        bar = ReplayBar(
            open_time=_row_ts(row["open_time"]),
            close_time=_row_ts(row["close_time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
        )
        highs.append(bar.high)
        lows.append(bar.low)
        closes.append(bar.close)
        if len(closes) < warmup_bars:
            continue
        macro, macro_index = _latest_macro_for_time(macro_rows, bar.close_time, macro_index)
        frame = ReplayFrame(
            bar=bar,
            indicators=indicators.compute(highs, lows, closes),
            macro=macro,
            market_features={},
        )
        # date range filter: warmup bars are consumed above but not emitted
        if from_date is not None and bar.close_time < from_date:
            continue
        if to_date is not None and bar.close_time > to_date:
            continue
        frames.append(frame)
    return frames


async def load_funding_events_from_supabase(
    db: Any,
    *,
    symbol: str = parameters.BINANCE_SYMBOL,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[FundingEvent]:
    builder = (
        db.table("arena_funding_rates")
        .select("symbol,funding_time,funding_rate")
        .eq(
            "symbol",
            symbol,
        )
    )
    if from_date is not None:
        builder = builder.gt("funding_time", _ts(from_date))
    if to_date is not None:
        builder = builder.lte("funding_time", _ts(to_date))
    try:
        res = await builder.order("funding_time").limit(5000).execute()
    except Exception:
        return []
    events: list[FundingEvent] = []
    for row in res.data or []:
        try:
            events.append(
                FundingEvent(
                    symbol=row["symbol"],
                    funding_time=_row_ts(row["funding_time"]),
                    funding_rate=float(row["funding_rate"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return events


def _ts(value: datetime) -> str:
    return execution_rules.format_utc_timestamp(value)


def _run_row(result: BacktestResult) -> dict[str, Any]:
    frames = result.frames
    settings = result.settings
    return {
        "backtest_run_id": result.backtest_run_id,
        "started_at": _ts(result.started_at),
        "completed_at": _ts(result.completed_at),
        "status": "completed",
        "runtime": "research",
        "symbol": settings.symbol,
        "interval": settings.interval,
        "strategy_version": settings.strategy_version,
        "params_version": settings.params_version,
        "feature_set_version": settings.feature_set_version,
        "risk_model_version": settings.risk_model_version,
        "params_snapshot": result.params_snapshot,
        "rules_snapshot": {
            "fee_bps": settings.fee_bps,
            "slippage_bps": settings.slippage_bps,
            "atr_multiple": settings.atr_multiple,
            "stop_loss_min_pct": settings.stop_loss_min_pct,
            "stop_loss_max_pct": settings.stop_loss_max_pct,
            "macro_stale_hours": settings.macro_stale_hours,
            "min_hold_hours": settings.min_hold_hours,
            "portfolio_risk": risk.policy_snapshot(_risk_policy(settings)),
            "funding_model": "funding_events_open_exclusive_close_inclusive_v1",
            "close_open_at_end": settings.close_open_at_end,
        },
        "data_start": _ts(frames[0].data_timestamp) if frames else None,
        "data_end": _ts(frames[-1].data_timestamp) if frames else None,
        "bar_count": len(frames),
        "warmup_bars": settings.warmup_bars,
        "algo_ids": list(result.metrics["by_algo"]),
        "fee_bps": settings.fee_bps,
        "slippage_bps": settings.slippage_bps,
        "metrics": result.metrics,
    }


def _trade_rows(result: BacktestResult) -> list[dict[str, Any]]:
    return [
        {
            "backtest_run_id": result.backtest_run_id,
            "algo_id": trade.algo_id,
            "direction": trade.direction,
            "open_time": _ts(trade.open_time),
            "close_time": _ts(trade.close_time),
            "entry_data_timestamp": _ts(trade.entry_data_timestamp),
            "close_data_timestamp": _ts(trade.close_data_timestamp),
            "open_price": trade.open_price,
            "close_price": trade.close_price,
            "stop_loss_price": trade.stop_loss_price,
            "ret_pct": trade.ret_pct,
            "gross_ret_pct": trade.gross_ret_pct,
            "trading_cost_pct": trade.trading_cost_pct,
            "funding_ret_pct": trade.funding_ret_pct,
            "net_ret_pct": trade.net_ret_pct,
            "hold_hours": trade.hold_hours,
            "exit_reason": trade.exit_reason,
            "params_snapshot": trade.params_snapshot,
            "indicator_snapshot": trade.indicator_snapshot,
            "macro_snapshot": trade.macro_snapshot,
            "risk_snapshot": trade.risk_snapshot,
        }
        for trade in result.trades
    ]


def _equity_rows(result: BacktestResult) -> list[dict[str, Any]]:
    return [
        {
            "backtest_run_id": result.backtest_run_id,
            "algo_id": point.algo_id,
            "data_timestamp": _ts(point.data_timestamp),
            "bar_open_time": _ts(point.bar_open_time),
            "bar_close_time": _ts(point.bar_close_time),
            "equity": point.equity,
            "realized_ret_pct": point.realized_ret_pct,
            "cumulative_ret_pct": point.cumulative_ret_pct,
            "drawdown_pct": point.drawdown_pct,
            "open_position": point.open_position,
        }
        for point in result.equity_curve
    ]


def _risk_event_rows(result: BacktestResult) -> list[dict[str, Any]]:
    return [
        {
            "backtest_run_id": result.backtest_run_id,
            "algo_id": event.algo_id,
            "data_timestamp": _ts(event.data_timestamp),
            "signal": event.signal,
            "event_type": event.event_type,
            "risk_decision": event.risk_decision,
            "risk_snapshot": event.risk_snapshot,
        }
        for event in result.risk_events
    ]


async def save_result_to_supabase(db: Any, result: BacktestResult) -> None:
    await db.table("arena_backtest_runs").insert(_run_row(result)).execute()
    trade_rows = _trade_rows(result)
    if trade_rows:
        await db.table("arena_backtest_trades").insert(trade_rows).execute()
    equity_rows = _equity_rows(result)
    for start in range(0, len(equity_rows), 500):
        await (
            db.table("arena_backtest_equity_curve")
            .insert(equity_rows[start : start + 500])
            .execute()
        )
    risk_event_rows = _risk_event_rows(result)
    if risk_event_rows:
        await db.table("arena_backtest_risk_events").insert(risk_event_rows).execute()


def _parse_date_arg(value: str) -> datetime:
    """'2026-03-21' 또는 ISO 8601 형식을 UTC datetime으로 변환."""
    from datetime import timezone

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"날짜 형식 오류: {value!r} (YYYY-MM-DD 또는 ISO 8601)")


async def _resolve_split_dates(
    db: Any,
    split_name: str,
    window: str,
) -> tuple[datetime, datetime]:
    """arena_walk_forward_splits에서 split의 train/test 날짜를 가져온다."""
    res = (
        await db.table("arena_walk_forward_splits")
        .select("train_start,train_end,test_start,test_end")
        .eq("split_name", split_name)
        .single()
        .execute()
    )
    row = res.data
    if window == "train":
        return _row_ts(row["train_start"]), _row_ts(row["train_end"])
    if window == "test":
        return _row_ts(row["test_start"]), _row_ts(row["test_end"])
    raise ValueError(f"window는 'train' 또는 'test'여야 합니다: {window!r}")


async def _amain(args: argparse.Namespace) -> int:
    from . import positions

    await positions.init()
    db = positions.db()

    from_date: datetime | None = getattr(args, "from_date", None)
    to_date: datetime | None = getattr(args, "to_date", None)

    if args.split:
        if not args.window:
            print(
                "--split 사용 시 --window train 또는 --window test 필요",
                file=__import__("sys").stderr,
            )
            return 1
        from_date, to_date = await _resolve_split_dates(db, args.split, args.window)
        print(f"split={args.split} window={args.window}: {_ts(from_date)} ~ {_ts(to_date)}")

    frames = await load_frames_from_supabase(
        db,
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        from_date=from_date,
        to_date=to_date,
    )
    if not frames:
        print("프레임 없음 — date range 또는 데이터를 확인하세요.")
        return 1

    funding_events = await load_funding_events_from_supabase(
        db,
        symbol=args.symbol,
        from_date=frames[0].bar.close_time if frames else None,
        to_date=frames[-1].bar.close_time if frames else None,
    )
    settings = BacktestSettings(
        symbol=args.symbol,
        interval=args.interval,
        slippage_bps=args.slippage_bps,
        close_open_at_end=not args.keep_open_at_end,
    )
    result = run_replay(frames, settings=settings, funding_events=funding_events)
    if args.save:
        await save_result_to_supabase(db, result)
    print(json.dumps(_run_row(result), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run arena rule-parity backtest.")
    parser.add_argument("--symbol", default=parameters.BINANCE_SYMBOL)
    parser.add_argument("--interval", default=parameters.BINANCE_KLINE_INTERVAL)
    parser.add_argument(
        "--limit", type=int, default=1000, help="--from-date/--to-date 미지정 시 최근 N bars 사용"
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        type=_parse_date_arg,
        default=None,
        metavar="YYYY-MM-DD",
        help="프레임 시작일 (포함). 이전 bars는 warmup으로만 사용",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        type=_parse_date_arg,
        default=None,
        metavar="YYYY-MM-DD",
        help="프레임 종료일 (포함)",
    )
    parser.add_argument(
        "--split",
        default=None,
        metavar="SPLIT_NAME",
        help="walk-forward split 이름 (예: BTCUSDT_4h_wf-v1_s00)",
    )
    parser.add_argument(
        "--window",
        choices=["train", "test"],
        default=None,
        help="--split 사용 시 train 또는 test window 선택",
    )
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--keep-open-at-end", action="store_true")
    parser.add_argument("--save", action="store_true")
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
