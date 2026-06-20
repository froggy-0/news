from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arena import algorithms, allocator, backtest, frequency, market_structure, regime, sleeves


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _trend_indicators(**overrides) -> dict:
    data = {
        "rsi": 50.0,
        "close": 100.0,
        "macd_hist": 1.0,
        "atr": 5.0,
        "atr_pct": 0.01,
        "bb_width": 5.0,
        "return_24h": 0.03,
        "return_72h": 0.08,
        "range_24h_atr": 2.0,
        "ema_fast": 110.0,
        "ema_slow": 100.0,
        "ema_fast_slope": 1.0,
    }
    data.update(overrides)
    return data


def test_market_structure_parsers_skip_malformed_rows() -> None:
    fetched_at = _dt(8)

    assert market_structure.parse_funding_row({}, fetched_at=fetched_at) is None
    assert (
        market_structure.parse_open_interest_row(
            {},
            symbol="BTCUSDT",
            period="4h",
            fetched_at=fetched_at,
        )
        is None
    )
    assert (
        market_structure.parse_mark_price_kline(
            [],
            symbol="BTCUSDT",
            interval="4h",
            price_type=market_structure.MARK_PRICE_TYPE,
            fetched_at=fetched_at,
        )
        is None
    )


def test_market_structure_builds_4h_feature_snapshot() -> None:
    fetched_at = _dt(8)
    funding = [
        {
            "fundingTime": int(_dt(0).timestamp() * 1000),
            "fundingRate": "0.001",
            "symbol": "BTCUSDT",
        },
        {
            "fundingTime": int(_dt(8).timestamp() * 1000),
            "fundingRate": "0.002",
            "symbol": "BTCUSDT",
        },
    ]
    funding_rows = [
        market_structure.parse_funding_row(row, fetched_at=fetched_at) for row in funding
    ]
    oi_rows = [
        market_structure.parse_open_interest_row(
            {
                "timestamp": int((_dt(8) - timedelta(hours=24)).timestamp() * 1000),
                "sumOpenInterestValue": "1000",
            },
            symbol="BTCUSDT",
            period="4h",
            fetched_at=fetched_at,
        ),
        market_structure.parse_open_interest_row(
            {
                "timestamp": int(_dt(8).timestamp() * 1000),
                "sumOpenInterestValue": "1100",
            },
            symbol="BTCUSDT",
            period="4h",
            fetched_at=fetched_at,
        ),
    ]
    mark_rows = [
        market_structure.parse_mark_price_kline(
            [
                int(_dt(4).timestamp() * 1000),
                "100",
                "102",
                "99",
                "101",
                "0",
                int(_dt(8).timestamp() * 1000),
            ],
            symbol="BTCUSDT",
            interval="4h",
            price_type=market_structure.MARK_PRICE_TYPE,
            fetched_at=fetched_at,
        )
    ]

    features = market_structure.build_market_features(
        data_timestamp=_dt(8),
        spot_close=100.0,
        funding_rates=[row for row in funding_rows if row],
        open_interest=[row for row in oi_rows if row],
        basis=[],
        mark_price_bars=[row for row in mark_rows if row],
        premium_index_bars=[],
        errors=[],
    )

    assert features["quality_status"] == "ok"
    assert features["latest_funding_rate"] == pytest.approx(0.002)
    assert features["funding_rate_24h"] == pytest.approx(0.003)
    assert features["open_interest_change_24h"] == pytest.approx(0.1)
    assert features["mark_spot_basis"] == pytest.approx(0.01)


def test_regime_gate_classifies_bull_bear_sideways_and_stress() -> None:
    assert regime.classify_regime(_trend_indicators()).regime_state == regime.REGIME_BULL_TREND
    assert (
        regime.classify_regime(
            _trend_indicators(
                return_24h=-0.03,
                return_72h=-0.08,
                ema_fast=90.0,
                ema_slow=100.0,
                ema_fast_slope=-1.0,
            )
        ).regime_state
        == regime.REGIME_BEAR_TREND
    )
    assert (
        regime.classify_regime(
            _trend_indicators(return_24h=0.005, return_72h=0.0, bb_width=2.0)
        ).regime_state
        == regime.REGIME_SIDEWAYS
    )
    assert (
        regime.classify_regime(_trend_indicators(return_24h=0.08)).regime_state
        == regime.REGIME_STRESS
    )


def test_trend_core_v1_is_shadow_only_and_symmetric() -> None:
    bull_macro = {"arena_regime_state": regime.REGIME_BULL_TREND}
    bear_macro = {"arena_regime_state": regime.REGIME_BEAR_TREND}

    assert algorithms.trend_core_v1(bull_macro, _trend_indicators()) == "long"
    assert (
        algorithms.trend_core_v1(
            bear_macro,
            _trend_indicators(
                macd_hist=-1.0,
                ema_fast=90.0,
                ema_slow=100.0,
                ema_fast_slope=-1.0,
            ),
        )
        == "short"
    )
    assert "trend_core_v1" not in algorithms.ALGORITHMS


def test_trend_core_shadow_cost_filter_blocks_low_edge_signal() -> None:
    profile = frequency.get_frequency_profile("research_1h")
    cost = frequency.get_cost_scenario("research_1h", "base")

    signal, regime_decision = sleeves.trend_core_sleeve(
        _trend_indicators(close=100000.0, atr=1.0, macd_hist=0.11),
        {},
        {},
        profile=profile,
        cost_scenario=cost,
    )

    assert regime_decision.regime_state == regime.REGIME_BULL_TREND
    assert signal.direction is None
    assert signal.target_weight == 0.0
    assert signal.reason["blocked_reason"] == "cost_aware_edge_below_threshold"
    assert signal.reason["cost_filter"]["passed"] is False
    assert signal.feature_snapshot["frequency_profile"]["frequency_profile_id"] == "research_1h"
    assert signal.feature_snapshot["cost_scenario"]["cost_scenario_id"] == "base"


def test_allocator_shadow_budget_does_not_create_live_position() -> None:
    signal = sleeves.SleeveSignal(
        sleeve_id="trend_core",
        algo_id="trend_core_v1",
        direction="long",
        confidence=0.8,
        raw_score=0.8,
        target_weight=1.5,
        reason={},
        feature_snapshot={},
    )

    decision = allocator.allocate_shadow(signal, regime_snapshot={}, risk_snapshot={})

    assert decision.allowed is True
    assert decision.target_weight == pytest.approx(0.6)
    assert decision.action == "shadow_open"


def _frame(index: int, close: float) -> backtest.ReplayFrame:
    open_time = _dt(0) + timedelta(hours=4 * index)
    return backtest.ReplayFrame(
        bar=backtest.ReplayBar(
            open_time=open_time,
            close_time=open_time + timedelta(hours=4),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
        ),
        indicators={"rsi": 50.0, "macd_hist": 0.0, "bb_pos": 0.5, "atr": 1.0},
    )


def test_backtest_includes_funding_in_net_return() -> None:
    def scripted(_macro, _ind):
        return "long"

    result = backtest.run_replay(
        [_frame(0, 100.0), _frame(1, 101.0)],
        strategy_fns={"funding_algo": scripted},
        settings=backtest.BacktestSettings(
            close_open_at_end=True,
            product_type="usdm_perp_paper",
            position_semantics="perp_long_short_sim",
        ),
        funding_events=[
            backtest.FundingEvent(
                symbol="BTCUSDT",
                funding_time=_dt(8),
                funding_rate=0.001,
            )
        ],
    )

    trade = result.trades[0]
    assert trade.gross_ret_pct == pytest.approx(0.01)
    assert trade.trading_cost_pct == pytest.approx(0.001)
    assert trade.funding_ret_pct == pytest.approx(-0.001)
    assert trade.ret_pct == pytest.approx(0.008)
