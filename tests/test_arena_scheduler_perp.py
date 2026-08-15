from __future__ import annotations

from arena import parameters, scheduler


def test_risk_policy_zeroes_short_caps_when_no_perp_algos_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "PERP_LIVE_ENABLED_ALGOS", frozenset())

    policy = scheduler._risk_policy()

    assert policy.max_short_positions == 0
    assert policy.max_net_short_exposure == 0.0


def test_risk_policy_opens_short_caps_when_any_perp_algo_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "PERP_LIVE_ENABLED_ALGOS", frozenset({"macd_momentum"}))

    policy = scheduler._risk_policy()

    assert policy.max_short_positions == scheduler.config.MAX_SHORT_POSITIONS
    assert policy.max_net_short_exposure == scheduler.config.MAX_NET_SHORT_EXPOSURE
