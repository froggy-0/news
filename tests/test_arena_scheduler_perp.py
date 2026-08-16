from __future__ import annotations

from arena import frequency, parameters, scheduler, spot_policy


def test_v39_out_of_scope_track_blocks_new_entry_but_not_management() -> None:
    """v39: perp에서 숏을 안 쓰는 알고(예: fng_contrarian)는 ALGORITHM_TRACK_SCOPE로
    perp 신규진입이 막힌다. 하지만 이미 열린 포지션이 있으면(scheduler._run_cycle의
    `current is None` 가드) 계속 관리 대상이어야 한다 — 이 테스트는 그 전제가 되는
    spot_policy 불변식(현재 포지션이 있으면 should_open은 절대 True가 아님)을 문서화한다.
    스코프 밖+포지션 없음이면 신규진입 차단(scheduler.py의 `if not in_scope and current
    is None: continue`), 스코프 밖+포지션 있음이면 정상 진행해 이 불변식 덕에 안전하게
    청산까지만 일어나고 재진입은 없다.
    """
    assert parameters.algorithm_in_track_scope("fng_contrarian", "BTCUSDT-PERP") is False

    current = {"id": 1, "direction": "long", "open_time": None}
    for raw_signal in (None, "long", "short"):
        decision = spot_policy.decide(raw_signal, current)
        assert decision.should_open is False


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
