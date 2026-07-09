"""알고리즘 5개 — 현물 long/flat 전용. short 신호 없음.

설계 원칙 (BTC 현물 심층 리서치 보고서 반영):
- 롱 추세추종을 코어로, 선물·매크로 데이터는 레짐/과열 필터로만 사용.
- 레짐 어휘는 로컬 4h 분류(bull_trend 등)와 매크로 오버레이 라벨(BullQuiet 등)을
  모두 인식하도록 정규화한다 (regime vocabulary 통일).
"""

from __future__ import annotations

from typing import Any, Callable

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
    """로컬 4h 레짐 우선, 없거나 'unknown'(규칙 미매칭)이면 매크로 오버레이 레짐으로 폴백.

    이전 버그: arena_regime_state='unknown'이 truthy라 `or` 폴백이 작동 안 해
    매크로가 BullQuiet여도 로컬이 혼조(unknown)면 regime_trend가 영구 차단됐음.
    게이트=일간 오버레이 / 트리거=4h 기술지표 철학과 일치(혼조 시 게이트는 일간 레짐 사용).
    """
    local = macro.get("arena_regime_state")
    if local and local != regime.REGIME_UNKNOWN:
        return local
    return macro.get("regime_state")


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


def _oi_diverged(macro: dict) -> bool:
    """OI-가격 7일 방향 불일치 여부 — flag>0 시 True (추세 미확인, 모멘텀 롱 억제).

    가격 7일수익률과 OI 7일변화의 부호가 반대(=추세가 포지셔닝으로 확인되지 않음).
    현물 long-only에서 모멘텀/추세 진입의 건전성 필터로 사용. 미수집(None) 시 False.
    """
    flag = macro.get("oi_divergence_flag")
    if flag is None:
        return False
    try:
        return float(flag) > 0.0
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
    """일간 200일 MA 하회 여부 — 구조적 하락추세 게이트 (Faber 2007, TSMOM).

    v24(2026-06-26)부터 omnibus UP_TREND·macd_momentum에서 사용. 4H 로컬 EMA 게이트
    (`_below_ema_trend`)와 별개로, 일간 구조적 추세를 거스르는 강세/모멘텀 롱을 보류한다.
    진단(macro 백필 6개월): 두 알고의 손실이 MA200 하회 구간의 역추세 롱에 집중
    (omnibus UP_TREND 14건 -3.23%, macd 13건 중 8건이 하회 손실). 게이트 후 omnibus
    -3.66→-2.05%·macd -3.53→-1.06%(독립 캡, 타 알고 무영향). 미수집(None) 시 graceful
    통과. 플래그 MA200_REGIME_GATE_ENABLED.
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


def _below_ema_trend(ind: dict) -> bool:
    """4H EMA200(200×4H ≈ 33일) 하회 여부 — 추세추종/모멘텀 롱 게이트.

    일간 btc_above_ma200 대신 로컬 4H 지표를 사용해 macro 지연 없이 실시간 판단.
    ema_200 미산출(0.0) 시 False(게이트 미적용).
    """
    close = ind.get("close", 0.0)
    ema_200 = ind.get("ema_200", 0.0)
    if ema_200 <= 0:
        return False
    return close < ema_200


def _below_ema_trend_strict(ind: dict, macro: dict) -> bool:
    """EMA200 게이트 — bull_trend 확인 시 레짐 분류기가 이미 구조적 추세 확인했으므로 비적용.

    4H EMA200 = 33일 EMA (Faber 200일 MA와 다름). bull_trend 레짐에서는 로컬 4H
    분류기가 동일 데이터로 이미 추세를 확인한 것 → EMA200 추가 게이트는 중복 필터.
    bull_trend 이외(sideways/unknown/stress): EMA200 게이트 유지 (구조적 방어선).
    """
    if macro.get("arena_regime_state") == regime.REGIME_BULL_TREND:
        return False
    return _below_ema_trend(ind)


def _below_ema_loose(ind: dict) -> bool:
    """4H EMA55(55×4H ≈ 9일) 하회 여부 — 복합팩터 소프트 게이트.

    multi_factor는 레짐 조건이 이미 내부 팩터에 포함돼 있어 단기 MA면 충분.
    ema_55 미산출(0.0) 시 False(게이트 미적용).
    """
    close = ind.get("close", 0.0)
    ema_55 = ind.get("ema_55", 0.0)
    if ema_55 <= 0:
        return False
    return close < ema_55


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

    WI-10(2026-07-09): TAKER_CONFIRM_4H_ENABLED 시 로컬 4h taker_ratio_4h(buySellRatio,
    1.0=중립)를 우선 사용 — 일간 lag1 z의 하루 지연 제거. 4h 값 미수집 시 일간 z로 폴백.
    z > 임계(또는 ratio ≥ 임계) = 공격적 매수 우위. 둘 다 미수집(None) 시 True(통과).
    """
    if parameters.TAKER_CONFIRM_4H_ENABLED:
        ratio = macro.get("taker_ratio_4h")
        if ratio is not None:
            try:
                return float(ratio) >= parameters.TAKER_CONFIRM_RATIO_4H_MIN
            except (TypeError, ValueError):
                return True
    z = macro.get("taker_imbalance_zscore")
    if z is None:
        return True
    try:
        return float(z) > parameters.TAKER_CONFIRM_ZSCORE
    except (TypeError, ValueError):
        return True


def _volume_confirms(ind: dict) -> bool:
    """돌파봉 거래량이 진성 돌파를 뒷받침하는지 — WI-4 regime_trend 돌파 확인.

    rel_volume ≥ MIN_REL(20봉 평균 대비 배수) = 진성 돌파. 미수집(None)·플래그 off 시
    True(통과 — 차단하지 않음). 근거: 저조한 볼륨 돌파는 실패율이 높다(Donchian 가짜돌파
    필터의 정석 — TrendSpider/LuxAlgo). backtest·live 공용(둘 다 rel_volume 주입).
    """
    if not parameters.VOLUME_CONFIRM_ENABLED:
        return True
    rv = ind.get("rel_volume")
    if rv is None:
        return True
    try:
        return float(rv) >= parameters.VOLUME_CONFIRM_MIN_REL
    except (TypeError, ValueError):
        return True


def _breadth_collapsed(macro: dict) -> bool:
    """시장 폭 붕괴 여부 — top10 알트 참여율이 임계 미만이면 True (협소 랠리 보류).

    breadth_up_ratio < 임계 = BTC 단독/협소 상승(건전성 낮음). 미수집(None) 시 False.
    """
    r = macro.get("breadth_up_ratio")
    if r is None:
        return False
    try:
        return float(r) < parameters.BREADTH_HEALTHY_MIN
    except (TypeError, ValueError):
        return False


def _stablecoin_contracting(macro: dict) -> bool:
    """온체인 유동성 수축 여부 — 스테이블코인 공급증가율 z가 임계 미만이면 True.

    z < 임계 = 자본 이탈(대기 매수력 감소). 미수집(None) 시 False — 차단하지 않음.
    """
    z = macro.get("stablecoin_supply_zscore")
    if z is None:
        return False
    try:
        return float(z) < parameters.STABLECOIN_CONTRACTION_Z
    except (TypeError, ValueError):
        return False


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


def _momentum_not_worsening(ind: dict, *, enabled: bool = True) -> bool:
    """하락 모멘텀이 더 악화되지 않을 때만 True — freefall 한복판 진입(칼받기) 회피.

    MACD 히스토그램이 직전 봉 대비 상승(>=)이면 하락 가속이 멈춘 것으로 본다(평균회귀
    진입 타이밍 필터: 매도 소진 대기). 미수집(None) 시 True(graceful). v23 백테스트
    (macro 백필 6개월): fng 종가자산 1.002→1.011·MaxDD -4.9→-2.9%·2월 -2.47→-1.40%.
    재현: scripts/analysis 실험. 플래그 FNG_CONTRARIAN_STABILIZATION_ENABLED.
    """
    if not enabled:
        return True
    mh = ind.get("macd_hist")
    mhp = ind.get("macd_hist_prev")
    if mh is None or mhp is None:
        return True
    try:
        return float(mh) >= float(mhp)
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
      ⑦ 4H EMA200(≈33일) 상회 — 로컬 중기 추세 게이트
      ⑧ 테이커 매수 우위로 돌파 확인 (주문흐름 동의 — 일간)
      ⑨ 롱숏비 군중 과밀 아님 (일간)
      ⑩ OI-가격 7일 방향 불일치 아님 (추세 확인 — 일간)
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
        and not _below_ema_trend_strict(ind, macro)
        and _taker_confirms(macro)
        and _volume_confirms(ind)  # WI-4: 돌파봉 거래량 확인(진성 돌파)
        and not _lsr_crowded(macro)
        and not _oi_diverged(macro)
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

    시장 환경 veto(multi_factor와 동일 기준):
    - breadth 붕괴(top10 상승비율 < 0.30): 전방위 하락장에서 역발산은 칼받기
    - stablecoin 수축(z < -1.5): 온체인 유동성 이탈 시 평균회귀 에너지 없음
    """
    fng = macro.get("fng")
    if fng is None:
        return None
    if _is_risk_off(_regime_state(macro)):
        return None
    if not _drawdown_sufficient(macro):
        return None
    if _breadth_collapsed(macro):
        return None
    if _stablecoin_contracting(macro):
        return None
    if fng < parameters.FNG_LONG_BELOW:
        # 안정화 게이트(v23): 하락 모멘텀이 더 악화되는 중이면 진입 보류(칼받기 회피).
        if not _momentum_not_worsening(
            ind, enabled=parameters.FNG_CONTRARIAN_STABILIZATION_ENABLED
        ):
            return None
        return "long"
    return None


def vix_rsi(macro: dict, ind: dict) -> str | None:
    """VIX 수준 + RSI 필터 — 시장 공포 완화 + 과열 미도달 시 매수.

    VIX가 40th percentile 이하(calm) AND RSI < 50 → 롱.
    vix_q40 미수집 시 vix_now < 20 fallback. risk-off 레짐 시 보류.

    시장 환경 veto:
    - breadth 붕괴(top10 상승비율 < 0.30): 하락장에서 VIX가 낮아도 RSI<50은 구조적 패턴
      → VIX/RSI 외생 신호가 노이즈가 되는 환경을 걸러낸다.
    - stablecoin 수축(z < -1.5): 온체인 유동성 이탈 시 매수 에너지 부재.
    MA200 게이트는 미적용 — VIX/RSI는 추세 방향성과 무관한 외생 신호.

    진입 안정화(v26): RSI<50 딥매수는 하락 가속 한복판에서 칼받기가 되기 쉬움
    (라이브 -5.43%·백테스트 11개월 -10.71%, 손실이 MACD 히스토그램 악화 중 진입에
    집중). fng v23에서 검증된 _momentum_not_worsening을 동일하게 적용 — 매도 소진
    (히스토그램 반등) 확인 후 진입.

    WI-5(v27, 2026-07-09): 엣지 부재(수정 후에도 백테스트 -0.57%) 대응 2단계.
    - Step1 MA200 게이트(VIX_RSI_MA200_GATE_ENABLED): 손실이 하락 구간에 집중 →
      일간 MA200 하회 시 보류. "외생 신호라 방향성 무관" 이론이 데이터와 충돌 → 데이터 우선.
    - Step2 크로스 트리거(VIX_RSI_TRIGGER_MODE="cross"): "RSI<50 상태"(하락 중 매수)를
      "RSI가 과매도선 상향 크로스"(반전 확인 매수) 이벤트로 재정의. 보유는 v26 히스테리시스.
    """
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)

    if vix_now is None:
        return None
    if _is_risk_off(_regime_state(macro)):
        return None
    if _breadth_collapsed(macro):
        return None
    if _stablecoin_contracting(macro):
        return None
    if parameters.VIX_RSI_MA200_GATE_ENABLED and _below_ma200(macro):
        return None
    if not _momentum_not_worsening(ind, enabled=parameters.VIX_RSI_STABILIZATION_ENABLED):
        return None

    # q40 기준 +5% 이내(VIX_CALM_TOLERANCE_BAND)는 실질 calm으로 인정.
    # 90일 롤링 추정치 오차를 감안한 허용 밴드 (18.44 vs 17.85 = 3.3% 차이는 노이즈).
    vix_calm = (
        (vix_now < vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND) if vix_q40 else (vix_now < 20.0)
    )
    if not vix_calm:
        return None

    if parameters.VIX_RSI_TRIGGER_MODE == "cross":
        # 과매도선을 하향(직전 봉) 후 상향(현재 봉) 돌파한 봉만 진입 — 반전 확인.
        rsi_prev = ind.get("rsi_prev", rsi)
        if rsi_prev < parameters.VIX_RSI_CROSS_OVERSOLD <= rsi:
            return "long"
        return None

    if rsi < parameters.VIX_RSI_LONG_MAX:
        return "long"
    return None


def macd_momentum(macro: dict, ind: dict) -> str | None:
    """MACD 히스토그램 모멘텀 — 신호선 위에서 증가 중인 모멘텀 매수.

    h > 0(시그널선 상회) + h > h_prev(모멘텀 강화 중) + RSI 과열 미도달 + BB 확장 + ADX 추세.
    이전 ATR 임계값(h > ATR×0.10)은 제거: 히스토그램이 양수면 이미 MACD>시그널(강세).
    ATR 임계는 이미 강한 모멘텀만 걸러 초기 형성 구간(0~ATR×0.10)을 전부 차단했음.

    펀딩 과열·risk-off 레짐·4H EMA200 하회·롱숏 과밀·OI 방향불일치에서는 보류. 숏 없음.

    WI-6(v27, 2026-07-09): TRIGGER_MODE="zero_cross" 시 "h>0 상태+증가"(늦은 진입,
    regime_trend와 중복)를 "h가 0선을 상향 크로스한 봉"(모멘텀 전환 초기)으로 재정의.
    진입이 빨라지며 RSI<65 충돌 완화 + regime_trend(돌파=추세 중기)와 시간축 차별화(중복
    해소). 보유는 exit_hold_override가 h>0 동안 flat 청산 보류(v26 vix_rsi 히스테리시스와
    동일 구조 — 크로스 봉 단발 진입 후 모멘텀 지속 시 유지). 청산=h≤0 또는 risk-off/트레일.
    """
    h = ind["macd_hist"]
    h_prev = ind.get("macd_hist_prev", h)
    rsi = ind.get("rsi", 50.0)
    bb_w = ind.get("bb_width", 100.0)
    adx = ind.get("adx", 0.0)

    cross_mode = parameters.MACD_MOMENTUM_TRIGGER_MODE == "zero_cross"
    # 크로스 모드는 스퀴즈 직후 발생 가능 → BB폭 게이트 제거를 옵션으로.
    apply_bb_gate = not (cross_mode and parameters.MACD_MOMENTUM_ZERO_CROSS_DROP_BB_GATE)
    if apply_bb_gate and bb_w < parameters.MACD_MOMENTUM_BB_WIDTH_MIN:
        return None
    if (
        _is_risk_off(_regime_state(macro))
        or _funding_hot(macro)
        or _etf_outflow_heavy(macro)
        or _below_ema_trend_strict(ind, macro)
        or _below_ma200(macro)  # v24: 구조적 하락추세(일간 MA200 하회) 시 모멘텀 롱 보류
        or _lsr_crowded(macro)
        or _oi_diverged(macro)
    ):
        return None
    rsi_ok = rsi < parameters.MACD_MOMENTUM_RSI_LONG_MAX
    adx_ok = adx >= parameters.MACD_MOMENTUM_ADX_MIN
    if cross_mode:
        if h_prev <= 0 < h and rsi_ok and adx_ok:
            return "long"
        return None
    if h > 0 and h > h_prev and rsi_ok and adx_ok:
        return "long"
    return None


def multi_factor(macro: dict, ind: dict) -> str | None:
    """복합 팩터 — 레짐·FNG·VIX·RSI·펀딩 5개 중 4개 이상 우호적일 때 매수.

    f1: 강세 레짐 (risk-off 아님 + 강세 확인)
    f2: FNG < 60 (과도한 탐욕 아님)
    f3: VIX calm (vix_now < vix_q40) — 미수집 시 우호적 처리
    f4: RSI < 50 (과열 전)
    f5: 펀딩 과열 아님 (롱 과밀 회피)
    단, risk-off 레짐·기관 ETF 대량 유출·롱숏 과밀·시장폭 붕괴·온체인 유동성 수축이면
    즉시 보류(veto).

    EMA55 veto 제거(arena-params-v19): 이 알고는 매크로/감정 5팩터 투표가 핵심이라
    9일 EMA가 veto로 작동하면 팩터 모두 우호적일 때도 차단되는 구조적 문제 발생.
    레짐 방향성(f1)이 이미 bearish 환경을 내부 팩터로 반영한다.

    WI-1(v27, 2026-07-09): 구조 결함 수정. 기존 "5중 4"는 방향성(f1 레짐)이 선택 사항이라
    조용한 하락장에서 f2~f5(FNG<60·VIX calm·RSI<55·펀딩 정상)만으로 4표 충족→진입했음
    (라이브 유일 거래·현 보유 포지션이 이 패턴). MULTI_FACTOR_REGIME_REQUIRED=True 시
    레짐(f1)을 필수 조건으로 승격하고 나머지 4팩터 중 MIN_VOTES_EX_REGIME 득표를 요구한다.
    ALLOW_SIDEWAYS=True면 강세뿐 아니라 횡보(sideways)도 방향성 통과로 인정(bear류만 배제).
    """
    if (
        _is_risk_off(_regime_state(macro))
        or _etf_outflow_heavy(macro)
        or _lsr_crowded(macro)
        or _breadth_collapsed(macro)
        or _stablecoin_contracting(macro)
    ):
        return None

    factors = _multi_factor_factors(macro, ind)
    if parameters.MULTI_FACTOR_REGIME_REQUIRED:
        state = _regime_state(macro)
        direction_ok = _is_bullish(state) or (
            parameters.MULTI_FACTOR_ALLOW_SIDEWAYS and state == regime.REGIME_SIDEWAYS
        )
        if not direction_ok:
            return None
        other_votes = sum(v for k, v in factors.items() if k != "bullish_regime")
        if other_votes >= parameters.MULTI_FACTOR_MIN_VOTES_EX_REGIME:
            return "long"
        return None

    if sum(factors.values()) >= 4:
        return "long"
    return None


def _multi_factor_factors(macro: dict, ind: dict) -> dict[str, bool]:
    """multi_factor 5팩터 평가 — 진입(≥4)·청산 히스테리시스·진단 공용."""
    state = _regime_state(macro)
    fng = macro.get("fng")
    vix_now = macro.get("vix_now")
    vix_q40 = macro.get("vix_q40")
    rsi = ind.get("rsi", 50.0)
    return {
        "bullish_regime": _is_bullish(state),
        "fng_below_60": fng is not None and fng < 60.0,
        "vix_calm_or_missing": (
            vix_now is None
            or (vix_q40 is not None and vix_now < vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND)
            or (vix_q40 is None and vix_now < 20.0)
        ),
        "rsi_below_long_max": rsi < parameters.MULTI_FACTOR_LONG_RSI_MAX,
        "funding_not_hot": not _funding_hot(macro),
    }


# ── omnibus (6번째 알고) 내부 헬퍼 ──────────────────────────────────────────

_OMNIBUS_UP_TREND = "UP_TREND"
_OMNIBUS_RANGE = "RANGE"
_OMNIBUS_DOWN_TREND = "DOWN_TREND"
_OMNIBUS_RISK_OFF = "RISK_OFF"
_OMNIBUS_TRANSITION = "TRANSITION"

_OMNIBUS_STRUCTURAL_DOWN = "STRUCTURAL_DOWN"
_OMNIBUS_PANIC_DROP = "PANIC_DROP"
_OMNIBUS_OVERSOLD_REBOUND = "OVERSOLD_REBOUND"

_OMNIBUS_RANGE_NEAR_LOW = "NEAR_LOW"
_OMNIBUS_RANGE_NEAR_HIGH = "NEAR_HIGH"
_OMNIBUS_RANGE_MIDDLE = "MIDDLE"


def _omnibus_regime(macro: dict, ind: dict) -> str:
    """UP_TREND / RANGE / DOWN_TREND / RISK_OFF / TRANSITION 5-state 분류.

    1순위: 로컬 4H arena_regime_state (strict_v1 레짐, 가장 신뢰할 수 있을 때 사용).
    2순위: arena_regime_state='unknown'(레짐 불명)이면 4H 지표 2of3 relaxed로 직접 계산.
           매크로 파이프라인(1일 1회 갱신)에 의존하지 않는 완전 자율 레짐 분류.

    중요: bear_trend는 _RISK_OFF_REGIMES에 포함되어 있지만 omnibus에서는
    DOWN_TREND로 처리한다 (OVERSOLD_REBOUND 허용이 omnibus의 존재 이유).
    RISK_OFF로 막는 것은 stress + BearPanic만.
    """
    local = macro.get("arena_regime_state", regime.REGIME_UNKNOWN)

    # stress는 즉시 RISK_OFF (급락 진행 중 — 아무 전략도 없음)
    if local == regime.REGIME_STRESS:
        return _OMNIBUS_RISK_OFF
    # 명확한 로컬 레짐이 있으면 직접 매핑
    if local == regime.REGIME_BULL_TREND:
        return _OMNIBUS_UP_TREND
    if local == regime.REGIME_BEAR_TREND:
        return _OMNIBUS_DOWN_TREND
    if local == regime.REGIME_SIDEWAYS:
        return _OMNIBUS_RANGE

    # 로컬 레짐 unknown → BearPanic 매크로 체크 후 4H 지표 2of3 직접 계산
    overlay = macro.get("regime_state")
    if overlay == "BearPanic":
        return _OMNIBUS_RISK_OFF

    # 2of3 투표: return_24h, return_72h, EMA 정렬
    return_24h = ind.get("return_24h", 0.0)
    return_72h = ind.get("return_72h", 0.0)
    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 1.0)
    bull_votes = sum([return_24h > 0, return_72h > 0, ema_fast > ema_slow])
    bear_votes = sum([return_24h < 0, return_72h < 0, ema_fast < ema_slow])

    if bull_votes >= 2 and bull_votes > bear_votes:
        return _OMNIBUS_UP_TREND
    if bear_votes >= 2 and bear_votes > bull_votes:
        return _OMNIBUS_DOWN_TREND

    # sideways 체크 (bb_width 좁음 + 소폭 등락)
    bb_width = ind.get("bb_width", 0.0)
    atr_pct = max(ind.get("atr_pct", 0.0), 0.0)
    if (
        bb_width <= parameters.REGIME_SIDEWAYS_BB_WIDTH_MAX
        and atr_pct > 0
        and abs(return_24h) <= parameters.REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE * atr_pct
    ):
        return _OMNIBUS_RANGE

    return _OMNIBUS_TRANSITION


def _downtrend_sub_state(ind: dict) -> tuple[str, dict]:
    """DOWN_TREND 세분화: STRUCTURAL_DOWN / PANIC_DROP / OVERSOLD_REBOUND.

    PANIC_DROP: return_24h 절댓값이 ATR의 stress 배수 초과 (급락 진행 중).
    OVERSOLD_REBOUND: 4개 지표 중 3개 이상 충족 (투표 방식 — 4-AND 제거).
      - rsi < OMNIBUS_RSI_REBOUND_MAX (35)
      - bb_pos < OMNIBUS_BB_POS_REBOUND_ENTRY (0.25)
      - macd_hist > macd_hist_prev (MACD 히스토그램 개선 중)
      - return_24h < OMNIBUS_REBOUND_MIN_RETURN_24H (-1.5%)
    STRUCTURAL_DOWN: 위 조건 미충족 (추세적 하락 継続).

    반환: (sub_state, votes_dict) — 진단용 투표 내역 포함.
    """
    rsi = ind.get("rsi", 50.0)
    bb_pos = ind.get("bb_pos", 0.5)
    macd_hist = ind.get("macd_hist", 0.0)
    macd_hist_prev = ind.get("macd_hist_prev", macd_hist)
    atr_pct = ind.get("atr_pct", 0.0)
    return_24h = ind.get("return_24h", 0.0)

    if atr_pct > 0 and abs(return_24h) > parameters.REGIME_STRESS_RETURN_ATR_MULTIPLE * atr_pct:
        return _OMNIBUS_PANIC_DROP, {}

    votes = {
        "rsi_oversold": rsi < parameters.OMNIBUS_RSI_REBOUND_MAX,
        "at_lower_bb": bb_pos < parameters.OMNIBUS_BB_POS_REBOUND_ENTRY,
        "macd_improving": macd_hist > macd_hist_prev,
        "had_drop": return_24h < parameters.OMNIBUS_REBOUND_MIN_RETURN_24H,
    }
    if sum(votes.values()) >= parameters.OMNIBUS_REBOUND_MIN_VOTES:
        return _OMNIBUS_OVERSOLD_REBOUND, votes

    return _OMNIBUS_STRUCTURAL_DOWN, votes


def _range_sub_state(ind: dict) -> str:
    """RANGE 내 위치: NEAR_LOW / NEAR_HIGH / MIDDLE (BB 포지션 기준)."""
    bb_pos = ind.get("bb_pos", 0.5)
    threshold = parameters.OMNIBUS_BB_POS_RANGE_ENTRY
    if bb_pos < threshold:
        return _OMNIBUS_RANGE_NEAR_LOW
    if bb_pos > (1.0 - threshold):
        return _OMNIBUS_RANGE_NEAR_HIGH
    return _OMNIBUS_RANGE_MIDDLE


def omnibus(macro: dict, ind: dict) -> str | None:
    """전천후 단일 라우터 — UP_TREND·RANGE·DOWN_TREND 레짐별 롱 전략 선택.

    레짐별 행동:
      UP_TREND   → 눌림목 롱 (EMA정배열 + RSI 32~55 + bb_pos<0.65 — 고점 추격 방지)
      RANGE      → 박스권 하단 평균회귀 롱 (bb_pos<0.30 + RSI<45 + ADX<25)
      DOWN_TREND → OVERSOLD_REBOUND만 허용 (4지표 중 3개 이상 투표 충족)
      RISK_OFF / TRANSITION → 진입 없음

    포지션 사이즈는 omnibus_position_multiplier()가 제공:
      UP_TREND=1.0, RANGE=0.4, OVERSOLD_REBOUND=0.25
    """
    omni_regime = _omnibus_regime(macro, ind)

    if omni_regime in (_OMNIBUS_RISK_OFF, _OMNIBUS_TRANSITION):
        return None

    ema_fast = ind.get("ema_fast", 0.0)
    ema_slow = ind.get("ema_slow", 0.0)
    rsi = ind.get("rsi", 50.0)
    bb_pos = ind.get("bb_pos", 0.5)

    if omni_regime == _OMNIBUS_UP_TREND:
        ema_aligned = ema_fast > ema_slow
        rsi_pullback = parameters.OMNIBUS_RSI_TREND_MIN < rsi < parameters.OMNIBUS_RSI_TREND_MAX
        bb_not_extended = bb_pos < parameters.OMNIBUS_BB_POS_TREND_MAX
        if (
            ema_aligned
            and rsi_pullback
            and bb_not_extended
            and not _below_ema_trend(ind)
            and not _below_ma200(macro)  # v24: 구조적 하락추세(MA200 하회) 시 역추세 추종 보류
            and not _funding_hot(macro)
            and not _etf_outflow_heavy(macro)
            and not _lsr_crowded(macro)
        ):
            return "long"
        return None

    if omni_regime == _OMNIBUS_RANGE:
        adx = ind.get("adx", 0.0)
        if (
            _range_sub_state(ind) == _OMNIBUS_RANGE_NEAR_LOW
            and rsi < parameters.OMNIBUS_RSI_RANGE_MAX
            and adx < parameters.OMNIBUS_ADX_RANGE_MAX
            and not _funding_hot(macro)
        ):
            return "long"
        return None

    if omni_regime == _OMNIBUS_DOWN_TREND:
        sub_state, _ = _downtrend_sub_state(ind)
        if (
            sub_state == _OMNIBUS_OVERSOLD_REBOUND
            and not _funding_hot(macro)
            and not _etf_outflow_heavy(macro)
        ):
            return "long"
        return None

    return None


def omnibus_position_multiplier(macro: dict, ind: dict) -> float:
    """omnibus 레짐별 포지션 사이즈 배수 (combined_position_weight에 추가 곱함).

    UP_TREND:          1.0 (기본, 변동성 타깃만 적용)
    RANGE:             0.40 (박스권 평균회귀 — 제한적)
    OVERSOLD_REBOUND:  0.25 (반등 소액 — 최대 제한)
    """
    omni_regime = _omnibus_regime(macro, ind)
    if omni_regime == _OMNIBUS_UP_TREND:
        return parameters.OMNIBUS_TREND_SIZE_MULT
    if omni_regime == _OMNIBUS_RANGE:
        return parameters.OMNIBUS_RANGE_SIZE_MULT
    if omni_regime == _OMNIBUS_DOWN_TREND:
        sub_state, _ = _downtrend_sub_state(ind)
        if sub_state == _OMNIBUS_OVERSOLD_REBOUND:
            return parameters.OMNIBUS_REBOUND_SIZE_MULT
    return 1.0


def omnibus_target_price(macro: dict, ind: dict, entry_price: float) -> float | None:
    """WI-7: omnibus 평균회귀 진입의 익절 목표가 (진입 시점 1회 산출·고정).

    RANGE(박스권 하단 매수) → BB 중앙선(bb_mid) 복귀에서 익절 (Bollinger 2002).
    OVERSOLD_REBOUND(과매도 반등) → 진입가 + ATR×OMNIBUS_REBOUND_TARGET_ATR_MULT.
    UP_TREND → None (추세는 트레일링 스톱이 담당, 목표가 미적용).
    플래그 off·데이터 부족 시 None(목표가 청산 비활성 → 기존 flat 청산 경로 유지).

    산출 결과는 signal_reason.omni_target_price에 고정 저장 — 진입 후 레짐/BB가 변해도
    목표가는 진입 시점 스냅샷을 유지(fng_ref_price 패턴). backtest·live 공용.
    """
    if not parameters.OMNIBUS_TARGET_EXIT_ENABLED:
        return None
    omni_regime = _omnibus_regime(macro, ind)
    if omni_regime == _OMNIBUS_RANGE:
        mid = ind.get("bb_mid", 0.0) or 0.0
        return float(mid) if mid > entry_price > 0 else None
    if omni_regime == _OMNIBUS_DOWN_TREND:
        sub_state, _ = _downtrend_sub_state(ind)
        if sub_state == _OMNIBUS_OVERSOLD_REBOUND:
            atr = ind.get("atr", 0.0) or 0.0
            if atr > 0 and entry_price > 0:
                return entry_price + atr * parameters.OMNIBUS_REBOUND_TARGET_ATR_MULT
    return None


def exit_hold_override(algo_id: str, macro: dict, ind: dict) -> bool:
    """raw flat 신호에도 청산을 보류(hold)할지 — 진입≠청산 임계 히스테리시스.

    vix_rsi: 진입 임계(RSI<50·VIX<q40×1.05)가 곧 청산 임계라 진입 직후 경계 진동
    (whipsaw)으로 진입가 부근 손실 청산이 반복됨(라이브 id16 -2.52% 등). 청산은
    RSI≥VIX_RSI_EXIT_RSI_MAX(모멘텀 소진 영역) 또는 VIX≥q40×VIX_EXIT_TOLERANCE_BAND
    (환경 실질 악화)일 때만 실행. risk-off·breadth·stablecoin veto는 히스테리시스에
    양보하지 않고 즉시 청산. 보유 중 하방은 래칫 트레일링 스톱이 계속 방어.
    scheduler(live)·backtest 공용 — 시그널 함수가 stateless라 청산측 분기는 여기서 처리.
    """
    if algo_id == "vix_rsi" and parameters.VIX_RSI_EXIT_HYSTERESIS_ENABLED:
        if _is_risk_off(_regime_state(macro)):
            return False
        if _breadth_collapsed(macro) or _stablecoin_contracting(macro):
            return False
        vix_now = macro.get("vix_now")
        vix_q40 = macro.get("vix_q40")
        rsi = ind.get("rsi", 50.0)
        if vix_now is None:
            return False
        vix_ok = (
            (vix_now < vix_q40 * parameters.VIX_EXIT_TOLERANCE_BAND)
            if vix_q40
            else (vix_now < 22.0)
        )
        return vix_ok and rsi < parameters.VIX_RSI_EXIT_RSI_MAX

    # WI-2: fng_contrarian 청산 히스테리시스 — 진입(FNG<30)≠청산(FNG≥NEUTRAL_MIN) 분리.
    #   반등 초입 조기 flat 청산이 물타기 평단 이점을 버리는 문제. risk-off·breadth·
    #   stablecoin veto는 즉시 청산(양보 없음), 보유 상한은 time_stop(72h)이 보장.
    if algo_id == "fng_contrarian" and parameters.FNG_EXIT_HYSTERESIS_ENABLED:
        if _is_risk_off(_regime_state(macro)):
            return False
        if _breadth_collapsed(macro) or _stablecoin_contracting(macro):
            return False
        fng = macro.get("fng")
        if fng is None:
            return False
        # FNG가 아직 중립 복귀(≥NEUTRAL_MIN)에 못 미치면 flat 청산 보류(회복 대기).
        try:
            return float(fng) < parameters.FNG_EXIT_NEUTRAL_MIN
        except (TypeError, ValueError):
            return False

    # WI-6: macd_momentum 보유 히스테리시스 — 크로스 봉 단발 진입 후, 모멘텀(h>0)이
    #   지속되는 동안 flat 청산 보류. 청산=h≤0(모멘텀 소멸) 또는 risk-off veto.
    if algo_id == "macd_momentum" and parameters.MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED:
        if _is_risk_off(_regime_state(macro)):
            return False
        h = ind.get("macd_hist")
        if h is None:
            return False
        try:
            return float(h) > 0.0
        except (TypeError, ValueError):
            return False

    return False


ALGORITHMS: dict[str, Callable[[dict, dict], str | None]] = {
    "regime_trend": regime_trend,
    "fng_contrarian": fng_contrarian,
    "vix_rsi": vix_rsi,
    "macd_momentum": macd_momentum,
    "multi_factor": multi_factor,
    "omnibus": omnibus,
}


def _diag_base(algo_id: str, raw_signal: str | None, macro: dict) -> dict[str, Any]:
    state = _regime_state(macro)
    return {
        "algo_id": algo_id,
        "raw_signal": raw_signal,
        "effective_regime_state": state,
        "overlay_regime_state": macro.get("regime_state"),
        "vetoes": [],
        "failed_conditions": [],
        "passed_conditions": [],
        "factors": {},
        "thresholds": {},
    }


def _record_condition(
    diag: dict[str, Any],
    name: str,
    passed: bool,
    *,
    veto: bool = False,
) -> None:
    target = "passed_conditions" if passed else "failed_conditions"
    diag[target].append(name)
    if veto and not passed:
        diag["vetoes"].append(name)


def _finish_diag(diag: dict[str, Any]) -> dict[str, Any]:
    diag["veto_count"] = len(diag["vetoes"])
    diag["failed_count"] = len(diag["failed_conditions"])
    diag["factor_score"] = sum(1 for value in diag["factors"].values() if value is True)
    return diag


def explain_signal(algo_id: str, macro: dict, ind: dict) -> dict[str, Any]:
    """Return deterministic signal diagnostics without changing strategy behavior.

    이 함수는 P1 로스터 진단용이다. 전략 함수의 raw signal과 같은 조건식을
    재평가해 `reason.diagnostics.vetoes` 집계를 가능하게 한다.
    """
    try:
        raw_signal = ALGORITHMS[algo_id](macro, ind) if algo_id in ALGORITHMS else None
    except (KeyError, TypeError, ValueError) as exc:
        diag = _diag_base(algo_id, None, macro)
        diag["failed_conditions"].append("diagnostics_input_error")
        diag["diagnostics_error"] = str(exc)
        return _finish_diag(diag)
    diag = _diag_base(algo_id, raw_signal, macro)
    state = _regime_state(macro)

    if algo_id == "regime_trend":
        close = ind.get("close", 0.0)
        dc_upper = ind.get("donchian_upper", 0.0)
        adx = ind.get("adx", 0.0)
        ema_fast = ind.get("ema_fast", 0.0)
        ema_slow = ind.get("ema_slow", 0.0)
        ema_fast_slope = ind.get("ema_fast_slope", 0.0)
        rsi = ind.get("rsi", 50.0)
        diag["thresholds"].update(
            {
                "adx_trend_min": parameters.ADX_TREND_MIN,
                "rsi_long_max": parameters.TREND_CORE_RSI_LONG_MAX,
            }
        )
        _record_condition(diag, "bullish_regime", _is_bullish(state), veto=True)
        _record_condition(
            diag,
            "donchian_breakout",
            bool(dc_upper and dc_upper > 0 and close > dc_upper),
            veto=True,
        )
        _record_condition(diag, "adx_trending", adx >= parameters.ADX_TREND_MIN, veto=True)
        _record_condition(
            diag,
            "ema_aligned_up",
            ema_fast > ema_slow and ema_fast_slope > 0,
            veto=True,
        )
        _record_condition(
            diag,
            "rsi_below_long_max",
            rsi < parameters.TREND_CORE_RSI_LONG_MAX,
            veto=True,
        )
        _record_condition(diag, "funding_not_hot", not _funding_hot(macro), veto=True)
        _record_condition(diag, "etf_outflow_not_heavy", not _etf_outflow_heavy(macro), veto=True)
        _record_condition(
            diag, "above_ema200_4h", not _below_ema_trend_strict(ind, macro), veto=True
        )
        _record_condition(diag, "taker_confirms", _taker_confirms(macro), veto=True)
        _record_condition(diag, "volume_confirms", _volume_confirms(ind), veto=True)
        _record_condition(diag, "lsr_not_crowded", not _lsr_crowded(macro), veto=True)
        _record_condition(diag, "oi_not_diverged", not _oi_diverged(macro), veto=True)
        return _finish_diag(diag)

    if algo_id == "fng_contrarian":
        fng = macro.get("fng")
        diag["thresholds"]["fng_long_below"] = parameters.FNG_LONG_BELOW
        _record_condition(diag, "fng_present", fng is not None, veto=True)
        _record_condition(diag, "not_risk_off", not _is_risk_off(state), veto=True)
        _record_condition(
            diag, "drawdown_sufficient_or_missing", _drawdown_sufficient(macro), veto=True
        )
        _record_condition(diag, "breadth_not_collapsed", not _breadth_collapsed(macro), veto=True)
        _record_condition(
            diag, "stablecoin_not_contracting", not _stablecoin_contracting(macro), veto=True
        )
        _record_condition(
            diag,
            "fng_extreme_fear",
            fng is not None and fng < parameters.FNG_LONG_BELOW,
            veto=True,
        )
        _record_condition(
            diag,
            "momentum_not_worsening",
            _momentum_not_worsening(ind, enabled=parameters.FNG_CONTRARIAN_STABILIZATION_ENABLED),
            veto=True,
        )
        return _finish_diag(diag)

    if algo_id == "vix_rsi":
        vix_now = macro.get("vix_now")
        vix_q40 = macro.get("vix_q40")
        rsi = ind.get("rsi", 50.0)
        vix_calm = False
        if vix_now is not None:
            vix_calm = (
                (vix_now < vix_q40 * parameters.VIX_CALM_TOLERANCE_BAND)
                if vix_q40
                else (vix_now < 20.0)
            )
        diag["thresholds"]["rsi_long_max"] = parameters.VIX_RSI_LONG_MAX
        diag["thresholds"]["vix_calm_tolerance"] = parameters.VIX_CALM_TOLERANCE_BAND
        _record_condition(diag, "vix_present", vix_now is not None, veto=True)
        _record_condition(diag, "not_risk_off", not _is_risk_off(state), veto=True)
        _record_condition(diag, "breadth_not_collapsed", not _breadth_collapsed(macro), veto=True)
        _record_condition(
            diag, "stablecoin_not_contracting", not _stablecoin_contracting(macro), veto=True
        )
        _record_condition(
            diag,
            "momentum_not_worsening",
            _momentum_not_worsening(ind, enabled=parameters.VIX_RSI_STABILIZATION_ENABLED),
            veto=True,
        )
        _record_condition(diag, "vix_calm", vix_calm, veto=True)
        _record_condition(diag, "rsi_below_long_max", rsi < parameters.VIX_RSI_LONG_MAX, veto=True)
        return _finish_diag(diag)

    if algo_id == "macd_momentum":
        h = ind.get("macd_hist", 0.0)
        h_prev = ind.get("macd_hist_prev", h)
        rsi = ind.get("rsi", 50.0)
        bb_w = ind.get("bb_width", 100.0)
        adx = ind.get("adx", 0.0)
        diag["thresholds"].update(
            {
                "bb_width_min": parameters.MACD_MOMENTUM_BB_WIDTH_MIN,
                "rsi_long_max": parameters.MACD_MOMENTUM_RSI_LONG_MAX,
                "adx_min": parameters.MACD_MOMENTUM_ADX_MIN,
            }
        )
        diag["factors"]["macd_hist"] = h
        diag["factors"]["macd_hist_prev"] = h_prev
        _record_condition(
            diag,
            "bb_width_sufficient",
            bb_w >= parameters.MACD_MOMENTUM_BB_WIDTH_MIN,
            veto=True,
        )
        _record_condition(diag, "not_risk_off", not _is_risk_off(state), veto=True)
        _record_condition(diag, "funding_not_hot", not _funding_hot(macro), veto=True)
        _record_condition(diag, "etf_outflow_not_heavy", not _etf_outflow_heavy(macro), veto=True)
        _record_condition(
            diag, "above_ema200_4h", not _below_ema_trend_strict(ind, macro), veto=True
        )
        _record_condition(diag, "lsr_not_crowded", not _lsr_crowded(macro), veto=True)
        _record_condition(diag, "oi_not_diverged", not _oi_diverged(macro), veto=True)
        _record_condition(diag, "macd_hist_positive", h > 0, veto=True)
        _record_condition(diag, "macd_hist_increasing", h > h_prev, veto=True)
        _record_condition(
            diag,
            "rsi_below_long_max",
            rsi < parameters.MACD_MOMENTUM_RSI_LONG_MAX,
            veto=True,
        )
        _record_condition(
            diag, "adx_sufficient", adx >= parameters.MACD_MOMENTUM_ADX_MIN, veto=True
        )
        return _finish_diag(diag)

    if algo_id == "multi_factor":
        diag["thresholds"].update(
            {
                "factor_score_min": 4,
                "fng_max": 60.0,
                "rsi_long_max": parameters.MULTI_FACTOR_LONG_RSI_MAX,
            }
        )
        _record_condition(diag, "not_risk_off", not _is_risk_off(state), veto=True)
        _record_condition(diag, "etf_outflow_not_heavy", not _etf_outflow_heavy(macro), veto=True)
        _record_condition(diag, "lsr_not_crowded", not _lsr_crowded(macro), veto=True)
        _record_condition(diag, "breadth_not_collapsed", not _breadth_collapsed(macro), veto=True)
        _record_condition(
            diag,
            "stablecoin_not_contracting",
            not _stablecoin_contracting(macro),
            veto=True,
        )

        factors = _multi_factor_factors(macro, ind)
        diag["factors"] = factors
        if parameters.MULTI_FACTOR_REGIME_REQUIRED:
            state_mf = _regime_state(macro)
            direction_ok = _is_bullish(state_mf) or (
                parameters.MULTI_FACTOR_ALLOW_SIDEWAYS and state_mf == regime.REGIME_SIDEWAYS
            )
            other_votes = sum(v for k, v in factors.items() if k != "bullish_regime")
            diag["thresholds"]["min_votes_ex_regime"] = parameters.MULTI_FACTOR_MIN_VOTES_EX_REGIME
            _record_condition(diag, "direction_regime_ok", direction_ok, veto=True)
            _record_condition(
                diag,
                "other_votes_sufficient",
                other_votes >= parameters.MULTI_FACTOR_MIN_VOTES_EX_REGIME,
                veto=True,
            )
        else:
            _record_condition(
                diag,
                "factor_score_at_least_4",
                sum(1 for value in factors.values() if value) >= 4,
                veto=True,
            )
        return _finish_diag(diag)

    if algo_id == "omnibus":
        omni_regime = _omnibus_regime(macro, ind)
        if omni_regime == _OMNIBUS_DOWN_TREND:
            sub_state, rebound_votes = _downtrend_sub_state(ind)
        else:
            sub_state, rebound_votes = "N/A", {}
        range_pos = _range_sub_state(ind) if omni_regime == _OMNIBUS_RANGE else "N/A"
        ema_fast = ind.get("ema_fast", 0.0)
        ema_slow = ind.get("ema_slow", 0.0)
        rsi = ind.get("rsi", 50.0)
        bb_pos = ind.get("bb_pos", 0.5)
        adx = ind.get("adx", 0.0)
        diag["thresholds"].update(
            {
                "rsi_trend_min": parameters.OMNIBUS_RSI_TREND_MIN,
                "rsi_trend_max": parameters.OMNIBUS_RSI_TREND_MAX,
                "bb_pos_trend_max": parameters.OMNIBUS_BB_POS_TREND_MAX,
                "rsi_range_max": parameters.OMNIBUS_RSI_RANGE_MAX,
                "rsi_rebound_max": parameters.OMNIBUS_RSI_REBOUND_MAX,
                "bb_pos_range_entry": parameters.OMNIBUS_BB_POS_RANGE_ENTRY,
                "adx_range_max": parameters.OMNIBUS_ADX_RANGE_MAX,
                "rebound_min_votes": parameters.OMNIBUS_REBOUND_MIN_VOTES,
            }
        )
        diag["factors"]["omni_regime"] = omni_regime
        diag["factors"]["downtrend_sub_state"] = sub_state
        diag["factors"]["range_sub_state"] = range_pos
        if rebound_votes:
            diag["factors"]["rebound_votes"] = rebound_votes
            diag["factors"]["rebound_vote_count"] = sum(rebound_votes.values())
        _record_condition(diag, "regime_not_risk_off", omni_regime != _OMNIBUS_RISK_OFF, veto=True)
        _record_condition(
            diag, "regime_not_transition", omni_regime != _OMNIBUS_TRANSITION, veto=True
        )
        if omni_regime == _OMNIBUS_UP_TREND:
            rsi_pullback = parameters.OMNIBUS_RSI_TREND_MIN < rsi < parameters.OMNIBUS_RSI_TREND_MAX
            _record_condition(diag, "ema_aligned", ema_fast > ema_slow, veto=True)
            _record_condition(diag, "rsi_pullback_range", rsi_pullback, veto=True)
            _record_condition(
                diag, "bb_not_extended", bb_pos < parameters.OMNIBUS_BB_POS_TREND_MAX, veto=True
            )
            _record_condition(diag, "above_ema200_4h", not _below_ema_trend(ind), veto=True)
            _record_condition(diag, "funding_not_hot", not _funding_hot(macro), veto=True)
            _record_condition(
                diag, "etf_outflow_not_heavy", not _etf_outflow_heavy(macro), veto=True
            )
            _record_condition(diag, "lsr_not_crowded", not _lsr_crowded(macro), veto=True)
        elif omni_regime == _OMNIBUS_RANGE:
            _record_condition(
                diag, "range_near_low", range_pos == _OMNIBUS_RANGE_NEAR_LOW, veto=True
            )
            _record_condition(
                diag, "rsi_below_range_max", rsi < parameters.OMNIBUS_RSI_RANGE_MAX, veto=True
            )
            _record_condition(
                diag, "adx_low_range", adx < parameters.OMNIBUS_ADX_RANGE_MAX, veto=True
            )
            _record_condition(diag, "funding_not_hot", not _funding_hot(macro), veto=True)
        elif omni_regime == _OMNIBUS_DOWN_TREND:
            vote_count = sum(rebound_votes.values()) if rebound_votes else 0
            _record_condition(
                diag,
                f"oversold_rebound_{vote_count}of{len(rebound_votes) or 4}votes",
                sub_state == _OMNIBUS_OVERSOLD_REBOUND,
                veto=True,
            )
            _record_condition(diag, "funding_not_hot", not _funding_hot(macro), veto=True)
            _record_condition(
                diag, "etf_outflow_not_heavy", not _etf_outflow_heavy(macro), veto=True
            )
        return _finish_diag(diag)

    diag["failed_conditions"].append("unknown_algo")
    return _finish_diag(diag)


def primary_flat_skip_reason(algo_id: str, macro: dict, ind: dict) -> str | None:
    diagnostic = explain_signal(algo_id, macro, ind)
    if diagnostic.get("raw_signal") is not None:
        return None
    vetoes = diagnostic.get("vetoes") or []
    if vetoes:
        return f"veto:{vetoes[0]}"
    failed = diagnostic.get("failed_conditions") or []
    if failed:
        return f"condition:{failed[0]}"
    return "flat_no_signal"
