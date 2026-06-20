"""Frequency, indicator, and cost profiles for Arena research."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import parameters

LIVE_4H_PROFILE_ID = "live_4h"
DEFAULT_INDICATOR_PROFILE_ID = "time_normalized_v1"
INTRADAY_INDICATOR_PROFILE_ID = "intraday_native_v1"
COST_MODEL_VERSION = "arena-cost-v2"
DEFAULT_COST_SCENARIO_ID = "base"


@dataclass(frozen=True)
class IndicatorSettings:
    indicator_profile_id: str
    interval: str
    rsi_period: int
    rsi_recent_multiple: int
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    bollinger_period: int
    bollinger_stddev: float
    atr_period: int
    atr_fallback_pct: float
    trend_ema_fast_period: int
    trend_ema_slow_period: int
    return_24h_bars: int
    return_72h_bars: int
    realized_vol_24h_bars: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "indicator_profile_id": self.indicator_profile_id,
            "interval": self.interval,
            "rsi_period": self.rsi_period,
            "rsi_recent_multiple": self.rsi_recent_multiple,
            "macd_fast_period": self.macd_fast_period,
            "macd_slow_period": self.macd_slow_period,
            "macd_signal_period": self.macd_signal_period,
            "bollinger_period": self.bollinger_period,
            "bollinger_stddev": self.bollinger_stddev,
            "atr_period": self.atr_period,
            "atr_fallback_pct": self.atr_fallback_pct,
            "trend_ema_fast_period": self.trend_ema_fast_period,
            "trend_ema_slow_period": self.trend_ema_slow_period,
            "return_24h_bars": self.return_24h_bars,
            "return_72h_bars": self.return_72h_bars,
            "realized_vol_24h_bars": self.realized_vol_24h_bars,
        }


@dataclass(frozen=True)
class FrequencyProfile:
    frequency_profile_id: str
    symbol: str
    interval: str
    decision_cadence_minutes: int
    live_enabled: bool
    shadow_candidate: bool
    train_days: int
    test_days: int
    embargo_hours: int
    ecr_threshold: float
    max_trades_per_day_per_algo: float
    min_hold_hours: dict[str, float]
    min_hold_fallback_hours: float
    default_indicator_profile_id: str = DEFAULT_INDICATOR_PROFILE_ID
    default_cost_scenario_id: str = DEFAULT_COST_SCENARIO_ID

    def as_dict(self) -> dict[str, Any]:
        return {
            "frequency_profile_id": self.frequency_profile_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "live_enabled": self.live_enabled,
            "shadow_candidate": self.shadow_candidate,
            "train_days": self.train_days,
            "test_days": self.test_days,
            "embargo_hours": self.embargo_hours,
            "ecr_threshold": self.ecr_threshold,
            "max_trades_per_day_per_algo": self.max_trades_per_day_per_algo,
            "min_hold_hours": dict(self.min_hold_hours),
            "min_hold_fallback_hours": self.min_hold_fallback_hours,
            "default_indicator_profile_id": self.default_indicator_profile_id,
            "default_cost_scenario_id": self.default_cost_scenario_id,
        }


@dataclass(frozen=True)
class CostScenario:
    cost_scenario_id: str
    frequency_profile_id: str
    cost_model_version: str
    fee_bps: float
    slippage_bps: float
    spread_bps_round_trip: float
    funding_buffer_bps_per_8h: float

    @property
    def trading_cost_bps_round_trip(self) -> float:
        return 2.0 * (self.fee_bps + self.slippage_bps) + self.spread_bps_round_trip

    @property
    def all_in_round_trip_bps(self) -> float:
        return self.trading_cost_bps_round_trip + self.funding_buffer_bps_per_8h

    @property
    def all_in_round_trip_cost_pct(self) -> float:
        return self.all_in_round_trip_bps / 10_000.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cost_scenario_id": self.cost_scenario_id,
            "frequency_profile_id": self.frequency_profile_id,
            "cost_model_version": self.cost_model_version,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "spread_bps_round_trip": self.spread_bps_round_trip,
            "funding_buffer_bps_per_8h": self.funding_buffer_bps_per_8h,
            "trading_cost_bps_round_trip": self.trading_cost_bps_round_trip,
            "all_in_round_trip_bps": self.all_in_round_trip_bps,
            "all_in_round_trip_cost_pct": self.all_in_round_trip_cost_pct,
        }


def interval_to_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    if interval.endswith("d"):
        return int(interval[:-1]) * 24 * 60
    raise ValueError(f"unsupported interval: {interval!r}")


def interval_to_hours(interval: str) -> float:
    return interval_to_minutes(interval) / 60.0


def bars_for_hours(hours: float, interval: str) -> int:
    if hours <= 0:
        return 0
    return max(1, int(math.ceil(hours * 60.0 / interval_to_minutes(interval))))


def bars_for_days(days: float, interval: str) -> int:
    return bars_for_hours(days * 24.0, interval)


def _scaled_period(period: int, interval: str) -> int:
    base_minutes = interval_to_minutes(parameters.BINANCE_KLINE_INTERVAL)
    current_minutes = interval_to_minutes(interval)
    return max(1, int(round(period * base_minutes / current_minutes)))


FREQUENCY_PROFILES: dict[str, FrequencyProfile] = {
    LIVE_4H_PROFILE_ID: FrequencyProfile(
        frequency_profile_id=LIVE_4H_PROFILE_ID,
        symbol=parameters.BINANCE_SYMBOL,
        interval="4h",
        decision_cadence_minutes=240,
        live_enabled=True,
        shadow_candidate=True,
        train_days=84,
        test_days=20,
        embargo_hours=24,
        ecr_threshold=1.3,
        max_trades_per_day_per_algo=3.0,
        min_hold_hours=dict(parameters.MIN_HOLD_HOURS),
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
    "research_1h": FrequencyProfile(
        frequency_profile_id="research_1h",
        symbol=parameters.BINANCE_SYMBOL,
        interval="1h",
        decision_cadence_minutes=60,
        live_enabled=False,
        shadow_candidate=True,
        train_days=90,
        test_days=21,
        embargo_hours=24,
        ecr_threshold=1.5,
        max_trades_per_day_per_algo=6.0,
        min_hold_hours={**parameters.MIN_HOLD_HOURS, "trend_core_v1": 12.0},
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
    "research_15m": FrequencyProfile(
        frequency_profile_id="research_15m",
        symbol=parameters.BINANCE_SYMBOL,
        interval="15m",
        decision_cadence_minutes=15,
        live_enabled=False,
        shadow_candidate=False,
        train_days=60,
        test_days=14,
        embargo_hours=12,
        ecr_threshold=1.7,
        max_trades_per_day_per_algo=12.0,
        min_hold_hours={**parameters.MIN_HOLD_HOURS, "trend_core_v1": 12.0},
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
}


_COST_SCENARIOS: dict[tuple[str, str], CostScenario] = {}


def _add_costs(profile_id: str, rows: list[tuple[str, float, float, float, float]]) -> None:
    for scenario_id, fee_bps, slippage_bps, spread_bps, funding_bps in rows:
        _COST_SCENARIOS[(profile_id, scenario_id)] = CostScenario(
            cost_scenario_id=scenario_id,
            frequency_profile_id=profile_id,
            cost_model_version=COST_MODEL_VERSION,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            spread_bps_round_trip=spread_bps,
            funding_buffer_bps_per_8h=funding_bps,
        )


_add_costs(
    LIVE_4H_PROFILE_ID,
    [
        # 현물 BTCUSDT 비용 현실화 (arena-cost-v2):
        # base = fee 5bps/leg + slippage 1bps/leg + spread 1bps 왕복 = 왕복 ~13bps.
        # 현물이므로 funding=0. low/high는 비용 민감도 하한/상한.
        ("low", parameters.FEE_BPS, 0.0, 0.0, 0.0),
        ("base", parameters.FEE_BPS, 1.0, 1.0, 0.0),
        ("high", parameters.FEE_BPS, 2.0, 3.0, 0.0),
    ],
)
_add_costs(
    "research_1h",
    [
        ("low", parameters.FEE_BPS, 1.0, 2.0, 0.25),
        ("base", parameters.FEE_BPS, 2.0, 3.0, 0.5),
        ("high", parameters.FEE_BPS, 4.0, 6.0, 1.0),
    ],
)
_add_costs(
    "research_15m",
    [
        ("low", parameters.FEE_BPS, 2.0, 3.0, 0.5),
        ("base", parameters.FEE_BPS, 4.0, 5.0, 1.0),
        ("high", parameters.FEE_BPS, 8.0, 10.0, 2.0),
    ],
)


def get_frequency_profile(profile_id: str = LIVE_4H_PROFILE_ID) -> FrequencyProfile:
    try:
        return FREQUENCY_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown frequency profile: {profile_id!r}") from exc


def get_cost_scenario(
    profile_id: str = LIVE_4H_PROFILE_ID,
    cost_scenario_id: str = DEFAULT_COST_SCENARIO_ID,
) -> CostScenario:
    try:
        return _COST_SCENARIOS[(profile_id, cost_scenario_id)]
    except KeyError as exc:
        raise ValueError(
            f"unknown cost scenario {cost_scenario_id!r} for profile {profile_id!r}"
        ) from exc


def all_cost_scenarios() -> list[CostScenario]:
    return list(_COST_SCENARIOS.values())


def indicator_settings(
    *,
    interval: str,
    indicator_profile_id: str = DEFAULT_INDICATOR_PROFILE_ID,
) -> IndicatorSettings:
    if indicator_profile_id == DEFAULT_INDICATOR_PROFILE_ID:

        def scale(period: int) -> int:
            return _scaled_period(period, interval)
    elif indicator_profile_id == INTRADAY_INDICATOR_PROFILE_ID:

        def scale(period: int) -> int:
            return period
    else:
        raise ValueError(f"unknown indicator profile: {indicator_profile_id!r}")

    return IndicatorSettings(
        indicator_profile_id=indicator_profile_id,
        interval=interval,
        rsi_period=scale(parameters.RSI_PERIOD),
        rsi_recent_multiple=parameters.RSI_RECENT_MULTIPLE,
        macd_fast_period=scale(parameters.MACD_FAST_PERIOD),
        macd_slow_period=scale(parameters.MACD_SLOW_PERIOD),
        macd_signal_period=scale(parameters.MACD_SIGNAL_PERIOD),
        bollinger_period=scale(parameters.BOLLINGER_PERIOD),
        bollinger_stddev=parameters.BOLLINGER_STDDEV,
        atr_period=scale(parameters.ATR_PERIOD),
        atr_fallback_pct=parameters.ATR_FALLBACK_PCT,
        trend_ema_fast_period=scale(parameters.TREND_EMA_FAST_PERIOD),
        trend_ema_slow_period=scale(parameters.TREND_EMA_SLOW_PERIOD),
        return_24h_bars=bars_for_hours(24.0, interval),
        return_72h_bars=bars_for_hours(72.0, interval),
        realized_vol_24h_bars=bars_for_hours(24.0, interval),
    )


def walk_forward_bar_counts(profile: FrequencyProfile) -> dict[str, int]:
    return {
        "train_bars": bars_for_days(profile.train_days, profile.interval),
        "test_bars": bars_for_days(profile.test_days, profile.interval),
        "step_bars": bars_for_days(profile.test_days, profile.interval),
        "embargo_bars": bars_for_hours(profile.embargo_hours, profile.interval),
    }


def profile_snapshot(
    profile: FrequencyProfile,
    *,
    indicator_profile_id: str | None = None,
    cost_scenario_id: str | None = None,
) -> dict[str, Any]:
    indicator_id = indicator_profile_id or profile.default_indicator_profile_id
    cost_id = cost_scenario_id or profile.default_cost_scenario_id
    cost = get_cost_scenario(profile.frequency_profile_id, cost_id)
    return {
        "frequency_profile": profile.as_dict(),
        "indicator_profile": indicator_settings(
            interval=profile.interval,
            indicator_profile_id=indicator_id,
        ).as_dict(),
        "cost_scenario": cost.as_dict(),
    }
