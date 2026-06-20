from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arena import execution_gate, frequency, tca_shadow


def _decision(allowed: bool = True) -> execution_gate.ExecutionGateDecision:
    return execution_gate.ExecutionGateDecision(
        allowed=allowed,
        decision="trade_allowed" if allowed else "no_trade",
        reject_reason=None if allowed else "spread_too_wide",
        expected_return_bps=60.0,
        expected_cost_bps=13.0,
        spread_bps=2.0,
        expected_slippage_bps=1.0,
        depth_score=1.0,
        volatility_score=0.0,
        api_latency_ms=100.0,
        policy=execution_gate.ExecutionGatePolicy(),
        evaluated_at=datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc),
        feature_snapshot={
            "symbol": "BTCUSDT",
            "last_bid": 99_990.0,
            "last_ask": 100_010.0,
            "depth_bids": [(99_990.0, 1.0), (99_950.0, 1.0)],
            "depth_asks": [(100_010.0, 1.0), (100_050.0, 1.0)],
            "depth_10bp_bid_usd": 199_940.0,
            "depth_10bp_ask_usd": 200_060.0,
        },
        risk_snapshot={},
    )


def test_shadow_tca_builds_parent_order_and_quality_rows() -> None:
    rows = tca_shadow.build_shadow_tca_rows(
        run_id="00000000-0000-0000-0000-000000000001",
        algo_id="macd_momentum",
        signal="long",
        timeframe="4h",
        evaluated_at=datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc),
        gate_decision=_decision(),
        cost_scenario=frequency.get_cost_scenario("live_4h", "base"),
        target_notional_usd=1_000.0,
    )

    parent = rows.parent_order
    quality = rows.execution_quality
    assert parent["side"] == "buy"
    assert parent["order_intent"] == "marketable_limit"
    assert parent["decision_snapshot"]["arrival_mid"] == 100_000.0
    assert parent["decision_snapshot"]["target_qty"] == pytest.approx(0.01)
    assert quality["parent_order_id"] == parent["parent_order_id"]
    assert quality["fill_ratio"] == pytest.approx(1.0)
    assert quality["realized_slippage_bps"] == pytest.approx(1.0)
    assert quality["realized_cost_bps"] == pytest.approx(13.0)
    assert quality["quality_snapshot"]["quality_status"] == "ok"


def test_shadow_tca_records_no_trade_and_degraded_without_depth() -> None:
    decision = _decision(allowed=False)
    decision = execution_gate.ExecutionGateDecision(
        **{
            **decision.__dict__,
            "feature_snapshot": {
                "symbol": "BTCUSDT",
                "last_bid": 99_990.0,
                "last_ask": 100_010.0,
            },
        }
    )

    rows = tca_shadow.build_shadow_tca_rows(
        run_id="00000000-0000-0000-0000-000000000001",
        algo_id="macd_momentum",
        signal="short",
        timeframe="4h",
        evaluated_at=datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc),
        gate_decision=decision,
        cost_scenario=frequency.get_cost_scenario("live_4h", "base"),
    )

    assert rows.parent_order["side"] == "sell"
    assert rows.parent_order["order_intent"] == "no_trade"
    assert rows.execution_quality["realized_slippage_bps"] == 1.0
    assert rows.execution_quality["quality_snapshot"]["quality_status"] == "degraded"
