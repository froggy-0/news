"""알고리즘 5개 정의. 각각 macro + 기술지표를 입력받아 'long'|'short'|None(flat) 반환."""

from __future__ import annotations

from typing import Callable

from . import parameters, regime


def supertrend(macro: dict, ind: dict) -> str | None:
    """Supertrend ATR(10, 3.0) trend-following. direction=1→long, -1→short."""
    direction = int(ind.get("supertrend_dir", 0))
    if direction == 1:
        return "long"
    if direction == -1:
        return "short"
    return None


def fng_contrarian(macro: dict, ind: dict) -> str | None:
    """FNG 역발산. 공포 매수, 탐욕 매도."""
    fng = macro.get("fng")
    if fng is None:
        return None
    if fng < parameters.FNG_LONG_BELOW:
        return "long"
    if fng > parameters.FNG_SHORT_ABOVE:
        return "short"
    return None


def ema_cross(macro: dict, ind: dict) -> str | None:
    """Triple EMA trend alignment: 21 > 55 > 200 → long; 21 < 55 < 200 → short."""
    ema_21 = ind.get("ema_21", 0.0)
    ema_55 = ind.get("ema_55", 0.0)
    ema_200 = ind.get("ema_200", 0.0)
    if ema_21 <= 0 or ema_55 <= 0 or ema_200 <= 0:
        return None
    if ema_21 > ema_55 > ema_200:
        return "long"
    if ema_21 < ema_55 < ema_200:
        return "short"
    return None


def macd_momentum(macro: dict, ind: dict) -> str | None:
    """MACD histogram 방향 추종 — ATR 임계값 + RSI 과열 + 히스토그램 모멘텀 필터.

    개선 v5 (arena-ec2-v5):
    - ATR 임계값 0.10: 강한 모멘텀만 신호화
    - RSI 필터: 과매수(≥65) 롱 차단, 과매도(≤35) 숏 차단
    - MACD 히스토그램 델타 필터 (핵심):
        Long : hist > threshold AND hist > hist_prev  (모멘텀 증가 중)
        Short: hist < -threshold AND hist < hist_prev (모멘텀 감소 중)
      히스토그램이 꺾인 후 진입하면 fade 구간으로 avgW↓ → 제거
    - BB width 필터 유지: 횡보장 진입 차단
    - min_hold_hours 8h (parameters.py)
    """
    h = ind["macd_hist"]
    h_prev = ind.get("macd_hist_prev", h)  # 이전 바 hist; 없으면 현재값 (필터 미적용)
    threshold = ind.get("atr", 0.0) * parameters.MACD_ATR_THRESHOLD_MULTIPLE
    rsi = ind.get("rsi", 50.0)
    bb_w = ind.get("bb_width", 100.0)

    if bb_w < parameters.MACD_MOMENTUM_BB_WIDTH_MIN:
        return None

    if h > threshold and h > h_prev and rsi < parameters.MACD_MOMENTUM_RSI_LONG_MAX:
        return "long"
    if h < -threshold and h < h_prev and rsi > parameters.MACD_MOMENTUM_RSI_SHORT_MIN:
        return "short"
    return None


def bb_squeeze(macro: dict, ind: dict) -> str | None:
    """Bollinger Band squeeze breakout: trade direction when BB is compressed.

    Squeeze = bb_width < threshold. Within squeeze, bb_pos + RSI confirm direction.
    """
    bb_w = ind.get("bb_width", 100.0)
    bb_pos = ind.get("bb_pos", 0.5)
    rsi = ind.get("rsi", 50.0)

    if bb_w > parameters.BB_SQUEEZE_WIDTH_MAX_PCT:
        return None

    if (
        bb_pos >= parameters.BB_SQUEEZE_BB_POS_LONG_MIN
        and rsi > parameters.BB_SQUEEZE_RSI_THRESHOLD
    ):
        return "long"
    if (
        bb_pos <= parameters.BB_SQUEEZE_BB_POS_SHORT_MAX
        and rsi < parameters.BB_SQUEEZE_RSI_THRESHOLD
    ):
        return "short"
    return None


def trend_core_v1(macro: dict, ind: dict) -> str | None:
    """Shadow-only trend-following core.

    Live paper trading is intentionally unchanged; this signal is evaluated via
    sleeves/allocator and written to arena_shadow_decisions only.
    """
    regime_state = macro.get("arena_regime_state") or macro.get("regime_state")
    h = ind["macd_hist"]
    threshold = ind.get("atr", 0.0) * parameters.TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE
    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 0.0)
    ema_fast_slope = ind.get("ema_fast_slope", 0.0)
    rsi = ind.get("rsi", 50.0)

    if (
        regime_state == regime.REGIME_BULL_TREND
        and ema_fast > ema_slow
        and ema_fast_slope > 0
        and h > threshold
        and rsi < parameters.TREND_CORE_RSI_LONG_MAX
    ):
        return "long"
    if (
        regime_state == regime.REGIME_BEAR_TREND
        and ema_fast < ema_slow
        and ema_fast_slope < 0
        and h < -threshold
        and rsi > parameters.TREND_CORE_RSI_SHORT_MIN
    ):
        return "short"
    return None


ALGORITHMS: dict[str, Callable[[dict, dict], str | None]] = {
    "supertrend": supertrend,
    "fng_contrarian": fng_contrarian,
    "ema_cross": ema_cross,
    "macd_momentum": macd_momentum,
    "bb_squeeze": bb_squeeze,
}
