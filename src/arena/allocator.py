"""Shadow allocator for Arena vNext sleeves."""

from __future__ import annotations

from typing import Any

from . import parameters
from .sleeves import AllocationDecision, SleeveSignal

SLEEVE_BUDGETS: dict[str, float] = {
    "trend_core": parameters.ALLOCATOR_BUDGET_TREND_CORE,
    "legacy_rule": parameters.ALLOCATOR_BUDGET_LEGACY_RULE,
    "carry": parameters.ALLOCATOR_BUDGET_CARRY,
}


def allocate_shadow(
    signal: SleeveSignal,
    *,
    regime_snapshot: dict[str, Any],
    risk_snapshot: dict[str, Any] | None = None,
) -> AllocationDecision:
    budget = SLEEVE_BUDGETS.get(signal.sleeve_id, 0.0)
    if budget <= 0:
        return AllocationDecision(
            allowed=False,
            target_weight=0.0,
            risk_budget=budget,
            reason={"rule": "sleeve_budget_zero", "sleeve_id": signal.sleeve_id},
            regime_snapshot=regime_snapshot,
            risk_snapshot=risk_snapshot or {},
        )
    if signal.direction is None or signal.target_weight == 0:
        return AllocationDecision(
            allowed=True,
            target_weight=0.0,
            risk_budget=budget,
            reason={"rule": "flat_signal"},
            regime_snapshot=regime_snapshot,
            risk_snapshot=risk_snapshot or {},
        )

    capped_weight = max(-budget, min(budget, signal.target_weight))
    return AllocationDecision(
        allowed=True,
        target_weight=capped_weight,
        risk_budget=budget,
        reason={
            "rule": "budget_capped_allocation",
            "requested_weight": signal.target_weight,
            "allocated_weight": capped_weight,
        },
        regime_snapshot=regime_snapshot,
        risk_snapshot=risk_snapshot or {},
    )
