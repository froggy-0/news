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

    # adf는 이제 dict[str, dict] 구조
    assert isinstance(results["adf"], dict)
    assert "btc_log_return" in results["adf"]
    assert results["adf"]["btc_log_return"]["stationary"] is True

    # Granger pairs: 4쌍 × 3 lags = 12 호출
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
        ("btc_long_short_ratio_lag1", "btc_log_return", 1),
        ("btc_long_short_ratio_lag1", "btc_log_return", 2),
        ("btc_long_short_ratio_lag1", "btc_log_return", 3),
        ("etf_net_inflow_usd_lag1", "btc_log_return", 1),
        ("etf_net_inflow_usd_lag1", "btc_log_return", 2),
        ("etf_net_inflow_usd_lag1", "btc_log_return", 3),
    ]


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
    # btc_long_short_ratio 없는 df
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

    # adf 키는 있지만 내부가 비어있을 수 있음 (모든 ADF가 실패)
    assert results["granger"] == []
