from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import (
    HYBRID_FEATURE_SCHEMA_VERSION,
    HYBRID_SIGN_ANCHOR,
    compute_hybrid_index,
)


def _frame(rows: int = 40) -> pd.DataFrame:
    """§1: HYBRID_FEATURE_CANDIDATES가 lag1 버전으로 변경되어 lag1 컬럼 사용."""
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.01 + (idx / rows) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
        }
    )


def test_compute_hybrid_index_returns_nan_when_features_are_insufficient() -> None:
    df = pd.DataFrame({"news_sentiment_mean_lag1": [0.1] * 20})

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


def test_compute_hybrid_index_pca_summary_has_feature_schema_version() -> None:
    """§5.2: pca_summary에 feature_schema_version이 기록되어야 한다."""
    result = compute_hybrid_index(_frame())

    pca_summary = result.attrs["hybrid_index_diagnostics"]["pca_summary"]
    assert "feature_schema_version" in pca_summary
    assert pca_summary["feature_schema_version"] == HYBRID_FEATURE_SCHEMA_VERSION


def test_compute_hybrid_index_sign_anchor_loading_is_positive() -> None:
    """§5.2: HYBRID_SIGN_ANCHOR의 PC1 loading이 양수여야 한다 (부호 정규화)."""
    result = compute_hybrid_index(_frame())

    pca_summary = result.attrs["hybrid_index_diagnostics"]["pca_summary"]
    if pca_summary["status"] != "ok":
        return  # VIF 제거로 anchor가 없으면 skip

    loadings = pca_summary.get("loadings", {})
    if HYBRID_SIGN_ANCHOR in loadings:
        assert loadings[HYBRID_SIGN_ANCHOR] >= 0, (
            f"HYBRID_SIGN_ANCHOR '{HYBRID_SIGN_ANCHOR}'의 loading이 음수입니다: {loadings[HYBRID_SIGN_ANCHOR]}"
        )
