"""Meridian(v36, 리서치 종합 롱/숏 알고) — 신호·leg 판정·트랙 스코프·사이징 회귀 테스트.

설계: docs/arena/research/meridian-combined-long-short-design-20260815.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arena import algorithms, backtest, parameters, short_signals


def test_meridian_registered_in_algorithms() -> None:
    assert algorithms.ALGORITHMS["meridian"] is algorithms.meridian_long


def test_meridian_short_registered_in_perp_short_algorithms() -> None:
    assert short_signals.PERP_SHORT_ALGORITHMS["meridian"] is algorithms.meridian_short


def test_meridian_perp_short_tracks_enabled_for_all_three_assets() -> None:
    for symbol in ("BTCUSDT-PERP", "ETHUSDT-PERP", "SOLUSDT-PERP"):
        assert (symbol, "meridian") in parameters.PERP_SHORT_ENABLED_TRACKS


# ── active leg 판정 ──────────────────────────────────────────────────────


def test_active_leg_trend_requires_local_bull_trend_and_positive_signal() -> None:
    macro = {"arena_regime_state": "bull_trend"}
    ind = {"tsmom_nl_return_126": 0.1, "tsmom_nl_vol_ewma": 0.01}
    assert algorithms.meridian_active_leg(macro, ind) == "trend"


def test_active_leg_trend_not_triggered_outside_bull_trend() -> None:
    # sideways는 로컬 bull_trend가 아니므로 추세 leg 미발화(역발산 조건도 없으면 None).
    macro = {"arena_regime_state": "sideways"}
    ind = {"tsmom_nl_return_126": 0.1, "tsmom_nl_vol_ewma": 0.01}
    assert algorithms.meridian_active_leg(macro, ind) is None


def test_active_leg_trend_overlay_fallback_label_does_not_trigger() -> None:
    # BullQuiet(매크로 오버레이 라벨)은 _regime_state 폴백으론 통과하지만, 추세 leg는
    # macro["arena_regime_state"] 원시값이 "bull_trend"일 때만 발화(설계 §2-2 원칙,
    # _below_ema_trend_strict와 동일 패턴) — 오버레이 폴백 라벨은 제외.
    macro = {"arena_regime_state": "unknown", "regime_state": "BullQuiet"}
    ind = {"tsmom_nl_return_126": 0.1, "tsmom_nl_vol_ewma": 0.01}
    assert algorithms.meridian_active_leg(macro, ind) is None


def test_active_leg_reversion_fng_fires_regardless_of_regime() -> None:
    macro = {"arena_regime_state": "sideways", "fng": 20.0}
    ind = {"rsi": 50.0}
    assert algorithms.meridian_active_leg(macro, ind) == "reversion"


def test_active_leg_reversion_vix_rsi_fires() -> None:
    macro = {"arena_regime_state": "sideways", "vix_now": 15.0, "vix_q40": 20.0}
    ind = {"rsi": 40.0}
    assert algorithms.meridian_active_leg(macro, ind) == "reversion"


def test_active_leg_risk_off_blocks_both_legs() -> None:
    macro = {"arena_regime_state": "bear_trend", "fng": 10.0}
    ind = {"tsmom_nl_return_126": 0.5, "tsmom_nl_vol_ewma": 0.01, "rsi": 30.0}
    assert algorithms.meridian_active_leg(macro, ind) is None


def test_active_leg_none_when_nothing_qualifies() -> None:
    macro = {"arena_regime_state": "sideways", "fng": 55.0}
    ind = {"rsi": 55.0}
    assert algorithms.meridian_active_leg(macro, ind) is None


# ── meridian_long/meridian_short 신호 함수 ──────────────────────────────


def test_meridian_long_mirrors_active_leg() -> None:
    macro = {"arena_regime_state": "bull_trend"}
    ind = {"tsmom_nl_return_126": 0.1, "tsmom_nl_vol_ewma": 0.01}
    assert algorithms.meridian_long(macro, ind) == "long"
    assert algorithms.meridian_long({"arena_regime_state": "sideways"}, {}) is None


def test_meridian_short_fires_on_extreme_greed() -> None:
    macro = {"arena_regime_state": "sideways", "fng": 80.0}
    assert algorithms.meridian_short(macro, {"rsi": 50.0}) == "short"


def test_meridian_short_fires_on_rsi_overheat_when_not_bullish() -> None:
    macro = {"arena_regime_state": "sideways", "fng": 50.0}
    assert algorithms.meridian_short(macro, {"rsi": 80.0}) == "short"


def test_meridian_short_does_not_fade_overheat_during_bull_trend() -> None:
    # 강세추세 중엔 RSI 과열이어도 fade 안 함(추세지속과 국소천장 구분, 설계 §2-3).
    macro = {"arena_regime_state": "bull_trend", "fng": 50.0}
    assert algorithms.meridian_short(macro, {"rsi": 80.0}) is None


def test_meridian_short_blocked_in_risk_off() -> None:
    macro = {"arena_regime_state": "bear_trend", "fng": 90.0}
    assert algorithms.meridian_short(macro, {"rsi": 90.0}) is None


def test_meridian_short_none_below_thresholds() -> None:
    macro = {"arena_regime_state": "sideways", "fng": 50.0}
    assert algorithms.meridian_short(macro, {"rsi": 50.0}) is None


# ── explain_signal 진단 ──────────────────────────────────────────────────


def test_explain_signal_meridian_reports_active_leg() -> None:
    macro = {"arena_regime_state": "bull_trend"}
    ind = {"tsmom_nl_return_126": 0.1, "tsmom_nl_vol_ewma": 0.01}
    diag = algorithms.explain_signal("meridian", macro, ind)
    assert diag["raw_signal"] == "long"
    assert diag["factors"]["active_leg"] == "trend"
    assert "unknown_algo" not in diag["failed_conditions"]


# ── 트랙 스코프 ───────────────────────────────────────────────────────────


def test_meridian_scoped_to_perp_tracks_only() -> None:
    assert parameters.algorithm_in_track_scope("meridian", "BTCUSDT-PERP") is True
    assert parameters.algorithm_in_track_scope("meridian", "ETHUSDT-PERP") is True
    assert parameters.algorithm_in_track_scope("meridian", "SOLUSDT-PERP") is True
    assert parameters.algorithm_in_track_scope("meridian", "BTCUSDT") is False
    assert parameters.algorithm_in_track_scope("meridian", "ETHUSDT") is False


def test_v39_non_short_algos_scoped_to_spot_only() -> None:
    """v39: perp에서 숏을 안 쓰는 기존 알고는 spot만 신규진입 허용, perp는 차단."""
    for algo_id in (
        "regime_trend",
        "fng_contrarian",
        "macd_momentum",
        "multi_factor",
        "omnibus",
    ):
        for spot_symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            assert parameters.algorithm_in_track_scope(algo_id, spot_symbol) is True
        for perp_symbol in ("BTCUSDT-PERP", "ETHUSDT-PERP", "SOLUSDT-PERP"):
            assert parameters.algorithm_in_track_scope(algo_id, perp_symbol) is False


def test_v39_vix_rsi_scoped_to_spot_and_eth_perp_only() -> None:
    """vix_rsi는 ETH-PERP에서만 숏이 승인돼 있어(PERP_SHORT_ENABLED_TRACKS) 그 트랙만
    perp 신규진입 허용, BTC/SOL-PERP는 차단."""
    for spot_symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert parameters.algorithm_in_track_scope("vix_rsi", spot_symbol) is True
    assert parameters.algorithm_in_track_scope("vix_rsi", "ETHUSDT-PERP") is True
    assert parameters.algorithm_in_track_scope("vix_rsi", "BTCUSDT-PERP") is False
    assert parameters.algorithm_in_track_scope("vix_rsi", "SOLUSDT-PERP") is False


# ── 사이징 배선(backtest.py 회귀) ─────────────────────────────────────────


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _force_local_regime(monkeypatch, regime_state: str) -> None:
    """run_replay 루프는 매 bar regime.classify_regime_variant()로 arena_regime_state를
    지표에서 직접 재계산해 macro에 주입한다 — 테스트 프레임이 macro에 직접 넣은
    arena_regime_state는 이 재계산으로 덮어써진다(test_arena_backtest.py와 동일 헬퍼)."""
    from arena import regime as regime_module

    def _fixed(
        indicators, market_features=None, macro=None, *, variant=regime_module.REGIME_VARIANT_STRICT
    ):
        return regime_module.RegimeDecision(
            regime_state=regime_state, confidence=1.0, reason={}, feature_snapshot={}
        )

    monkeypatch.setattr(regime_module, "classify_regime_variant", _fixed)
    monkeypatch.setattr(backtest.regime, "classify_regime_variant", _fixed)


def _frame(
    index: int,
    *,
    close: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    atr: float = 1.0,
    indicators: dict | None = None,
    macro: dict | None = None,
) -> backtest.ReplayFrame:
    open_time = _dt(0) + timedelta(hours=4 * index)
    close_time = open_time + timedelta(hours=4)
    ind = {"rsi": 50.0, "macd_hist": 0.0, "bb_pos": 0.5, "atr": atr}
    if indicators:
        ind.update(indicators)
    return backtest.ReplayFrame(
        bar=backtest.ReplayBar(
            open_time=open_time,
            close_time=close_time,
            open=close,
            high=high if high is not None else close + 1.0,
            low=low if low is not None else close - 1.0,
            close=close,
        ),
        indicators=ind,
        macro=macro or {},
    )


def test_backtest_meridian_trend_leg_applies_tsmom_sizing_multiplier(monkeypatch) -> None:
    _force_local_regime(monkeypatch, "bull_trend")
    trend_macro = {"arena_regime_state": "bull_trend"}
    trend_ind = {"tsmom_nl_return_126": 0.15, "tsmom_nl_vol_ewma": 0.01}

    frames = [
        _frame(0, macro=trend_macro, indicators=trend_ind),
        _frame(1, close=101.0, high=102.0, low=100.0, macro=trend_macro, indicators=trend_ind),
    ]
    result = backtest.run_replay(
        frames,
        strategy_fns={"meridian": algorithms.meridian_long},
        settings=backtest.BacktestSettings(close_open_at_end=True),
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    s = algorithms._tsmom_nl_signal(trend_ind)
    expected_mult = max(0.0, min(parameters.TSMOM_NL_WEIGHT_CAP, s / (s * s + 1.0)))
    # combined_position_weight()는 VOL_WEIGHT_MIN(0.25) 이상으로 클램프되므로, f(s) 곱이
    # 적용됐다면 최종 비중은 그 클램프보다 작아야 한다(사이징이 실제로 걸렸다는 증거).
    assert trade.position_weight == pytest.approx(parameters.VOL_WEIGHT_MIN * expected_mult)
    assert trade.position_weight < parameters.VOL_WEIGHT_MIN


def test_backtest_meridian_reversion_leg_skips_tsmom_sizing(monkeypatch) -> None:
    _force_local_regime(monkeypatch, "sideways")
    reversion_macro = {"arena_regime_state": "sideways", "fng": 20.0}
    frames = [
        _frame(0, macro=reversion_macro),
        _frame(1, close=101.0, high=102.0, low=100.0, macro=reversion_macro),
    ]
    result = backtest.run_replay(
        frames,
        strategy_fns={"meridian": algorithms.meridian_long},
        settings=backtest.BacktestSettings(close_open_at_end=True),
    )
    assert len(result.trades) == 1
    # 역발산 leg는 TSMOM f(s) 사이징을 곱하지 않으므로 기본 클램프(VOL_WEIGHT_MIN) 그대로.
    assert result.trades[0].position_weight == pytest.approx(parameters.VOL_WEIGHT_MIN)


def test_backtest_meridian_short_applies_size_dampener(monkeypatch) -> None:
    _force_local_regime(monkeypatch, "sideways")
    short_macro = {"arena_regime_state": "sideways", "fng": 80.0}
    frames = [
        _frame(0, macro=short_macro),
        _frame(1, close=99.0, high=100.0, low=98.0, macro=short_macro),
    ]
    result = backtest.run_replay(
        frames,
        strategy_fns={"meridian": algorithms.meridian_short},
        settings=backtest.BacktestSettings(product_type="usdm_perp", close_open_at_end=True),
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "short"
    assert trade.position_weight == pytest.approx(
        parameters.VOL_WEIGHT_MIN * parameters.MERIDIAN_SHORT_SIZE_DAMPENER
    )
