from arena import algorithms, execution_rules, parameters


def test_momentum_not_worsening_magnitude_gate_blocks_deep_negative_even_if_improving() -> None:
    # 방향은 개선(hist -3.0 → -2.5, mh>=mhp)이지만 여전히 max_abs_hist(2.0)보다 깊은 음수
    # → 매그니튜드 게이트가 없으면(max_abs_hist=None) 통과, 있으면 차단.
    ind = {"macd_hist": -2.5, "macd_hist_prev": -3.0}
    assert algorithms._momentum_not_worsening(ind, max_abs_hist=None) is True
    assert algorithms._momentum_not_worsening(ind, max_abs_hist=2.0) is False
    # 임계 안쪽(|-1.0| < 2.0)이면 매그니튜드 게이트 있어도 통과.
    ind_shallow = {"macd_hist": -1.0, "macd_hist_prev": -1.5}
    assert algorithms._momentum_not_worsening(ind_shallow, max_abs_hist=2.0) is True


def test_momentum_magnitude_threshold_defaults_to_none_when_algo_not_in_dict() -> None:
    # 기본 빈 dict → 등록 안 된 알고는 항상 None(무효과).
    assert parameters.MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO == {}
    assert algorithms._momentum_magnitude_threshold("fng_contrarian", {"atr": 100.0}) is None


def test_momentum_magnitude_threshold_scales_by_atr(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters, "MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO", {"fng_contrarian": 0.25}
    )
    assert algorithms._momentum_magnitude_threshold("fng_contrarian", {"atr": 100.0}) == 25.0
    # atr 미수집 → None(graceful).
    assert algorithms._momentum_magnitude_threshold("fng_contrarian", {}) is None
    # 임계 dict에 없는 알고는 여전히 None.
    assert algorithms._momentum_magnitude_threshold("vix_rsi", {"atr": 100.0}) is None


def test_fng_contrarian_default_off_unaffected_by_magnitude_gate_dict() -> None:
    # 빈 dict(기본값)일 때 fng_contrarian 진입 로직은 기존 동작과 완전히 동일해야 한다.
    macro = {"arena_regime_state": "bull_trend", "fng": 20.0, "btc_drawdown_90d": -0.15}
    assert algorithms.fng_contrarian(macro, {"macd_hist": -50.0, "macd_hist_prev": -60.0}) == "long"


def test_regime_unknown_reads_raw_local_regime_before_overlay_fallback() -> None:
    assert algorithms._regime_unknown({}) is True
    assert algorithms._regime_unknown({"arena_regime_state": "unknown"}) is True
    # 오버레이(regime_state)가 뭐든 로컬이 unknown이면 unknown으로 본다 — _regime_state()의
    # 폴백과 달리 이 헬퍼는 "로컬이 실제로 분류됐는가"만 본다.
    assert (
        algorithms._regime_unknown({"arena_regime_state": "unknown", "regime_state": "BullQuiet"})
        is True
    )
    assert algorithms._regime_unknown({"arena_regime_state": "bull_trend"}) is False


def test_fng_vix_unknown_multiplier_defaults_to_noop() -> None:
    assert parameters.UNKNOWN_REGIME_SIZE_MULT_BY_ALGO == {}
    macro = {"arena_regime_state": "unknown"}
    assert algorithms.fng_vix_unknown_multiplier("fng_contrarian", macro) == 1.0
    assert algorithms.fng_vix_unknown_multiplier("vix_rsi", macro) == 1.0


def test_fng_vix_unknown_multiplier_applies_only_when_regime_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters, "UNKNOWN_REGIME_SIZE_MULT_BY_ALGO", {"fng_contrarian": 0.5, "vix_rsi": 0.65}
    )
    assert (
        algorithms.fng_vix_unknown_multiplier("fng_contrarian", {"arena_regime_state": "unknown"})
        == 0.5
    )
    assert (
        algorithms.fng_vix_unknown_multiplier("vix_rsi", {"arena_regime_state": "unknown"}) == 0.65
    )
    # 로컬 레짐이 분류돼 있으면(unknown 아님) 무효과 — 오버레이가 뭐든 상관없다.
    assert (
        algorithms.fng_vix_unknown_multiplier(
            "fng_contrarian", {"arena_regime_state": "bull_trend"}
        )
        == 1.0
    )
    # dict에 없는 알고는 항상 1.0.
    assert (
        algorithms.fng_vix_unknown_multiplier("omnibus", {"arena_regime_state": "unknown"}) == 1.0
    )


def test_fng_duration_scale_defaults_to_noop() -> None:
    assert parameters.FNG_DURATION_FEATURE_ENABLED is False
    assert algorithms.fng_duration_scale({"fng_days_below_30": 1}) == 1.0
    assert algorithms.fng_duration_scale({"fng_days_below_30": None}) == 1.0


def test_fng_duration_scale_day1_reduced_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_DURATION_FEATURE_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_DURATION_MODE", "sizing")
    monkeypatch.setattr(parameters, "FNG_DAY1_SIZE_MULT", 0.5)
    assert algorithms.fng_duration_scale({"fng_days_below_30": 0}) == 0.5
    assert algorithms.fng_duration_scale({"fng_days_below_30": 1}) == 0.5
    assert algorithms.fng_duration_scale({"fng_days_below_30": 2}) == 1.0
    assert algorithms.fng_duration_scale({"fng_days_below_30": 10}) == 1.0
    # 필드 미수집(None) → graceful 1.0.
    assert algorithms.fng_duration_scale({"fng_days_below_30": None}) == 1.0


def test_fng_duration_scale_noop_in_gate_mode(monkeypatch) -> None:
    # sizing 계산은 MODE=="sizing"일 때만 — gate 모드에선 사이징 쪽은 항상 1.0.
    monkeypatch.setattr(parameters, "FNG_DURATION_FEATURE_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_DURATION_MODE", "gate")
    assert algorithms.fng_duration_scale({"fng_days_below_30": 0}) == 1.0


def test_fng_scaled_tranches_identity_at_scale_1() -> None:
    assert algorithms.fng_scaled_tranches(1.0) is parameters.FNG_CONTRARIAN_PRICE_TRANCHES


def test_fng_scaled_tranches_scales_weight_keeps_drop() -> None:
    scaled = algorithms.fng_scaled_tranches(0.5)
    for (drop, w), (orig_drop, orig_w) in zip(scaled, parameters.FNG_CONTRARIAN_PRICE_TRANCHES):
        assert drop == orig_drop
        assert w == orig_w * 0.5


def test_fng_contrarian_gate_mode_blocks_short_duration_fear(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_DURATION_FEATURE_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_DURATION_MODE", "gate")
    monkeypatch.setattr(parameters, "FNG_DURATION_MIN_DAYS", 2)
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "fng_days_below_30": 1,
    }
    assert algorithms.fng_contrarian(macro, {}) is None
    macro["fng_days_below_30"] = 2
    assert algorithms.fng_contrarian(macro, {}) == "long"
    # 필드 미수집 → graceful(게이트 미적용).
    macro["fng_days_below_30"] = None
    assert algorithms.fng_contrarian(macro, {}) == "long"


def test_fng_contrarian_default_off_unaffected_by_duration_feature() -> None:
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "fng_days_below_30": 1,
    }
    assert algorithms.fng_contrarian(macro, {}) == "long"


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


def test_regime_trend_exit_hold_override_disabled_by_default() -> None:
    # §5-1 무회귀: 플래그 off면 항상 False(기존 즉시청산 동작 그대로).
    macro = {"arena_regime_state": "bull_trend", "funding_zscore": 0.0}
    ind = {"ema_fast": 2.0, "ema_slow": 1.0, "ema_fast_slope": 0.1, "adx": 25.0, "rsi": 50.0}
    assert algorithms.exit_hold_override("regime_trend", macro, ind) is False


def test_regime_trend_exit_hold_override_variant_a_state_conditions(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_HYSTERESIS_ENABLED", True)
    macro = {"arena_regime_state": "bull_trend", "funding_zscore": 0.0}
    # 상태조건(EMA정배열·ADX강함·RSI<70·funding미과열) 전부 참, donchian_breakout은
    # 아예 안 봄(변형A는 이벤트 조건을 보유판정에서 제외) → hold.
    ind_ok = {"ema_fast": 2.0, "ema_slow": 1.0, "ema_fast_slope": -0.1, "adx": 25.0, "rsi": 50.0}
    assert algorithms.exit_hold_override("regime_trend", macro, ind_ok) is True

    # EMA 역배열 → 청산.
    ind_bad_ema = dict(ind_ok, ema_fast=1.0, ema_slow=2.0)
    assert algorithms.exit_hold_override("regime_trend", macro, ind_bad_ema) is False

    # ADX 약화(<20) → 청산.
    ind_weak_adx = dict(ind_ok, adx=15.0)
    assert algorithms.exit_hold_override("regime_trend", macro, ind_weak_adx) is False

    # RSI 과열(>=70) → 청산.
    ind_hot_rsi = dict(ind_ok, rsi=75.0)
    assert algorithms.exit_hold_override("regime_trend", macro, ind_hot_rsi) is False

    # funding 과열 → 청산.
    macro_hot = dict(macro, funding_zscore=parameters.FUNDING_HOT_ZSCORE + 1)
    assert algorithms.exit_hold_override("regime_trend", macro_hot, ind_ok) is False


def test_regime_trend_exit_hold_override_variant_a_slope_ab(monkeypatch) -> None:
    macro = {"arena_regime_state": "bull_trend", "funding_zscore": 0.0}
    # 기울기 음전(ema_fast_slope<0), 정배열은 유지.
    ind = {"ema_fast": 2.0, "ema_slow": 1.0, "ema_fast_slope": -0.1, "adx": 25.0, "rsi": 50.0}

    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_HYSTERESIS_ENABLED", True)
    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_STATE_REQUIRE_SLOPE", False)
    # A1(기울기 제외): 정배열만 보므로 hold 유지.
    assert algorithms.exit_hold_override("regime_trend", macro, ind) is True

    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_STATE_REQUIRE_SLOPE", True)
    # A2(기울기 포함): 기울기 음전이라 청산.
    assert algorithms.exit_hold_override("regime_trend", macro, ind) is False


def test_regime_trend_exit_hold_override_variant_b_donchian_exit(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_HYSTERESIS_ENABLED", True)
    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_MODE", "donchian_exit")
    macro = {"arena_regime_state": "bull_trend", "funding_zscore": 0.0}
    # 종가가 하단 채널 위 → 보유.
    ind_above = {"close": 105.0, "donchian_lower": 100.0}
    assert algorithms.exit_hold_override("regime_trend", macro, ind_above) is True
    # 종가가 하단 이탈 → 청산.
    ind_below = {"close": 95.0, "donchian_lower": 100.0}
    assert algorithms.exit_hold_override("regime_trend", macro, ind_below) is False
    # 지표 미산출(0) → graceful, 기존 동작(즉시청산) 유지.
    ind_missing = {"close": 105.0, "donchian_lower": 0.0}
    assert algorithms.exit_hold_override("regime_trend", macro, ind_missing) is False


def test_regime_trend_exit_hold_override_no_hysteresis_bypass(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_EXIT_HYSTERESIS_ENABLED", True)
    # risk-off·breadth붕괴·stablecoin수축은 히스테리시스에 양보하지 않고 즉시청산.
    ind_ok = {"ema_fast": 2.0, "ema_slow": 1.0, "adx": 25.0, "rsi": 50.0, "funding_zscore": 0.0}

    macro_risk_off = {"arena_regime_state": "bear_trend"}
    assert algorithms.exit_hold_override("regime_trend", macro_risk_off, ind_ok) is False

    macro_breadth = {
        "arena_regime_state": "bull_trend",
        "breadth_up_ratio": parameters.BREADTH_HEALTHY_MIN - 0.1,
    }
    assert algorithms.exit_hold_override("regime_trend", macro_breadth, ind_ok) is False

    macro_stable = {
        "arena_regime_state": "bull_trend",
        "stablecoin_supply_zscore": parameters.STABLECOIN_CONTRACTION_Z - 1,
    }
    assert algorithms.exit_hold_override("regime_trend", macro_stable, ind_ok) is False


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
    # v28: WI-1 활성화(MULTI_FACTOR_REGIME_REQUIRED=True)로 레짐(방향성)이 필수 조건이 됨.
    # unknown/Transitional은 강세도 횡보도 아니므로 direction_regime_ok가 최우선 veto.
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

    assert reason == "veto:direction_regime_ok"
