"""기술지표 계산 — 순수 Python, 외부 라이브러리 없음."""

from __future__ import annotations

import math

from . import frequency, parameters


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def rsi(
    closes: list[float],
    period: int = parameters.RSI_PERIOD,
    *,
    recent_multiple: int = parameters.RSI_RECENT_MULTIPLE,
) -> float:
    """Wilder 방식 RSI. 데이터 부족 시 중립값 50 반환."""
    if len(closes) < period + 1:
        return parameters.RSI_NEUTRAL
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period * recent_multiple) :]
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


def macd_histogram(
    closes: list[float],
    *,
    fast_period: int = parameters.MACD_FAST_PERIOD,
    slow_period: int = parameters.MACD_SLOW_PERIOD,
    signal_period: int = parameters.MACD_SIGNAL_PERIOD,
) -> tuple[float, float]:
    """MACD(12,26,9) histogram.

    Returns (current_hist, prev_hist).
    양수 = 상승 모멘텀. current > prev = 모멘텀 증가 중.
    """
    fast = _ema(closes, fast_period)
    slow = _ema(closes, slow_period)
    neutral = parameters.MACD_NEUTRAL
    if len(fast) < signal_period or not slow:
        return neutral, neutral
    offset = len(fast) - len(slow)
    macd_line = [fast[offset + i] - slow[i] for i in range(len(slow))]
    signal = _ema(macd_line, signal_period)
    if len(signal) < 2:
        return neutral, neutral
    return macd_line[-1] - signal[-1], macd_line[-2] - signal[-2]


def _bb_stats(
    closes: list[float],
    period: int = parameters.BOLLINGER_PERIOD,
    *,
    stddev: float = parameters.BOLLINGER_STDDEV,
) -> tuple[float, float, float]:
    """(mean, std, band_width_pct) — band_width_pct = (upper-lower)/mean * 100."""
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    window = closes[-period:]
    mean = sum(window) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    band_width_pct = (stddev * 2.0 * std / mean * 100.0) if mean else 0.0
    return mean, std, band_width_pct


def bb_position(
    closes: list[float],
    period: int = parameters.BOLLINGER_PERIOD,
    *,
    stddev: float = parameters.BOLLINGER_STDDEV,
) -> float:
    """볼린저 밴드(20, 2σ) 내 현재 위치. 0=하단, 0.5=중앙, 1=상단."""
    if len(closes) < period:
        return parameters.BOLLINGER_NEUTRAL
    mean, std, _ = _bb_stats(closes, period, stddev=stddev)
    if std == 0.0:
        return parameters.BOLLINGER_NEUTRAL
    width = stddev * 2.0 * std
    pos = (closes[-1] - (mean - stddev * std)) / width
    return max(0.0, min(1.0, pos))


def bb_width(
    closes: list[float],
    period: int = parameters.BOLLINGER_PERIOD,
    *,
    stddev: float = parameters.BOLLINGER_STDDEV,
) -> float:
    """볼린저 밴드 폭 (% of SMA). 값이 클수록 추세 시장, 작을수록 횡보."""
    _, _, band_width_pct = _bb_stats(closes, period, stddev=stddev)
    return band_width_pct


def ema_value(closes: list[float], period: int) -> float:
    values = _ema(closes, period)
    return values[-1] if values else 0.0


def bb_mid(
    closes: list[float],
    period: int = parameters.BOLLINGER_PERIOD,
) -> float:
    """볼린저 밴드 중앙선(SMA). 평균회귀 목표가(WI-7 omnibus)용. 부족 시 0.0."""
    if len(closes) < period:
        return 0.0
    return sum(closes[-period:]) / period


def relative_volume(
    volumes: list[float],
    period: int = parameters.VOLUME_SMA_PERIOD,
) -> float | None:
    """직전(마지막) 봉 볼륨 / 직전 period봉 SMA. 돌파 진위 확인(WI-4)용.

    >1.0 = 평균 이상 거래량 동반(진성 돌파 방증), <1.0 = 저조(가짜 돌파 의심).
    데이터 부족·SMA 0 시 None → 알고리즘이 graceful 통과(차단하지 않음).
    """
    if len(volumes) < period + 1:
        return None
    window = volumes[-period - 1 : -1]  # 현재 봉 제외한 직전 period봉
    sma = sum(window) / period
    if sma <= 0:
        return None
    return volumes[-1] / sma


def supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = parameters.SUPERTREND_ATR_PERIOD,
    mult: float = parameters.SUPERTREND_MULT,
) -> tuple[float, float, int]:
    """Supertrend ATR(period, mult) dynamic trend bands.

    Returns (upper_band, lower_band, direction).
    direction: 1=uptrend (long), -1=downtrend (short), 0=insufficient data.
    """
    n = len(closes)
    if n < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0, 0.0, 0

    tr_list: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

    atr_vals: list[float] = []
    atr_v = sum(tr_list[:period]) / period
    atr_vals.append(atr_v)
    for tr in tr_list[period:]:
        atr_v = (atr_v * (period - 1) + tr) / period
        atr_vals.append(atr_v)

    offset = period  # atr_vals[k] aligns to closes[offset + k]
    final_upper = 0.0
    final_lower = 0.0
    direction = 1

    for k, av in enumerate(atr_vals):
        idx = offset + k
        hl_mid = (highs[idx] + lows[idx]) / 2.0
        basic_upper = hl_mid + mult * av
        basic_lower = hl_mid - mult * av

        if k == 0:
            final_upper = basic_upper
            final_lower = basic_lower
            direction = -1 if closes[idx] < hl_mid else 1
        else:
            prev_close = closes[idx - 1]
            prev_upper = final_upper
            prev_lower = final_lower
            prev_dir = direction

            final_upper = (
                basic_upper if basic_upper < prev_upper or prev_close > prev_upper else prev_upper
            )
            final_lower = (
                basic_lower if basic_lower > prev_lower or prev_close < prev_lower else prev_lower
            )

            if prev_dir == 1:
                direction = -1 if closes[idx] < final_lower else 1
            else:
                direction = 1 if closes[idx] > final_upper else -1

    return final_upper, final_lower, direction


def ema_slope(closes: list[float], period: int) -> float:
    values = _ema(closes, period)
    if len(values) < 2:
        return 0.0
    return values[-1] - values[-2]


def donchian_channel(
    highs: list[float],
    lows: list[float],
    period: int = parameters.DONCHIAN_PERIOD,
) -> tuple[float, float, float]:
    """Donchian 채널 — 직전 `period` 바(현재 바 제외)의 최고가/최저가.

    Returns (upper, lower, mid).
    추세추종 브레이크아웃: close > upper → 신고가 돌파(롱 진입 트리거).
    현재(마지막) 바를 제외해야 "직전 N봉 고점 돌파" 정의가 성립한다.
    데이터 부족 시 (0, 0, 0).
    """
    if len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0, 0.0, 0.0
    window_high = highs[-period - 1 : -1]
    window_low = lows[-period - 1 : -1]
    upper = max(window_high)
    lower = min(window_low)
    return upper, lower, (upper + lower) / 2.0


def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = parameters.ADX_PERIOD,
) -> tuple[float, float, float]:
    """Wilder ADX(14) — 추세 강도. 방향성 무관.

    Returns (adx, plus_di, minus_di).
    ADX > 25 ≈ 추세장, < 20 ≈ 횡보. +DI > -DI = 상승 우위.
    데이터 부족 시 (0, 0, 0) — 중립(추세 약함)으로 해석.
    """
    n = len(closes)
    if n < 2 * period + 1 or len(highs) < n or len(lows) < n:
        return 0.0, 0.0, 0.0

    trs: list[float] = []
    plus_dms: list[float] = []
    minus_dms: list[float] = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dms.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dms.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        trs.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    # Wilder 평활: 초기 period 합으로 시드 후 점화식 적용.
    atr_w = sum(trs[:period])
    plus_w = sum(plus_dms[:period])
    minus_w = sum(minus_dms[:period])
    dxs: list[float] = []
    for i in range(period, len(trs)):
        atr_w = atr_w - atr_w / period + trs[i]
        plus_w = plus_w - plus_w / period + plus_dms[i]
        minus_w = minus_w - minus_w / period + minus_dms[i]
        if atr_w <= 0:
            continue
        pdi = 100.0 * plus_w / atr_w
        mdi = 100.0 * minus_w / atr_w
        denom = pdi + mdi
        dxs.append(100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0)

    if not dxs:
        return 0.0, 0.0, 0.0

    last_pdi = pdi if atr_w > 0 else 0.0
    last_mdi = mdi if atr_w > 0 else 0.0

    if len(dxs) < period:
        adx_val = sum(dxs) / len(dxs)
    else:
        adx_val = sum(dxs[:period]) / period
        for dx in dxs[period:]:
            adx_val = (adx_val * (period - 1) + dx) / period

    return adx_val, last_pdi, last_mdi


def return_over_bars(closes: list[float], bars: int) -> float:
    if bars <= 0 or len(closes) <= bars:
        return 0.0
    base = closes[-bars - 1]
    if base <= 0:
        return 0.0
    return closes[-1] / base - 1.0


def realized_vol(closes: list[float], bars: int) -> float:
    if bars <= 1 or len(closes) <= bars:
        return 0.0
    window = closes[-(bars + 1) :]
    returns = []
    for prev, current in zip(window, window[1:]):
        if prev <= 0:
            continue
        returns.append(math.log(current / prev))
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / len(returns)
    return math.sqrt(variance)


def realized_vol_ewma(
    closes: list[float],
    lam: float = parameters.VOL_EWMA_LAMBDA,
    min_bars: int = parameters.VOL_EWMA_MIN_BARS,
) -> float:
    """EWMA 봉 변동성 (RiskMetrics σ²_t = λσ²_{t-1} + (1−λ)r²_t). 지수가중이라 6봉 표본
    표준편차보다 추정 노이즈가 작다. 데이터 부족(<min_bars) 시 0.0(호출측이 6봉으로 폴백)."""
    rets: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0 and cur > 0:
            rets.append(math.log(cur / prev))
    if len(rets) < min_bars:
        return 0.0
    var = sum(r * r for r in rets[:min_bars]) / min_bars  # 초기 window로 시드
    for r in rets[min_bars:]:
        var = lam * var + (1.0 - lam) * r * r
    return math.sqrt(var) if var > 0 else 0.0


def realized_vol_sizing(closes: list[float], bars: int) -> float:
    """사이징용 변동성 — 플래그 on 시 max(6봉, EWMA)(보수: 저변동 착시로 과대사이징 방지),
    off 시 기존 6봉값. combined_position_weight 입력 전용."""
    rv6 = realized_vol(closes, bars)
    if not parameters.VOL_ESTIMATOR_ROBUST_ENABLED:
        return rv6
    ewma = realized_vol_ewma(closes)
    return max(rv6, ewma) if ewma > 0 else rv6


def high_low_range_atr_ratio(
    highs: list[float],
    lows: list[float],
    atr_value: float,
    bars: int,
) -> float:
    if bars <= 0 or len(highs) < bars or len(lows) < bars or atr_value <= 0:
        return 0.0
    return (max(highs[-bars:]) - min(lows[-bars:])) / atr_value


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = parameters.ATR_PERIOD,
    fallback_pct: float = parameters.ATR_FALLBACK_PCT,
) -> float:
    """Wilder ATR(14) — 변동성 기반 동적 손절 계산용.

    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    데이터 부족 시 최근 Close 기준 1% 반환 (보수적 fallback).
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return closes[-1] * fallback_pct if closes else 0.0
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


def compute(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    indicator_profile_id: str = frequency.DEFAULT_INDICATOR_PROFILE_ID,
) -> dict[str, float]:
    settings = frequency.indicator_settings(
        interval=interval,
        indicator_profile_id=indicator_profile_id,
    )
    hist, hist_prev = macd_histogram(
        closes,
        fast_period=settings.macd_fast_period,
        slow_period=settings.macd_slow_period,
        signal_period=settings.macd_signal_period,
    )
    atr_value = atr(
        highs,
        lows,
        closes,
        period=settings.atr_period,
        fallback_pct=settings.atr_fallback_pct,
    )
    close = closes[-1] if closes else 0.0
    ema_fast = ema_value(closes, settings.trend_ema_fast_period)
    ema_slow = ema_value(closes, settings.trend_ema_slow_period)
    st_upper, st_lower, st_dir = supertrend(
        highs,
        lows,
        closes,
        period=parameters.SUPERTREND_ATR_PERIOD,
        mult=parameters.SUPERTREND_MULT,
    )
    dc_upper, dc_lower, dc_mid = donchian_channel(
        highs,
        lows,
        period=parameters.DONCHIAN_PERIOD,
    )
    adx_val, plus_di, minus_di = adx(highs, lows, closes, period=parameters.ADX_PERIOD)
    result = {
        "close": close,
        "rsi": rsi(
            closes,
            period=settings.rsi_period,
            recent_multiple=settings.rsi_recent_multiple,
        ),
        # WI-5: 직전 봉 RSI — vix_rsi 크로스(과매도선 상향 돌파) 이벤트 판정용.
        "rsi_prev": rsi(
            closes[:-1],
            period=settings.rsi_period,
            recent_multiple=settings.rsi_recent_multiple,
        )
        if len(closes) > 1
        else parameters.RSI_NEUTRAL,
        "macd_hist": hist,
        "macd_hist_prev": hist_prev,
        "bb_pos": bb_position(
            closes,
            period=settings.bollinger_period,
            stddev=settings.bollinger_stddev,
        ),
        "bb_width": bb_width(
            closes,
            period=settings.bollinger_period,
            stddev=settings.bollinger_stddev,
        ),
        # WI-7: BB 중앙선(SMA) — omnibus RANGE 평균회귀 목표가.
        "bb_mid": bb_mid(closes, period=settings.bollinger_period),
        "atr": atr_value,
        "atr_pct": atr_value / close if close > 0 else 0.0,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_fast_slope": ema_slope(closes, settings.trend_ema_fast_period),
        "ema_slow_slope": ema_slope(closes, settings.trend_ema_slow_period),
        "ema_21": ema_value(closes, parameters.EMA_21_PERIOD),
        "ema_55": ema_value(closes, parameters.EMA_55_PERIOD),
        "ema_200": ema_value(closes, parameters.EMA_200_PERIOD),
        "supertrend_upper": st_upper,
        "supertrend_lower": st_lower,
        "supertrend_dir": float(st_dir),
        "donchian_upper": dc_upper,
        "donchian_lower": dc_lower,
        "donchian_mid": dc_mid,
        "adx": adx_val,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "return_24h": return_over_bars(closes, settings.return_24h_bars),
        "return_72h": return_over_bars(closes, settings.return_72h_bars),
        "realized_vol_24h": realized_vol(closes, settings.realized_vol_24h_bars),
        # R2: 사이징 전용 변동성(플래그 on 시 max(6봉,EWMA)). realized_vol_24h는 레짐·진단 유지.
        "realized_vol_sizing": realized_vol_sizing(closes, settings.realized_vol_24h_bars),
        "range_24h_atr": high_low_range_atr_ratio(
            highs,
            lows,
            atr_value,
            settings.return_24h_bars,
        ),
    }
    # WI-4: 상대 볼륨(돌파 확인). volumes 미전달 시 None → 알고리즘 graceful 통과.
    result["rel_volume"] = relative_volume(volumes) if volumes else None
    return result
