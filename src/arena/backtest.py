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

from . import (
    algorithms,
    execution_rules,
    frequency,
    indicators,
    market_structure,
    parameters,
    realtime_risk,
    regime,
    risk,
    spot_policy,
)

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
    frequency_profile_id: str = frequency.LIVE_4H_PROFILE_ID
    indicator_profile_id: str = frequency.DEFAULT_INDICATOR_PROFILE_ID
    cost_model_version: str = frequency.COST_MODEL_VERSION
    cost_scenario_id: str = frequency.DEFAULT_COST_SCENARIO_ID
    strategy_version: str = parameters.STRATEGY_VERSION
    params_version: str = parameters.PARAMS_VERSION
    feature_set_version: str = parameters.FEATURE_SET_VERSION
    risk_model_version: str = parameters.RISK_MODEL_VERSION
    regime_variant: str = regime.REGIME_VARIANT_STRICT
    product_type: str = parameters.TARGET_PRODUCT
    position_semantics: str = parameters.POSITION_SEMANTICS
    symbol: str = parameters.BINANCE_SYMBOL
    interval: str = parameters.BINANCE_KLINE_INTERVAL
    fee_bps: float = parameters.FEE_BPS
    slippage_bps: float = 0.0
    spread_bps_round_trip: float = 0.0
    funding_buffer_bps_per_8h: float = 0.0
    ecr_threshold: float = 1.3
    max_trades_per_day_per_algo: float = 3.0
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
    replay_execution_gate_blocks: bool = False
    replay_realtime_risk_blocks: bool = False
    close_open_at_end: bool = True
    warmup_bars: int = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD


@dataclass
class SimPosition:
    algo_id: str
    direction: str
    open_time: datetime
    open_price: float
    stop_loss_price: float
    trail_distance: float
    position_weight: float
    entry_data_timestamp: datetime
    params_snapshot: dict[str, Any]
    indicator_snapshot: dict[str, Any]
    macro_snapshot: dict[str, Any]
    risk_snapshot: dict[str, Any]
    fng_ref_price: float = 0.0
    fng_filled_count: int = 0
    omni_target_price: float | None = None  # WI-7: omnibus 평균회귀 익절 목표가(진입 시 고정)
    fng_target_pct: float | None = None  # P-A: fng 이익포착 목표 상승률(평단×(1+pct) 익절)

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
    position_weight: float
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
    snapshot = execution_rules.build_params_snapshot(
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
    snapshot["frequency_research"] = {
        "frequency_profile_id": settings.frequency_profile_id,
        "indicator_profile_id": settings.indicator_profile_id,
        "cost_model_version": settings.cost_model_version,
        "cost_scenario_id": settings.cost_scenario_id,
        "spread_bps_round_trip": settings.spread_bps_round_trip,
        "funding_buffer_bps_per_8h": settings.funding_buffer_bps_per_8h,
        "ecr_threshold": settings.ecr_threshold,
        "max_trades_per_day_per_algo": settings.max_trades_per_day_per_algo,
    }
    snapshot["regime_research"] = {
        "regime_variant": settings.regime_variant,
        "live_default_regime_variant": regime.REGIME_VARIANT_STRICT,
    }
    snapshot["live_gate_replay"] = {
        "replay_execution_gate_blocks": settings.replay_execution_gate_blocks,
        "replay_realtime_risk_blocks": settings.replay_realtime_risk_blocks,
    }
    snapshot["execution_product"] = {
        "target_product": settings.product_type,
        "position_semantics": settings.position_semantics,
        "short_signal_action": parameters.SHORT_SIGNAL_ACTION,
        "allow_live_short": settings.product_type != "spot",
        "spot_execution_only": settings.product_type == "spot",
        "derivatives_data_usage": "research_features_only",
    }
    return snapshot


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


def _base_params_snapshot_from_settings(settings: BacktestSettings) -> dict[str, Any]:
    snapshot = parameters.base_params_snapshot()
    snapshot["market_data"].update(
        {
            "symbol": settings.symbol,
            "kline_interval": settings.interval,
            "frequency_profile_id": settings.frequency_profile_id,
            "indicator_profile_id": settings.indicator_profile_id,
            "cost_model_version": settings.cost_model_version,
            "cost_scenario_id": settings.cost_scenario_id,
        }
    )
    try:
        profile = frequency.get_frequency_profile(settings.frequency_profile_id)
        cost = frequency.get_cost_scenario(settings.frequency_profile_id, settings.cost_scenario_id)
        snapshot["frequency_research"] = frequency.profile_snapshot(
            profile,
            indicator_profile_id=settings.indicator_profile_id,
            cost_scenario_id=cost.cost_scenario_id,
        )
    except ValueError:
        snapshot["frequency_research"] = {
            "frequency_profile_id": settings.frequency_profile_id,
            "indicator_profile_id": settings.indicator_profile_id,
            "cost_model_version": settings.cost_model_version,
            "cost_scenario_id": settings.cost_scenario_id,
        }
    snapshot["regime_research"] = {
        "regime_variant": settings.regime_variant,
        "live_default_regime_variant": regime.REGIME_VARIANT_STRICT,
    }
    snapshot["live_gate_replay"] = {
        "replay_execution_gate_blocks": settings.replay_execution_gate_blocks,
        "replay_realtime_risk_blocks": settings.replay_realtime_risk_blocks,
    }
    snapshot["execution_product"] = {
        "target_product": settings.product_type,
        "position_semantics": settings.position_semantics,
        "short_signal_action": parameters.SHORT_SIGNAL_ACTION,
        "allow_live_short": settings.product_type != "spot",
        "spot_execution_only": settings.product_type == "spot",
        "derivatives_data_usage": "research_features_only",
    }
    return snapshot


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
    # 포지션 사이징 — live(scheduler)와 동일 가중치를 백테스트 equity에도 반영.
    fng_ref_price = 0.0
    fng_filled_count = 0
    if algo_id == "fng_contrarian" and parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED:
        # 역발산: 1차 트랜치만 진입. 추가 트랜치는 가격 하락 시 물타기(_maybe_scale_in_fng_sim).
        position_weight = parameters.FNG_CONTRARIAN_PRICE_TRANCHES[0][1]
        fng_ref_price = frame.bar.close  # 물타기 기준가 = 최초 진입가
        fng_filled_count = 1
    else:
        position_weight = execution_rules.combined_position_weight(
            float(frame.indicators.get("realized_vol_24h") or 0.0),
            frame.bar.close,
            stop_loss_price,
            target_vol=parameters.VOL_TARGET_PER_BAR,
            risk_budget_pct=parameters.RISK_PER_TRADE_PCT,
            weight_min=parameters.VOL_WEIGHT_MIN,
            weight_max=parameters.VOL_WEIGHT_MAX,
        )
    # WI-7: omnibus 평균회귀 익절 목표가(진입 시점 고정). live scheduler와 동일 순수함수.
    omni_target_price = None
    if algo_id == "omnibus":
        omni_target_price = algorithms.omnibus_target_price(
            macro, frame.indicators, frame.bar.close
        )
    # P-A: fng 이익포착 목표 상승률(비율). 물타기로 평단 하락 시 청산가 자동 하향.
    fng_tp = None
    if algo_id == "fng_contrarian":
        fng_tp = algorithms.fng_target_pct(frame.indicators, frame.bar.close)
    return SimPosition(
        algo_id=algo_id,
        direction=direction,
        open_time=frame.bar.close_time,
        open_price=frame.bar.close,
        stop_loss_price=stop_loss_price,
        trail_distance=execution_rules.trail_distance_from_stop(frame.bar.close, stop_loss_price),
        position_weight=position_weight,
        entry_data_timestamp=frame.data_timestamp,
        params_snapshot=_params_snapshot(algo_id, settings),
        indicator_snapshot=dict(frame.indicators),
        macro_snapshot=dict(macro),
        risk_snapshot=risk_snapshot,
        fng_ref_price=fng_ref_price,
        fng_filled_count=fng_filled_count,
        omni_target_price=omni_target_price,
        fng_target_pct=fng_tp,
    )


def _maybe_scale_in_fng_sim(position: SimPosition, eval_price: float) -> SimPosition:
    """역발산 가격 기준 물타기(backtest) — live positions.maybe_scale_in_fng_price 패리티.

    봉 저가(eval_price)가 다음 트랜치 한계가(ref×(1+drop)) 이하로 내려가면 그 한계가에
    추가 체결. 누적 비중 VOL_WEIGHT_MAX 상한. live(1m 틱)와 동일 한계가 체결로 패리티.
    추가분 없으면 원본 포지션 그대로 반환.
    """
    ref_price = position.fng_ref_price or position.open_price
    pending = execution_rules.pending_price_tranches(
        eval_price,
        ref_price,
        position.fng_filled_count,
        parameters.FNG_CONTRARIAN_PRICE_TRANCHES,
    )
    if not pending:
        return position
    new_open, new_weight, applied = execution_rules.fill_price_tranches(
        position.open_price,
        position.position_weight,
        ref_price,
        pending,
        parameters.FNG_CONTRARIAN_PRICE_TRANCHES,
        parameters.VOL_WEIGHT_MAX,
    )
    if applied <= 0:
        return position
    return replace(
        position,
        open_price=new_open,
        position_weight=new_weight,
        fng_filled_count=position.fng_filled_count + applied,
    )


def _stop_fill_price(position: SimPosition, bar: ReplayBar) -> float | None:
    if position.direction == "long" and bar.low <= position.stop_loss_price:
        return min(bar.open, position.stop_loss_price)
    if position.direction == "short" and bar.high >= position.stop_loss_price:
        return max(bar.open, position.stop_loss_price)
    return None


def _stop_exit_reason(position: SimPosition) -> str:
    """초기 손절 vs 트레일링 래칫 손절 구분 (live stream.py와 동일 라벨)."""
    if execution_rules.is_trailing_exit(
        direction=position.direction,
        open_price=position.open_price,
        stop_loss_price=position.stop_loss_price,
        trail_distance=position.trail_distance,
    ):
        return "trailing_stop"
    return "stop_loss"


def _live_gate_block_reason(frame: ReplayFrame, settings: BacktestSettings) -> str | None:
    features = frame.market_features or {}
    if settings.replay_execution_gate_blocks and features.get("execution_gate_allowed") is False:
        return str(features.get("execution_gate_reject_reason") or "execution_gate_blocked")
    if settings.replay_realtime_risk_blocks and features.get("realtime_risk_fresh") is True:
        risk_state = features.get("realtime_risk_state")
        if risk_state in {
            realtime_risk.STATE_BLOCK_ENTRY,
            realtime_risk.STATE_EXIT_CANDIDATE,
            realtime_risk.STATE_FORCE_EXIT_CANDIDATE,
        }:
            return f"realtime_risk:{risk_state}"
    return None


def _ratchet_sim_position(position: SimPosition, bar: ReplayBar) -> None:
    """봉 종가 기준 트레일링 손절가 래칫(인플레이스). look-ahead 방지를 위해
    스톱 트리거 체크가 끝난 뒤 호출 → 갱신값은 다음 봉부터 적용."""
    if not parameters.TRAILING_STOP_ENABLED or position.trail_distance <= 0:
        return
    position.stop_loss_price = execution_rules.ratchet_trailing_stop(
        direction=position.direction,
        current_price=bar.close,
        current_stop=position.stop_loss_price,
        trail_distance=position.trail_distance,
    )


def _position_product_type(position: SimPosition) -> str:
    return str(position.params_snapshot.get("execution_product", {}).get("target_product") or "")


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
    trading_cost = (
        2.0 * (settings.fee_bps + settings.slippage_bps) + settings.spread_bps_round_trip
    ) / 10_000.0
    funding_rows = [
        {
            "funding_time": execution_rules.format_utc_timestamp(event.funding_time),
            "funding_rate": event.funding_rate,
        }
        for event in (funding_events or [])
    ]
    funding_ret = 0.0
    if _position_product_type(position) != "spot":
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
        position_weight=position.position_weight,
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
    frames: list[ReplayFrame],
) -> dict[str, Any]:
    by_algo: dict[str, Any] = {}
    data_days = 0.0
    if len(frames) >= 2:
        data_days = max(
            (frames[-1].data_timestamp - frames[0].data_timestamp).total_seconds() / 86400.0,
            1e-9,
        )
    for algo_id in algo_ids:
        algo_trades = [trade for trade in trades if trade.algo_id == algo_id]
        wins = [trade for trade in algo_trades if trade.ret_pct > 0]
        gross_return = sum(trade.gross_ret_pct for trade in algo_trades)
        trading_cost = sum(trade.trading_cost_pct for trade in algo_trades)
        funding_return = sum(trade.funding_ret_pct for trade in algo_trades)
        non_eod_return = sum(
            trade.ret_pct for trade in algo_trades if trade.exit_reason != "end_of_data"
        )
        by_algo[algo_id] = {
            "trade_count": len(algo_trades),
            "win_rate": len(wins) / len(algo_trades) if algo_trades else None,
            "total_return_pct": equity_by_algo[algo_id] - 1.0,
            "total_return_ex_end_of_data_pct": non_eod_return if algo_trades else 0.0,
            "gross_return_pct": gross_return,
            "trading_cost_drag_pct": -trading_cost,
            "funding_drag_pct": funding_return,
            "cost_to_gross_ratio": (trading_cost / abs(gross_return)) if gross_return else None,
            "trades_per_day": (len(algo_trades) / data_days) if data_days else None,
            "turnover_per_day": (2.0 * len(algo_trades) / data_days) if data_days else None,
            "avg_trade_ret_pct": (
                sum(trade.ret_pct for trade in algo_trades) / len(algo_trades)
                if algo_trades
                else None
            ),
            "avg_hold_hours": (
                sum(trade.hold_hours for trade in algo_trades) / len(algo_trades)
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

    def record_realized(
        algo_id: str, ret_pct: float, close_time: datetime, weight: float = 1.0
    ) -> None:
        # 변동성 타깃 가중 적용 — live 대시보드/risk_metrics와 동일한 equity 회계.
        weighted_ret = weight * ret_pct
        equity_by_algo[algo_id] *= 1.0 + weighted_ret
        peak_by_algo[algo_id] = max(peak_by_algo[algo_id], equity_by_algo[algo_id])
        drawdown = equity_by_algo[algo_id] / peak_by_algo[algo_id] - 1.0
        max_drawdown_by_algo[algo_id] = min(max_drawdown_by_algo[algo_id], drawdown)
        day_key = close_time.date().isoformat()
        daily_realized_by_date[day_key] = daily_realized_by_date.get(day_key, 0.0) + weighted_ret

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
            # 역발산 계열은 가격 손절 제외 — 시간 손절로 대체(아래 time_stop 블록).
            price_stop_on = algo_id not in parameters.PRICE_STOP_DISABLED_ALGOS
            stop_fill = (
                _stop_fill_price(position, frame.bar) if (position and price_stop_on) else None
            )
            # 시간 손절: 최대 보유시간 초과 시 청산(가격 손절 제거 알고 보완).
            ts_hours = parameters.TIME_STOP_HOURS_BY_ALGO.get(algo_id)
            if (
                position
                and stop_fill is None
                and ts_hours
                and execution_rules.time_stop_triggered(
                    position.open_time, frame.bar.close_time, ts_hours
                )
            ):
                trade = _close_position(
                    position,
                    close_time=frame.bar.close_time,
                    close_data_timestamp=frame.data_timestamp,
                    close_price=frame.bar.close,
                    exit_reason="time_stop",
                    settings=settings,
                    funding_events=funding_events,
                )
                trades.append(trade)
                record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                frame_realized[algo_id] += trade.position_weight * trade.ret_pct
                positions_by_algo[algo_id] = None
                position = None
            if position and stop_fill is not None:
                trade = _close_position(
                    position,
                    close_time=frame.bar.close_time,
                    close_data_timestamp=frame.data_timestamp,
                    close_price=stop_fill,
                    exit_reason=_stop_exit_reason(position),
                    settings=settings,
                    funding_events=funding_events,
                )
                trades.append(trade)
                record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                frame_realized[algo_id] += trade.position_weight * trade.ret_pct
                positions_by_algo[algo_id] = None
                position = None
            # WI-7: omnibus 목표가 익절(인트라바). long: 봉 high가 목표가 도달 시 한계가 체결.
            #   live(1m 틱)와 동일 순수함수. 익절이므로 min_hold 무관(손절과 비대칭).
            if (
                position is not None
                and parameters.OMNIBUS_TARGET_EXIT_ENABLED
                and algo_id == "omnibus"
                and position.omni_target_price is not None
                and execution_rules.target_exit_triggered(
                    direction=position.direction,
                    current_price=frame.bar.high,
                    target_price=position.omni_target_price,
                )
            ):
                trade = _close_position(
                    position,
                    close_time=frame.bar.close_time,
                    close_data_timestamp=frame.data_timestamp,
                    close_price=position.omni_target_price,
                    exit_reason="target_exit",
                    settings=settings,
                    funding_events=funding_events,
                )
                trades.append(trade)
                record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                frame_realized[algo_id] += trade.position_weight * trade.ret_pct
                positions_by_algo[algo_id] = None
                position = None
            # P-A: fng 이익포착 익절(인트라바). 봉 high가 평단×(1+target_pct) 도달 시 그 가격에
            #   체결. 물타기로 평단(open_price)이 내려가면 목표가도 함께 하향. min_hold 무관(익절).
            if (
                position is not None
                and parameters.FNG_TARGET_EXIT_ENABLED
                and algo_id == "fng_contrarian"
                and position.fng_target_pct is not None
            ):
                fng_target = position.open_price * (1.0 + position.fng_target_pct)
                if execution_rules.target_exit_triggered(
                    direction=position.direction,
                    current_price=frame.bar.high,
                    target_price=fng_target,
                ):
                    trade = _close_position(
                        position,
                        close_time=frame.bar.close_time,
                        close_data_timestamp=frame.data_timestamp,
                        close_price=fng_target,
                        exit_reason="target_exit",
                        settings=settings,
                        funding_events=funding_events,
                    )
                    trades.append(trade)
                    record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                    frame_realized[algo_id] += trade.position_weight * trade.ret_pct
                    positions_by_algo[algo_id] = None
                    position = None

            macro = _clean_macro(frame.macro, frame.data_timestamp, settings)
            # 라이브 scheduler와 동일하게 로컬 4h 레짐을 주입(패리티). 미주입 시 백테스트는
            # 오버레이 레짐을, 라이브는 로컬 레짐을 써 regime_trend 게이팅이 달라졌었음.
            macro["arena_regime_state"] = regime.classify_regime_variant(
                frame.indicators,
                {},
                macro,
                variant=settings.regime_variant,
            ).regime_state
            raw_signal = fn(macro, frame.indicators)
            if settings.product_type == "spot":
                product_decision = spot_policy.decide(
                    raw_signal,
                    position.as_live_position() if position else None,
                )
                if product_decision.should_close:
                    # 청산 히스테리시스: flat 청산만 보류 대상(legacy short 청산 등은 즉시).
                    if (
                        position
                        and product_decision.close_reason == "flat_signal"
                        and algorithms.exit_hold_override(algo_id, macro, frame.indicators)
                    ):
                        continue
                    if position and (
                        raw_signal == "short"
                        or execution_rules.min_hold_ok(
                            position.as_live_position(),
                            frame.bar.close_time,
                            algo_id,
                            settings.min_hold_hours,
                            settings.min_hold_fallback_hours,
                        )
                    ):
                        trade = _close_position(
                            position,
                            close_time=frame.bar.close_time,
                            close_data_timestamp=frame.data_timestamp,
                            close_price=frame.bar.close,
                            exit_reason=product_decision.close_reason or product_decision.action,
                            settings=settings,
                            funding_events=funding_events,
                        )
                        trades.append(trade)
                        record_realized(
                            algo_id, trade.ret_pct, trade.close_time, trade.position_weight
                        )
                        frame_realized[algo_id] += trade.position_weight * trade.ret_pct
                        positions_by_algo[algo_id] = None
                    continue
                if not product_decision.should_open:
                    # 역발산 물타기: 보유(hold) 중 가격 하락 시 추가 트랜치 체결(봉 저가 평가).
                    if (
                        position is not None
                        and product_decision.action == "hold"
                        and algo_id == "fng_contrarian"
                        and parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED
                    ):
                        positions_by_algo[algo_id] = _maybe_scale_in_fng_sim(
                            position, frame.bar.low
                        )
                    continue
                signal = product_decision.executable_signal
            else:
                signal = raw_signal

            if signal is None:
                if position and algorithms.exit_hold_override(algo_id, macro, frame.indicators):
                    continue
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
                    record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                    frame_realized[algo_id] += trade.position_weight * trade.ret_pct
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
                record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
                frame_realized[algo_id] += trade.position_weight * trade.ret_pct

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

            live_gate_block_reason = _live_gate_block_reason(frame, settings)
            if live_gate_block_reason:
                risk_events.append(
                    BacktestRiskEvent(
                        algo_id=algo_id,
                        data_timestamp=frame.data_timestamp,
                        signal=signal,
                        event_type=live_gate_block_reason,
                        risk_decision={"allowed": False, "reason": live_gate_block_reason},
                        risk_snapshot={
                            "source": "live_gate_replay",
                            "market_features": frame.market_features,
                        },
                    )
                )
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
            # 봉 종가 기준 트레일링 래칫 — 스톱 트리거 체크(프레임 상단) 이후라 look-ahead 없음.
            if open_position is not None:
                _ratchet_sim_position(open_position, frame.bar)
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
            record_realized(algo_id, trade.ret_pct, trade.close_time, trade.position_weight)
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
            frames=sorted_frames,
        ),
        params_snapshot=_base_params_snapshot_from_settings(settings),
    )


def _row_ts(value: Any) -> datetime:
    return execution_rules.parse_utc_datetime(value)


def _macro_signal_from_snapshot(row: dict[str, Any], decision_time: datetime) -> dict[str, Any]:
    risk_overlay = row.get("risk_overlay") or {}
    raw = risk_overlay.get("regimeRaw") or {}
    # 라이브 scheduler._fetch_macro와 동일한 regimeRaw 매핑 — 백테스트가 동일 게이트
    # (MA200·낙폭·LSR·taker·breadth·stablecoin·funding·OI·ETF)를 평가하도록 한다.
    # 이전엔 fng/vix만 추출해 모든 macro 게이트가 None→스킵되어 라이브와 다른 전략을 검증했음.
    macro = {
        "regime_state": risk_overlay.get("regimeState", ""),
        "fng": raw.get("fng"),
        "vix_now": raw.get("vix_now"),
        "vix_q40": raw.get("vix_q40"),
        # 선물/파생 — 현물 진입 과열 회피 필터
        "funding_zscore": raw.get("funding_zscore"),
        "oi_divergence_flag": raw.get("oi_divergence_flag"),
        "etf_flow_zscore": raw.get("etf_flow_zscore"),
        # 구조적 강세 게이트 + 군중 과밀 + 주문흐름 확인 + 낙폭 컨텍스트
        "btc_above_ma200": raw.get("btc_above_ma200"),
        "long_short_ratio_zscore": raw.get("long_short_ratio_zscore"),
        "taker_imbalance_zscore": raw.get("taker_imbalance_zscore"),
        "btc_drawdown_90d": raw.get("btc_drawdown_90d"),
        # 시장 폭 + 온체인 유동성 (복합 투표 알고 건전성 필터)
        "breadth_up_ratio": raw.get("breadth_up_ratio"),
        "stablecoin_supply_zscore": raw.get("stablecoin_supply_zscore"),
        # 변동성 환경 라벨 (사이징/신뢰도 컨텍스트)
        "vol_level": risk_overlay.get("volLevel"),
        "vol_trend": risk_overlay.get("volTrend"),
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


def _interval_hours(interval: str) -> float:
    """'4h' → 4, '1h' → 1, '1d' → 24."""
    return frequency.interval_to_hours(interval)


async def load_frames_from_supabase(
    db: Any,
    *,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    limit: int = 1000,
    warmup_bars: int = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD,
    indicator_profile_id: str = frequency.DEFAULT_INDICATOR_PROFILE_ID,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    macro_rows: list[dict[str, Any]] | None = None,
) -> list[ReplayFrame]:
    """Load replay frames from Supabase.

    When from_date / to_date are given, bars outside the window are fetched only
    for indicator warm-up and are not included in the returned frames.
    limit is ignored when a date range is specified.
    """
    from datetime import timedelta

    async def fetch_bar_rows(*, desc: bool, row_limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_size = 1000
        for start in range(0, row_limit, page_size):
            end = min(start + page_size, row_limit) - 1
            builder = (
                db.table("arena_ohlcv_bars")
                .select("open_time,close_time,open,high,low,close,volume")
                .eq("symbol", symbol)
                .eq("interval", interval)
            )
            if from_date is not None:
                pre_start = from_date - timedelta(
                    hours=_interval_hours(interval) * (warmup_bars + 5)
                )
                builder = builder.gte("open_time", _ts(pre_start))
            if to_date is not None:
                builder = builder.lte("close_time", _ts(to_date))
            res = await builder.order("open_time", desc=desc).range(start, end).execute()
            page = res.data or []
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows

    if from_date is not None or to_date is not None:
        bar_rows = await fetch_bar_rows(desc=False, row_limit=max(limit, 20_000))
    else:
        bar_rows = await fetch_bar_rows(desc=True, row_limit=limit)
    bar_rows = sorted(bar_rows, key=lambda row: row["open_time"])

    macro_filter: dict[str, Any] = {}
    if from_date is not None:
        macro_filter["gte"] = (
            "fetched_at",
            _ts(from_date - timedelta(hours=_interval_hours(interval) * (warmup_bars + 5))),
        )
    # macro_rows 주입 시 DB 조회를 건너뛴다 — 히스토리 백필(sentiment_join parquet에서
    # 재구성한 일간 regimeRaw)로 백테스트를 돌릴 때 사용. 각 행은 fetched_at·risk_overlay
    # 키를 가져야 하며 fetched_at 오름차순 정렬 전제.
    if macro_rows is None:
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
    volumes: list[float] = []  # WI-4: 돌파 확인용 봉 거래량 누적
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
        volumes.append(bar.volume)
        if len(closes) < warmup_bars:
            continue
        macro, macro_index = _latest_macro_for_time(macro_rows, bar.close_time, macro_index)
        frame = ReplayFrame(
            bar=bar,
            indicators=indicators.compute(
                highs,
                lows,
                closes,
                volumes=volumes,
                interval=interval,
                indicator_profile_id=indicator_profile_id,
            ),
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
        "frequency_profile_id": settings.frequency_profile_id,
        "indicator_profile_id": settings.indicator_profile_id,
        "cost_model_version": settings.cost_model_version,
        "cost_scenario_id": settings.cost_scenario_id,
        "params_snapshot": result.params_snapshot,
        "rules_snapshot": {
            "fee_bps": settings.fee_bps,
            "slippage_bps": settings.slippage_bps,
            "spread_bps_round_trip": settings.spread_bps_round_trip,
            "funding_buffer_bps_per_8h": settings.funding_buffer_bps_per_8h,
            "ecr_threshold": settings.ecr_threshold,
            "max_trades_per_day_per_algo": settings.max_trades_per_day_per_algo,
            "atr_multiple": settings.atr_multiple,
            "stop_loss_min_pct": settings.stop_loss_min_pct,
            "stop_loss_max_pct": settings.stop_loss_max_pct,
            "macro_stale_hours": settings.macro_stale_hours,
            "min_hold_hours": settings.min_hold_hours,
            "portfolio_risk": risk.policy_snapshot(_risk_policy(settings)),
            "regime_variant": settings.regime_variant,
            "live_gate_replay": {
                "replay_execution_gate_blocks": settings.replay_execution_gate_blocks,
                "replay_realtime_risk_blocks": settings.replay_realtime_risk_blocks,
            },
            "execution_product": {
                "target_product": settings.product_type,
                "position_semantics": settings.position_semantics,
                "short_signal_action": parameters.SHORT_SIGNAL_ACTION,
                "allow_live_short": settings.product_type != "spot",
                "spot_execution_only": settings.product_type == "spot",
                "derivatives_data_usage": "research_features_only",
            },
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

    profile = frequency.get_frequency_profile(args.profile)
    indicator_profile_id = args.indicator_profile or profile.default_indicator_profile_id
    cost_scenario = frequency.get_cost_scenario(args.profile, args.cost_scenario)
    interval = args.interval or profile.interval
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else cost_scenario.slippage_bps
    )
    warmup_bars = max(
        parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD,
        frequency.indicator_settings(
            interval=interval,
            indicator_profile_id=indicator_profile_id,
        ).macd_slow_period
        + frequency.indicator_settings(
            interval=interval,
            indicator_profile_id=indicator_profile_id,
        ).macd_signal_period,
    )
    frames = await load_frames_from_supabase(
        db,
        symbol=args.symbol,
        interval=interval,
        limit=args.limit,
        warmup_bars=warmup_bars,
        indicator_profile_id=indicator_profile_id,
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
        frequency_profile_id=profile.frequency_profile_id,
        indicator_profile_id=indicator_profile_id,
        cost_model_version=cost_scenario.cost_model_version,
        cost_scenario_id=cost_scenario.cost_scenario_id,
        regime_variant=args.regime_variant,
        replay_execution_gate_blocks=args.replay_execution_gate_blocks,
        replay_realtime_risk_blocks=args.replay_realtime_risk_blocks,
        product_type=args.product,
        position_semantics=(
            parameters.POSITION_SEMANTICS if args.product == "spot" else "perp_long_short_sim"
        ),
        symbol=args.symbol,
        interval=interval,
        fee_bps=cost_scenario.fee_bps,
        slippage_bps=slippage_bps,
        spread_bps_round_trip=cost_scenario.spread_bps_round_trip,
        funding_buffer_bps_per_8h=cost_scenario.funding_buffer_bps_per_8h,
        ecr_threshold=profile.ecr_threshold,
        max_trades_per_day_per_algo=profile.max_trades_per_day_per_algo,
        min_hold_hours=dict(profile.min_hold_hours),
        min_hold_fallback_hours=profile.min_hold_fallback_hours,
        close_open_at_end=not args.keep_open_at_end,
        warmup_bars=warmup_bars,
    )
    result = run_replay(frames, settings=settings, funding_events=funding_events)
    if args.save:
        await save_result_to_supabase(db, result)
    print(json.dumps(_run_row(result), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run arena rule-parity backtest.")
    parser.add_argument("--symbol", default=parameters.BINANCE_SYMBOL)
    parser.add_argument("--profile", default=frequency.LIVE_4H_PROFILE_ID)
    parser.add_argument("--indicator-profile", default=None)
    parser.add_argument("--cost-scenario", default=frequency.DEFAULT_COST_SCENARIO_ID)
    parser.add_argument(
        "--product",
        choices=["spot", "usdm_perp_paper"],
        default=parameters.TARGET_PRODUCT,
        help="Replay semantics. spot maps short signals to exit/no-trade.",
    )
    parser.add_argument("--interval", default=None, help="Override interval from --profile")
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
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument(
        "--regime-variant",
        choices=[regime.REGIME_VARIANT_STRICT, regime.REGIME_VARIANT_RELAXED_2OF3],
        default=regime.REGIME_VARIANT_STRICT,
        help="Research-only local regime classifier variant.",
    )
    parser.add_argument("--replay-execution-gate-blocks", action="store_true")
    parser.add_argument("--replay-realtime-risk-blocks", action="store_true")
    parser.add_argument("--keep-open-at-end", action="store_true")
    parser.add_argument("--save", action="store_true")
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
