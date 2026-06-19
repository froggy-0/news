"""Shadow sleeve contracts for Arena vNext research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import algorithms, execution_rules, parameters, regime


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


SleeveBuilder = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    tuple[SleeveSignal, regime.RegimeDecision],
]


def _signed_weight(direction: str | None, weight: float) -> float:
    if direction is None:
        return 0.0
    return execution_rules.direction_sign(direction) * weight


def trend_core_sleeve(
    indicators: dict[str, Any],
    market_features: dict[str, Any],
    macro: dict[str, Any],
) -> tuple[SleeveSignal, regime.RegimeDecision]:
    regime_decision = regime.classify_regime(indicators, market_features, macro)
    enriched_macro = dict(macro)
    enriched_macro["arena_regime_state"] = regime_decision.regime_state
    direction = algorithms.trend_core_v1(enriched_macro, indicators)
    confidence = regime_decision.confidence if direction else 0.0
    raw_score = confidence * (1.0 if direction == "long" else -1.0 if direction == "short" else 0.0)
    target_weight = _signed_weight(direction, parameters.ALLOCATOR_BUDGET_TREND_CORE)
    signal = SleeveSignal(
        sleeve_id="trend_core",
        algo_id="trend_core_v1",
        direction=direction,
        confidence=confidence,
        raw_score=raw_score,
        target_weight=target_weight,
        reason={
            "strategy": "trend_core_v1",
            "regime": regime_decision.regime_state,
            "regime_reason": regime_decision.reason,
        },
        feature_snapshot={
            "indicators": dict(indicators),
            "market_features": dict(market_features),
            "regime": regime_decision.as_dict(),
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
) -> list[tuple[SleeveSignal, regime.RegimeDecision]]:
    return [builder(indicators, market_features, macro) for builder in SHADOW_SLEEVES.values()]
