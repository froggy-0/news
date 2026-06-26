from __future__ import annotations

from datetime import datetime, timezone

from arena import risk


def _now() -> datetime:
    return datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)


def test_exposure_snapshot_counts_long_short_and_net_exposure() -> None:
    snapshot = risk.exposure_snapshot(
        {
            "a": {"algo_id": "a", "direction": "long", "status": "open"},
            "b": {"algo_id": "b", "direction": "short", "status": "open"},
            "c": None,
        }
    )

    assert snapshot.open_positions_total == 2
    assert snapshot.long_positions == 1
    assert snapshot.short_positions == 1
    assert snapshot.gross_exposure == 2.0
    assert snapshot.net_exposure == 0.0


def test_risk_gate_blocks_same_direction_over_max_long_limit() -> None:
    decision = risk.evaluate_open(
        algo_id="new_algo",
        direction="long",
        open_positions={
            "a": {"algo_id": "a", "direction": "long", "status": "open"},
            "b": {"algo_id": "b", "direction": "long", "status": "open"},
        },
        state=risk.PortfolioRiskState(),
        evaluated_at=_now(),
        policy=risk.PortfolioRiskPolicy(max_long_positions=2),
    )

    assert decision.allowed is False
    assert decision.reason == "max_long_positions"
    assert decision.proposed_exposure.long_positions == 3


def test_risk_gate_blocks_daily_loss_and_algo_drawdown() -> None:
    daily_loss = risk.evaluate_open(
        algo_id="algo",
        direction="short",
        open_positions={},
        state=risk.PortfolioRiskState(daily_realized_ret_pct=-0.06),
        evaluated_at=_now(),
        policy=risk.PortfolioRiskPolicy(daily_loss_limit_pct=0.05),
    )
    drawdown = risk.evaluate_open(
        algo_id="algo",
        direction="short",
        open_positions={},
        state=risk.PortfolioRiskState(algo_drawdown_pct={"algo": -0.11}),
        evaluated_at=_now(),
        policy=risk.PortfolioRiskPolicy(algo_max_drawdown_kill_pct=0.10),
    )

    assert daily_loss.allowed is False
    assert daily_loss.reason == "daily_loss_limit"
    assert drawdown.allowed is False
    assert drawdown.reason == "algo_drawdown_kill"


def test_allowed_risk_decision_is_json_snapshot_ready() -> None:
    decision = risk.evaluate_open(
        algo_id="algo",
        direction="long",
        open_positions={},
        state=risk.PortfolioRiskState(),
        evaluated_at=_now(),
    )

    payload = decision.as_dict()

    assert payload["allowed"] is True
    assert payload["policy"]["risk_model_version"] == "portfolio-risk-v2"
    assert payload["proposed_exposure"]["long_positions"] == 1
