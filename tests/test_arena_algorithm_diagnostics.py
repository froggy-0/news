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


def test_fng_contrarian_relaxed_mode_defaults_on_with_v34() -> None:
    assert parameters.FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED is True
    assert parameters.FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES == 2


def test_liquidation_exhaustion_gate_defaults_to_noop() -> None:
    # WI-9 v2(2026-08-10, 검증 전) — 기본 off라 어떤 asymmetry 값이든 항상 통과.
    assert parameters.LIQUIDATION_EXHAUSTION_GATE_ENABLED is False
    assert algorithms._liquidation_exhaustion_sufficient({}) is True
    assert algorithms._liquidation_exhaustion_sufficient({"liq_asymmetry_24h": 0.99}) is True


def test_liquidation_exhaustion_gate_blocks_ongoing_selloff_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "LIQUIDATION_EXHAUSTION_GATE_ENABLED", True)
    monkeypatch.setattr(parameters, "LIQUIDATION_EXHAUSTION_MAX_ASYMMETRY", 0.5)
    # 롱청산(투매) 지배(0.9 > 0.5) → 아직 소진 안 됨 → 차단.
    assert algorithms._liquidation_exhaustion_sufficient({"liq_asymmetry_24h": 0.9}) is False
    # 균형 근처(0.1 <= 0.5) → 통과.
    assert algorithms._liquidation_exhaustion_sufficient({"liq_asymmetry_24h": 0.1}) is True
    # 미관측(None, 데이터부족) → graceful pass.
    assert algorithms._liquidation_exhaustion_sufficient({}) is True


def test_fng_contrarian_default_off_unaffected_by_liquidation_gate() -> None:
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "liq_asymmetry_24h": 0.99,  # 극단값이어도 게이트 off라 무영향.
    }
    assert algorithms.fng_contrarian(macro, {}) == "long"


def test_fng_contrarian_blocked_by_liquidation_gate_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "LIQUIDATION_EXHAUSTION_GATE_ENABLED", True)
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "liq_asymmetry_24h": 0.9,
    }
    assert algorithms.fng_contrarian(macro, {}) is None
    diagnostic = algorithms.explain_signal("fng_contrarian", macro, {})
    assert "liquidation_exhaustion_sufficient" in diagnostic["vetoes"]
    macro["liq_asymmetry_24h"] = 0.1
    assert algorithms.fng_contrarian(macro, {}) == "long"


def test_omnibus_rebound_default_off_unaffected_by_liquidation_gate() -> None:
    macro = {"arena_regime_state": "bear_trend", "liq_asymmetry_24h": 0.99}
    ind = {
        "rsi": 30.0,
        "bb_pos": 0.1,
        "macd_hist": -1.0,
        "macd_hist_prev": -2.0,
        "return_24h": -0.03,
        "atr_pct": 0.0,
    }
    assert algorithms.omnibus(macro, ind) == "long"


def test_omnibus_rebound_blocked_by_liquidation_gate_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "LIQUIDATION_EXHAUSTION_GATE_ENABLED", True)
    macro = {"arena_regime_state": "bear_trend", "liq_asymmetry_24h": 0.9}
    ind = {
        "rsi": 30.0,
        "bb_pos": 0.1,
        "macd_hist": -1.0,
        "macd_hist_prev": -2.0,
        "return_24h": -0.03,
        "atr_pct": 0.0,
    }
    assert algorithms.omnibus(macro, ind) is None
    diagnostic = algorithms.explain_signal("omnibus", macro, ind)
    assert "liquidation_exhaustion_sufficient" in diagnostic["vetoes"]
    macro["liq_asymmetry_24h"] = 0.1
    assert algorithms.omnibus(macro, ind) == "long"
    # UP_TREND/RANGE 레그는 완전히 무관해야 한다(레그 격리 확인, omnibus-stop-distance-design
    # 선례와 동일 원칙) — 강세 레짐에서는 게이트가 켜져 있어도 REBOUND 조건 자체가 안 걸림.
    up_macro = {"arena_regime_state": "bull_trend", "liq_asymmetry_24h": 0.99}
    up_ind = {"rsi": 40.0, "ema_fast": 2.0, "ema_slow": 1.0, "bb_pos": 0.3}
    assert algorithms.omnibus(up_macro, up_ind) == "long"


def test_fng_contrarian_strict_mode_requires_all_three_environment_conditions(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED", False)
    macro = {"arena_regime_state": "bull_trend", "fng": 20.0, "btc_drawdown_90d": -0.15}
    assert algorithms.fng_contrarian(macro, {}) == "long"
    # 환경필터 1개만 깨져도(breadth 붕괴) strict 모드에서는 즉시 차단.
    macro_breadth_collapsed = dict(macro, breadth_up_ratio=0.10)
    assert algorithms.fng_contrarian(macro_breadth_collapsed, {}) is None


def test_fng_contrarian_relaxed_mode_tolerates_one_environment_failure(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES", 2)
    # breadth 붕괴 1개 실패 → 3개 중 2개 충족(경계값) → 진입 허용.
    macro_one_fail = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "breadth_up_ratio": 0.10,
    }
    assert algorithms.fng_contrarian(macro_one_fail, {}) == "long"
    # 2개 실패(stablecoin 수축 추가) → 1개 충족 <2 → 차단.
    macro_two_fail = dict(macro_one_fail, stablecoin_supply_zscore=-3.0)
    assert algorithms.fng_contrarian(macro_two_fail, {}) is None


def test_fng_contrarian_momentum_and_risk_off_never_relaxed(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES", 0)
    macro = {"arena_regime_state": "bull_trend", "fng": 20.0}
    # 환경필터 임계를 0으로 낮춰도(전부 면제) 하락 모멘텀 악화 중이면 여전히 차단.
    ind_worsening = {"macd_hist": -2.0, "macd_hist_prev": -1.0}
    assert algorithms.fng_contrarian(macro, ind_worsening) is None
    # risk-off 레짐이면 여전히 차단.
    macro_risk_off = dict(macro, arena_regime_state="bear_trend")
    assert algorithms.fng_contrarian(macro_risk_off, {}) is None


def test_fng_contrarian_explain_signal_reports_relaxed_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_CONTRARIAN_ENTRY_MIN_SECONDARY_VOTES", 2)
    macro = {
        "arena_regime_state": "bull_trend",
        "fng": 20.0,
        "btc_drawdown_90d": -0.15,
        "breadth_up_ratio": 0.10,
    }
    diag = algorithms.explain_signal("fng_contrarian", macro, {})
    assert diag["raw_signal"] == "long"
    assert diag["thresholds"]["entry_relaxed_enabled"] is True
    assert diag["secondary_votes"] == 2
    assert diag["secondary_total"] == 3
    assert "breadth_not_collapsed" not in diag["vetoes"]
    assert "breadth_not_collapsed" in diag["failed_conditions"]


def test_vix_rsi_relaxed_mode_defaults_on_with_v34() -> None:
    assert parameters.VIX_RSI_ENTRY_RELAXED_ENABLED is True
    assert parameters.VIX_RSI_ENTRY_MIN_SECONDARY_VOTES == 1


def test_vix_rsi_strict_mode_requires_both_environment_conditions(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "VIX_RSI_ENTRY_RELAXED_ENABLED", False)
    macro = {"arena_regime_state": "bull_trend", "vix_now": 15.0, "vix_q40": 18.0}
    assert algorithms.vix_rsi(macro, {"rsi": 45.0}) == "long"
    macro_breadth_collapsed = dict(macro, breadth_up_ratio=0.10)
    assert algorithms.vix_rsi(macro_breadth_collapsed, {"rsi": 45.0}) is None


def test_vix_rsi_relaxed_mode_tolerates_one_environment_failure(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "VIX_RSI_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "VIX_RSI_ENTRY_MIN_SECONDARY_VOTES", 1)
    # breadth 붕괴 1개 실패 → 2개 중 1개 충족(경계값) → 진입 허용.
    macro_one_fail = {
        "arena_regime_state": "bull_trend",
        "vix_now": 15.0,
        "vix_q40": 18.0,
        "breadth_up_ratio": 0.10,
    }
    assert algorithms.vix_rsi(macro_one_fail, {"rsi": 45.0}) == "long"
    # 2개 실패(stablecoin 수축 추가) → 0개 충족 <1 → 차단.
    macro_two_fail = dict(macro_one_fail, stablecoin_supply_zscore=-3.0)
    assert algorithms.vix_rsi(macro_two_fail, {"rsi": 45.0}) is None


def test_vix_rsi_explain_signal_reports_relaxed_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "VIX_RSI_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "VIX_RSI_ENTRY_MIN_SECONDARY_VOTES", 1)
    macro = {
        "arena_regime_state": "bull_trend",
        "vix_now": 15.0,
        "vix_q40": 18.0,
        "breadth_up_ratio": 0.10,
    }
    diag = algorithms.explain_signal("vix_rsi", macro, {"rsi": 45.0})
    assert diag["raw_signal"] == "long"
    assert diag["secondary_votes"] == 1
    assert diag["secondary_total"] == 2
    assert "breadth_not_collapsed" not in diag["vetoes"]
    assert "breadth_not_collapsed" in diag["failed_conditions"]


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


def _regime_trend_core_ind() -> dict:
    return {
        "close": 110.0,
        "donchian_upper": 100.0,
        "adx": 25.0,
        "ema_fast": 105.0,
        "ema_slow": 100.0,
        "ema_fast_slope": 1.0,
        "rsi": 50.0,
    }


def test_regime_trend_relaxed_mode_defaults_off_with_v38_rollback() -> None:
    # arena-params-v38(2026-08-16): v33/v34 완화의 부분 롤백 — regime_trend만 v32
    # 이전(unanimous AND, 8개 전부 요구)으로 원복(evidence-criteria-framework-
    # 20260816.md 재검증에서 2×2 사후귀속 −7.62%p로 6알고 중 유일하게 뚜렷한 해악
    # 확인, 전/후반 분할도 방향 일관). 나머지 5알고 완화는 무변경.
    assert parameters.REGIME_TREND_ENTRY_RELAXED_ENABLED is False
    assert parameters.REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES == 5


def test_regime_trend_strict_mode_requires_all_eight_secondary_conditions(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_RELAXED_ENABLED", False)
    macro = {"arena_regime_state": "bull_trend"}
    ind = _regime_trend_core_ind()
    assert algorithms.regime_trend(macro, ind) == "long"
    # 부차조건 1개만 깨져도(RSI 과열) strict 모드에서는 즉시 차단.
    ind_hot_rsi = dict(ind, rsi=80.0)
    assert algorithms.regime_trend(macro, ind_hot_rsi) is None


def test_regime_trend_relaxed_mode_tolerates_up_to_three_secondary_failures(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES", 5)
    ind = _regime_trend_core_ind()
    # funding 과열 + LSR 과밀 + OI 발산 3개 실패 → 8개 중 5개 충족(경계값) → 진입 허용.
    macro_three_fail = {
        "arena_regime_state": "bull_trend",
        "funding_zscore": 2.0,
        "long_short_ratio_zscore": 3.0,
        "oi_divergence_flag": 1.0,
    }
    assert algorithms.regime_trend(macro_three_fail, ind) == "long"
    # 4개 실패(RSI 과열 추가) → 4개 충족 <5 → 차단.
    ind_hot_rsi = dict(ind, rsi=80.0)
    assert algorithms.regime_trend(macro_three_fail, ind_hot_rsi) is None


def test_regime_trend_core_conditions_never_relaxed(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES", 0)
    macro = {"arena_regime_state": "bull_trend"}
    # 부차조건 임계를 0으로 낮춰도(전부 면제) ADX(핵심조건) 미달이면 여전히 차단.
    ind_weak_adx = dict(_regime_trend_core_ind(), adx=5.0)
    assert algorithms.regime_trend(macro, ind_weak_adx) is None


def test_regime_trend_explain_signal_reports_relaxed_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES", 5)
    macro = {
        "arena_regime_state": "bull_trend",
        "funding_zscore": 2.0,
        "long_short_ratio_zscore": 3.0,
        "oi_divergence_flag": 1.0,
    }
    diag = algorithms.explain_signal("regime_trend", macro, _regime_trend_core_ind())
    assert diag["raw_signal"] == "long"
    assert diag["thresholds"]["entry_relaxed_enabled"] is True
    assert diag["secondary_votes"] == 5
    assert diag["secondary_total"] == 8
    # relaxed 모드에서는 개별 부차조건 실패가 vetoes에 안 들어간다(단독으로 안 막으므로).
    assert "funding_not_hot" not in diag["vetoes"]
    assert "funding_not_hot" in diag["failed_conditions"]


def _macd_momentum_core_ind() -> dict:
    return {
        "macd_hist": 5.0,
        "macd_hist_prev": 3.0,
        "rsi": 50.0,
        "bb_width": 10.0,
        "adx": 25.0,
    }


def test_macd_momentum_relaxed_mode_defaults_on_with_v34() -> None:
    # arena-params-v34(2026-08-07): v33(4)에서 한 단계 더 완화된 기본값이어야 한다.
    assert parameters.MACD_MOMENTUM_ENTRY_RELAXED_ENABLED is True
    assert parameters.MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES == 3


def test_macd_momentum_strict_mode_requires_all_six_secondary_conditions(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)  # 레거시 MACD 경로 검증
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED", False)
    macro = {"arena_regime_state": "bull_trend"}
    ind = _macd_momentum_core_ind()
    assert algorithms.macd_momentum(macro, ind) == "long"
    macro_lsr_crowded = dict(macro, long_short_ratio_zscore=3.0)
    assert algorithms.macd_momentum(macro_lsr_crowded, ind) is None


def test_macd_momentum_relaxed_mode_tolerates_up_to_two_secondary_failures(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)  # 레거시 MACD 경로 검증
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES", 4)
    ind = _macd_momentum_core_ind()
    # LSR 과밀 + OI 발산 2개 실패 → 6개 중 4개 충족(경계값) → 진입 허용.
    macro_two_fail = {
        "arena_regime_state": "bull_trend",
        "long_short_ratio_zscore": 3.0,
        "oi_divergence_flag": 1.0,
    }
    assert algorithms.macd_momentum(macro_two_fail, ind) == "long"
    # 3개 실패(펀딩 과열 추가) → 3개 충족 <4 → 차단.
    macro_three_fail = dict(macro_two_fail, funding_zscore=2.0)
    assert algorithms.macd_momentum(macro_three_fail, ind) is None


def test_macd_momentum_risk_off_never_relaxed(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)  # 레거시 MACD 경로 검증
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES", 0)
    macro = {"arena_regime_state": "bear_trend"}  # risk-off
    assert algorithms.macd_momentum(macro, _macd_momentum_core_ind()) is None


def test_macd_momentum_explain_signal_reports_relaxed_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)  # 레거시 MACD 경로 검증
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED", True)
    monkeypatch.setattr(parameters, "MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES", 4)
    macro = {
        "arena_regime_state": "bull_trend",
        "long_short_ratio_zscore": 3.0,
        "oi_divergence_flag": 1.0,
    }
    diag = algorithms.explain_signal("macd_momentum", macro, _macd_momentum_core_ind())
    assert diag["raw_signal"] == "long"
    assert diag["secondary_votes"] == 4
    assert diag["secondary_total"] == 6


# ── Nonlinear TSMOM (macd_momentum 대체, v35(2026-08-08) 기본 활성화 — 레거시 대비
#    walk-forward 6/6 구간 개선 근거. docs/arena/research/nonlinear-tsmom-design-
#    20260808.md §9) ──────────────────────────────────────────────────────────


def test_tsmom_nl_enabled_by_default_since_v35() -> None:
    assert parameters.TSMOM_NL_ENABLED is True
    assert parameters.TSMOM_NL_LOOKBACK_BARS == 126
    assert parameters.TSMOM_NL_VOL_MODE == "ewma"
    assert parameters.TSMOM_NL_MIN_SIGNAL == 0.0


def test_tsmom_nl_signal_none_when_return_missing() -> None:
    assert algorithms._tsmom_nl_signal({}) is None


def test_tsmom_nl_signal_none_when_vol_zero() -> None:
    ind = {"tsmom_nl_return_180": 0.1, "realized_vol_24h": 0.0}
    assert algorithms._tsmom_nl_signal(ind) is None


def test_tsmom_nl_signal_computes_expected_value(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 180)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "rv6")
    ind = {"tsmom_nl_return_180": 0.18, "realized_vol_24h": 0.01}
    # s = ret / (sqrt(T)*vol) = 0.18 / (sqrt(180)*0.01)
    import math

    expected = 0.18 / (math.sqrt(180) * 0.01)
    assert algorithms._tsmom_nl_signal(ind) == expected


def test_tsmom_nl_signal_uses_ewma_vol_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 126)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "ewma")
    ind = {
        "tsmom_nl_return_126": 0.1,
        "realized_vol_24h": 0.02,
        "tsmom_nl_vol_ewma": 0.01,
    }
    import math

    expected = 0.1 / (math.sqrt(126) * 0.01)
    assert algorithms._tsmom_nl_signal(ind) == expected


def test_tsmom_nl_position_multiplier_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)
    assert algorithms.tsmom_nl_position_multiplier({}, {}) == 1.0


def test_tsmom_nl_position_multiplier_zero_for_nonpositive_signal(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", True)
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 180)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "rv6")
    ind = {"tsmom_nl_return_180": -0.1, "realized_vol_24h": 0.01}
    assert algorithms.tsmom_nl_position_multiplier({}, ind) == 0.0
    assert algorithms.tsmom_nl_position_multiplier({}, {}) == 0.0  # 데이터 없음


def test_tsmom_nl_position_multiplier_clamped_to_weight_cap(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", True)
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 180)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "rv6")
    monkeypatch.setattr(parameters, "TSMOM_NL_WEIGHT_CAP", 0.5)
    # s=1이면 f(s)=0.5(이론적 최댓값) — 매우 강한 신호(대량 vol 대비 큰 T봉 수익률)로 근사.
    import math

    bars = 180
    vol = 0.01
    ret_for_s1 = math.sqrt(bars) * vol  # s = ret/(sqrt(T)*vol) = 1
    ind = {f"tsmom_nl_return_{bars}": ret_for_s1, "realized_vol_24h": vol}
    mult = algorithms.tsmom_nl_position_multiplier({}, ind)
    assert abs(mult - 0.5) < 1e-9
    # 극단적으로 큰 신호도 상한(WEIGHT_CAP)을 넘지 않는다.
    ind_extreme = {f"tsmom_nl_return_{bars}": ret_for_s1 * 100, "realized_vol_24h": vol}
    assert algorithms.tsmom_nl_position_multiplier({}, ind_extreme) <= 0.5


def test_macd_momentum_uses_tsmom_nl_signal_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", True)
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 180)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "rv6")
    monkeypatch.setattr(parameters, "TSMOM_NL_MIN_SIGNAL", 0.0)
    macro = {"arena_regime_state": "bull_trend"}
    ind_positive = {"tsmom_nl_return_180": 0.1, "realized_vol_24h": 0.01}
    assert algorithms.macd_momentum(macro, ind_positive) == "long"
    ind_negative = {"tsmom_nl_return_180": -0.1, "realized_vol_24h": 0.01}
    assert algorithms.macd_momentum(macro, ind_negative) is None
    # risk-off는 TSMOM_NL 경로에서도 하드 veto — 완화 대상 아님.
    macro_risk_off = {"arena_regime_state": "bear_trend"}
    assert algorithms.macd_momentum(macro_risk_off, ind_positive) is None
    # 완전 무시되던 MACD 관련 필드가 있어도 영향 없음(신호 로직 전면 교체 확인).
    ind_with_stale_macd = dict(ind_positive, macd_hist=-999.0, macd_hist_prev=999.0)
    assert algorithms.macd_momentum(macro, ind_with_stale_macd) == "long"


def test_macd_momentum_explain_signal_tsmom_nl_branch(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", True)
    monkeypatch.setattr(parameters, "TSMOM_NL_LOOKBACK_BARS", 180)
    monkeypatch.setattr(parameters, "TSMOM_NL_VOL_MODE", "rv6")
    monkeypatch.setattr(parameters, "TSMOM_NL_MIN_SIGNAL", 0.0)
    macro = {"arena_regime_state": "bull_trend"}
    ind = {"tsmom_nl_return_180": 0.1, "realized_vol_24h": 0.01}
    diag = algorithms.explain_signal("macd_momentum", macro, ind)
    assert diag["raw_signal"] == "long"
    assert diag["thresholds"]["lookback_bars"] == 180
    assert diag["factors"]["tsmom_nl_signal"] is not None
