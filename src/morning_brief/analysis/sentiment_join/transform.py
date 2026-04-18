from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_dates(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    normalized = df.copy()
    if normalized.empty:
        return normalized

    parsed = pd.to_datetime(normalized[date_col], utc=True, errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"Invalid date values found in column: {date_col}")
    normalized[date_col] = parsed.dt.strftime("%Y-%m-%d")
    return normalized


def forward_fill_prices(
    df: pd.DataFrame,
    cols: list[str],
    max_periods: int = 2,
) -> tuple[pd.DataFrame, int]:
    filled = df.copy()
    if filled.empty:
        return filled, 0

    filled = filled.sort_values("date").reset_index(drop=True)
    total_filled = 0
    for col in cols:
        before_missing = int(filled[col].isna().sum())
        filled[col] = filled[col].ffill(limit=max_periods)
        after_missing = int(filled[col].isna().sum())
        total_filled += before_missing - after_missing
    return filled, total_filled


def reindex_to_calendar(
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    date_col: str = "date",
) -> pd.DataFrame:
    """결측 달력일을 포함하도록 DataFrame을 reindex한다.

    USDKRW처럼 외환시장이 주말에 닫혀 Sat/Sun 행이 비는 소스를
    전체 달력일로 확장해 이후 ffill이 주말을 금요일 값으로 채울 수 있게 한다.
    BTC(24/7) 기준 inner merge에서 주말 행이 유지되도록 하는 것이 목적.

    기존 행은 그대로 유지하고, 누락된 날짜는 NaN으로 채워진 행이 추가된다.
    """
    if df.empty:
        return df.copy()

    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    all_dates = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d").tolist()

    working = df.copy()
    working[date_col] = working[date_col].astype(str)
    indexed = working.set_index(date_col)
    reindexed = indexed.reindex(all_dates)
    reindexed.index.name = date_col
    return reindexed.reset_index()


def compute_returns(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    computed = df.copy()
    if computed.empty:
        return computed.drop(columns=[price_col], errors="ignore")

    close = pd.to_numeric(computed[price_col], errors="coerce").where(lambda values: values > 0)
    computed[f"{price_col}_log_return"] = np.log(close / close.shift(1))
    computed[f"{price_col}_return"] = close.pct_change(fill_method=None)
    computed = computed.drop(columns=[price_col])
    return computed


def trim_to_date_range(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    return df.loc[mask].reset_index(drop=True)


__all__ = [
    "compute_returns",
    "forward_fill_prices",
    "normalize_dates",
    "reindex_to_calendar",
    "trim_to_date_range",
]
