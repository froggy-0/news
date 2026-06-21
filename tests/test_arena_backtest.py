from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from arena import backtest


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _frame(
    index: int,
    *,
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    atr: float = 1.0,
    macro: dict | None = None,
) -> backtest.ReplayFrame:
    open_time = _dt(0) + timedelta(hours=4 * index)
    close_time = open_time + timedelta(hours=4)
    return backtest.ReplayFrame(
        bar=backtest.ReplayBar(
            open_time=open_time,
            close_time=close_time,
            open=open_price,
            high=high,
            low=low,
            close=close,
        ),
        indicators={"rsi": 50.0, "macd_hist": 0.0, "bb_pos": 0.5, "atr": atr},
        macro=macro or {},
    )


def test_backtest_stop_loss_uses_intrabar_ohlc_and_live_cost_rule() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(close_open_at_end=False)
    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, open_price=99.0, high=100.0, low=97.0, close=98.0),
        ],
        strategy_fns={"test_algo": always_long},
        settings=settings,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.close_price == pytest.approx(97.5)
    assert trade.ret_pct == pytest.approx(-0.026)
    assert result.equity_curve[-1].open_position["direction"] == "long"


def test_backtest_min_hold_blocks_early_reverse_then_allows_later_reverse() -> None:
    signals = iter(["long", "short", "short"])

    def scripted(macro, indicators):
        return next(signals)

    settings = backtest.BacktestSettings(
        close_open_at_end=False,
        min_hold_hours={"test_algo": 8.0},
        product_type="usdm_perp_paper",
        position_semantics="perp_long_short_sim",
    )
    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, close=101.0),
            _frame(2, close=102.0),
        ],
        strategy_fns={"test_algo": scripted},
        settings=settings,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "signal_reverse"
    assert result.trades[0].hold_hours == pytest.approx(8.0)
    assert result.equity_curve[-1].open_position["direction"] == "short"


def test_backtest_disables_stale_macro_before_strategy_call() -> None:
    def macro_long_only(macro, indicators):
        return "long" if macro.get("regime_state") == "BullQuiet" else None

    settings = backtest.BacktestSettings(close_open_at_end=False, macro_stale_hours=36.0)
    result = backtest.run_replay(
        [
            _frame(
                0,
                macro={
                    "regime_state": "BullQuiet",
                    "reference_date": "2026-06-17",
                    "stale_hours": 1.0,
                },
            )
        ],
        strategy_fns={"macro_algo": macro_long_only},
        settings=settings,
    )

    assert result.trades == []
    assert result.equity_curve[0].open_position is None


def test_backtest_run_row_is_json_ready_and_versioned() -> None:
    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [_frame(0), _frame(1, close=101.0)],
        strategy_fns={"test_algo": always_long},
        settings=backtest.BacktestSettings(close_open_at_end=True),
        backtest_run_id="00000000-0000-0000-0000-000000000001",
    )

    row = backtest._run_row(result)

    assert row["backtest_run_id"] == "00000000-0000-0000-0000-000000000001"
    assert row["strategy_version"] == "arena-spot-v3"
    assert row["rules_snapshot"]["fee_bps"] == 5.0
    assert row["frequency_profile_id"] == "live_4h"
    assert row["indicator_profile_id"] == "time_normalized_v1"
    assert row["cost_model_version"] == "arena-cost-v2"
    assert row["cost_scenario_id"] == "base"
    assert row["rules_snapshot"]["portfolio_risk"]["max_open_positions_total"] == 3
    assert row["rules_snapshot"]["execution_product"]["target_product"] == "spot"
    assert row["rules_snapshot"]["execution_product"]["spot_execution_only"] is True
    assert row["rules_snapshot"]["execution_product"]["allow_live_short"] is False
    assert row["bar_count"] == 2
    assert row["metrics"]["by_algo"]["test_algo"]["trade_count"] == 1


def test_spot_backtest_maps_short_to_exit_or_no_trade() -> None:
    signals = iter(["short", "long", "short"])

    def scripted(macro, indicators):
        return next(signals)

    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, close=101.0),
            _frame(2, close=102.0),
        ],
        strategy_fns={"test_algo": scripted},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="spot",
            position_semantics="spot_long_flat",
        ),
    )

    assert len(result.trades) == 1
    assert result.trades[0].direction == "long"
    assert result.trades[0].exit_reason == "short_signal_spot_risk_off"
    assert all(
        point.open_position is None or point.open_position["direction"] == "long"
        for point in result.equity_curve
    )


def test_backtest_frequency_metrics_include_cost_and_turnover() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(
        close_open_at_end=True,
        fee_bps=5.0,
        slippage_bps=2.0,
        spread_bps_round_trip=3.0,
    )
    result = backtest.run_replay(
        [_frame(0, close=100.0), _frame(1, close=101.0)],
        strategy_fns={"test_algo": always_long},
        settings=settings,
    )

    trade = result.trades[0]
    metrics = result.metrics["by_algo"]["test_algo"]

    assert trade.gross_ret_pct == pytest.approx(0.01)
    assert trade.trading_cost_pct == pytest.approx(0.0017)
    assert trade.net_ret_pct == pytest.approx(0.0083)
    assert metrics["gross_return_pct"] == pytest.approx(0.01)
    assert metrics["trading_cost_drag_pct"] == pytest.approx(-0.0017)
    assert metrics["cost_to_gross_ratio"] == pytest.approx(0.17)
    assert metrics["trades_per_day"] == pytest.approx(6.0)
    assert metrics["turnover_per_day"] == pytest.approx(12.0)
    assert metrics["avg_hold_hours"] == pytest.approx(4.0)
    assert metrics["total_return_ex_end_of_data_pct"] == 0.0


def test_backtest_portfolio_risk_blocks_excess_long_exposure() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(
        close_open_at_end=False,
        max_long_positions=1,
        max_open_positions_total=5,
    )
    result = backtest.run_replay(
        [_frame(0), _frame(1)],
        strategy_fns={"first": always_long, "second": always_long},
        settings=settings,
    )

    assert result.equity_curve[0].open_position["algo_id"] == "first"
    assert result.equity_curve[1].open_position is None
    assert len(result.risk_events) == 2
    assert {event.event_type for event in result.risk_events} == {"max_long_positions"}


def test_load_frames_from_supabase_paginates_ohlcv_rows() -> None:
    rows = [
        {
            "open_time": (_dt(0) + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
            "close_time": (_dt(0) + timedelta(hours=index + 1)).isoformat().replace("+00:00", "Z"),
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.0 + index,
            "volume": 1.0,
        }
        for index in range(1200)
    ]

    class FakeResult:
        def __init__(self, data):
            self.data = data

    class FakeBuilder:
        def __init__(self, table_name: str) -> None:
            self.table_name = table_name
            self.start = 0
            self.end = 0
            self.range_calls: list[tuple[int, int]] = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args):
            return self

        def gte(self, *_args):
            return self

        def lte(self, *_args):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, start: int, end: int):
            self.start = start
            self.end = end
            self.range_calls.append((start, end))
            return self

        async def execute(self):
            if self.table_name == "arena_macro_snapshots":
                return FakeResult([])
            return FakeResult(rows[self.start : self.end + 1])

    class FakeDb:
        def __init__(self) -> None:
            self.ohlcv_builders: list[FakeBuilder] = []

        def table(self, table_name: str):
            builder = FakeBuilder(table_name)
            if table_name == "arena_ohlcv_bars":
                self.ohlcv_builders.append(builder)
            return builder

    db = FakeDb()
    frames = asyncio.run(backtest.load_frames_from_supabase(db, limit=1200, warmup_bars=1))

    assert len(frames) == 1200
    assert [builder.range_calls[0] for builder in db.ohlcv_builders] == [
        (0, 999),
        (1000, 1199),
    ]
