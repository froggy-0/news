from __future__ import annotations

import json

from arena import algorithms, feature_registry, indicators, parameters


def test_arena_parameter_snapshot_is_json_serializable() -> None:
    snapshot = parameters.base_params_snapshot()

    assert snapshot["params_version"] == parameters.PARAMS_VERSION
    assert snapshot["feature_set_version"] == parameters.FEATURE_SET_VERSION
    assert snapshot["params_version"] == "arena-params-v6"
    assert snapshot["risk_model_version"] == "portfolio-risk-v1"
    assert snapshot["runtime"] == "ec2"
    assert snapshot["market_data"]["symbol"] == "BTCUSDT"
    assert snapshot["indicators"]["macd_fast_period"] == 12
    assert snapshot["risk_defaults"]["max_open_positions_total"] == 3
    assert snapshot["risk_defaults"]["daily_loss_limit_pct"] == 0.05
    json.dumps(snapshot)


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


def test_macd_momentum_uses_atr_threshold() -> None:
    # trending + momentum building (hist > hist_prev)
    trending_up = {"rsi": 50.0, "bb_width": 5.0, "macd_hist_prev": 0.05}
    trending_dn = {"rsi": 50.0, "bb_width": 5.0, "macd_hist_prev": -0.05}

    # threshold=0.10: hist < 0.10*ATR → None regardless
    assert algorithms.macd_momentum({}, {"macd_hist": 0.01, "atr": 1.0, **trending_up}) is None
    assert algorithms.macd_momentum({}, {"macd_hist": 0.09, "atr": 1.0, **trending_up}) is None
    # hist > 0.10*ATR + increasing + trending → long/short
    assert algorithms.macd_momentum({}, {"macd_hist": 0.11, "atr": 1.0, **trending_up}) == "long"
    assert algorithms.macd_momentum({}, {"macd_hist": -0.11, "atr": 1.0, **trending_dn}) == "short"
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


def test_multi_factor_is_symmetric_for_short_filter() -> None:
    bull = {"regime_state": parameters.REGIME_LONG_STATE}
    bear = {"regime_state": parameters.REGIME_SHORT_STATE}

    assert algorithms.multi_factor(bull, {"rsi": 49.0, "macd_hist": 0.1}) == "long"
    assert algorithms.multi_factor(bear, {"rsi": 56.0, "macd_hist": -0.1}) == "short"
    assert algorithms.multi_factor(bear, {"rsi": 56.0, "macd_hist": 0.1}) is None


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
