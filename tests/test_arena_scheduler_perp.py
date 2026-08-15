from __future__ import annotations

from arena import frequency, parameters, scheduler


def test_risk_policy_zeroes_short_caps_for_spot_even_when_perp_pair_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters,
        "PERP_SHORT_ENABLED_TRACKS",
        frozenset({("BTCUSDT-PERP", "macd_momentum")}),
    )
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)

    policy = scheduler._risk_policy(profile)

    assert policy.max_short_positions == 0
    assert policy.max_net_short_exposure == 0.0
    assert scheduler._short_enabled_for(profile, "macd_momentum") is False


def test_risk_policy_opens_short_caps_for_approved_perp_track(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters,
        "PERP_SHORT_ENABLED_TRACKS",
        frozenset({("BTCUSDT-PERP", "macd_momentum")}),
    )
    profile = frequency.get_frequency_profile(frequency.perp_live_profile_id("BTCUSDT"))

    policy = scheduler._risk_policy(profile)

    assert policy.max_short_positions == scheduler.config.MAX_SHORT_POSITIONS
    assert policy.max_net_short_exposure == scheduler.config.MAX_NET_SHORT_EXPOSURE
    assert scheduler._short_enabled_for(profile, "macd_momentum") is True


def test_short_gate_does_not_leak_to_other_perp_asset(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters,
        "PERP_SHORT_ENABLED_TRACKS",
        frozenset({("BTCUSDT-PERP", "macd_momentum")}),
    )
    eth_profile = frequency.get_frequency_profile(frequency.perp_live_profile_id("ETHUSDT"))

    assert scheduler._short_enabled_for(eth_profile, "macd_momentum") is False
    assert scheduler._risk_policy(eth_profile).max_short_positions == 0
