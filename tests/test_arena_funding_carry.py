"""funding_carry(v43, 델타중립 펀딩비 캐리) — 순수함수·신호·등록·양방향 가격손절
비활성화 회귀 테스트.

설계 근거: parameters.py PARAMS_VERSION v43 changelog 및
docs/arena/research/funding-carry-sleeve-design-20260818.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arena import algorithms, backtest, market_structure, parameters, short_signals

# ── market_structure.trailing_funding_mean ──────────────────────────────


def test_trailing_funding_mean_averages_rows_within_lookback() -> None:
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    rows = [
        {"funding_time": (now - timedelta(hours=4)).isoformat(), "funding_rate": 0.0002},
        {"funding_time": (now - timedelta(hours=12)).isoformat(), "funding_rate": 0.0004},
        {"funding_time": (now - timedelta(hours=20)).isoformat(), "funding_rate": 0.0006},
    ]
    mean = market_structure.trailing_funding_mean(rows, now=now, lookback_hours=24.0)
    assert mean is not None
    assert abs(mean - 0.0004) < 1e-9


def test_trailing_funding_mean_excludes_rows_outside_lookback() -> None:
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    rows = [
        {"funding_time": (now - timedelta(hours=4)).isoformat(), "funding_rate": 0.001},
        {"funding_time": (now - timedelta(hours=200)).isoformat(), "funding_rate": -0.01},
    ]
    mean = market_structure.trailing_funding_mean(rows, now=now, lookback_hours=24.0)
    assert mean == 0.001


def test_trailing_funding_mean_returns_none_when_no_rows_in_window() -> None:
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    rows = [{"funding_time": (now - timedelta(hours=200)).isoformat(), "funding_rate": 0.001}]
    assert market_structure.trailing_funding_mean(rows, now=now, lookback_hours=24.0) is None


def test_trailing_funding_mean_empty_rows_returns_none() -> None:
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    assert market_structure.trailing_funding_mean([], now=now, lookback_hours=168.0) is None


def test_trailing_funding_mean_ignores_unparseable_rows() -> None:
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    rows = [
        {"funding_time": (now - timedelta(hours=4)).isoformat(), "funding_rate": 0.002},
        {"funding_time": None, "funding_rate": 0.5},
        {"funding_rate": 0.5},
    ]
    mean = market_structure.trailing_funding_mean(rows, now=now, lookback_hours=24.0)
    assert mean == 0.002


# ── 신호 함수 ────────────────────────────────────────────────────────────


def test_funding_carry_long_fires_above_threshold() -> None:
    macro = {"funding_carry_trailing_mean": parameters.FUNDING_CARRY_ENTRY_MEAN_THRESHOLD + 1e-5}
    assert algorithms.funding_carry_long(macro, {}) == "long"


def test_funding_carry_short_fires_above_threshold() -> None:
    macro = {"funding_carry_trailing_mean": parameters.FUNDING_CARRY_ENTRY_MEAN_THRESHOLD + 1e-5}
    assert algorithms.funding_carry_short(macro, {}) == "short"


def test_funding_carry_no_signal_below_threshold() -> None:
    macro = {"funding_carry_trailing_mean": -0.0001}
    assert algorithms.funding_carry_long(macro, {}) is None
    assert algorithms.funding_carry_short(macro, {}) is None


def test_funding_carry_no_signal_when_data_missing() -> None:
    assert algorithms.funding_carry_long({}, {}) is None
    assert algorithms.funding_carry_short({}, {}) is None


def test_funding_carry_disabled_flag_forces_none(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FUNDING_CARRY_ENABLED", False)
    macro = {"funding_carry_trailing_mean": 1.0}
    assert algorithms.funding_carry_long(macro, {}) is None
    assert algorithms.funding_carry_short(macro, {}) is None


def test_funding_carry_long_and_short_share_the_same_gate() -> None:
    # 두 다리가 별도 트랙에서 독립 스케줄되면서도 논리적으로 동기화되는 근거 —
    # 같은 macro 입력에 대해 항상 같은 판정(둘 다 발화 또는 둘 다 미발화).
    for mean in (-0.0002, 0.0, parameters.FUNDING_CARRY_ENTRY_MEAN_THRESHOLD + 1e-6, 0.001):
        macro = {"funding_carry_trailing_mean": mean}
        long_fires = algorithms.funding_carry_long(macro, {}) == "long"
        short_fires = algorithms.funding_carry_short(macro, {}) == "short"
        assert long_fires == short_fires


def test_explain_signal_funding_carry_reports_factor_and_thresholds() -> None:
    macro = {"funding_carry_trailing_mean": 0.0005}
    diag = algorithms.explain_signal("funding_carry", macro, {})
    assert diag["factors"]["funding_carry_trailing_mean"] == 0.0005
    assert diag["raw_signal"] == "long"
    assert "funding_carry_positive" in diag["passed_conditions"]


def test_explain_signal_funding_carry_vetoes_when_data_missing() -> None:
    diag = algorithms.explain_signal("funding_carry", {}, {})
    assert diag["raw_signal"] is None
    assert "funding_data_present" in diag["vetoes"]


# ── 등록/스코프 ──────────────────────────────────────────────────────────


def test_funding_carry_registered_in_algorithms() -> None:
    assert algorithms.ALGORITHMS["funding_carry"] is algorithms.funding_carry_long


def test_funding_carry_short_registered_in_perp_short_algorithms() -> None:
    assert short_signals.PERP_SHORT_ALGORITHMS["funding_carry"] is algorithms.funding_carry_short


def test_funding_carry_perp_short_enabled_only_for_btc_eth() -> None:
    assert ("BTCUSDT-PERP", "funding_carry") in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("ETHUSDT-PERP", "funding_carry") in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("SOLUSDT-PERP", "funding_carry") not in parameters.PERP_SHORT_ENABLED_TRACKS


def test_funding_carry_perp_long_blocked_for_btc_eth() -> None:
    # 필수 — 안 막으면 매 사이클 long_signal=="long"과 short_signal=="short"이 동시에
    # 참이 돼 short_signals.resolve()의 충돌 규칙(resolved=None)에 걸려 perp 트랙이
    # 영원히 진입 못 한다(v42 메커니즘 재사용, funding_carry는 필수 사용처).
    assert not parameters.perp_long_enabled(track_symbol="BTCUSDT-PERP", algo_id="funding_carry")
    assert not parameters.perp_long_enabled(track_symbol="ETHUSDT-PERP", algo_id="funding_carry")


def test_funding_carry_track_scope_excludes_sol_and_bare_spot_of_others() -> None:
    scope = parameters.ALGORITHM_TRACK_SCOPE["funding_carry"]
    assert scope == frozenset({"BTCUSDT", "ETHUSDT", "BTCUSDT-PERP", "ETHUSDT-PERP"})
    assert "SOLUSDT" not in scope
    assert "SOLUSDT-PERP" not in scope


def test_funding_carry_resolve_perp_track_yields_short_only() -> None:
    macro = {"funding_carry_trailing_mean": 0.001}
    decision = short_signals.resolve(
        algo_id="funding_carry",
        long_signal=algorithms.funding_carry_long(macro, {}),
        macro=macro,
        indicators={},
        short_enabled=True,
        long_enabled=parameters.perp_long_enabled(
            track_symbol="BTCUSDT-PERP", algo_id="funding_carry"
        ),
    )
    assert decision.resolved_signal == "short"
    assert not decision.conflict


def test_funding_carry_resolve_spot_track_yields_long_only() -> None:
    macro = {"funding_carry_trailing_mean": 0.001}
    decision = short_signals.resolve(
        algo_id="funding_carry",
        long_signal=algorithms.funding_carry_long(macro, {}),
        macro=macro,
        indicators={},
        short_enabled=False,
    )
    assert decision.resolved_signal == "long"


def test_funding_carry_min_hold_is_fourteen_days() -> None:
    assert parameters.MIN_HOLD_HOURS["funding_carry"] == 336.0


# ── 양방향 가격손절 비활성화 (backtest 회귀) ────────────────────────────


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _frame(
    index: int,
    *,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    atr: float = 1.0,
) -> backtest.ReplayFrame:
    open_time = _dt(0) + timedelta(hours=4 * index)
    close_time = open_time + timedelta(hours=4)
    return backtest.ReplayFrame(
        bar=backtest.ReplayBar(
            open_time=open_time,
            close_time=close_time,
            open=close,
            high=high,
            low=low,
            close=close,
        ),
        indicators={"rsi": 50.0, "macd_hist": 0.0, "bb_pos": 0.5, "atr": atr},
        macro={},
        market_features={},
    )


def test_funding_carry_long_survives_crash_without_price_stop() -> None:
    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            # atr=1.0 default → 표준 ATR손절이면 이 정도 급락은 이미 손절됐을 거리.
            _frame(1, close=70.0, low=50.0, high=101.0),
            _frame(2, close=70.0, low=50.0, high=101.0),
        ],
        strategy_fns={"funding_carry": always_long},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="spot",
            position_semantics="spot_long_flat",
        ),
    )
    # 가격손절/트레일링 트레이드가 하나도 없어야 함(포지션이 계속 열려 있으므로 trades=0).
    assert len(result.trades) == 0


def test_funding_carry_short_survives_spike_without_price_stop() -> None:
    def always_short(macro, indicators):
        return "short"

    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            # 숏 포지션 기준 급등 — 표준 ATR손절이면 이미 트리거됐을 거리.
            _frame(1, close=130.0, high=150.0, low=99.0),
            _frame(2, close=130.0, high=150.0, low=99.0),
        ],
        strategy_fns={"funding_carry": always_short},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="usdm_perp",
            position_semantics="usdm_perp_long_short",
        ),
    )
    assert len(result.trades) == 0


def test_other_algo_still_gets_price_stop_control() -> None:
    # 회귀 방지 — PRICE_STOP_DISABLED_ALGOS_ALL_DIRECTIONS는 funding_carry 전용이지,
    # 다른 알고의 가격손절까지 우연히 꺼버리면 안 된다.
    assert "regime_trend" not in parameters.PRICE_STOP_DISABLED_ALGOS_ALL_DIRECTIONS

    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, close=70.0, low=50.0, high=101.0),
        ],
        strategy_fns={"regime_trend": always_long},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="spot",
            position_semantics="spot_long_flat",
        ),
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason in ("stop_loss", "trailing_stop")
