from arena import algorithms, execution_rules


def test_fng_contrarian_stabilization_blocks_worsening_momentum() -> None:
    # 게이트 통과 macro: 공포(fng<30)·risk-off 아님·충분한 낙폭.
    macro = {"arena_regime_state": "bull_trend", "fng": 20.0, "btc_drawdown_90d": -0.15}
    # 하락 모멘텀 악화(hist < prev) → 칼받기 회피로 진입 보류.
    assert algorithms.fng_contrarian(macro, {"macd_hist": -2.0, "macd_hist_prev": -1.0}) is None
    # 모멘텀 안정/개선(hist >= prev) → 진입 허용.
    assert algorithms.fng_contrarian(macro, {"macd_hist": -1.0, "macd_hist_prev": -2.0}) == "long"
    # macd 미수집 → graceful(게이트 미적용) → 진입 허용.
    assert algorithms.fng_contrarian(macro, {}) == "long"


def test_vix_rsi_stabilization_blocks_worsening_momentum() -> None:
    # 게이트 통과 macro: VIX calm·risk-off 아님.
    macro = {"arena_regime_state": "bull_trend", "vix_now": 15.0, "vix_q40": 18.0}
    # 하락 모멘텀 악화(hist < prev) → 칼받기 회피로 진입 보류 (v26).
    ind_worse = {"rsi": 45.0, "macd_hist": -2.0, "macd_hist_prev": -1.0}
    assert algorithms.vix_rsi(macro, ind_worse) is None
    diagnostic = algorithms.explain_signal("vix_rsi", macro, ind_worse)
    assert "momentum_not_worsening" in diagnostic["vetoes"]
    # 모멘텀 안정/개선 → 진입 허용.
    assert algorithms.vix_rsi(macro, {"rsi": 45.0, "macd_hist": -1.0, "macd_hist_prev": -2.0}) == (
        "long"
    )
    # macd 미수집 → graceful(게이트 미적용) → 진입 허용.
    assert algorithms.vix_rsi(macro, {"rsi": 45.0}) == "long"


def test_vix_rsi_exit_hold_override_hysteresis() -> None:
    macro = {"arena_regime_state": "bull_trend", "vix_now": 18.5, "vix_q40": 18.0}
    # 진입 조건(RSI<50·VIX<q40×1.05)은 깨졌지만 청산 임계(RSI<60·VIX<q40×1.15) 이내 → hold.
    assert algorithms.exit_hold_override("vix_rsi", macro, {"rsi": 55.0}) is True
    # RSI≥60 → 모멘텀 소진, 청산 실행.
    assert algorithms.exit_hold_override("vix_rsi", macro, {"rsi": 61.0}) is False
    # VIX가 청산 밴드(q40×1.15) 초과 → 환경 악화, 청산 실행.
    macro_vix_spike = dict(macro, vix_now=21.0)
    assert algorithms.exit_hold_override("vix_rsi", macro_vix_spike, {"rsi": 55.0}) is False
    # risk-off 레짐 → 히스테리시스 미적용(즉시 청산).
    macro_risk_off = dict(macro, arena_regime_state="bear_trend")
    assert algorithms.exit_hold_override("vix_rsi", macro_risk_off, {"rsi": 55.0}) is False
    # 다른 알고에는 미적용.
    assert algorithms.exit_hold_override("multi_factor", macro, {"rsi": 55.0}) is False


def test_below_ma200_structural_gate_reads_macro_flag() -> None:
    # btc_above_ma200=0(하회) → 역추세/모멘텀 롱 보류 트리거.
    assert algorithms._below_ma200({"btc_above_ma200": 0.0}) is True
    # 상회 → 통과.
    assert algorithms._below_ma200({"btc_above_ma200": 1.0}) is False
    # 미수집(None) → graceful 통과(게이트 미적용).
    assert algorithms._below_ma200({}) is False


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
