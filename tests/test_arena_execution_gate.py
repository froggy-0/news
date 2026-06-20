from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arena import execution_gate, frequency, risk


def _now() -> datetime:
    return datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)


def test_execution_gate_allows_signal_when_edge_clears_cost_and_quality() -> None:
    cost = frequency.get_cost_scenario("live_4h", "base")
    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 200.0, "atr": 100.0},
        realtime_features={
            "spread_bps_avg": 1.0,
            "expected_slippage_bps": 1.0,
            "depth_score": 1.0,
            "volatility_score": 0.0,
            "api_latency_ms_p95": 100.0,
        },
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=1.0),
    )

    assert decision.allowed is True
    assert decision.decision == "trade_allowed"
    assert decision.reject_reason is None
    json.dumps(decision.as_dict())


def test_execution_gate_blocks_when_cost_floor_is_not_cleared() -> None:
    cost = frequency.get_cost_scenario("research_1h", "base")
    decision = execution_gate.evaluate_execution_gate(
        algo_id="trend_core_v1",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1.0, "atr": 1.0},
        realtime_features={"spread_bps_avg": 1.0, "expected_slippage_bps": 1.0},
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
    )

    assert decision.allowed is False
    assert decision.reject_reason == "expected_return_below_cost_floor"


@pytest.mark.parametrize(
    ("features", "reject_reason"),
    [
        ({"spread_bps_avg": 99.0}, "spread_too_wide"),
        ({"expected_slippage_bps": 99.0}, "slippage_too_high"),
        ({"depth_score": 0.1}, "depth_too_thin"),
        ({"volatility_score": 2.0}, "volatility_spike"),
        ({"api_latency_ms_p95": 9999.0}, "latency_too_high"),
    ],
)
def test_execution_gate_quality_reject_reasons(features, reject_reason) -> None:
    cost = frequency.get_cost_scenario("live_4h", "low")
    base_features = {
        "spread_bps_avg": 1.0,
        "expected_slippage_bps": 1.0,
        "depth_score": 1.0,
        "volatility_score": 0.0,
        "api_latency_ms_p95": 10.0,
    }
    base_features.update(features)

    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1_000.0, "atr": 1_000.0},
        realtime_features=base_features,
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=0.1),
    )

    assert decision.allowed is False
    assert decision.reject_reason == reject_reason


def test_execution_gate_blocks_when_portfolio_risk_blocks() -> None:
    cost = frequency.get_cost_scenario("live_4h", "low")
    policy = risk.PortfolioRiskPolicy(max_open_positions_total=0)
    risk_decision = risk.evaluate_open(
        algo_id="macd_momentum",
        direction="long",
        open_positions={},
        state=risk.PortfolioRiskState(),
        evaluated_at=_now(),
        policy=policy,
    )

    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1_000.0, "atr": 1_000.0},
        realtime_features={},
        cost_scenario=cost,
        risk_decision=risk_decision,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=0.1),
    )

    assert decision.allowed is False
    assert decision.reject_reason == "risk_max_open_positions_total"
