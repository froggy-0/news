from __future__ import annotations

import os

from dotenv import load_dotenv

from . import parameters

load_dotenv()


def _bool_env(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"필수 환경변수 누락: {key}")
    return val


SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
R2_BASE_URL: str = os.environ.get("NEXT_PUBLIC_R2_BASE_URL", "").rstrip("/")
ENABLE_ARENA_SHADOW_VNEXT: bool = _bool_env(
    "ENABLE_ARENA_SHADOW_VNEXT",
    parameters.ARENA_SHADOW_VNEXT_ENABLED,
)
ENABLE_ARENA_FREQUENCY_SHADOW: bool = _bool_env(
    "ENABLE_ARENA_FREQUENCY_SHADOW",
    parameters.ARENA_FREQUENCY_SHADOW_ENABLED,
)
ENABLE_ARENA_REALTIME_COLLECTOR: bool = _bool_env(
    "ENABLE_ARENA_REALTIME_COLLECTOR",
    parameters.ARENA_REALTIME_COLLECTOR_ENABLED,
)
ENABLE_ARENA_REALTIME_RISK: bool = _bool_env(
    "ENABLE_ARENA_REALTIME_RISK",
    parameters.ARENA_REALTIME_RISK_ENABLED,
)
ENABLE_ARENA_REALTIME_RISK_LIVE: bool = _bool_env(
    "ENABLE_ARENA_REALTIME_RISK_LIVE",
    parameters.ARENA_REALTIME_RISK_LIVE_ENABLED,
)
ENABLE_ARENA_EXECUTION_GATE_SHADOW: bool = _bool_env(
    "ENABLE_ARENA_EXECUTION_GATE_SHADOW",
    parameters.ARENA_EXECUTION_GATE_SHADOW_ENABLED,
)
ENABLE_ARENA_EXECUTION_GATE_LIVE: bool = _bool_env(
    "ENABLE_ARENA_EXECUTION_GATE_LIVE",
    parameters.ARENA_EXECUTION_GATE_LIVE_ENABLED,
)
TARGET_PRODUCT: str = parameters.TARGET_PRODUCT
POSITION_SEMANTICS: str = parameters.POSITION_SEMANTICS
SHORT_SIGNAL_ACTION: str = parameters.SHORT_SIGNAL_ACTION
ALLOW_LIVE_SHORT: bool = False
RESEARCH_PERP_SHADOW_ENABLED: bool = _bool_env(
    "ARENA_RESEARCH_PERP_SHADOW_ENABLED",
    parameters.RESEARCH_PERP_SHADOW_ENABLED,
)

STOP_LOSS_PCT: float = float(
    os.environ.get("STOP_LOSS_PCT", str(parameters.STOP_LOSS_FALLBACK_PCT))
)  # 고정 손절 fallback
FEE_BPS: float = float(os.environ.get("FEE_BPS", str(parameters.FEE_BPS)))  # per leg

# ATR 기반 동적 손절 — stop_distance = ATR(14) × ATR_MULTIPLE
# 상하한 클램핑: STOP_LOSS_MIN_PCT ~ STOP_LOSS_MAX_PCT
ATR_MULTIPLE: float = float(os.environ.get("ATR_MULTIPLE", str(parameters.ATR_MULTIPLE)))
STOP_LOSS_MIN_PCT: float = float(
    os.environ.get("STOP_LOSS_MIN_PCT", str(parameters.STOP_LOSS_MIN_PCT))
)
STOP_LOSS_MAX_PCT: float = float(
    os.environ.get("STOP_LOSS_MAX_PCT", str(parameters.STOP_LOSS_MAX_PCT))
)

# 매크로 데이터 신선도 경고 임계 (시간)
MACRO_STALE_HOURS: float = float(
    os.environ.get("MACRO_STALE_HOURS", str(parameters.MACRO_STALE_HOURS))
)

POSITION_UNIT: float = float(os.environ.get("POSITION_UNIT", str(parameters.POSITION_UNIT)))
MAX_OPEN_POSITIONS_TOTAL: int = int(
    os.environ.get("MAX_OPEN_POSITIONS_TOTAL", str(parameters.MAX_OPEN_POSITIONS_TOTAL))
)
MAX_LONG_POSITIONS: int = int(
    os.environ.get("MAX_LONG_POSITIONS", str(parameters.MAX_LONG_POSITIONS))
)
MAX_SHORT_POSITIONS: int = int(
    os.environ.get("MAX_SHORT_POSITIONS", str(parameters.MAX_SHORT_POSITIONS))
)
MAX_NET_LONG_EXPOSURE: float = float(
    os.environ.get("MAX_NET_LONG_EXPOSURE", str(parameters.MAX_NET_LONG_EXPOSURE))
)
MAX_NET_SHORT_EXPOSURE: float = float(
    os.environ.get("MAX_NET_SHORT_EXPOSURE", str(parameters.MAX_NET_SHORT_EXPOSURE))
)
DAILY_LOSS_LIMIT_PCT: float = float(
    os.environ.get("DAILY_LOSS_LIMIT_PCT", str(parameters.DAILY_LOSS_LIMIT_PCT))
)
ALGO_MAX_DRAWDOWN_KILL_PCT: float = float(
    os.environ.get("ALGO_MAX_DRAWDOWN_KILL_PCT", str(parameters.ALGO_MAX_DRAWDOWN_KILL_PCT))
)
COOLDOWN_AFTER_KILL_HOURS: float = float(
    os.environ.get("COOLDOWN_AFTER_KILL_HOURS", str(parameters.COOLDOWN_AFTER_KILL_HOURS))
)

SLACK_BOT_TOKEN: str = os.environ.get("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL: str = os.environ.get("SLACK_CHANNEL", "").strip()

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
BINANCE_COMBINED_WS_URL = "wss://stream.binance.com:9443/stream"
# WI-9: 강제청산(forceOrder)은 선물 스트림 전용(현물 kline과 별도 커넥션·태스크).
#   수집 전용 — 트레이딩 경로와 완전 분리(수집 실패 무영향).
BINANCE_FUTURES_LIQUIDATION_WS_URL = "wss://fstream.binance.com/ws/btcusdt@forceOrder"
ARENA_LIQUIDATION_STREAM_ENABLED: bool = (
    os.environ.get("ARENA_LIQUIDATION_STREAM_ENABLED", "false").strip().lower() == "true"
)
BINANCE_REST_URL = "https://api.binance.com/api/v3/klines"
BINANCE_BOOK_TICKER_URL = "https://api.binance.com/api/v3/ticker/bookTicker"
BINANCE_DEPTH_URL = "https://api.binance.com/api/v3/depth"
SYMBOL = parameters.BINANCE_SYMBOL
KLINES_LIMIT = parameters.BINANCE_KLINES_LIMIT
REALTIME_FEATURE_WINDOW_SECONDS = int(
    os.environ.get(
        "REALTIME_FEATURE_WINDOW_SECONDS",
        str(parameters.REALTIME_FEATURE_WINDOW_SECONDS),
    )
)
REALTIME_RISK_HISTORY_WINDOWS = int(
    os.environ.get(
        "REALTIME_RISK_HISTORY_WINDOWS",
        str(parameters.REALTIME_RISK_HISTORY_WINDOWS),
    )
)
REALTIME_RISK_FRESHNESS_SECONDS = int(
    os.environ.get(
        "REALTIME_RISK_FRESHNESS_SECONDS",
        str(parameters.REALTIME_RISK_FRESHNESS_SECONDS),
    )
)
EXEC_GATE_ECR_MULTIPLE: float = float(
    os.environ.get("EXEC_GATE_ECR_MULTIPLE", str(parameters.EXEC_GATE_ECR_MULTIPLE))
)
EXEC_GATE_MAX_SPREAD_BPS: float = float(
    os.environ.get("EXEC_GATE_MAX_SPREAD_BPS", str(parameters.EXEC_GATE_MAX_SPREAD_BPS))
)
EXEC_GATE_MAX_SLIPPAGE_BPS: float = float(
    os.environ.get("EXEC_GATE_MAX_SLIPPAGE_BPS", str(parameters.EXEC_GATE_MAX_SLIPPAGE_BPS))
)
EXEC_GATE_MIN_DEPTH_SCORE: float = float(
    os.environ.get("EXEC_GATE_MIN_DEPTH_SCORE", str(parameters.EXEC_GATE_MIN_DEPTH_SCORE))
)
EXEC_GATE_MAX_LATENCY_MS: float = float(
    os.environ.get("EXEC_GATE_MAX_LATENCY_MS", str(parameters.EXEC_GATE_MAX_LATENCY_MS))
)
EXEC_GATE_VOL_SPIKE_MAX: float = float(
    os.environ.get("EXEC_GATE_VOL_SPIKE_MAX", str(parameters.EXEC_GATE_VOL_SPIKE_MAX))
)
EXEC_GATE_MIN_DEPTH_10BP_USD: float = float(
    os.environ.get("EXEC_GATE_MIN_DEPTH_10BP_USD", str(parameters.EXEC_GATE_MIN_DEPTH_10BP_USD))
)
SHADOW_ORDER_NOTIONAL_USD: float = float(
    os.environ.get("ARENA_SHADOW_ORDER_NOTIONAL_USD", str(parameters.SHADOW_ORDER_NOTIONAL_USD))
)
SHADOW_ORDER_TIMEOUT_SEC: int = int(
    os.environ.get("ARENA_SHADOW_ORDER_TIMEOUT_SEC", str(parameters.SHADOW_ORDER_TIMEOUT_SEC))
)
SHADOW_ARRIVAL_BENCHMARK_SEC: int = int(
    os.environ.get(
        "ARENA_SHADOW_ARRIVAL_BENCHMARK_SEC",
        str(parameters.SHADOW_ARRIVAL_BENCHMARK_SEC),
    )
)
LATEST_JSON_URL = f"{R2_BASE_URL}/analytics/sentiment/latest.json" if R2_BASE_URL else ""
ARENA_FREQUENCY_SHADOW_PROFILES: tuple[str, ...] = tuple(
    profile.strip()
    for profile in os.environ.get(
        "ARENA_FREQUENCY_SHADOW_PROFILES",
        ",".join(parameters.ARENA_FREQUENCY_SHADOW_PROFILES),
    ).split(",")
    if profile.strip()
)


def require_supabase_config() -> tuple[str, str]:
    return _require("SUPABASE_URL"), _require("SUPABASE_SERVICE_ROLE_KEY")
