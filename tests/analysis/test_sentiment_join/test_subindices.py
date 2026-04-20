from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import compute_hybrid_indices
from morning_brief.analysis.sentiment_join.subindices import (
    FUNDING_LSR_INTERACTION,
    SENTIMENT_VIX_INTERACTION,
    compute_subindices,
)


def _frame(rows: int = 40) -> pd.DataFrame:
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "oi_change_pct_lag1": np.cos(idx / 10) * 0.02,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
            "vix_lag1": 18 + np.sin(idx / 10) * 3,
        }
    )


def test_compute_subindices_adds_four_scores() -> None:
    result = compute_subindices(_frame())

    for name in ("sentiment", "positioning", "flow", "vol"):
        score = result[f"{name}_subindex_score"].dropna()
        assert not score.empty
        assert score.min() >= 0.0
        assert score.max() <= 100.0


def test_compute_subindices_adds_interaction_features() -> None:
    df = _frame()
    result = compute_subindices(df)

    assert FUNDING_LSR_INTERACTION in result.columns
    assert SENTIMENT_VIX_INTERACTION in result.columns
    assert result[FUNDING_LSR_INTERACTION].notna().all()
    assert result[SENTIMENT_VIX_INTERACTION].notna().all()


def test_compute_subindices_degrades_when_features_missing() -> None:
    result = compute_subindices(pd.DataFrame({"news_sentiment_mean_lag1": [0.1] * 20}))

    diagnostics = result.attrs["subindex_diagnostics"]
    assert diagnostics["positioning"]["status"] == "insufficient_features"
    assert result["positioning_subindex_score"].isna().all()


def test_subindices_coexist_with_hybrid_indices() -> None:
    df = _frame()
    with_hybrid = compute_hybrid_indices(df)
    result = compute_subindices(with_hybrid)

    assert "full_hybrid_index_score" in result.columns
    assert "core_hybrid_index_score" in result.columns
    assert "sentiment_subindex_score" in result.columns
