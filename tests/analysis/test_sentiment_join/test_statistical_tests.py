from __future__ import annotations

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join import statistical_tests


def _sample_df(rows: int = 35) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-03-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "news_sentiment_mean": [0.1] * rows,
            "fng_value": pd.array([55] * rows, dtype="Int64"),
            "funding_rate_lag1": [0.001] * rows,
            "btc_log_return": [0.01] * rows,
        }
    )


def test_run_statistical_tests_skips_when_rows_are_insufficient() -> None:
    results = statistical_tests.run_statistical_tests(_sample_df(rows=10))
    assert results == {}


def test_run_statistical_tests_invokes_expected_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )

    def fake_granger(df: pd.DataFrame, predictor: str, target: str, lag: int):
        calls.append((predictor, target, lag))
        return {"predictor": predictor, "target": target, "lag": lag, "pvalue": 0.04}

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert results["adf"]["stationary"] is True
    assert calls == [
        ("news_sentiment_mean", "btc_log_return", 1),
        ("news_sentiment_mean", "btc_log_return", 2),
        ("news_sentiment_mean", "btc_log_return", 3),
        ("funding_rate_lag1", "btc_log_return", 1),
        ("funding_rate_lag1", "btc_log_return", 2),
        ("funding_rate_lag1", "btc_log_return", 3),
        ("fng_value", "btc_log_return", 1),
        ("fng_value", "btc_log_return", 2),
        ("fng_value", "btc_log_return", 3),
    ]


def test_run_statistical_tests_isolates_adf_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert "adf" not in results
    assert results["granger"] == []
