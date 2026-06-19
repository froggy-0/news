"""Arena trading parameter registry.

This module intentionally has no environment-variable reads. Runtime secrets and
deployment-specific overrides stay in config.py; pure trading defaults live here
so EC2 code has one local source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STRATEGY_VERSION = "arena-ec2-v5"
PARAMS_VERSION = "arena-params-v6"
FEATURE_SET_VERSION = "arena-features-v3"
RISK_MODEL_VERSION = "portfolio-risk-v1"
RUNTIME = "ec2"

BINANCE_SYMBOL = "BTCUSDT"
BINANCE_KLINE_INTERVAL = "4h"
BINANCE_KLINES_LIMIT = 150

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

MIN_HOLD_HOURS: dict[str, float] = {
    "regime_v2": 24.0,
    "fng_contrarian": 24.0,
    "vix_rsi": 8.0,
    "macd_momentum": 8.0,  # 4H 단일바 노이즈 제거 (12h↑는 역효과 확인됨)
    "multi_factor": 8.0,
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
            "vix_rsi_long_max": VIX_RSI_LONG_MAX,
            "macd_atr_threshold_multiple": MACD_ATR_THRESHOLD_MULTIPLE,
            "multi_factor_long_rsi_max": MULTI_FACTOR_LONG_RSI_MAX,
            "multi_factor_short_rsi_min": MULTI_FACTOR_SHORT_RSI_MIN,
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
    }
