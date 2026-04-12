from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import compute_hybrid_index


def _frame(rows: int = 40) -> pd.DataFrame:
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean": np.sin(idx / 5),
            "fng_value": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.01 + (idx / rows) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
        }
    )


def test_compute_hybrid_index_returns_nan_when_features_are_insufficient() -> None:
    df = pd.DataFrame({"news_sentiment_mean": [0.1] * 20})

    result = compute_hybrid_index(df)

    assert result["hybrid_index"].isna().all()
    assert (
        result.attrs["hybrid_index_diagnostics"]["pca_summary"]["status"] == "insufficient_features"
    )


def test_compute_hybrid_index_adds_diagnostics_on_success() -> None:
    result = compute_hybrid_index(_frame())

    assert result["hybrid_index"].notna().sum() > 0
    diagnostics = result.attrs["hybrid_index_diagnostics"]
    assert "vif_diagnostics" in diagnostics
    assert diagnostics["pca_summary"]["status"] == "ok"
    assert diagnostics["pca_summary"]["n_components"] >= 1
