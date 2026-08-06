from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/analysis"))

from p2_edge_cost_audit import _cross_window_algo_verdict, edge_cost_metrics


def _trade(*, gross_bps: float, cost_bps: float = 13.0, weight: float = 1.0):
    gross = gross_bps / 10_000
    cost = cost_bps / 10_000
    return SimpleNamespace(
        gross_ret_pct=gross,
        trading_cost_pct=cost,
        net_ret_pct=gross - cost,
        position_weight=weight,
    )


def test_edge_cost_metrics_uses_weighted_trade_economics() -> None:
    metrics = edge_cost_metrics(
        [
            _trade(gross_bps=52.0, weight=0.5),
            _trade(gross_bps=26.0, weight=1.0),
        ],
        n_boot=100,
    )

    assert metrics["gross_edge_per_trade_bps"] == pytest.approx(26.0)
    assert metrics["cost_per_trade_bps"] == pytest.approx(9.75)
    assert metrics["edge_cost_ratio"] == pytest.approx(8 / 3)
    assert metrics["point_pass"] is False


def test_edge_cost_metrics_marks_threshold_and_sample_readiness_separately() -> None:
    metrics = edge_cost_metrics([_trade(gross_bps=52.0) for _ in range(20)], n_boot=100)

    assert metrics["edge_cost_ratio"] == pytest.approx(4.0)
    assert metrics["point_pass"] is True
    assert metrics["inference_ready"] is True
    assert metrics["edge_cost_ci95_low"] == pytest.approx(4.0)


def test_edge_cost_metrics_handles_no_trades() -> None:
    metrics = edge_cost_metrics([])

    assert metrics["trades"] == 0
    assert metrics["edge_cost_ratio"] is None
    assert metrics["point_pass"] is False


def test_cross_window_algo_verdict_separates_point_and_robust_pass() -> None:
    metric = {
        "point_pass": True,
        "inference_ready": True,
        "edge_cost_ci95_low": 2.5,
    }
    empty = {
        "point_pass": False,
        "inference_ready": False,
        "edge_cost_ci95_low": None,
    }
    windows = {
        window: {
            symbol: {
                "algorithms": {
                    algo: (metric if symbol == "SOLUSDT" and algo == "multi_factor" else empty)
                    for algo in (
                        "regime_trend",
                        "fng_contrarian",
                        "vix_rsi",
                        "macd_momentum",
                        "multi_factor",
                        "omnibus",
                    )
                }
            }
            for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        }
        for window in ("bull", "bear")
    }

    verdict = _cross_window_algo_verdict(windows)["SOLUSDT"]["multi_factor"]

    assert verdict["both_windows_point_pass"] is True
    assert verdict["both_windows_ci95_low_pass"] is False
    assert verdict["status"] == "point_pass_unconfirmed"
