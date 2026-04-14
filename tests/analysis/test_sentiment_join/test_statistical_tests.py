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
            "btc_long_short_ratio": [0.9] * rows,
            "btc_long_short_ratio_lag1": [0.9] * rows,
            "etf_net_inflow_usd_lag1": [1000000.0] * rows,
        }
    )


def test_run_statistical_tests_skips_when_rows_are_insufficient() -> None:
    results = statistical_tests.run_statistical_tests(_sample_df(rows=10))
    assert results == {}


def test_run_statistical_tests_adf_runs_at_30_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADF는 30행 이상이면 실행된다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=35))

    assert "adf" in results
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_granger_skips_at_179_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 179행이면 Granger 미실행."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    granger_calls: list[tuple] = []

    def fake_granger(df, predictor, target, lag):
        granger_calls.append((predictor, target, lag))
        return {"predictor": predictor, "target": target, "lag": lag, "pvalue": 0.04}

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=179))

    assert results["granger"] == []
    assert granger_calls == []
    assert results["granger_executed"] is False
    assert results["granger_eligible_rows"] == 179


def test_run_statistical_tests_granger_runs_at_180_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 180행이면 Granger 실행."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    granger_calls: list[tuple] = []

    def fake_granger(df, predictor, target, lag):
        granger_calls.append((predictor, target, lag))
        return {"predictor": predictor, "target": target, "lag": lag, "pvalue": 0.04}

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    # 5쌍 × 3 lags = 15 호출
    assert len(granger_calls) == 15
    assert len(results["granger"]) == 15
    assert results["granger_executed"] is True
    assert results["granger_eligible_rows"] == 180


def test_run_statistical_tests_returns_multi_adf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert isinstance(results["adf"], dict)
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_skips_missing_adf_column(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _sample_df().drop(columns=["btc_long_short_ratio"])
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(df)

    assert "btc_long_short_ratio" not in results["adf"]
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_isolates_adf_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert results["granger"] == []


def test_adf_and_granger_thresholds_are_independent() -> None:
    """ADF 기준(30)과 Granger 기준(180)이 독립적인지 확인."""
    assert statistical_tests.MIN_ROWS_FOR_ADF == 30
    assert statistical_tests.MIN_ROWS_FOR_GRANGER == 180
