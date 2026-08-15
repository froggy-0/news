from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from arena import parameters, perp_policy, positions


def test_perp_policy_opens_long_from_flat() -> None:
    decision = perp_policy.decide("long", None)

    assert decision.action == "open"
    assert decision.executable_signal == "long"
    assert decision.should_open is True
    assert decision.should_close is False


def test_perp_policy_opens_short_from_flat() -> None:
    decision = perp_policy.decide("short", None)

    assert decision.action == "open"
    assert decision.executable_signal == "short"
    assert decision.should_open is True
    assert decision.should_close is False


def test_perp_policy_holds_same_direction() -> None:
    long_hold = perp_policy.decide("long", {"direction": "long"})
    short_hold = perp_policy.decide("short", {"direction": "short"})

    assert long_hold.action == "hold"
    assert long_hold.should_open is False
    assert long_hold.should_close is False
    assert short_hold.action == "hold"
    assert short_hold.should_open is False
    assert short_hold.should_close is False


def test_perp_policy_reverses_long_to_short() -> None:
    decision = perp_policy.decide("short", {"direction": "long"})

    assert decision.action == "signal_reverse"
    assert decision.close_reason == "signal_reverse"
    assert decision.should_close is True
    assert decision.should_open is True
    assert decision.executable_signal == "short"


def test_perp_policy_reverses_short_to_long() -> None:
    decision = perp_policy.decide("long", {"direction": "short"})

    assert decision.action == "signal_reverse"
    assert decision.should_close is True
    assert decision.should_open is True
    assert decision.executable_signal == "long"


def test_perp_policy_closes_on_flat_signal() -> None:
    decision = perp_policy.decide(None, {"direction": "long"})

    assert decision.action == "close_flat"
    assert decision.close_reason == "flat_signal"
    assert decision.should_close is True
    assert decision.should_open is False


def test_perp_policy_flat_skip_when_already_flat() -> None:
    decision = perp_policy.decide(None, None)

    assert decision.action == "flat_skip"
    assert decision.should_close is False
    assert decision.should_open is False


def test_perp_policy_snapshot_shape_matches_spot_policy_fields() -> None:
    decision = perp_policy.decide("long", None)
    snapshot = decision.policy_snapshot()

    assert snapshot["target_product"] == "usdm_perp"
    assert snapshot["allow_live_short"] is True
    assert snapshot["spot_execution_only"] is False


def test_open_position_allows_short_for_perp_enabled_algo(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "PERP_LIVE_ENABLED_ALGOS", frozenset({"macd_momentum"}))

    async def call() -> None:
        await positions.open_position(
            "macd_momentum",
            "short",
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            100.0,
            105.0,
            data_timestamp=datetime(2026, 8, 15, tzinfo=timezone.utc),
            strategy_version="arena-spot-v4",
            params_version="arena-params-v35",
            params_snapshot={},
            indicator_snapshot={},
            macro_snapshot={},
            market_snapshot={},
            signal_reason={},
        )

    # 아직 positions.init() 미호출이라 DB 단계에서 RuntimeError로 넘어가야 정상 —
    # 즉 algo_id 허용목록 가드는 통과했다는 뜻(가드가 여전히 막고 있다면 ValueError).
    with pytest.raises(RuntimeError, match="positions.init"):
        asyncio.run(call())


def test_open_position_still_rejects_short_for_non_enabled_algo() -> None:
    async def call() -> None:
        await positions.open_position(
            "regime_trend",
            "short",
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            100.0,
            105.0,
            data_timestamp=datetime(2026, 8, 15, tzinfo=timezone.utc),
            strategy_version="arena-spot-v4",
            params_version="arena-params-v35",
            params_snapshot={},
            indicator_snapshot={},
            macro_snapshot={},
            market_snapshot={},
            signal_reason={},
        )

    with pytest.raises(ValueError, match="PERP_LIVE_ENABLED_ALGOS"):
        asyncio.run(call())


def test_target_product_for_algo_defaults_to_spot() -> None:
    assert parameters.target_product_for_algo("macd_momentum") == "spot"
    assert parameters.target_position_semantics_for_algo("macd_momentum") == "spot_long_flat"


def test_target_product_for_algo_returns_perp_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "PERP_LIVE_ENABLED_ALGOS", frozenset({"macd_momentum"}))

    assert parameters.target_product_for_algo("macd_momentum") == "usdm_perp"
    assert parameters.target_product_for_algo("regime_trend") == "spot"


def test_open_position_uses_explicit_product_type_when_given(monkeypatch) -> None:
    # Phase A2(2026-08-15): 트랙(scheduler.py의 profile.product_type)이 명시적으로
    # product_type을 넘기면 알고별 결정(target_product_for_algo)을 오버라이드해야 한다
    # — 숏은 여전히 PERP_LIVE_ENABLED_ALGOS로 게이트되므로 롱으로 검증.
    monkeypatch.setattr(parameters, "PERP_LIVE_ENABLED_ALGOS", frozenset())
    captured: dict = {}

    class _FakeTable:
        def insert(self, payload):
            captured.update(payload)
            return self

        async def execute(self):
            return type("R", (), {"data": [{**captured, "id": 1}]})()

    class _FakeDb:
        def table(self, name):
            return _FakeTable()

    monkeypatch.setattr(positions, "_client", _FakeDb())

    asyncio.run(
        positions.open_position(
            "regime_trend",
            "long",
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            100.0,
            95.0,
            data_timestamp=datetime(2026, 8, 15, tzinfo=timezone.utc),
            strategy_version="arena-spot-v4",
            params_version="arena-params-v35",
            symbol="BTCUSDT-PERP",
            product_type="usdm_perp",
            position_semantics="usdm_perp_long_short",
            params_snapshot={},
            indicator_snapshot={},
            macro_snapshot={},
            market_snapshot={},
            signal_reason={},
        )
    )

    # regime_trend은 PERP_LIVE_ENABLED_ALGOS에 없지만, 트랙이 명시한 product_type이
    # 그대로 기록돼야 한다(더 이상 algo_id로 product_type을 재계산하지 않음).
    assert captured["product_type"] == "usdm_perp"
    assert captured["position_semantics"] == "usdm_perp_long_short"
