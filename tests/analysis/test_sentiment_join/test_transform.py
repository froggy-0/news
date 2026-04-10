from __future__ import annotations

import math

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from morning_brief.analysis.sentiment_join.transform import (
    compute_returns,
    forward_fill_prices,
    normalize_dates,
    trim_to_date_range,
)


def test_normalize_dates_converts_to_utc_string() -> None:
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-04-10 09:00:00+09:00")],
            "value": [1],
        }
    )

    normalized = normalize_dates(df)

    assert normalized.loc[0, "date"] == "2026-04-10"


@settings(max_examples=100)
@given(gap=st.integers(min_value=1, max_value=5))
def test_forward_fill_prices_respects_max_periods(gap: int) -> None:
    values = [1.0] + [None] * gap + [2.0]
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-04-10", periods=len(values), freq="D").strftime("%Y-%m-%d"),
            "close": values,
        }
    )

    filled, ffill_count = forward_fill_prices(df, ["close"], max_periods=2)

    if gap <= 2:
        assert filled["close"].isna().sum() == 0
        assert ffill_count == gap
    else:
        assert filled["close"].isna().sum() == gap - 2
        assert ffill_count == 2


def test_compute_returns_handles_zero_without_infinity() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-10", "2026-04-11", "2026-04-12"],
            "close": [100.0, 0.0, 110.0],
        }
    )

    computed = compute_returns(df, "close")

    assert pd.isna(computed.loc[0, "close_log_return"])
    assert pd.isna(computed.loc[0, "close_return"])
    assert pd.isna(computed.loc[1, "close_log_return"])
    assert not math.isinf(float(computed["close_log_return"].fillna(0.0).iloc[1]))
    assert "close" not in computed.columns


def test_trim_to_date_range_removes_extra_row() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-09", "2026-04-10", "2026-04-11"],
            "close_return": [0.1, 0.2, 0.3],
        }
    )

    trimmed = trim_to_date_range(df, "2026-04-10", "2026-04-11")

    assert list(trimmed["date"]) == ["2026-04-10", "2026-04-11"]


def test_compute_returns_constant_series_yields_zero_change() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-10", "2026-04-11", "2026-04-12"],
            "close": [100.0, 100.0, 100.0],
        }
    )

    computed = compute_returns(df, "close")

    assert computed.loc[1, "close_log_return"] == 0.0
    assert computed.loc[1, "close_return"] == 0.0
