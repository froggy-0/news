from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from arena import positions, spot_policy


def test_spot_policy_maps_short_without_position_to_no_trade() -> None:
    decision = spot_policy.decide("short", None)

    assert decision.action == "spot_short_no_trade"
    assert decision.executable_signal is None
    assert decision.should_open is False
    assert decision.skipped_reason == "spot_short_signal_no_position"


def test_spot_policy_maps_short_with_long_to_risk_off_close() -> None:
    decision = spot_policy.decide("short", {"direction": "long"})

    assert decision.action == "close_spot_risk_off"
    assert decision.executable_signal is None
    assert decision.should_close is True
    assert decision.close_reason == "short_signal_spot_risk_off"


def test_spot_policy_allows_long_open_and_hold() -> None:
    open_decision = spot_policy.decide("long", None)
    hold_decision = spot_policy.decide("long", {"direction": "long"})

    assert open_decision.action == "open"
    assert open_decision.executable_signal == "long"
    assert open_decision.should_open is True
    assert hold_decision.action == "hold"
    assert hold_decision.should_open is False


def test_spot_policy_closes_legacy_short() -> None:
    decision = spot_policy.decide(None, {"direction": "short"})

    assert decision.action == "close_legacy_short"
    assert decision.should_close is True
    assert decision.legacy_short_close is True
    assert decision.close_reason == "spot_semantics_migration"


def test_open_position_rejects_short_for_spot_before_db_use() -> None:
    async def call() -> None:
        await positions.open_position(
            "algo",
            "short",
            datetime(2026, 6, 20, tzinfo=timezone.utc),
            100.0,
            105.0,
            data_timestamp=datetime(2026, 6, 20, tzinfo=timezone.utc),
            strategy_version="arena-spot-v1",
            params_version="arena-params-v11",
            params_snapshot={},
            indicator_snapshot={},
            macro_snapshot={},
            market_snapshot={},
            signal_reason={},
        )

    with pytest.raises(ValueError, match="cannot open short"):
        asyncio.run(call())
