"""risk_overlay.py — 3계층 Risk Overlay Score 산출.

Layer 1 (항상): RegimeState  — 현재 시장 구조 분류
Layer 2 (항상): VolEnvironment — 변동성 레벨 + 방향
Layer 3 (조건부): SignalConfidence — 신호 신뢰도 (HIGH/MEDIUM/None)

외부에서 사용하는 진입점: compute_risk_overlay(df, overlay_gate_decision)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

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


def compute_regime_state(df: pd.DataFrame) -> RegimeState:
    """최신 행의 피처를 기반으로 현재 시장 regime을 분류."""

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

    # 롤링 분위수 계산
    vix_q_high = (
        float(vix_series.dropna().tail(_VIX_WINDOW).quantile(_VIX_QUANTILE_HIGH))
        if vix_series.dropna().__len__() >= _VIX_MIN_PERIODS
        else None
    )
    vix_q_mid = (
        float(vix_series.dropna().tail(_VIX_WINDOW).quantile(_VIX_QUANTILE_MID))
        if vix_series.dropna().__len__() >= _VIX_MIN_PERIODS
        else None
    )
    rv_q = (
        float(rv_series.dropna().tail(_RV_WINDOW).quantile(_RV_QUANTILE))
        if rv_series.dropna().__len__() >= _RV_MIN_PERIODS
        else None
    )

    raw = {
        "vix_now": vix_now,
        "vix_q80": vix_q_high,
        "vix_q40": vix_q_mid,
        "rv_now": rv_now,
        "rv_q45": rv_q,
        "funding_zscore": funding_z,
        "fng": fng,
        "oi_divergence_flag": oi_div,
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
    "fng_contrarian": "공포 구간 — 역발산 가능성",
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
    if fng is not None and fng <= _FNG_FEAR:
        reasons.append("fng_contrarian")

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
@dataclass
class RiskOverlay:
    regime: RegimeState
    vol: VolEnvironment
    confidence: SignalConfidence
    overlay_gate_decision: str = "research_only"

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
