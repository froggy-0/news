"""Arena trading parameter registry.

This module intentionally has no environment-variable reads. Runtime secrets and
deployment-specific overrides stay in config.py; pure trading defaults live here
so EC2 code has one local source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STRATEGY_VERSION = "arena-ec2-v7"
PARAMS_VERSION = "arena-params-v9"
FEATURE_SET_VERSION = "arena-features-v5"
RISK_MODEL_VERSION = "portfolio-risk-v1"
RUNTIME = "ec2"

BINANCE_SYMBOL = "BTCUSDT"
BINANCE_KLINE_INTERVAL = "4h"
BINANCE_KLINES_LIMIT = 300
ARENA_SHADOW_VNEXT_ENABLED = True
ARENA_FREQUENCY_SHADOW_ENABLED = False
ARENA_FREQUENCY_SHADOW_PROFILES = ("research_1h",)

HTTP_TIMEOUT_SECONDS = 30
WEBSOCKET_PING_INTERVAL_SECONDS = 20
WEBSOCKET_RECONNECT_DELAY_SECONDS = 5
SCHEDULER_CRON_HOUR = "*/4"
SCHEDULER_CRON_MINUTE = 5
SERVER_IDLE_SLEEP_SECONDS = 3600

STOP_LOSS_FALLBACK_PCT = 0.05
FEE_BPS = 5.0
ATR_MULTIPLE = 2.5
STOP_LOSS_MIN_PCT = 0.02
STOP_LOSS_MAX_PCT = 0.08
MACRO_STALE_HOURS = 36.0

POSITION_UNIT = 1.0
MAX_OPEN_POSITIONS_TOTAL = 3
MAX_LONG_POSITIONS = 2
MAX_SHORT_POSITIONS = 2
MAX_NET_LONG_EXPOSURE = 2.0
MAX_NET_SHORT_EXPOSURE = 2.0
DAILY_LOSS_LIMIT_PCT = 0.05
ALGO_MAX_DRAWDOWN_KILL_PCT = 0.10
COOLDOWN_AFTER_KILL_HOURS = 24.0

# Supertrend (ATR-based dynamic band trend signal)
SUPERTREND_ATR_PERIOD = 10
SUPERTREND_MULT = 3.0

# Multi-period EMA (ema_cross algo)
EMA_21_PERIOD = 21
EMA_55_PERIOD = 55
EMA_200_PERIOD = 200

# BB Squeeze mean-reversion thresholds
BB_SQUEEZE_WIDTH_MAX_PCT = 3.5
BB_SQUEEZE_BB_POS_LONG_MIN = 0.60
BB_SQUEEZE_BB_POS_SHORT_MAX = 0.40
BB_SQUEEZE_RSI_THRESHOLD = 50.0

RSI_PERIOD = 14
RSI_NEUTRAL = 50.0
RSI_RECENT_MULTIPLE = 3
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
MACD_NEUTRAL = 0.0
BOLLINGER_PERIOD = 20
BOLLINGER_STDDEV = 2.0
BOLLINGER_NEUTRAL = 0.5
ATR_PERIOD = 14
ATR_FALLBACK_PCT = 0.01

REGIME_LONG_STATE = "BullQuiet"
REGIME_SHORT_STATE = "BearPanic"
FNG_LONG_BELOW = 30.0
FNG_SHORT_ABOVE = 70.0
VIX_RSI_LONG_MAX = 50.0
MACD_ATR_THRESHOLD_MULTIPLE = 0.10
MACD_MOMENTUM_RSI_LONG_MAX = 65.0  # 과매수 구간 롱 진입 차단
MACD_MOMENTUM_RSI_SHORT_MIN = 35.0  # 과매도 구간 숏 진입 차단
MACD_MOMENTUM_BB_WIDTH_MIN = 3.5  # BB 폭 최소값 (% of SMA): 미달 시 횡보장으로 판단, 진입 차단
MULTI_FACTOR_LONG_RSI_MAX = 50.0
MULTI_FACTOR_SHORT_RSI_MIN = 55.0

TREND_EMA_FAST_PERIOD = 12
TREND_EMA_SLOW_PERIOD = 26
TREND_RETURN_24H_BARS = 6
TREND_RETURN_72H_BARS = 18
TREND_REALIZED_VOL_24H_BARS = 6
TREND_CORE_RSI_LONG_MAX = 70.0
TREND_CORE_RSI_SHORT_MIN = 30.0
TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE = 0.10
REGIME_STRESS_RETURN_ATR_MULTIPLE = 3.0
REGIME_STRESS_RANGE_ATR_MULTIPLE = 5.0
REGIME_TREND_BB_WIDTH_MIN = 3.5
REGIME_SIDEWAYS_BB_WIDTH_MAX = 3.5
REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE = 1.0

ALLOCATOR_BUDGET_TREND_CORE = 0.60
ALLOCATOR_BUDGET_LEGACY_RULE = 0.40
ALLOCATOR_BUDGET_CARRY = 0.00

MIN_HOLD_HOURS: dict[str, float] = {
    "supertrend": 12.0,
    "fng_contrarian": 24.0,
    "ema_cross": 12.0,
    "macd_momentum": 8.0,  # 4H 단일바 노이즈 제거 (12h↑는 역효과 확인됨)
    "bb_squeeze": 8.0,
    "trend_core_v1": 12.0,
}
MIN_HOLD_FALLBACK_HOURS = 4.0

# Walk-forward split configuration
WF_VERSION = "wf-v1"
WF_TRAIN_BARS = 500  # expanding anchor window (~83 days of 4H)
WF_TEST_BARS = 120  # test window per split (~20 days of 4H)
WF_STEP_BARS = 120  # advance per split (non-overlapping test windows)
WF_EMBARGO_BARS = 6  # gap between train end and test start (24 h of 4H)
WF_MIN_TOTAL_BARS = WF_TRAIN_BARS + WF_EMBARGO_BARS + WF_TEST_BARS


def base_params_snapshot() -> dict[str, Any]:
    """Return JSON-serializable default parameters for trade reproducibility."""
    return {
        "params_version": PARAMS_VERSION,
        "runtime": RUNTIME,
        "feature_set_version": FEATURE_SET_VERSION,
        "risk_model_version": RISK_MODEL_VERSION,
        "market_data": {
            "symbol": BINANCE_SYMBOL,
            "kline_interval": BINANCE_KLINE_INTERVAL,
            "klines_limit": BINANCE_KLINES_LIMIT,
            "shadow_vnext_enabled": ARENA_SHADOW_VNEXT_ENABLED,
            "frequency_shadow_enabled": ARENA_FREQUENCY_SHADOW_ENABLED,
            "frequency_shadow_profiles": list(ARENA_FREQUENCY_SHADOW_PROFILES),
        },
        "schedule": {
            "cron_hour": SCHEDULER_CRON_HOUR,
            "cron_minute": SCHEDULER_CRON_MINUTE,
            "min_hold_hours": deepcopy(MIN_HOLD_HOURS),
            "min_hold_fallback_hours": MIN_HOLD_FALLBACK_HOURS,
        },
        "indicators": {
            "rsi_period": RSI_PERIOD,
            "rsi_neutral": RSI_NEUTRAL,
            "rsi_recent_multiple": RSI_RECENT_MULTIPLE,
            "macd_fast_period": MACD_FAST_PERIOD,
            "macd_slow_period": MACD_SLOW_PERIOD,
            "macd_signal_period": MACD_SIGNAL_PERIOD,
            "macd_neutral": MACD_NEUTRAL,
            "bollinger_period": BOLLINGER_PERIOD,
            "bollinger_stddev": BOLLINGER_STDDEV,
            "bollinger_neutral": BOLLINGER_NEUTRAL,
            "atr_period": ATR_PERIOD,
            "atr_fallback_pct": ATR_FALLBACK_PCT,
        },
        "strategy_thresholds": {
            "regime_long_state": REGIME_LONG_STATE,
            "regime_short_state": REGIME_SHORT_STATE,
            "fng_long_below": FNG_LONG_BELOW,
            "fng_short_above": FNG_SHORT_ABOVE,
            "supertrend_atr_period": SUPERTREND_ATR_PERIOD,
            "supertrend_mult": SUPERTREND_MULT,
            "ema_21_period": EMA_21_PERIOD,
            "ema_55_period": EMA_55_PERIOD,
            "ema_200_period": EMA_200_PERIOD,
            "bb_squeeze_width_max_pct": BB_SQUEEZE_WIDTH_MAX_PCT,
            "bb_squeeze_bb_pos_long_min": BB_SQUEEZE_BB_POS_LONG_MIN,
            "bb_squeeze_bb_pos_short_max": BB_SQUEEZE_BB_POS_SHORT_MAX,
            "bb_squeeze_rsi_threshold": BB_SQUEEZE_RSI_THRESHOLD,
            "macd_atr_threshold_multiple": MACD_ATR_THRESHOLD_MULTIPLE,
            "trend_core_rsi_long_max": TREND_CORE_RSI_LONG_MAX,
            "trend_core_rsi_short_min": TREND_CORE_RSI_SHORT_MIN,
            "trend_core_macd_atr_threshold_multiple": TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE,
            "regime_stress_return_atr_multiple": REGIME_STRESS_RETURN_ATR_MULTIPLE,
            "regime_stress_range_atr_multiple": REGIME_STRESS_RANGE_ATR_MULTIPLE,
            "regime_trend_bb_width_min": REGIME_TREND_BB_WIDTH_MIN,
            "regime_sideways_bb_width_max": REGIME_SIDEWAYS_BB_WIDTH_MAX,
            "regime_sideways_return_atr_multiple": REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE,
        },
        "risk_defaults": {
            "stop_loss_fallback_pct": STOP_LOSS_FALLBACK_PCT,
            "fee_bps": FEE_BPS,
            "atr_multiple": ATR_MULTIPLE,
            "stop_loss_min_pct": STOP_LOSS_MIN_PCT,
            "stop_loss_max_pct": STOP_LOSS_MAX_PCT,
            "macro_stale_hours": MACRO_STALE_HOURS,
            "position_unit": POSITION_UNIT,
            "max_open_positions_total": MAX_OPEN_POSITIONS_TOTAL,
            "max_long_positions": MAX_LONG_POSITIONS,
            "max_short_positions": MAX_SHORT_POSITIONS,
            "max_net_long_exposure": MAX_NET_LONG_EXPOSURE,
            "max_net_short_exposure": MAX_NET_SHORT_EXPOSURE,
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
            "algo_max_drawdown_kill_pct": ALGO_MAX_DRAWDOWN_KILL_PCT,
            "cooldown_after_kill_hours": COOLDOWN_AFTER_KILL_HOURS,
        },
        "allocator": {
            "trend_core_budget": ALLOCATOR_BUDGET_TREND_CORE,
            "legacy_rule_budget": ALLOCATOR_BUDGET_LEGACY_RULE,
            "carry_budget": ALLOCATOR_BUDGET_CARRY,
        },
    }
