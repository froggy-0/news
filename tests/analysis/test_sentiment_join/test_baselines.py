from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.baselines import (
    always_up,
    btc_momo_20d,
    evaluate_baseline,
    fng_contrarian,
    vol_regime,
    vol_regime_v2,
)


def _frame(rows: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "btc_log_return": np.sin(np.arange(rows) / 5) * 0.01,
            "fng_value_lag1": [20, 80, 50, 10] * (rows // 4),
            "vix_lag1": np.linspace(12, 30, rows),
            "btc_realized_vol_20d_lag1": np.sin(np.arange(rows) / 8) * 0.01 + 0.04,
        }
    )


def test_baseline_signals_have_input_length() -> None:
    df = _frame()
    for signal in (
        always_up(df),
        fng_contrarian(df),
        btc_momo_20d(df),
        vol_regime(df),
        vol_regime_v2(df),
    ):
        assert len(signal) == len(df)


def test_fng_contrarian_direction() -> None:
    signal = fng_contrarian(_frame())

    assert signal.iloc[0] == 1.0
    assert signal.iloc[1] == -1.0
    assert signal.iloc[2] == 0.0


def test_evaluate_baseline_returns_metrics() -> None:
    df = _frame()
    metrics = evaluate_baseline(df, always_up(df), return_col="btc_log_return")

    assert 0.0 <= metrics["hit_rate"] <= 1.0
    assert 0.0 <= metrics["coverage"] <= 1.0


def test_evaluate_baseline_missing_return_col_degrades() -> None:
    df = _frame().drop(columns=["btc_log_return"])
    metrics = evaluate_baseline(df, always_up(df), return_col="btc_log_return")

    assert pd.isna(metrics["hit_rate"])
    assert metrics["coverage"] == 0.0


def test_vol_regime_v2_is_sparse_confirmed_regime() -> None:
    df = _frame()
    signal = vol_regime_v2(df)

    assert set(signal.dropna().unique()) <= {-1.0, 0.0, 1.0}
    assert (signal == 0).any()
    assert (signal != 0).any()
