"""Shadow sleeve contracts for Arena vNext research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import algorithms, execution_rules, frequency, parameters, regime


@dataclass(frozen=True)
class SleeveSignal:
    sleeve_id: str
    algo_id: str
    direction: str | None
    confidence: float
    raw_score: float
    target_weight: float
    reason: dict[str, Any]
    feature_snapshot: dict[str, Any]

    @property
    def signal(self) -> str | None:
        return self.direction

    def as_dict(self) -> dict[str, Any]:
        return {
            "sleeve_id": self.sleeve_id,
            "algo_id": self.algo_id,
            "direction": self.direction,
            "confidence": self.confidence,
            "raw_score": self.raw_score,
            "target_weight": self.target_weight,
            "reason": self.reason,
            "feature_snapshot": self.feature_snapshot,
        }


@dataclass(frozen=True)
class AllocationDecision:
    allowed: bool
    target_weight: float
    risk_budget: float
    reason: dict[str, Any]
    regime_snapshot: dict[str, Any]
    risk_snapshot: dict[str, Any]

    @property
    def action(self) -> str:
        if not self.allowed:
            return "shadow_blocked"
        if self.target_weight == 0:
            return "shadow_flat"
        return "shadow_open"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "target_weight": self.target_weight,
            "risk_budget": self.risk_budget,
            "reason": self.reason,
            "regime_snapshot": self.regime_snapshot,
            "risk_snapshot": self.risk_snapshot,
            "action": self.action,
        }


SleeveBuilder = Callable[..., tuple[SleeveSignal, regime.RegimeDecision]]


def _signed_weight(direction: str | None, weight: float) -> float:
    if direction is None:
        return 0.0
    return execution_rules.direction_sign(direction) * weight


def _cost_aware_threshold(
    indicators: dict[str, Any],
    profile: frequency.FrequencyProfile,
    cost_scenario: frequency.CostScenario,
) -> dict[str, Any]:
    atr_threshold = (
        float(indicators.get("atr") or 0.0) * parameters.TREND_CORE_MACD_ATR_THRESHOLD_MULTIPLE
    )
    close = float(indicators.get("close") or 0.0)
    cost_threshold = close * cost_scenario.all_in_round_trip_cost_pct * profile.ecr_threshold
    required_edge = max(atr_threshold, cost_threshold)
    observed_edge = abs(float(indicators.get("macd_hist") or 0.0))
    return {
        "rule": "cost_aware_edge_filter_v1",
        "observed_edge": observed_edge,
        "required_edge": required_edge,
        "atr_threshold": atr_threshold,
        "cost_threshold": cost_threshold,
        "all_in_round_trip_cost_pct": cost_scenario.all_in_round_trip_cost_pct,
        "ecr_threshold": profile.ecr_threshold,
        "passed": observed_edge >= required_edge,
    }


def trend_core_sleeve(
    indicators: dict[str, Any],
    market_features: dict[str, Any],
    macro: dict[str, Any],
    *,
    profile: frequency.FrequencyProfile | None = None,
    cost_scenario: frequency.CostScenario | None = None,
) -> tuple[SleeveSignal, regime.RegimeDecision]:
    profile = profile or frequency.get_frequency_profile()
    cost_scenario = cost_scenario or frequency.get_cost_scenario(profile.frequency_profile_id)
    regime_decision = regime.classify_regime(indicators, market_features, macro)
    enriched_macro = dict(macro)
    enriched_macro["arena_regime_state"] = regime_decision.regime_state
    direction = algorithms.regime_trend(enriched_macro, indicators)
    cost_filter = _cost_aware_threshold(indicators, profile, cost_scenario)
    blocked_reason: str | None = None
    if direction and not cost_filter["passed"]:
        blocked_reason = "cost_aware_edge_below_threshold"
        direction = None
    confidence = regime_decision.confidence if direction else 0.0
    raw_score = confidence * (1.0 if direction == "long" else -1.0 if direction == "short" else 0.0)
    target_weight = _signed_weight(direction, parameters.ALLOCATOR_BUDGET_TREND_CORE)
    signal = SleeveSignal(
        sleeve_id="trend_core",
        algo_id="regime_trend",
        direction=direction,
        confidence=confidence,
        raw_score=raw_score,
        target_weight=target_weight,
        reason={
            "strategy": "regime_trend",
            "regime": regime_decision.regime_state,
            "regime_reason": regime_decision.reason,
            "cost_filter": cost_filter,
            "blocked_reason": blocked_reason,
        },
        feature_snapshot={
            "indicators": dict(indicators),
            "market_features": dict(market_features),
            "regime": regime_decision.as_dict(),
            "frequency_profile": profile.as_dict(),
            "cost_scenario": cost_scenario.as_dict(),
        },
    )
    return signal, regime_decision


SHADOW_SLEEVES: dict[str, SleeveBuilder] = {
    "trend_core": trend_core_sleeve,
}


def evaluate_shadow_sleeves(
    indicators: dict[str, Any],
    market_features: dict[str, Any],
    macro: dict[str, Any],
    *,
    profile: frequency.FrequencyProfile | None = None,
    cost_scenario: frequency.CostScenario | None = None,
) -> list[tuple[SleeveSignal, regime.RegimeDecision]]:
    return [
        builder(
            indicators,
            market_features,
            macro,
            profile=profile,
            cost_scenario=cost_scenario,
        )
        for builder in SHADOW_SLEEVES.values()
    ]
