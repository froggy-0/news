"""risk_overlay.py — 3계층 Risk Overlay Score 산출.

Layer 1 (항상): RegimeState  — 현재 시장 구조 분류
Layer 2 (항상): VolEnvironment — 변동성 레벨 + 방향
Layer 3 (조건부): SignalConfidence — 신호 신뢰도 (HIGH/MEDIUM/None)

외부에서 사용하는 진입점: compute_risk_overlay(df, overlay_gate_decision)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
_VIX_WINDOW = 90
_VIX_QUANTILE_HIGH = 0.80  # BearPanic 판단 기준
_VIX_QUANTILE_MID = 0.40  # vol_regime_v2와 동일
_VIX_MIN_PERIODS = 30

_RV_WINDOW = 45
_RV_QUANTILE = 0.45
_RV_MIN_PERIODS = 20

_FUNDING_HEAT_THRESHOLD = 1.5  # zscore
_FUNDING_EXTREME_THRESHOLD = 2.5

_FNG_FEAR = 30
_FNG_GREED = 70
_FNG_EXTREME_FEAR = 20
_FNG_EXTREME_GREED = 80

_SHORT_VOL_WINDOW = 7
_LONG_VOL_WINDOW = 20


# ---------------------------------------------------------------------------
# Layer 1: RegimeState
# ---------------------------------------------------------------------------
_REGIME_LABELS = {
    "BullHeated": "과열 상승 — 신호 신뢰도 낮음",
    "BullQuiet": "안정 상승 — 신호 우호적",
    "BearPanic": "공포 하락 — 역발산 가능",
    "Choppy": "방향 불명 — 관망 권고",
    "Transitional": "전환 구간 — 신중 접근",
}


@dataclass
class RegimeState:
    label: str  # BullHeated / BullQuiet / BearPanic / Choppy / Transitional
    description: str
    raw: dict[str, Any] = field(default_factory=dict)


def _last_valid(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _last_rolling_zscore(
    series: pd.Series,
    window: int = 30,
    min_periods: int = 15,
) -> float | None:
    """직전 window 기준 롤링 z-score의 마지막 값.

    누수 방지: 호출 측에서 lag1(전일) 시리즈를 넘겨야 한다.
    표준편차 0 또는 데이터 부족 시 None.
    """
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() < min_periods:
        return None
    roll_mean = s.rolling(window, min_periods=min_periods).mean()
    roll_std = s.rolling(window, min_periods=min_periods).std()
    z = (s - roll_mean) / roll_std.replace(0.0, np.nan)
    return _last_valid(z)


def _read_precomputed_or_fallback(
    df: pd.DataFrame,
    precomputed_col: str,
    series: pd.Series,
    window: int,
    min_periods: int,
    quantile: float,
) -> float | None:
    """join.py 사전 계산 컬럼이 있으면 마지막 행을 읽고, 없으면 .tail() fallback.

    사전 계산 컬럼(join.py _add_regime_quantile_features)을 우선 사용하면
    compute_regime_state()가 어떤 df 슬라이스로 호출되든 동일한 결과를 보장한다.
    """
    if precomputed_col in df.columns:
        val = pd.to_numeric(df[precomputed_col], errors="coerce").iloc[-1]
        return float(val) if pd.notna(val) else None
    clean = series.dropna()
    if len(clean) < min_periods:
        return None
    return float(clean.tail(window).quantile(quantile))


def _fng_streak_below(series: pd.Series, threshold: float) -> int | None:
    """시계열 끝에서 역방향으로 threshold 미만이 연속된 일수(P3, arena fng_contrarian용).

    공포 1일차(뉴스 쇼크, 추가 하락 여지)와 N일 지속(매도 소진)의 평균회귀 품질이
    다르다는 근거(Kaminski·Lo)에 기반한 진입 품질 피처. lag 불요 — FNG는 발표 즉시
    가용하므로 기존 `fng` 필드와 동일 취급(당일 값 포함해도 누수 아님). 마지막 값이
    임계 이상이면 0. 결측일은 스트릭 중단(보수적 — 결측을 "공포 아님"으로 취급).
    """
    s = pd.to_numeric(series, errors="coerce")
    if s.empty:
        return None
    streak = 0
    for val in reversed(s.tolist()):
        if pd.isna(val) or val >= threshold:
            break
        streak += 1
    return streak


def _compute_sjm_state(df: pd.DataFrame) -> str | None:
    """SJM(통계적 점프모델) 2상태 레짐 분류 — 섀도우 전용 (알고 게이트 미적용).

    JumpModel(n=2, penalty=15)로 bull/bear 구분. 평균 수익률 기준으로 상태 라벨 결정.
    jumpmodels 미설치 또는 데이터 부족 시 None → 알고는 graceful 처리(veto 없음).
    30일 관찰 후 rule-based 레짐 대비 비교로 승격 여부 결정.
    """
    try:
        from jumpmodels.jump import JumpModel  # noqa: PLC0415
        from sklearn.preprocessing import StandardScaler  # noqa: PLC0415
    except ImportError:
        return None

    try:
        feats = ["btc_log_return", "btc_realized_vol_20d_lag1"]
        if any(f not in df.columns for f in feats):
            return None
        X = df[feats].copy().apply(pd.to_numeric, errors="coerce").dropna()
        if len(X) < 60:
            return None

        X_scaled = StandardScaler().fit_transform(X)
        jm = JumpModel(n_components=2, jump_penalty=15.0, random_state=42)
        jm.fit(X_scaled)
        states = jm.predict(X_scaled)

        ret_vals = X["btc_log_return"].values
        mean_ret_0 = ret_vals[states == 0].mean() if (states == 0).any() else 0.0
        mean_ret_1 = ret_vals[states == 1].mean() if (states == 1).any() else 0.0
        bull_state = 0 if mean_ret_0 >= mean_ret_1 else 1
        return "sjm_bull" if int(states[-1]) == bull_state else "sjm_bear"
    except Exception as exc:
        logger.debug("SJM 계산 실패 (무시): %s", exc)
        return None


def compute_regime_state(df: pd.DataFrame) -> RegimeState:
    """최신 행의 피처를 기반으로 현재 시장 regime을 분류.

    롤링 분위수는 join.py의 _add_regime_quantile_features()가 사전 계산한
    vix_q40_90d / vix_q80_90d / rv_q45_45d / fng_q70_90d 컬럼을 우선 사용한다.
    컬럼이 없는 환경(테스트, 단독 호출)에서는 .tail() 기반 fallback으로 계산한다.
    """
    vix_col = "vix_lag1" if "vix_lag1" in df.columns else "vix"
    vix_series = pd.to_numeric(df.get(vix_col, pd.Series(dtype=float)), errors="coerce")
    vix_now = _last_valid(vix_series)

    rv_series = pd.to_numeric(
        df.get("btc_realized_vol_20d_lag1", pd.Series(dtype=float)), errors="coerce"
    )
    rv_now = _last_valid(rv_series)

    funding_z = _last_valid(df.get("funding_rate_zscore_30d", pd.Series(dtype=float)))
    fng = _last_valid(df.get("fng_value", pd.Series(dtype=float)))
    oi_div = _last_valid(df.get("oi_price_divergence_flag_7d", pd.Series(dtype=float)))

    # 기관 ETF 순유입 z-score — 누수 방지를 위해 lag1(전일) 시리즈 사용.
    # 양수 = 기관 매수 우위(risk-on), 큰 음수 = 기관 유출(risk-off).
    etf_flow_col = (
        "etf_net_inflow_usd_lag1"
        if "etf_net_inflow_usd_lag1" in df.columns
        else "etf_net_inflow_usd"
    )
    etf_flow_z = _last_rolling_zscore(df.get(etf_flow_col, pd.Series(dtype=float)))

    # --- arena 알고리즘 보강용 일간 피처 (모두 lag1/backward-looking, 누수 방지) ---
    # 체결 공격성: 테이커 매수 우위 z-score. 양수 = 공격적 매수 우위(돌파 동의),
    # 음수 = 공격적 매도 우위. regime_trend 돌파의 주문흐름 확인에 사용.
    taker_imb_z = _last_valid(df.get("btc_taker_imbalance_zscore_30d_lag1", pd.Series(dtype=float)))
    # 선물 롱숏 포지셔닝: lag1 원시값에서 롤링 z. 큰 양수 = 롱 군중 과밀(contrarian veto).
    lsr_col = (
        "btc_long_short_ratio_lag1"
        if "btc_long_short_ratio_lag1" in df.columns
        else "btc_long_short_ratio"
    )
    lsr_z = _last_rolling_zscore(df.get(lsr_col, pd.Series(dtype=float)))
    # 200일 이동평균 상회 여부(0/1) — 구조적 강세장 게이트(Faber 2007, TSMOM).
    above_ma200_col = (
        "btc_above_ma200_lag1" if "btc_above_ma200_lag1" in df.columns else "btc_above_ma200"
    )
    above_ma200 = _last_valid(df.get(above_ma200_col, pd.Series(dtype=float)))
    # 90일 고점 대비 낙폭(<=0, 0=신고가) — 역발산 품질·리스크 사이징 컨텍스트.
    drawdown_90d = _last_valid(df.get("btc_drawdown_90d", pd.Series(dtype=float)))
    # 시장 폭: Binance top10 알트 중 7일 수익률 양(+) 비율(0~1) — 광범위 참여 확인.
    breadth_up_ratio = _last_valid(df.get("binance_top10_up_ratio_7d_lag1", pd.Series(dtype=float)))
    # 스테이블코인(USDT+USDC) 7일 공급 증가율의 롤링 z — 큰 음수 = 유동성 수축(롱 보류).
    # 근거: 공급 증가 = 대기 매수력(deployable capital), 수축 = 자본 이탈.
    stablecoin_supply_z = _last_rolling_zscore(
        df.get("usdt_usdc_supply_change_7d_lag1", pd.Series(dtype=float))
    )

    # 롤링 분위수: 사전 계산 컬럼 우선, 없으면 .tail() fallback
    vix_q_high = _read_precomputed_or_fallback(
        df, "vix_q80_90d", vix_series, _VIX_WINDOW, _VIX_MIN_PERIODS, _VIX_QUANTILE_HIGH
    )
    vix_q_mid = _read_precomputed_or_fallback(
        df, "vix_q40_90d", vix_series, _VIX_WINDOW, _VIX_MIN_PERIODS, _VIX_QUANTILE_MID
    )
    rv_q = _read_precomputed_or_fallback(
        df, "rv_q45_45d", rv_series, _RV_WINDOW, _RV_MIN_PERIODS, _RV_QUANTILE
    )

    # FNG rolling q70: SignalConfidence 레이어에서 greed_block 판단에 사용
    # BullQuiet 경계 조건에는 사용하지 않는다.
    # 이유: rolling q70은 공포장 지속 시 16 수준까지 하락해 BullQuiet을 오차단함
    fng_q70 = _read_precomputed_or_fallback(
        df,
        "fng_q70_90d",
        pd.to_numeric(df.get("fng_value", pd.Series(dtype=float)), errors="coerce"),
        90,
        30,
        0.70,
    )

    raw = {
        "vix_now": vix_now,
        "vix_q80": vix_q_high,
        "vix_q40": vix_q_mid,
        "rv_now": rv_now,
        "rv_q45": rv_q,
        "funding_zscore": funding_z,
        "fng": fng,
        "fng_q70": fng_q70,
        "oi_divergence_flag": oi_div,
        "etf_flow_zscore": etf_flow_z,
        # arena 알고리즘 보강용 일간 피처 (graceful: 미수집 시 None)
        "taker_imbalance_zscore": taker_imb_z,
        "long_short_ratio_zscore": lsr_z,
        "btc_above_ma200": above_ma200,
        "btc_drawdown_90d": drawdown_90d,
        "breadth_up_ratio": breadth_up_ratio,
        "stablecoin_supply_zscore": stablecoin_supply_z,
        # P3(2026-07-21): fng<30 연속일수 — arena fng_contrarian 진입 품질 피처(공포 1일차 vs
        # N일 지속 매도소진 구분). lag 불요, fng와 동일 컬럼에서 파생.
        "fng_days_below_30": _fng_streak_below(df.get("fng_value", pd.Series(dtype=float)), 30.0),
        # SJM 섀도우: 통계적 점프모델 2상태 레짐 (알고 게이트 미적용, 30일 관찰용)
        "sjm_state": _compute_sjm_state(df),
    }

    # --- 분류 로직 ---

    # BearPanic: VIX 고점 + 극단 공포
    vix_elevated = vix_now is not None and vix_q_high is not None and vix_now >= vix_q_high
    extreme_fear = fng is not None and fng <= _FNG_EXTREME_FEAR
    if vix_elevated and extreme_fear:
        return RegimeState("BearPanic", _REGIME_LABELS["BearPanic"], raw)

    # BullHeated: funding 과열 AND (극단 탐욕 OR OI 과열)
    funding_hot = funding_z is not None and funding_z >= _FUNDING_HEAT_THRESHOLD
    extreme_greed = fng is not None and fng >= _FNG_EXTREME_GREED
    oi_diverged = oi_div is not None and oi_div > 0
    if funding_hot and (extreme_greed or oi_diverged):
        return RegimeState("BullHeated", _REGIME_LABELS["BullHeated"], raw)

    # BullQuiet: vol_regime_v2 조건 (VIX < q40 AND rv < q45) + fng 중립
    # FNG 경계는 기존 고정값(20~80) 유지 — rolling q70 적응형은 BullQuiet 오차단을 유발함
    vix_low = vix_now is not None and vix_q_mid is not None and vix_now < vix_q_mid
    rv_low = rv_now is not None and rv_q is not None and rv_now < rv_q
    fng_neutral = fng is not None and _FNG_EXTREME_FEAR < fng < _FNG_EXTREME_GREED
    if vix_low and rv_low and fng_neutral:
        return RegimeState("BullQuiet", _REGIME_LABELS["BullQuiet"], raw)

    # Transitional: 방향성은 있지만 조건이 섞인 경우
    has_direction = vix_now is not None and vix_q_mid is not None
    if (
        has_direction
        and not (funding_hot and extreme_greed)
        and not (vix_elevated and extreme_fear)
    ):
        return RegimeState("Transitional", _REGIME_LABELS["Transitional"], raw)

    return RegimeState("Choppy", _REGIME_LABELS["Choppy"], raw)


# ---------------------------------------------------------------------------
# Layer 2: VolEnvironment
# ---------------------------------------------------------------------------
_VOL_LEVEL_LABELS = {
    "High": "변동성 높음",
    "Mid": "변동성 보통",
    "Low": "변동성 낮음",
}


@dataclass
class VolEnvironment:
    level: str  # High / Mid / Low
    trend: str  # rising / falling / stable
    description: str
    rv_now: float | None = None
    rv_short: float | None = None


def compute_vol_environment(df: pd.DataFrame) -> VolEnvironment:
    """단기(7일) vs 중기(20일) realized vol 비교로 레벨 + 방향 산출."""

    rv_series = pd.to_numeric(
        df.get("btc_realized_vol_20d_lag1", pd.Series(dtype=float)), errors="coerce"
    ).dropna()

    if rv_series.empty:
        return VolEnvironment("Mid", "stable", "데이터 부족")

    rv_now = float(rv_series.iloc[-1])

    # 단기 vol (7일 rolling mean of daily returns)
    ret_col = "btc_log_return" if "btc_log_return" in df.columns else None
    rv_short: float | None = None
    if ret_col:
        rets = pd.to_numeric(df[ret_col], errors="coerce").dropna()
        if len(rets) >= _SHORT_VOL_WINDOW:
            rv_short = float(rets.tail(_SHORT_VOL_WINDOW).std() * np.sqrt(365))

    # 롤링 분위수로 레벨 판단
    q33 = float(rv_series.tail(_LONG_VOL_WINDOW * 3).quantile(0.33))
    q67 = float(rv_series.tail(_LONG_VOL_WINDOW * 3).quantile(0.67))

    if rv_now >= q67:
        level = "High"
    elif rv_now <= q33:
        level = "Low"
    else:
        level = "Mid"

    # 방향: 단기 vs 중기 비교
    if rv_short is not None:
        ratio = rv_short / rv_now if rv_now > 0 else 1.0
        if ratio >= 1.15:
            trend = "rising"
        elif ratio <= 0.85:
            trend = "falling"
        else:
            trend = "stable"
    else:
        trend = "stable"

    desc = f"{_VOL_LEVEL_LABELS[level]}, {trend}"
    return VolEnvironment(level, trend, desc, rv_now=rv_now, rv_short=rv_short)


# ---------------------------------------------------------------------------
# Layer 3: SignalConfidence
# ---------------------------------------------------------------------------
_CONFIDENCE_REASONS: dict[str, str] = {
    "vol_regime_v2_promoted": "vol_regime_v2 overlay gate 통과",
    "vol_quiet": "변동성 안정 구간",
    "funding_normal": "자금조달 비율 정상",
    "sentiment_vol_divergence": "변동성 낮은데 감정 공포 — 역발산 구간",
    "fng_greed_block": "탐욕 상위 30% 구간 — 고점 신호",
    "research_rules_agree": "research rules 2/3 동의",
    "regime_unfavorable": "현재 regime에서 신호 신뢰도 낮음",
    "vol_elevated": "변동성 상승 중",
    "funding_overheated": "자금조달 비율 과열",
}


@dataclass
class SignalConfidence:
    level: str | None  # HIGH / MEDIUM / None
    reasons: list[str]  # reason code list
    reason_labels: list[str]  # 사용자 표시용 한국어


def compute_signal_confidence(
    df: pd.DataFrame,
    regime: RegimeState,
    vol: VolEnvironment,
    overlay_gate_decision: str,
) -> SignalConfidence:
    """overlay_gate_decision + 현재 regime을 기반으로 신호 신뢰도 판단.

    Args:
        overlay_gate_decision: "promote" | "research_only"
    """
    reasons: list[str] = []
    negative_reasons: list[str] = []

    # 신호 발화 불가 구간
    if regime.label in ("BullHeated", "Choppy"):
        negative_reasons.append("regime_unfavorable")
        return SignalConfidence(
            None,
            negative_reasons,
            [_CONFIDENCE_REASONS[r] for r in negative_reasons],
        )

    # 긍정 신호 수집
    if overlay_gate_decision == "promote":
        reasons.append("vol_regime_v2_promoted")

    if vol.level == "Low":
        reasons.append("vol_quiet")
    elif vol.level == "High" or vol.trend == "rising":
        negative_reasons.append("vol_elevated")

    raw = regime.raw
    funding_z = raw.get("funding_zscore")
    if funding_z is not None:
        if abs(funding_z) < _FUNDING_HEAT_THRESHOLD:
            reasons.append("funding_normal")
        elif funding_z >= _FUNDING_HEAT_THRESHOLD:
            negative_reasons.append("funding_overheated")

    fng = raw.get("fng")

    if fng is not None:
        if fng >= _FNG_GREED:
            # FNG >= 70 (탐욕 구간): vol_ok여도 BTC 90일 고점 근처일 확률 높음 → 차단
            # 근거: vol_ok + FNG>=70 구간의 97.6%가 BTC 90일 최고점 5% 이내로 확인됨
            # rolling q70을 사용하지 않는 이유: 공포장 지속 시 q70이 16 수준까지 하락해
            # FNG=26(공포) 조차 "탐욕 상위 30%"로 오분류됨 — 절대 임계값이 더 robust
            negative_reasons.append("fng_greed_block")
        elif fng <= _FNG_FEAR and regime.label == "BullQuiet":
            # 변동성 낮은데 감정만 공포인 "감정-변동성 괴리" 상태
            # BullQuiet(vol_ok) 안에서만 의미 있음 — 단독 FNG fear는 대부분 하락장 중임
            reasons.append("sentiment_vol_divergence")

    # 신뢰도 판정
    positive = len(reasons)
    negative = len(negative_reasons)

    if overlay_gate_decision == "promote" and positive >= 2 and negative == 0:
        level = "HIGH"
    elif positive >= 1 and negative <= 1:
        level = "MEDIUM"
    else:
        level = None

    all_reasons = reasons + negative_reasons
    return SignalConfidence(
        level,
        all_reasons,
        [_CONFIDENCE_REASONS[r] for r in all_reasons],
    )


# ---------------------------------------------------------------------------
# 통합 진입점
# ---------------------------------------------------------------------------
def regime_to_direction(regime_label: str) -> str | None:
    """Regime → 신호 방향.

    BullQuiet  → "long"  (안정 상승 — 롱)
    BearPanic  → "long"  (극단 공포 역발산 — contrarian long)
    나머지      → None   (방향 없음 — hit/miss 평가 제외)
    """
    if regime_label in ("BullQuiet", "BearPanic"):
        return "long"
    return None


@dataclass
class RiskOverlay:
    regime: RegimeState
    vol: VolEnvironment
    confidence: SignalConfidence
    overlay_gate_decision: str = "research_only"

    @property
    def direction(self) -> str | None:
        return regime_to_direction(self.regime.label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regimeState": self.regime.label,
            "regimeDescription": self.regime.description,
            "regimeRaw": self.regime.raw,
            "volLevel": self.vol.level,
            "volTrend": self.vol.trend,
            "volDescription": self.vol.description,
            "signalConfidence": self.confidence.level,
            "signalReasons": self.confidence.reasons,
            "signalReasonLabels": self.confidence.reason_labels,
            "overlayGateDecision": self.overlay_gate_decision,
            "direction": self.direction,
        }


def compute_risk_overlay(
    df: pd.DataFrame,
    overlay_gate_decision: str = "research_only",
) -> RiskOverlay:
    """df: sentiment_join parquet의 전체 DataFrame (최신 행이 오늘 기준).

    overlay_gate_decision: latest.json의 alpha.promotionGate.volRegimeV2Overlay.decision
    """
    regime = compute_regime_state(df)
    vol = compute_vol_environment(df)
    confidence = compute_signal_confidence(df, regime, vol, overlay_gate_decision)
    return RiskOverlay(
        regime=regime,
        vol=vol,
        confidence=confidence,
        overlay_gate_decision=overlay_gate_decision,
    )
