"""알고리즘 5개 정의. 각각 macro + 기술지표를 입력받아 'long'|'short'|None(flat) 반환."""

from __future__ import annotations

from typing import Callable

from . import parameters


def regime_v2(macro: dict, ind: dict) -> str | None:
    """거시 regime만 사용. BullQuiet=long, BearPanic=short."""
    r = macro.get("regime_state", "")
    if r == parameters.REGIME_LONG_STATE:
        return "long"
    if r == parameters.REGIME_SHORT_STATE:
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


def vix_rsi(macro: dict, ind: dict) -> str | None:
    """VIX 안정 구간 + RSI 과매수 미달 시 매수."""
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    if vix_now is None or vix_q40 is None:
        return None
    if vix_now < vix_q40 and ind["rsi"] < parameters.VIX_RSI_LONG_MAX:
        return "long"
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


def multi_factor(macro: dict, ind: dict) -> str | None:
    """BullQuiet + RSI<50 + MACD양 복합. BearPanic + RSI>55 + MACD음 숏.

    수정(이전): 숏 조건에 MACD 확인이 없어 롱/숏 간 비대칭 존재.
    수정(이후): 숏도 MACD < 0 추가 → 양방향 동일한 엄격도 적용.
    """
    r = macro.get("regime_state", "")
    h = ind["macd_hist"]
    if (
        r == parameters.REGIME_LONG_STATE
        and ind["rsi"] < parameters.MULTI_FACTOR_LONG_RSI_MAX
        and h > 0
    ):
        return "long"
    if (
        r == parameters.REGIME_SHORT_STATE
        and ind["rsi"] > parameters.MULTI_FACTOR_SHORT_RSI_MIN
        and h < 0
    ):
        return "short"
    return None


ALGORITHMS: dict[str, Callable[[dict, dict], str | None]] = {
    "regime_v2": regime_v2,
    "fng_contrarian": fng_contrarian,
    "vix_rsi": vix_rsi,
    "macd_momentum": macd_momentum,
    "multi_factor": multi_factor,
}
