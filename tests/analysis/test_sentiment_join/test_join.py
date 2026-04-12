from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from morning_brief.analysis.sentiment_join.join import detect_outliers_rolling_iqr, merge_sources


def _date_range(days: int) -> list[str]:
    return pd.date_range("2026-03-01", periods=days, freq="D").strftime("%Y-%m-%d").tolist()


def _sentiment_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "news_sentiment_mean": [0.1] * days,
            "news_sentiment_std": [0.05] * days,
            "n_articles": pd.array([3] * days, dtype="Int64"),
            "signal_sentiment_mean": [0.05] * days,
            "signal_sentiment_std": [0.02] * days,
            "n_signals": pd.array([6] * days, dtype="Int64"),
        }
    )


def _fng_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame({"date": dates, "fng_value": pd.array([55] * days, dtype="Int64")})


def _btc_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    returns = [0.01] * days
    returns[-1] = 0.5
    return pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": [0.01] * days,
            "btc_return": returns,
            "btc_quote_volume": [1e9] * days,
        }
    )


def _futures_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "funding_rate": [0.001] * days,
            "open_interest_usd": [1000.0 + idx for idx in range(days)],
            "btc_long_short_ratio": [0.9] * days,
        }
    )


def _usdkrw_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "usdkrw_log_return": [0.001] * days,
            "usdkrw_return": [0.001] * days,
        }
    )


def test_merge_sources_inner_join_and_drop_missing_sentiment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentiment_df = _sentiment_df(35)
    sentiment_df.loc[0, "news_sentiment_mean"] = np.nan
    fng_df = _fng_df(34).iloc[1:].reset_index(drop=True)
    btc_df = _btc_df(35)
    usdkrw_df = _usdkrw_df(35)

    with caplog.at_level(logging.WARNING):
        merged = merge_sources(sentiment_df, fng_df, btc_df, usdkrw_df)

    assert "close" not in merged.columns
    assert list(merged.columns) == [
        "date",
        "news_sentiment_mean",
        "news_sentiment_std",
        "n_articles",
        "signal_sentiment_mean",
        "signal_sentiment_std",
        "n_signals",
        "fng_value",
        "btc_log_return",
        "btc_return",
        "btc_quote_volume",
        "usdkrw_log_return",
        "usdkrw_return",
        "funding_rate",
        "open_interest_usd",
        "btc_long_short_ratio",
        "funding_rate_lag1",
        "oi_change_pct_lag1",
        "btc_long_short_ratio_lag1",
        "is_outlier",
    ]
    assert merged["news_sentiment_mean"].notna().all()
    assert any(getattr(record, "event", None) == "rows.dropped" for record in caplog.records)


def test_detect_outliers_flags_extreme_value() -> None:
    df = _btc_df(40).merge(_usdkrw_df(40), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"])
    assert bool(detected.iloc[-1]["is_outlier"]) is True


def test_detect_outliers_cold_start_is_false() -> None:
    df = _btc_df(10).merge(_usdkrw_df(10), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"], min_periods=15)
    assert not detected["is_outlier"].any()


def test_detect_outliers_window_length_equal_dataset_returns_false() -> None:
    df = _btc_df(30).merge(_usdkrw_df(30), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"], window=30)
    assert not detected["is_outlier"].any()


def test_merge_sources_warns_when_rows_under_minimum(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        merge_sources(_sentiment_df(20), _fng_df(20), _btc_df(20), _usdkrw_df(20))

    assert any(
        getattr(record, "event", None) == "join.insufficient_rows" for record in caplog.records
    )


def test_merge_sources_sources_used_excludes_all_nan_btc() -> None:
    btc_df = _btc_df(35)
    btc_df["btc_log_return"] = np.nan
    btc_df["btc_return"] = np.nan

    merged = merge_sources(_sentiment_df(35), _fng_df(35), btc_df, _usdkrw_df(35))

    assert "is_outlier" in merged.columns


def test_merge_sources_adds_lagged_futures_columns() -> None:
    merged = merge_sources(
        _sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35), _futures_df(35)
    )

    assert pd.isna(merged.loc[0, "funding_rate_lag1"])
    assert merged.loc[1, "funding_rate_lag1"] == pytest.approx(0.001)
    assert pd.isna(merged.loc[0, "oi_change_pct_lag1"])


def test_merge_sources_adds_btc_long_short_ratio_lag1() -> None:
    merged = merge_sources(
        _sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35), _futures_df(35)
    )

    assert "btc_long_short_ratio_lag1" in merged.columns
    assert pd.isna(merged.loc[0, "btc_long_short_ratio_lag1"])
    assert merged.loc[1, "btc_long_short_ratio_lag1"] == pytest.approx(0.9)


def test_merge_sources_outlier_detection_includes_long_short_ratio() -> None:
    futures_df = _futures_df(40)
    # 마지막 행에 극단적인 Long/Short Ratio 삽입
    futures_df.loc[39, "btc_long_short_ratio"] = 999.0

    merged = merge_sources(_sentiment_df(40), _fng_df(40), _btc_df(40), _usdkrw_df(40), futures_df)

    assert bool(merged.iloc[-1]["is_outlier"]) is True


def test_merge_sources_btc_quote_volume_preserved() -> None:
    merged = merge_sources(_sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35))

    assert "btc_quote_volume" in merged.columns


@settings(max_examples=100)
@given(length=st.integers(min_value=31, max_value=60))
def test_detect_outliers_constant_series_is_false(length: int) -> None:
    dates = _date_range(length)
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_return": [0.01] * length,
            "usdkrw_return": [0.001] * length,
        }
    )

    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"])

    assert not detected["is_outlier"].any()


@settings(max_examples=100)
@given(length=st.integers(min_value=35, max_value=60))
def test_merge_sources_never_returns_nan_sentiment(length: int) -> None:
    sentiment_df = _sentiment_df(length)
    sentiment_df.loc[0, "news_sentiment_mean"] = np.nan

    merged = merge_sources(sentiment_df, _fng_df(length), _btc_df(length), _usdkrw_df(length))

    assert merged["news_sentiment_mean"].notna().all()
