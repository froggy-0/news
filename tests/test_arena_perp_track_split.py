from __future__ import annotations

from arena import config, frequency, parameters, scheduler


def test_perp_track_symbol_and_real_ticker_round_trip() -> None:
    assert parameters.perp_track_symbol("BTCUSDT") == "BTCUSDT-PERP"
    assert parameters.real_ticker_for_track("BTCUSDT-PERP") == "BTCUSDT"
    # spot 트랙(접미사 없음)은 그대로 통과 — round-trip 무변화.
    assert parameters.real_ticker_for_track("BTCUSDT") == "BTCUSDT"


def test_perp_live_profiles_registered_for_all_multi_asset_symbols() -> None:
    for symbol in parameters.MULTI_ASSET_SYMBOLS:
        profile_id = frequency.perp_live_profile_id(symbol)
        profile = frequency.get_frequency_profile(profile_id)

        assert profile.symbol == f"{symbol}-PERP"
        assert profile.binance_symbol == symbol
        assert profile.product_type == "usdm_perp"
        # 자산별 재튜닝 금지 원칙 — spot 라이브 프로파일과 사양 동일.
        base = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
        assert profile.interval == base.interval
        assert profile.min_hold_hours == base.min_hold_hours


def test_perp_live_profile_cost_scenario_registered() -> None:
    profile_id = frequency.perp_live_profile_id("BTCUSDT")
    cost = frequency.get_cost_scenario(profile_id, "base")

    assert cost.fee_bps == parameters.FEE_BPS


def test_spot_profiles_unaffected_by_binance_symbol_field() -> None:
    # 기존 spot/shadow 프로파일은 symbol == binance_symbol이라 REST 호출부(profile.
    # binance_symbol로 전환된 scheduler.py)가 완전히 동일한 값을 쓴다 — 무회귀 확인.
    live = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    assert live.symbol == live.binance_symbol == parameters.BINANCE_SYMBOL

    eth_shadow = frequency.get_frequency_profile(frequency.multi_asset_shadow_profile_id("ETHUSDT"))
    assert eth_shadow.symbol == eth_shadow.binance_symbol == "ETHUSDT"
    assert eth_shadow.product_type == "spot"


def test_position_semantics_for_product_type() -> None:
    assert scheduler._position_semantics_for_product_type("spot") == "spot_long_flat"
    assert scheduler._position_semantics_for_product_type("usdm_perp") == "usdm_perp_long_short"


def test_live_tracks_by_symbol_matches_spot_only_when_perp_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "ARENA_LIVE_SYMBOLS", ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    monkeypatch.setattr(config, "ENABLE_ARENA_PERP_LIVE", False)

    mapping = config._live_tracks_by_symbol()

    assert mapping == {
        "BTCUSDT": ("BTCUSDT",),
        "ETHUSDT": ("ETHUSDT",),
        "SOLUSDT": ("SOLUSDT",),
    }


def test_live_tracks_by_symbol_adds_perp_track_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "ARENA_LIVE_SYMBOLS", ("BTCUSDT",))
    monkeypatch.setattr(config, "ENABLE_ARENA_PERP_LIVE", True)

    mapping = config._live_tracks_by_symbol()

    # BTCUSDT는 spot 라이브(ARENA_LIVE_SYMBOLS)에도 있으니 두 트랙 다 — ETH/SOL은
    # spot 라이브가 아니어도(멀티에셋 shadow 꺼짐) perp 트랙은 MULTI_ASSET_SYMBOLS
    # 전체에서 독립적으로 생긴다(spot과 무관하게 perp를 켤 수 있어야 하므로).
    assert mapping["BTCUSDT"] == ("BTCUSDT", "BTCUSDT-PERP")
    assert mapping["ETHUSDT"] == ("ETHUSDT-PERP",)
    assert mapping["SOLUSDT"] == ("SOLUSDT-PERP",)


def test_symbol_label_marks_perp_tracks() -> None:
    from arena import slack_notify

    assert slack_notify._symbol_label("BTCUSDT") == "BTC"
    assert slack_notify._symbol_label("BTCUSDT-PERP") == "BTC-F"
    assert slack_notify._symbol_label("SOLUSDT-PERP") == "SOL-F"
