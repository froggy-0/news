from __future__ import annotations

import pytest

from arena import backtest_validation


def _run(*, bar_count: int = 2) -> dict:
    return {
        "backtest_run_id": "00000000-0000-0000-0000-000000000001",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "data_start": "2026-06-19T04:00:00Z",
        "data_end": "2026-06-19T08:00:00Z",
        "bar_count": bar_count,
        "algo_ids": ["test_algo"],
        "fee_bps": 5.0,
        "slippage_bps": 0.0,
        "risk_model_version": "portfolio-risk-v1",
        "rules_snapshot": {
            "fee_bps": 5.0,
            "slippage_bps": 0.0,
            "macro_stale_hours": 36.0,
            "min_hold_hours": {"test_algo": 4.0},
            "portfolio_risk": {
                "risk_model_version": "portfolio-risk-v1",
                "position_unit": 1.0,
                "max_open_positions_total": 3,
                "max_long_positions": 2,
                "max_short_positions": 2,
                "max_net_long_exposure": 2.0,
                "max_net_short_exposure": 2.0,
                "daily_loss_limit_pct": 0.05,
                "algo_max_drawdown_kill_pct": 0.10,
                "cooldown_after_kill_hours": 24.0,
            },
        },
        "params_snapshot": {
            "schedule": {
                "min_hold_hours": {"test_algo": 4.0},
                "min_hold_fallback_hours": 4.0,
            }
        },
    }


def _bars() -> list[dict]:
    return [
        {
            "open_time": "2026-06-19T00:00:00Z",
            "close_time": "2026-06-19T04:00:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        },
        {
            "open_time": "2026-06-19T04:00:00Z",
            "close_time": "2026-06-19T08:00:00Z",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
        },
    ]


def _equity_rows() -> list[dict]:
    return [
        {
            "backtest_run_id": "00000000-0000-0000-0000-000000000001",
            "algo_id": "test_algo",
            "data_timestamp": "2026-06-19T04:00:00Z",
        },
        {
            "backtest_run_id": "00000000-0000-0000-0000-000000000001",
            "algo_id": "test_algo",
            "data_timestamp": "2026-06-19T08:00:00Z",
        },
    ]


def _trade(**overrides) -> dict:
    trade = {
        "id": 1,
        "backtest_run_id": "00000000-0000-0000-0000-000000000001",
        "algo_id": "test_algo",
        "direction": "long",
        "open_time": "2026-06-19T04:00:00Z",
        "close_time": "2026-06-19T08:00:00Z",
        "entry_data_timestamp": "2026-06-19T04:00:00Z",
        "close_data_timestamp": "2026-06-19T08:00:00Z",
        "open_price": 100.0,
        "close_price": 101.0,
        "stop_loss_price": 97.5,
        "ret_pct": 0.009,
        "hold_hours": 4.0,
        "exit_reason": "signal_flat",
        "params_snapshot": {"risk": {"fee_bps": 5.0}},
        "indicator_snapshot": {"atr": 1.0, "rsi": 50.0},
        "macro_snapshot": {},
        "risk_snapshot": {"allowed": True},
    }
    trade.update(overrides)
    return trade


def _check_by_name(report: backtest_validation.ValidationReport) -> dict:
    return {check.check_name: check for check in report.checks}


def test_validation_passes_integrity_and_warns_on_small_sample() -> None:
    report = backtest_validation.validate_backtest_bundle(
        run=_run(),
        trades=[_trade()],
        equity_rows=_equity_rows(),
        bars=_bars(),
        validation_run_id="10000000-0000-0000-0000-000000000001",
    )
    checks = _check_by_name(report)

    assert report.status == "warn"
    assert checks["equity_row_count"].status == "pass"
    assert checks["fee_adjusted_return_replay"].status == "pass"
    assert checks["min_hold_signal_exits"].status == "pass"
    assert checks["signal_exit_close_price_policy"].status == "pass"
    assert checks["stop_loss_fill_policy"].status == "na"
    assert checks["research_sample_size"].status == "warn"


def test_validation_fails_when_fee_adjusted_return_does_not_replay() -> None:
    report = backtest_validation.validate_backtest_bundle(
        run=_run(),
        trades=[_trade(ret_pct=0.01)],
        equity_rows=_equity_rows(),
        bars=_bars(),
    )
    checks = _check_by_name(report)

    assert report.status == "fail"
    assert checks["fee_adjusted_return_replay"].status == "fail"
    assert checks["fee_adjusted_return_replay"].severity == "critical"


def test_validation_checks_stop_loss_ohlc_reachability_and_gap_fill() -> None:
    stop_bars = _bars()
    stop_bars[1] = {
        "open_time": "2026-06-19T04:00:00Z",
        "close_time": "2026-06-19T08:00:00Z",
        "open": 99.0,
        "high": 100.0,
        "low": 97.0,
        "close": 98.0,
    }
    stop_trade = _trade(
        close_price=97.5,
        ret_pct=-0.026,
        exit_reason="stop_loss",
    )

    report = backtest_validation.validate_backtest_bundle(
        run=_run(),
        trades=[stop_trade],
        equity_rows=_equity_rows(),
        bars=stop_bars,
    )
    checks = _check_by_name(report)

    assert checks["stop_loss_fill_policy"].status == "pass"
    assert checks["signal_exit_close_price_policy"].observed["checked_trades"] == 0


def test_validation_fails_min_hold_violation() -> None:
    report = backtest_validation.validate_backtest_bundle(
        run=_run(),
        trades=[_trade(hold_hours=3.9)],
        equity_rows=_equity_rows(),
        bars=_bars(),
    )
    checks = _check_by_name(report)

    assert checks["min_hold_signal_exits"].status == "fail"
    assert checks["min_hold_signal_exits"].details["bad_rows"][0][
        "required_hours"
    ] == pytest.approx(4.0)
