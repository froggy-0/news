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
    "trim_to_date_range",
]
