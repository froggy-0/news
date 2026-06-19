"""기술지표 계산 — 순수 Python, 외부 라이브러리 없음."""

from __future__ import annotations

import math

from . import parameters


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def rsi(closes: list[float], period: int = parameters.RSI_PERIOD) -> float:
    """Wilder 방식 RSI. 데이터 부족 시 중립값 50 반환."""
    if len(closes) < period + 1:
        return parameters.RSI_NEUTRAL
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period * parameters.RSI_RECENT_MULTIPLE) :]
    gains = [max(d, 0.0) for d in recent]
    losses = [abs(min(d, 0.0)) for d in recent]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0.0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def macd_histogram(closes: list[float]) -> tuple[float, float]:
    """MACD(12,26,9) histogram.

    Returns (current_hist, prev_hist).
    양수 = 상승 모멘텀. current > prev = 모멘텀 증가 중.
    """
    fast = _ema(closes, parameters.MACD_FAST_PERIOD)
    slow = _ema(closes, parameters.MACD_SLOW_PERIOD)
    neutral = parameters.MACD_NEUTRAL
    if len(fast) < parameters.MACD_SIGNAL_PERIOD or not slow:
        return neutral, neutral
    offset = len(fast) - len(slow)
    macd_line = [fast[offset + i] - slow[i] for i in range(len(slow))]
    signal = _ema(macd_line, parameters.MACD_SIGNAL_PERIOD)
    if len(signal) < 2:
        return neutral, neutral
    return macd_line[-1] - signal[-1], macd_line[-2] - signal[-2]


def _bb_stats(
    closes: list[float], period: int = parameters.BOLLINGER_PERIOD
) -> tuple[float, float, float]:
    """(mean, std, band_width_pct) — band_width_pct = (upper-lower)/mean * 100."""
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    window = closes[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    band_width_pct = (parameters.BOLLINGER_STDDEV * 2.0 * std / mean * 100.0) if mean else 0.0
    return mean, std, band_width_pct


def bb_position(closes: list[float], period: int = parameters.BOLLINGER_PERIOD) -> float:
    """볼린저 밴드(20, 2σ) 내 현재 위치. 0=하단, 0.5=중앙, 1=상단."""
    if len(closes) < period:
        return parameters.BOLLINGER_NEUTRAL
    mean, std, _ = _bb_stats(closes, period)
    if std == 0.0:
        return parameters.BOLLINGER_NEUTRAL
    width = parameters.BOLLINGER_STDDEV * 2.0 * std
    pos = (closes[-1] - (mean - parameters.BOLLINGER_STDDEV * std)) / width
    return max(0.0, min(1.0, pos))


def bb_width(closes: list[float], period: int = parameters.BOLLINGER_PERIOD) -> float:
    """볼린저 밴드 폭 (% of SMA). 값이 클수록 추세 시장, 작을수록 횡보."""
    _, _, band_width_pct = _bb_stats(closes, period)
    return band_width_pct


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = parameters.ATR_PERIOD,
) -> float:
    """Wilder ATR(14) — 변동성 기반 동적 손절 계산용.

    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    데이터 부족 시 최근 Close 기준 1% 반환 (보수적 fallback).
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return closes[-1] * parameters.ATR_FALLBACK_PCT if closes else 0.0
    tr_list: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    atr_val = sum(tr_list[:period]) / period
    for tr in tr_list[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def compute(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, float]:
    hist, hist_prev = macd_histogram(closes)
    return {
        "rsi": rsi(closes),
        "macd_hist": hist,
        "macd_hist_prev": hist_prev,
        "bb_pos": bb_position(closes),
        "bb_width": bb_width(closes),
        "atr": atr(highs, lows, closes),
    }
