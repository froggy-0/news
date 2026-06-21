"""Arena trading parameter registry.

This module intentionally has no environment-variable reads. Runtime secrets and
deployment-specific overrides stay in config.py; pure trading defaults live here
so EC2 code has one local source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STRATEGY_VERSION = "arena-spot-v3"
PARAMS_VERSION = "arena-params-v14"
FEATURE_SET_VERSION = "arena-features-v5"
RISK_MODEL_VERSION = "portfolio-risk-v1"
REALTIME_RISK_MODEL_VERSION = "realtime-risk-v1"
RUNTIME = "ec2"

BINANCE_SYMBOL = "BTCUSDT"
BINANCE_KLINE_INTERVAL = "4h"
BINANCE_KLINES_LIMIT = 300
ARENA_SHADOW_VNEXT_ENABLED = True
ARENA_FREQUENCY_SHADOW_ENABLED = False
ARENA_FREQUENCY_SHADOW_PROFILES = ("research_1h",)
ARENA_REALTIME_COLLECTOR_ENABLED = True
ARENA_REALTIME_RISK_ENABLED = True
ARENA_REALTIME_RISK_LIVE_ENABLED = False
ARENA_EXECUTION_GATE_SHADOW_ENABLED = True
ARENA_EXECUTION_GATE_LIVE_ENABLED = False
TARGET_PRODUCT = "spot"
POSITION_SEMANTICS = "spot_long_flat"
SHORT_SIGNAL_ACTION = "exit_or_no_trade"
ALLOW_LIVE_SHORT = False
RESEARCH_PERP_SHADOW_ENABLED = True

HTTP_TIMEOUT_SECONDS = 30
WEBSOCKET_PING_INTERVAL_SECONDS = 20
WEBSOCKET_RECONNECT_DELAY_SECONDS = 5
REALTIME_FEATURE_WINDOW_SECONDS = 60
REALTIME_RISK_HISTORY_WINDOWS = 60
REALTIME_RISK_FRESHNESS_SECONDS = 180
SCHEDULER_CRON_HOUR = "*/4"
SCHEDULER_CRON_MINUTE = 5
SERVER_IDLE_SLEEP_SECONDS = 3600

STOP_LOSS_FALLBACK_PCT = 0.05
FEE_BPS = 5.0
ATR_MULTIPLE = 2.5
STOP_LOSS_MIN_PCT = 0.02
STOP_LOSS_MAX_PCT = 0.08
MACRO_STALE_HOURS = 48.0  # 일간 매크로(FNG/VIX/ETF) — 브리프 1일 지연 허용

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

# Donchian 채널 브레이크아웃 (추세추종 코어 진입 트리거)
DONCHIAN_PERIOD = 20  # 직전 20봉(4h 기준 ~3.3일) 고점 돌파 = 롱 트리거

# ADX 추세강도 (whipsaw 차단 게이트)
ADX_PERIOD = 14
ADX_TREND_MIN = 20.0  # ADX < 20 = 추세 약함, 추세추종 진입 차단

# 변동성 타깃 포지션 사이징 (보고서 최우선: 변동성 스케일링)
# weight = clamp(TARGET_VOL_PER_BAR / realized_vol_24h, MIN, MAX)
# realized_vol_24h = 4h 봉 로그수익률 표준편차(직전 6봉). 고변동 → 축소, 저변동 → 확대.
VOL_TARGET_PER_BAR = 0.02  # 목표 4h 봉 변동성(2%)
VOL_WEIGHT_MIN = 0.25  # 최소 노출 (현물: 자본의 25%)
VOL_WEIGHT_MAX = 1.0  # 최대 노출 (현물: 레버리지 없음, 자본의 100%)

# 펀딩/OI 과열 회피 (선물 데이터를 현물 진입 필터로 활용)
FUNDING_HOT_ZSCORE = 1.5  # funding zscore 초과 시 롱 과열 — 진입 억제

# 기관 ETF 순유입 (펀더멘털 레짐 = 포지션 허용 스위치)
ETF_OUTFLOW_HEAVY_Z = -1.5  # ETF 순유입 z-score 미만 시 기관 대량 유출 — 롱 보류

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

EXEC_GATE_ECR_MULTIPLE = 3.0
EXEC_GATE_MAX_SPREAD_BPS = 5.0
EXEC_GATE_MAX_SLIPPAGE_BPS = 8.0
EXEC_GATE_MIN_DEPTH_SCORE = 0.5
EXEC_GATE_MAX_LATENCY_MS = 750.0
EXEC_GATE_VOL_SPIKE_MAX = 1.0
EXEC_GATE_MIN_DEPTH_10BP_USD = 1_000_000.0
SHADOW_ORDER_NOTIONAL_USD = 1_000.0
SHADOW_ORDER_TIMEOUT_SEC = 30
SHADOW_ARRIVAL_BENCHMARK_SEC = 1

REALTIME_RISK_WEIGHT_VOLATILITY_SPIKE = 0.18
REALTIME_RISK_WEIGHT_SPREAD_WIDENING = 0.18
REALTIME_RISK_WEIGHT_DEPTH_COLLAPSE = 0.22
REALTIME_RISK_WEIGHT_VOLUME_SHOCK = 0.10
REALTIME_RISK_WEIGHT_ORDER_FLOW_IMBALANCE = 0.12
REALTIME_RISK_WEIGHT_EXPECTED_SLIPPAGE = 0.15
REALTIME_RISK_WEIGHT_FUTURES_STRESS = 0.05
REALTIME_RISK_CAUTION_THRESHOLD = 0.35
REALTIME_RISK_BLOCK_ENTRY_THRESHOLD = 0.55
REALTIME_RISK_EXIT_CANDIDATE_THRESHOLD = 0.70
REALTIME_RISK_FORCE_EXIT_THRESHOLD = 0.85
REALTIME_RISK_SUSTAINED_WINDOWS = 2

MIN_HOLD_HOURS: dict[str, float] = {
    "regime_trend": 12.0,
    "fng_contrarian": 24.0,
    "vix_rsi": 12.0,
    "macd_momentum": 8.0,
    "multi_factor": 12.0,
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
            "realtime_collector_enabled": ARENA_REALTIME_COLLECTOR_ENABLED,
            "realtime_feature_window_seconds": REALTIME_FEATURE_WINDOW_SECONDS,
        },
        "execution_product": {
            "target_product": TARGET_PRODUCT,
            "position_semantics": POSITION_SEMANTICS,
            "short_signal_action": SHORT_SIGNAL_ACTION,
            "allow_live_short": ALLOW_LIVE_SHORT,
            "research_perp_shadow_enabled": RESEARCH_PERP_SHADOW_ENABLED,
            "spot_execution_only": True,
            "derivatives_data_usage": "research_features_only",
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
            "fng_long_below": FNG_LONG_BELOW,
            "vix_rsi_long_max": VIX_RSI_LONG_MAX,
            "macd_atr_threshold_multiple": MACD_ATR_THRESHOLD_MULTIPLE,
            "macd_momentum_rsi_long_max": MACD_MOMENTUM_RSI_LONG_MAX,
            "macd_momentum_bb_width_min": MACD_MOMENTUM_BB_WIDTH_MIN,
            "multi_factor_long_rsi_max": MULTI_FACTOR_LONG_RSI_MAX,
            "trend_core_rsi_long_max": TREND_CORE_RSI_LONG_MAX,
            "trend_core_macd_atr_threshold_multiple": TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE,
            "donchian_period": DONCHIAN_PERIOD,
            "adx_period": ADX_PERIOD,
            "adx_trend_min": ADX_TREND_MIN,
            "funding_hot_zscore": FUNDING_HOT_ZSCORE,
            "etf_outflow_heavy_z": ETF_OUTFLOW_HEAVY_Z,
            "regime_stress_return_atr_multiple": REGIME_STRESS_RETURN_ATR_MULTIPLE,
            "regime_stress_range_atr_multiple": REGIME_STRESS_RANGE_ATR_MULTIPLE,
            "regime_trend_bb_width_min": REGIME_TREND_BB_WIDTH_MIN,
            "regime_sideways_bb_width_max": REGIME_SIDEWAYS_BB_WIDTH_MAX,
            "regime_sideways_return_atr_multiple": REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE,
        },
        "position_sizing": {
            "vol_target_per_bar": VOL_TARGET_PER_BAR,
            "vol_weight_min": VOL_WEIGHT_MIN,
            "vol_weight_max": VOL_WEIGHT_MAX,
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
        "execution_gate": {
            "shadow_enabled": ARENA_EXECUTION_GATE_SHADOW_ENABLED,
            "live_enabled": ARENA_EXECUTION_GATE_LIVE_ENABLED,
            "ecr_multiple": EXEC_GATE_ECR_MULTIPLE,
            "max_spread_bps": EXEC_GATE_MAX_SPREAD_BPS,
            "max_slippage_bps": EXEC_GATE_MAX_SLIPPAGE_BPS,
            "min_depth_score": EXEC_GATE_MIN_DEPTH_SCORE,
            "max_latency_ms": EXEC_GATE_MAX_LATENCY_MS,
            "vol_spike_max": EXEC_GATE_VOL_SPIKE_MAX,
            "min_depth_10bp_usd": EXEC_GATE_MIN_DEPTH_10BP_USD,
            "shadow_order_notional_usd": SHADOW_ORDER_NOTIONAL_USD,
            "shadow_order_timeout_sec": SHADOW_ORDER_TIMEOUT_SEC,
            "shadow_arrival_benchmark_sec": SHADOW_ARRIVAL_BENCHMARK_SEC,
        },
        "realtime_risk": {
            "risk_model_version": REALTIME_RISK_MODEL_VERSION,
            "enabled": ARENA_REALTIME_RISK_ENABLED,
            "live_enabled": ARENA_REALTIME_RISK_LIVE_ENABLED,
            "history_windows": REALTIME_RISK_HISTORY_WINDOWS,
            "freshness_seconds": REALTIME_RISK_FRESHNESS_SECONDS,
            "weights": {
                "volatility_spike": REALTIME_RISK_WEIGHT_VOLATILITY_SPIKE,
                "spread_widening": REALTIME_RISK_WEIGHT_SPREAD_WIDENING,
                "depth_collapse": REALTIME_RISK_WEIGHT_DEPTH_COLLAPSE,
                "volume_shock": REALTIME_RISK_WEIGHT_VOLUME_SHOCK,
                "order_flow_imbalance": REALTIME_RISK_WEIGHT_ORDER_FLOW_IMBALANCE,
                "expected_slippage": REALTIME_RISK_WEIGHT_EXPECTED_SLIPPAGE,
                "futures_stress": REALTIME_RISK_WEIGHT_FUTURES_STRESS,
            },
            "thresholds": {
                "caution": REALTIME_RISK_CAUTION_THRESHOLD,
                "block_entry": REALTIME_RISK_BLOCK_ENTRY_THRESHOLD,
                "exit_candidate": REALTIME_RISK_EXIT_CANDIDATE_THRESHOLD,
                "force_exit_candidate": REALTIME_RISK_FORCE_EXIT_THRESHOLD,
                "sustained_windows": REALTIME_RISK_SUSTAINED_WINDOWS,
            },
            "spot_execution_only": True,
        },
    }
