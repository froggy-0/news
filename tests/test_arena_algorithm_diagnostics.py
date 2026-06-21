from arena import algorithms, execution_rules


def test_vix_rsi_diagnostics_explain_flat_vetoes() -> None:
    macro = {"arena_regime_state": "bull_trend", "vix_now": 25.0, "vix_q40": 20.0}
    ind = {"rsi": 55.0}

    diagnostic = algorithms.explain_signal("vix_rsi", macro, ind)

    assert diagnostic["raw_signal"] is None
    assert "vix_calm" in diagnostic["vetoes"]
    assert "rsi_below_long_max" in diagnostic["vetoes"]


def test_multi_factor_diagnostics_include_factor_score() -> None:
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 23.0,
        "vix_now": 18.0,
        "vix_q40": 20.0,
        "funding_zscore": 0.0,
    }
    ind = {"rsi": 45.0}

    diagnostic = algorithms.explain_signal("multi_factor", macro, ind)

    assert diagnostic["raw_signal"] == "long"
    assert diagnostic["factor_score"] == 5
    assert diagnostic["vetoes"] == []


def test_signal_reason_inputs_cover_roster_diagnostics_fields() -> None:
    reason = execution_rules.build_signal_reason(
        algo_id="regime_trend",
        signal=None,
        indicators={
            "close": 100.0,
            "ema_fast": 101.0,
            "ema_slow": 99.0,
            "ema_fast_slope": 1.0,
            "macd_hist_prev": 0.1,
        },
        macro={
            "arena_regime_state": "unknown",
            "regime_state": "Transitional",
            "btc_above_ma200": 1.0,
            "long_short_ratio_zscore": 0.0,
            "taker_imbalance_zscore": 0.5,
            "breadth_up_ratio": 0.7,
            "stablecoin_supply_zscore": 0.2,
            "btc_drawdown_90d": -0.12,
        },
    )

    inputs = reason["inputs"]
    assert inputs["close"] == 100.0
    assert inputs["ema_fast"] == 101.0
    assert inputs["btc_above_ma200"] == 1.0
    assert inputs["taker_imbalance_zscore"] == 0.5


def test_scheduler_uses_primary_veto_as_flat_skip_reason() -> None:
    macro = {
        "arena_regime_state": "unknown",
        "regime_state": "Transitional",
        "fng": 23.0,
        "vix_now": 18.0,
        "vix_q40": 20.0,
        "funding_zscore": 0.0,
    }
    ind = {"rsi": 55.0}

    reason = algorithms.primary_flat_skip_reason("multi_factor", macro, ind)

    assert reason == "veto:factor_score_at_least_4"
