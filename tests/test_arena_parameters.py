from __future__ import annotations

import json

from arena import algorithms, config, feature_registry, frequency, indicators, parameters


def test_arena_parameter_snapshot_is_json_serializable() -> None:
    snapshot = parameters.base_params_snapshot()

    assert snapshot["params_version"] == parameters.PARAMS_VERSION
    assert snapshot["feature_set_version"] == parameters.FEATURE_SET_VERSION
    assert snapshot["params_version"] == "arena-params-v20"
    assert snapshot["feature_set_version"] == "arena-features-v8"
    assert snapshot["risk_model_version"] == "portfolio-risk-v1"
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
    assert snapshot["risk_defaults"]["max_open_positions_total"] == 3
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
    assert base_1h.trading_cost_bps_round_trip == 17.0
    assert base_1h.all_in_round_trip_bps == 17.5
    assert base_15m.trading_cost_bps_round_trip == 23.0
    assert base_15m.all_in_round_trip_bps == 24.0


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
    # RSI filter: long blocked when RSI ≥ 65
    assert (
        algorithms.macd_momentum(
            {}, {"macd_hist": 0.5, "atr": 1.0, "rsi": 65.0, "bb_width": 5.0, "macd_hist_prev": 0.3}
        )
        is None
    )


def test_strategy_version_metadata_matches_parameter_versions() -> None:
    snapshot = parameters.base_params_snapshot()
    row = feature_registry.strategy_version_row(snapshot)

    assert row["strategy_version"] == parameters.STRATEGY_VERSION
    assert row["params_version"] == parameters.PARAMS_VERSION
    assert row["feature_set_version"] == parameters.FEATURE_SET_VERSION
    assert row["risk_model_version"] == parameters.RISK_MODEL_VERSION
    assert row["methodology"]["feature_timing"] == "closed_candle_only"
    json.dumps(row)


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
