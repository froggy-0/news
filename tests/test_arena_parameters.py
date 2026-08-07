from __future__ import annotations

import json

from arena import algorithms, config, feature_registry, frequency, indicators, parameters


def test_arena_parameter_snapshot_is_json_serializable() -> None:
    snapshot = parameters.base_params_snapshot()

    assert snapshot["params_version"] == parameters.PARAMS_VERSION
    assert snapshot["feature_set_version"] == parameters.FEATURE_SET_VERSION
    assert snapshot["params_version"] == "arena-params-v34"
    assert snapshot["feature_set_version"] == "arena-features-v8"
    assert snapshot["position_sizing"]["vol_weight_max"] == 0.7
    assert snapshot["position_sizing"]["risk_per_trade_pct"] == 0.015
    assert snapshot["risk_model_version"] == "portfolio-risk-v2"
    assert snapshot["runtime"] == "ec2"
    assert snapshot["market_data"]["symbol"] == "BTCUSDT"
    assert snapshot["market_data"]["frequency_shadow_enabled"] is False
    assert snapshot["market_data"]["frequency_shadow_profiles"] == ["research_1h"]
    assert snapshot["market_data"]["realtime_collector_enabled"] is True
    assert snapshot["execution_product"]["target_product"] == "spot"
    assert snapshot["execution_product"]["position_semantics"] == "spot_long_flat"
    assert snapshot["execution_product"]["allow_live_short"] is False
    assert snapshot["execution_product"]["spot_execution_only"] is True
    assert snapshot["execution_product"]["derivatives_data_usage"] == "research_features_only"
    assert snapshot["execution_gate"]["shadow_order_notional_usd"] == 1_000.0
    assert snapshot["realtime_risk"]["risk_model_version"] == "realtime-risk-v1"
    assert snapshot["realtime_risk"]["enabled"] is True
    assert snapshot["realtime_risk"]["live_enabled"] is False
    assert snapshot["indicators"]["macd_fast_period"] == 12
    assert snapshot["risk_defaults"]["max_open_positions_total"] == 6
    assert snapshot["risk_defaults"]["daily_loss_limit_pct"] == 0.05
    json.dumps(snapshot)


def test_live_config_is_hard_locked_to_spot_execution() -> None:
    assert config.TARGET_PRODUCT == "spot"
    assert config.POSITION_SEMANTICS == "spot_long_flat"
    assert config.SHORT_SIGNAL_ACTION == "exit_or_no_trade"
    assert config.ALLOW_LIVE_SHORT is False


def test_frequency_profiles_convert_time_to_bars_and_costs() -> None:
    live = frequency.get_frequency_profile("live_4h")
    research_1h = frequency.get_frequency_profile("research_1h")
    research_15m = frequency.get_frequency_profile("research_15m")

    assert live.interval == "4h"
    assert research_1h.interval == "1h"
    assert research_15m.interval == "15m"

    counts = frequency.walk_forward_bar_counts(research_1h)
    assert counts == {
        "train_bars": 2160,
        "test_bars": 504,
        "step_bars": 504,
        "embargo_bars": 24,
    }

    base_1h = frequency.get_cost_scenario("research_1h", "base")
    base_15m = frequency.get_cost_scenario("research_15m", "base")
    assert base_1h.trading_cost_bps_round_trip == 27.0
    assert base_1h.all_in_round_trip_bps == 27.5
    assert base_15m.trading_cost_bps_round_trip == 33.0
    assert base_15m.all_in_round_trip_bps == 34.0


def test_time_normalized_indicator_profile_preserves_4h_and_scales_intraday() -> None:
    live_settings = frequency.indicator_settings(interval="4h")
    one_hour_settings = frequency.indicator_settings(interval="1h")
    fifteen_min_settings = frequency.indicator_settings(interval="15m")
    native_settings = frequency.indicator_settings(
        interval="1h",
        indicator_profile_id=frequency.INTRADAY_INDICATOR_PROFILE_ID,
    )

    assert live_settings.rsi_period == parameters.RSI_PERIOD
    assert live_settings.macd_slow_period == parameters.MACD_SLOW_PERIOD
    assert one_hour_settings.rsi_period == 56
    assert one_hour_settings.macd_slow_period == 104
    assert fifteen_min_settings.rsi_period == 224
    assert fifteen_min_settings.macd_slow_period == 416
    assert native_settings.rsi_period == parameters.RSI_PERIOD
    assert one_hour_settings.return_24h_bars == 24
    assert fifteen_min_settings.return_24h_bars == 96


def test_arena_indicators_keep_default_contracts() -> None:
    closes = [float(100 + i) for i in range(80)]
    highs = [close + 2.0 for close in closes]
    lows = [close - 2.0 for close in closes]

    computed = indicators.compute(highs, lows, closes)

    assert {
        "rsi",
        "macd_hist",
        "macd_hist_prev",
        "bb_pos",
        "bb_width",
        "atr",
        "atr_pct",
        "ema_fast",
        "ema_slow",
        "ema_fast_slope",
        "return_24h",
        "return_72h",
        "realized_vol_24h",
        "range_24h_atr",
    } <= set(computed)
    assert computed["rsi"] > 50.0
    assert computed["atr"] > 0.0
    assert 0.0 <= computed["bb_pos"] <= 1.0


def test_macd_momentum_signal_conditions() -> None:
    # trending + momentum building (hist > hist_prev)
    trending_up = {"rsi": 50.0, "bb_width": 5.0, "adx": 25.0, "macd_hist_prev": 0.05}
    trending_dn = {"rsi": 50.0, "bb_width": 5.0, "macd_hist_prev": -0.05}

    # hist > 0 but decreasing (< h_prev=0.05) → None
    assert algorithms.macd_momentum({}, {"macd_hist": 0.01, "atr": 1.0, **trending_up}) is None
    # hist > 0 + increasing → long (ATR threshold removed since arena-params-v19)
    assert algorithms.macd_momentum({}, {"macd_hist": 0.09, "atr": 1.0, **trending_up}) == "long"
    assert algorithms.macd_momentum({}, {"macd_hist": 0.11, "atr": 1.0, **trending_up}) == "long"
    # negative hist → None
    assert algorithms.macd_momentum({}, {"macd_hist": -0.11, "atr": 1.0, **trending_dn}) is None
    # MACD delta filter: hist must be increasing — if decreasing, None
    fading = {"rsi": 50.0, "bb_width": 5.0, "macd_hist_prev": 0.5}
    assert algorithms.macd_momentum({}, {"macd_hist": 0.3, "atr": 1.0, **fading}) is None
    # BB width filter: choppy market (bb_width < 3.5) → always None
    choppy = {"rsi": 50.0, "bb_width": 3.0, "macd_hist_prev": 0.05}
    assert algorithms.macd_momentum({}, {"macd_hist": 0.5, "atr": 1.0, **choppy}) is None
    # RSI filter: long blocked when RSI >= 75 (P7 2026-07-25: 65→75, near-miss n=83 evidence)
    assert (
        algorithms.macd_momentum(
            {}, {"macd_hist": 0.5, "atr": 1.0, "rsi": 75.0, "bb_width": 5.0, "macd_hist_prev": 0.3}
        )
        is None
    )
    assert (
        algorithms.macd_momentum(
            {},
            {
                "macd_hist": 0.5,
                "atr": 1.0,
                "rsi": 70.0,
                "adx": 25.0,
                "bb_width": 5.0,
                "macd_hist_prev": 0.3,
            },
        )
        == "long"
    )


def test_multi_factor_sideways_excluded_by_default() -> None:
    """v32 (2026-07-30): 정성분석(라이브 손실 6/7이 sideways 진입) + 20개월 백필 재검증
    (Δ+9.45, 전/후반 분할 둘 다 개선)으로 MULTI_FACTOR_ALLOW_SIDEWAYS True→False 번복."""
    macro = {"arena_regime_state": "sideways", "fng": 40.0}
    ind = {"rsi": 40.0}
    assert parameters.MULTI_FACTOR_ALLOW_SIDEWAYS is False
    assert algorithms.multi_factor(macro, ind) is None
    saved = parameters.MULTI_FACTOR_ALLOW_SIDEWAYS
    try:
        parameters.MULTI_FACTOR_ALLOW_SIDEWAYS = True
        assert algorithms.multi_factor(macro, ind) == "long"
    finally:
        parameters.MULTI_FACTOR_ALLOW_SIDEWAYS = saved


def test_strategy_version_metadata_matches_parameter_versions() -> None:
    snapshot = parameters.base_params_snapshot()
    row = feature_registry.strategy_version_row(snapshot)

    assert row["strategy_version"] == parameters.STRATEGY_VERSION
    assert row["params_version"] == parameters.PARAMS_VERSION
    assert row["feature_set_version"] == parameters.FEATURE_SET_VERSION
    assert row["risk_model_version"] == parameters.RISK_MODEL_VERSION
    assert row["methodology"]["feature_timing"] == "closed_candle_only"
    json.dumps(row)


def test_multi_asset_shadow_defaults_off_and_symbols_include_btc_eth_sol() -> None:
    """2026-07-31 멀티자산 확장 P1-1 — 기본값은 off, BTC 라이브 경로 무회귀 보장."""
    assert parameters.MULTI_ASSET_SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert parameters.ARENA_MULTI_ASSET_SHADOW_ENABLED is False
    assert parameters.ARENA_MULTI_ASSET_SHADOW_SYMBOLS == ("ETHUSDT", "SOLUSDT")
    assert config.ENABLE_ARENA_MULTI_ASSET_SHADOW is False
    assert config.ARENA_MULTI_ASSET_SHADOW_SYMBOLS == ("ETHUSDT", "SOLUSDT")
    # BTC 라이브 프로파일은 절대 변경되면 안 됨 (기존 데이터와의 연속성).
    live = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    assert live.symbol == "BTCUSDT"
    assert live.live_enabled is True


def test_multi_asset_shadow_profiles_registered_for_eth_and_sol() -> None:
    """ETH/SOL shadow 프로파일이 BTC 라이브와 동일 파라미터(자산별 재튜닝 없음)로 등록됨.

    live_enabled=True(2026-08-07 정정): 2026-08-06 실거래 승격 후 이 필드가 stale False로
    남아있던 걸 발견·수정. 필드 자체는 런타임 게이트가 아니라 설명용 메타데이터(frequency.py
    FrequencyProfile 주석 참조) — 실제 게이팅은 config.ENABLE_ARENA_MULTI_ASSET_SHADOW.
    """
    live = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    for symbol in ("ETHUSDT", "SOLUSDT"):
        profile_id = frequency.multi_asset_shadow_profile_id(symbol)
        profile = frequency.get_frequency_profile(profile_id)
        assert profile.symbol == symbol
        assert profile.live_enabled is True
        assert profile.shadow_candidate is True
        assert profile.interval == live.interval
        assert profile.train_days == live.train_days
        assert profile.test_days == live.test_days
        assert profile.ecr_threshold == live.ecr_threshold
        assert profile.min_hold_hours == live.min_hold_hours
        cost = frequency.get_cost_scenario(profile_id, "base")
        live_cost = frequency.get_cost_scenario(frequency.LIVE_4H_PROFILE_ID, "base")
        assert cost.trading_cost_bps_round_trip == live_cost.trading_cost_bps_round_trip


def test_feature_registry_rows_are_leakage_safe_model_inputs() -> None:
    rows = feature_registry.feature_registry_rows()
    by_name = {row["feature_name"]: row for row in rows}

    assert {
        "rsi",
        "macd_hist",
        "macd_hist_prev",
        "bb_pos",
        "bb_width",
        "atr",
        "ema_fast",
        "ema_slow",
        "return_24h",
        "return_72h",
        "funding_rate_24h",
        "open_interest_change_24h",
        "regime_state",
        "fng",
        "vix_now",
        "vix_q40",
    } <= set(by_name)
    assert all(row["feature_set_version"] == parameters.FEATURE_SET_VERSION for row in rows)
    assert all(row["leakage_safe"] is True for row in rows)
    assert all(row["lag_bars"] >= 0 for row in rows)
    assert by_name["macd_hist"]["risk_impact"] == "high"
    assert by_name["atr"]["unit"] == "price"
    json.dumps(rows)
