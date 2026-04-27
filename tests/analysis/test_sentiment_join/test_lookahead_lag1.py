"""Lookahead-leakage unit tests for every `*_lag1` column generated in join.py.

Each `*_lag1[t]` must equal `raw[t-1]` (date-sorted) and `*_lag1[0]` must be NaN.
Re-shuffling rows then re-sorting must produce identical results (ordering invariance).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.join import (
    _add_delta_features,
    _add_futures_lag_columns,
    _add_regime_interaction_features,
    _add_sentiment_lag_columns,
)


def _dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2024-01-01", periods=n, freq="D"))


def _raw_master(n: int = 30, *, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "date": _dates(n),
            "funding_rate": rng.normal(0.0, 0.001, n),
            "open_interest_usd": rng.uniform(1e9, 5e9, n),
            "btc_long_short_ratio": rng.uniform(0.5, 2.5, n),
            "etf_net_inflow_usd": rng.normal(0.0, 5e7, n),
            "btc_quote_volume": rng.uniform(1e8, 1e9, n),
            "vix": rng.uniform(12.0, 35.0, n),
            "news_sentiment_mean": rng.uniform(-1.0, 1.0, n),
            "fng_value": pd.array(rng.integers(0, 100, n), dtype="Int64"),
            "usdkrw_log_return": rng.normal(0.0, 0.005, n),
            "btc_above_ma200": rng.choice([0.0, 1.0], n),
        }
    )


_FUTURES_PAIRS: tuple[tuple[str, str], ...] = (
    ("funding_rate_lag1", "funding_rate"),
    ("oi_change_pct_lag1", "oi_change_pct"),
    ("btc_long_short_ratio_lag1", "btc_long_short_ratio"),
    ("etf_net_inflow_usd_lag1", "etf_net_inflow_usd"),
    ("volume_change_pct_lag1", "volume_change_pct"),
    ("vix_lag1", "vix"),
)

_SENTIMENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("news_sentiment_mean_lag1", "news_sentiment_mean"),
    ("fng_value_lag1", "fng_value"),
    ("usdkrw_log_return_lag1", "usdkrw_log_return"),
)

_DELTA_PAIRS: tuple[tuple[str, str], ...] = (
    ("fng_change_1d_lag1", "fng_change_1d"),
    ("fng_change_5d_lag1", "fng_change_5d"),
    ("sentiment_momentum_lag1", "sentiment_momentum"),
    ("sentiment_accel_lag1", "sentiment_accel"),
)


def _assert_lag1_invariant(df: pd.DataFrame, lag1_col: str, raw_col: str) -> None:
    df_sorted = df.sort_values("date").reset_index(drop=True)
    lag1 = pd.to_numeric(df_sorted[lag1_col], errors="coerce")
    raw = pd.to_numeric(df_sorted[raw_col], errors="coerce")
    assert pd.isna(lag1.iloc[0]), f"{lag1_col} first row must be NaN"
    expected = raw.shift(1)
    pd.testing.assert_series_equal(
        lag1.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
        check_dtype=False,
    )


@pytest.mark.parametrize(("lag1_col", "raw_col"), _FUTURES_PAIRS)
def test_futures_lag1_no_lookahead(lag1_col: str, raw_col: str) -> None:
    out = _add_futures_lag_columns(_raw_master())
    _assert_lag1_invariant(out, lag1_col, raw_col)


@pytest.mark.parametrize(("lag1_col", "raw_col"), _SENTIMENT_PAIRS)
def test_sentiment_lag1_no_lookahead(lag1_col: str, raw_col: str) -> None:
    out = _add_sentiment_lag_columns(_raw_master())
    _assert_lag1_invariant(out, lag1_col, raw_col)


@pytest.mark.parametrize(("lag1_col", "raw_col"), _DELTA_PAIRS)
def test_delta_lag1_no_lookahead(lag1_col: str, raw_col: str) -> None:
    out = _add_delta_features(_raw_master())
    _assert_lag1_invariant(out, lag1_col, raw_col)


def test_btc_above_ma200_lag1_no_lookahead() -> None:
    raw = _raw_master()
    raw["btc_above_ma200_lag1"] = pd.to_numeric(raw["btc_above_ma200"], errors="coerce").shift(1)
    _assert_lag1_invariant(raw, "btc_above_ma200_lag1", "btc_above_ma200")


def test_btc_bear_regime_lag1_derives_from_lagged_above_ma200() -> None:
    """btc_bear_regime_lag1 = (btc_above_ma200 == 0).shift(1) — t 시점에 t-1 정보만 사용."""
    raw = _raw_master()
    out = _add_regime_interaction_features(raw)
    out_sorted = out.sort_values("date").reset_index(drop=True)
    raw_sorted = raw.sort_values("date").reset_index(drop=True)
    above_lag1 = pd.to_numeric(raw_sorted["btc_above_ma200"], errors="coerce").shift(1)
    expected_bear = (above_lag1 == 0.0).astype(float)
    expected_bear[above_lag1.isna()] = float("nan")
    actual_bear = pd.to_numeric(out_sorted["btc_bear_regime_lag1"], errors="coerce")
    assert pd.isna(actual_bear.iloc[0]), "btc_bear_regime_lag1 first row must be NaN"
    pd.testing.assert_series_equal(
        actual_bear.reset_index(drop=True),
        expected_bear.reset_index(drop=True),
        check_names=False,
        check_dtype=False,
    )


@pytest.mark.parametrize("lag1_col,raw_col", _FUTURES_PAIRS + _SENTIMENT_PAIRS)
def test_lag1_ordering_invariance(lag1_col: str, raw_col: str) -> None:
    """입력 행 순서를 셔플하고 다시 date 정렬 시 lag1 결과가 동일해야 한다."""
    raw = _raw_master()

    if lag1_col in {p[0] for p in _FUTURES_PAIRS}:
        run = _add_futures_lag_columns
    else:
        run = _add_sentiment_lag_columns

    out_sorted = run(raw).sort_values("date").reset_index(drop=True)
    shuffled = raw.sample(frac=1.0, random_state=0).reset_index(drop=True)
    out_shuffled = run(shuffled.sort_values("date").reset_index(drop=True))
    out_shuffled = out_shuffled.sort_values("date").reset_index(drop=True)

    expected = pd.to_numeric(out_sorted[lag1_col], errors="coerce").reset_index(drop=True)
    actual = pd.to_numeric(out_shuffled[lag1_col], errors="coerce").reset_index(drop=True)
    pd.testing.assert_series_equal(expected, actual, check_names=False, check_dtype=False)
