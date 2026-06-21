"""알고리즘 5개 — 현물 long/flat 전용. short 신호 없음.

설계 원칙 (BTC 현물 심층 리서치 보고서 반영):
- 롱 추세추종을 코어로, 선물·매크로 데이터는 레짐/과열 필터로만 사용.
- 레짐 어휘는 로컬 4h 분류(bull_trend 등)와 매크로 오버레이 라벨(BullQuiet 등)을
  모두 인식하도록 정규화한다 (regime vocabulary 통일).
"""

from __future__ import annotations

from typing import Callable

from . import parameters, regime

# ── 레짐 어휘 정규화 ──────────────────────────────────────────────
# 로컬 4h regime.classify_regime() → bull_trend / bear_trend / sideways / stress
# 매크로 오버레이(risk_overlay.py)   → BullQuiet / BullHeated / BearPanic / Choppy / Transitional
_BULLISH_REGIMES = {
    regime.REGIME_BULL_TREND,  # "bull_trend"
    "BullQuiet",
    "BullHeated",
    "BullTrend",
}
_RISK_OFF_REGIMES = {
    regime.REGIME_BEAR_TREND,  # "bear_trend"
    regime.REGIME_STRESS,  # "stress"
    "BearPanic",
}


def _regime_state(macro: dict) -> str | None:
    """로컬 4h 레짐 우선, 없으면 매크로 오버레이 레짐."""
    return macro.get("arena_regime_state") or macro.get("regime_state")


def _is_bullish(state: str | None) -> bool:
    return state in _BULLISH_REGIMES


def _is_risk_off(state: str | None) -> bool:
    return state in _RISK_OFF_REGIMES


def _funding_hot(macro: dict) -> bool:
    """펀딩 z-score 과열 여부 — 롱 과밀(과열) 시 True (진입 억제)."""
    z = macro.get("funding_zscore")
    if z is None:
        return False
    try:
        return float(z) >= parameters.FUNDING_HOT_ZSCORE
    except (TypeError, ValueError):
        return False


def _etf_outflow_heavy(macro: dict) -> bool:
    """기관 ETF 대량 유출 여부 — z-score < 임계 시 True (롱 보류).

    데이터 미수집(None) 시 False — 보유한 정보가 없을 때는 차단하지 않는다.
    """
    z = macro.get("etf_flow_zscore")
    if z is None:
        return False
    try:
        return float(z) < parameters.ETF_OUTFLOW_HEAVY_Z
    except (TypeError, ValueError):
        return False


def _below_ma200(macro: dict) -> bool:
    """200일 이동평균 하회(구조적 약세) 여부 — 추세추종/모멘텀 롱 게이트.

    근거: Faber(2007), Moskowitz·Ooi·Pedersen(2012, Time Series Momentum) — 장기
    추세 필터 아래에서 롱을 보류하면 하락장 노출·whipsaw가 줄어 위험조정수익 개선.
    btc_above_ma200(0/1)은 일간 parquet에서 옴. 미수집(None) 시 게이트 미적용(False).
    """
    if not parameters.MA200_REGIME_GATE_ENABLED:
        return False
    above = macro.get("btc_above_ma200")
    if above is None:
        return False
    try:
        return float(above) < 1.0
    except (TypeError, ValueError):
        return False


def _lsr_crowded(macro: dict) -> bool:
    """선물 롱숏비 군중 과밀 여부 — z-score 극단 시 True (crowded long, veto).

    근거: 극단 롱숏비는 과밀 롱 → 조정 선행 신호. 단독 예측력은 약해 진입 트리거가
    아닌 veto로만 사용. 미수집(None) 시 False.
    """
    z = macro.get("long_short_ratio_zscore")
    if z is None:
        return False
    try:
        return float(z) >= parameters.LSR_CROWDED_ZSCORE
    except (TypeError, ValueError):
        return False


def _taker_confirms(macro: dict) -> bool:
    """체결 공격성(테이커 매수 우위)이 돌파에 동의하는지 — 돌파 확인용.

    z > 임계 = 공격적 매수 우위. 미수집(None) 시 True(확인 통과 — 차단하지 않음).
    """
    z = macro.get("taker_imbalance_zscore")
    if z is None:
        return True
    try:
        return float(z) > parameters.TAKER_CONFIRM_ZSCORE
    except (TypeError, ValueError):
        return True


def _drawdown_sufficient(macro: dict) -> bool:
    """90일 고점 대비 낙폭이 역발산 진입 품질 기준을 만족하는지.

    btc_drawdown_90d <= 임계(-0.10) = 충분한 낙폭. 미수집(None) 시 True(게이트 미적용).
    """
    dd = macro.get("btc_drawdown_90d")
    if dd is None:
        return True
    try:
        return float(dd) <= parameters.FNG_CONTRARIAN_MIN_DRAWDOWN
    except (TypeError, ValueError):
        return True


def regime_trend(macro: dict, ind: dict) -> str | None:
    """추세추종 코어 — Donchian 돌파 + 레짐/ADX/EMA 필터 (Zarattini 2025 근거).

    롱 진입 조건(전부 충족):
      ① 강세 레짐 (bull_trend / BullQuiet 등)
      ② Donchian(20) 상단 돌파 — 직전 20봉 고점 초과 (신고가 추세)
      ③ ADX > 20 — 추세 강도 확인 (횡보 whipsaw 차단)
      ④ EMA 정배열 + 단기 EMA 상승
      ⑤ RSI 과열 미도달
      ⑥ 펀딩 과열 아님
      ⑦ 200일 MA 상회 (구조적 강세 게이트 — 일간)
      ⑧ 테이커 매수 우위로 돌파 확인 (주문흐름 동의 — 일간)
      ⑨ 롱숏비 군중 과밀 아님 (일간)
    그 외 모든 경우 flat.
    """
    state = _regime_state(macro)
    close = ind.get("close", 0.0)
    dc_upper = ind.get("donchian_upper", 0.0)
    adx = ind.get("adx", 0.0)
    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 0.0)
    ema_fast_slope = ind.get("ema_fast_slope", 0.0)
    rsi = ind.get("rsi", 50.0)

    breakout = dc_upper > 0 and close > dc_upper
    trending = adx >= parameters.ADX_TREND_MIN
    ema_aligned = ema_fast > ema_slow and ema_fast_slope > 0

    if (
        _is_bullish(state)
        and breakout
        and trending
        and ema_aligned
        and rsi < parameters.TREND_CORE_RSI_LONG_MAX
        and not _funding_hot(macro)
        and not _etf_outflow_heavy(macro)
        and not _below_ma200(macro)
        and _taker_confirms(macro)
        and not _lsr_crowded(macro)
    ):
        return "long"
    return None


def fng_contrarian(macro: dict, ind: dict) -> str | None:
    """공포탐욕 역발산 — 극도의 공포 구간(FNG < 30) 매수만.

    단, risk-off 레짐(BearPanic/bear_trend/stress)에서는 진입 보류
    (단독 FNG 공포는 대부분 하락장 중간이라는 보고서 근거). 탐욕 구간 flat, 숏 없음.

    품질 게이트(일간): 극단 공포만으로는 즉시 바닥이 아닌 경우가 많으므로
    90일 고점 대비 충분한 낙폭(<= -10%)이 동반될 때만 진입 — 역발산 진입 품질 향상.
    역추세 전략이므로 200일 MA 게이트는 적용하지 않는다.
    """
    fng = macro.get("fng")
    if fng is None:
        return None
    if _is_risk_off(_regime_state(macro)):
        return None
    if not _drawdown_sufficient(macro):
        return None
    if fng < parameters.FNG_LONG_BELOW:
        return "long"
    return None


def vix_rsi(macro: dict, ind: dict) -> str | None:
    """VIX 수준 + RSI 필터 — 시장 공포 완화 + 과열 미도달 시 매수.

    VIX가 40th percentile 이하(calm) AND RSI < 50 → 롱.
    vix_q40 미수집 시 vix_now < 20 fallback. risk-off 레짐 또는 200일 MA 하회 시 보류.
    """
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)

    if vix_now is None:
        return None
    if _is_risk_off(_regime_state(macro)):
        return None
    if _below_ma200(macro):
        return None

    vix_calm = (vix_now < vix_q40) if vix_q40 else (vix_now < 20.0)

    if vix_calm and rsi < parameters.VIX_RSI_LONG_MAX:
        return "long"
    return None


def macd_momentum(macro: dict, ind: dict) -> str | None:
    """MACD 히스토그램 모멘텀 — 증가 중인 강한 모멘텀만 매수.

    ATR 임계값 초과 + 히스토그램 증가 + RSI 과열 미도달 + BB 확장 + ADX 추세.
    펀딩 과열·risk-off 레짐·200일 MA 하회·롱숏 과밀에서는 보류. 숏 없음.
    """
    h = ind["macd_hist"]
    h_prev = ind.get("macd_hist_prev", h)
    threshold = ind.get("atr", 0.0) * parameters.MACD_ATR_THRESHOLD_MULTIPLE
    rsi = ind.get("rsi", 50.0)
    bb_w = ind.get("bb_width", 100.0)
    adx = ind.get("adx", 0.0)

    if bb_w < parameters.MACD_MOMENTUM_BB_WIDTH_MIN:
        return None
    if (
        _is_risk_off(_regime_state(macro))
        or _funding_hot(macro)
        or _etf_outflow_heavy(macro)
        or _below_ma200(macro)
        or _lsr_crowded(macro)
    ):
        return None
    if (
        h > threshold
        and h > h_prev
        and rsi < parameters.MACD_MOMENTUM_RSI_LONG_MAX
        and adx >= parameters.ADX_TREND_MIN
    ):
        return "long"
    return None


def multi_factor(macro: dict, ind: dict) -> str | None:
    """복합 팩터 — 레짐·FNG·VIX·RSI·펀딩 5개 중 4개 이상 우호적일 때 매수.

    f1: 강세 레짐 (risk-off 아님 + 강세 확인)
    f2: FNG < 60 (과도한 탐욕 아님)
    f3: VIX calm (vix_now < vix_q40) — 미수집 시 우호적 처리
    f4: RSI < 50 (과열 전)
    f5: 펀딩 과열 아님 (롱 과밀 회피)
    단, risk-off 레짐·기관 ETF 대량 유출·200일 MA 하회·롱숏 과밀이면 즉시 보류(veto).
    (일간 구조 게이트는 veto로 두고, 5팩터 4-of-5 코어 로직은 그대로 유지)
    """
    state = _regime_state(macro)
    fng = macro.get("fng")
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)

    if (
        _is_risk_off(state)
        or _etf_outflow_heavy(macro)
        or _below_ma200(macro)
        or _lsr_crowded(macro)
    ):
        return None

    f1 = _is_bullish(state)
    f2 = fng is not None and fng < 60.0
    f3 = (
        vix_now is None
        or (vix_q40 is not None and vix_now < vix_q40)
        or (vix_q40 is None and vix_now < 20.0)
    )
    f4 = rsi < parameters.MULTI_FACTOR_LONG_RSI_MAX
    f5 = not _funding_hot(macro)

    if sum([f1, f2, f3, f4, f5]) >= 4:
        return "long"
    return None


ALGORITHMS: dict[str, Callable[[dict, dict], str | None]] = {
    "regime_trend": regime_trend,
    "fng_contrarian": fng_contrarian,
    "vix_rsi": vix_rsi,
    "macd_momentum": macd_momentum,
    "multi_factor": multi_factor,
}
