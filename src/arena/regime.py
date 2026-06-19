"""Rule-based market regime gate for Arena vNext shadow strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import parameters

REGIME_BULL_TREND = "bull_trend"
REGIME_BEAR_TREND = "bear_trend"
REGIME_SIDEWAYS = "sideways"
REGIME_STRESS = "stress"
REGIME_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeDecision:
    regime_state: str
    confidence: float
    reason: dict[str, Any]
    feature_snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime_state": self.regime_state,
            "confidence": self.confidence,
            "reason": self.reason,
            "feature_snapshot": self.feature_snapshot,
        }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _macro_usable(macro: dict[str, Any]) -> bool:
    stale_hours = macro.get("stale_hours")
    if stale_hours is None:
        return True
    return _float(stale_hours, parameters.MACRO_STALE_HOURS + 1.0) <= parameters.MACRO_STALE_HOURS


def classify_regime(
    indicators: dict[str, Any],
    market_features: dict[str, Any] | None = None,
    macro: dict[str, Any] | None = None,
) -> RegimeDecision:
    market_features = market_features or {}
    macro = macro or {}
    atr_pct = max(_float(indicators.get("atr_pct")), 0.0)
    return_24h = _float(indicators.get("return_24h"))
    return_72h = _float(indicators.get("return_72h"))
    bb_width = _float(indicators.get("bb_width"))
    range_24h_atr = _float(indicators.get("range_24h_atr"))
    ema_fast = _float(indicators.get("ema_fast"))
    ema_slow = _float(indicators.get("ema_slow"))
    ema_fast_slope = _float(indicators.get("ema_fast_slope"))
    funding_24h = market_features.get("funding_rate_24h")
    oi_change_24h = market_features.get("open_interest_change_24h")
    macro_regime = macro.get("regime_state") if _macro_usable(macro) else None

    feature_snapshot = {
        "return_24h": return_24h,
        "return_72h": return_72h,
        "atr_pct": atr_pct,
        "bb_width": bb_width,
        "range_24h_atr": range_24h_atr,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_fast_slope": ema_fast_slope,
        "funding_rate_24h": funding_24h,
        "open_interest_change_24h": oi_change_24h,
        "macro_regime_state": macro_regime,
    }

    if atr_pct <= 0 or ema_fast <= 0 or ema_slow <= 0:
        return RegimeDecision(
            REGIME_UNKNOWN,
            0.0,
            {"rule": "insufficient_core_features"},
            feature_snapshot,
        )

    stress_return = abs(return_24h) > parameters.REGIME_STRESS_RETURN_ATR_MULTIPLE * atr_pct
    stress_range = range_24h_atr > parameters.REGIME_STRESS_RANGE_ATR_MULTIPLE
    if stress_return or stress_range:
        return RegimeDecision(
            REGIME_STRESS,
            0.75,
            {
                "rule": "atr_extreme_move",
                "stress_return": stress_return,
                "stress_range": stress_range,
            },
            feature_snapshot,
        )

    bull = (
        return_24h > 0
        and return_72h > 0
        and bb_width >= parameters.REGIME_TREND_BB_WIDTH_MIN
        and ema_fast > ema_slow
    )
    if bull:
        return RegimeDecision(
            REGIME_BULL_TREND,
            0.7 + (0.1 if ema_fast_slope > 0 else 0.0),
            {"rule": "positive_returns_and_ema_trend"},
            feature_snapshot,
        )

    bear = (
        return_24h < 0
        and return_72h < 0
        and bb_width >= parameters.REGIME_TREND_BB_WIDTH_MIN
        and ema_fast < ema_slow
    )
    if bear:
        return RegimeDecision(
            REGIME_BEAR_TREND,
            0.7 + (0.1 if ema_fast_slope < 0 else 0.0),
            {"rule": "negative_returns_and_ema_trend"},
            feature_snapshot,
        )

    sideways = (
        bb_width <= parameters.REGIME_SIDEWAYS_BB_WIDTH_MAX
        and abs(return_24h) <= parameters.REGIME_SIDEWAYS_RETURN_ATR_MULTIPLE * atr_pct
    )
    if sideways:
        return RegimeDecision(
            REGIME_SIDEWAYS,
            0.6,
            {"rule": "low_band_width_and_small_atr_move"},
            feature_snapshot,
        )

    return RegimeDecision(
        REGIME_UNKNOWN,
        0.3,
        {"rule": "no_rule_matched"},
        feature_snapshot,
    )
