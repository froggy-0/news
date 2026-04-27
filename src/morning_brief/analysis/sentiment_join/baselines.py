from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 365  # BTC 24/7 calendar-day candles, no weekend gap → 365 (not 252)


def _as_signal(values: pd.Series, index: pd.Index) -> pd.Series:
    return values.reindex(index).fillna(0).astype(float)


def always_up(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index, name="always_up")


def fng_contrarian(df: pd.DataFrame) -> pd.Series:
    col = "fng_value_lag1" if "fng_value_lag1" in df.columns else "fng_value"
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, name="fng_contrarian")
    fng = pd.to_numeric(df[col], errors="coerce")
    signal = pd.Series(0.0, index=df.index, name="fng_contrarian")
    signal.loc[fng <= 25] = 1.0
    signal.loc[fng >= 75] = -1.0
    return signal


def btc_momo_20d(df: pd.DataFrame) -> pd.Series:
    if "btc_log_return" not in df.columns:
        return pd.Series(0.0, index=df.index, name="btc_momo_20d")
    momo = pd.to_numeric(df["btc_log_return"], errors="coerce").shift(1).rolling(20).sum()
    signal = np.sign(momo).replace(0, np.nan)
    return _as_signal(signal, df.index).rename("btc_momo_20d")


def vol_regime(df: pd.DataFrame) -> pd.Series:
    col = "vix_lag1" if "vix_lag1" in df.columns else "vix"
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, name="vol_regime")
    vol = pd.to_numeric(df[col], errors="coerce")
    threshold = vol.rolling(60, min_periods=10).median()
    threshold = threshold.fillna(vol.median())
    signal = pd.Series(1.0, index=df.index, name="vol_regime")
    signal.loc[vol > threshold] = -1.0
    signal.loc[vol.isna()] = 0.0
    return signal


def evaluate_baseline(
    df: pd.DataFrame,
    signal: pd.Series,
    *,
    return_col: str = "btc_log_return",
) -> dict[str, float]:
    if return_col not in df.columns:
        return {"hit_rate": float("nan"), "sharpe": float("nan"), "coverage": 0.0}
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    if aligned.empty:
        return {"hit_rate": float("nan"), "sharpe": float("nan"), "coverage": 0.0}
    active = aligned[aligned["signal"] != 0]
    coverage = float(len(active) / len(df)) if len(df) else 0.0
    if active.empty:
        return {"hit_rate": float("nan"), "sharpe": float("nan"), "coverage": coverage}
    hits = np.sign(active["signal"].to_numpy()) == np.sign(active["ret"].to_numpy())
    strategy_ret = np.sign(active["signal"].to_numpy()) * active["ret"].to_numpy()
    sigma = float(np.std(strategy_ret, ddof=1)) if len(strategy_ret) > 1 else 0.0
    sharpe = (
        float(np.mean(strategy_ret)) / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)
        if sigma > 1e-12
        else float("nan")
    )
    return {"hit_rate": float(np.mean(hits)), "sharpe": sharpe, "coverage": coverage}


__all__ = [
    "always_up",
    "btc_momo_20d",
    "evaluate_baseline",
    "fng_contrarian",
    "vol_regime",
]
