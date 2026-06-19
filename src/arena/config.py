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

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
BINANCE_REST_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = parameters.BINANCE_SYMBOL
KLINES_LIMIT = parameters.BINANCE_KLINES_LIMIT
LATEST_JSON_URL = f"{R2_BASE_URL}/analytics/sentiment/latest.json" if R2_BASE_URL else ""


def require_supabase_config() -> tuple[str, str]:
    return _require("SUPABASE_URL"), _require("SUPABASE_SERVICE_ROLE_KEY")
