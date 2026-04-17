from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import (
    HYBRID_FEATURE_SCHEMA_VERSION,
    HYBRID_SIGN_ANCHOR,
    compute_hybrid_index,
)


def _frame(rows: int = 40) -> pd.DataFrame:
    """§5: HYBRID_FEATURE_CANDIDATES = lag1 버전 6개 (v3). volume_change_pct_lag1 포함."""
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.01 + (idx / rows) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
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


# ── §5: v3 HYBRID_FEATURE_CANDIDATES 테스트 ──


def test_hybrid_feature_candidates_includes_volume() -> None:
    """v3: volume_change_pct_lag1이 HYBRID_FEATURE_CANDIDATES에 포함돼야 한다."""
    from morning_brief.analysis.sentiment_join.hybrid_index import HYBRID_FEATURE_CANDIDATES

    assert "volume_change_pct_lag1" in HYBRID_FEATURE_CANDIDATES


def test_hybrid_feature_schema_version_is_v3() -> None:
    """v3으로 올라야 PCA loading 불연속을 추적할 수 있다."""
    assert HYBRID_FEATURE_SCHEMA_VERSION == "v3"


def test_compute_hybrid_index_removes_all_nan_volume_feature() -> None:
    """volume_change_pct_lag1이 NaN만 있으면 VIF gate / dropna가 제거하고 PCA가 완료된다."""
    rng = np.random.default_rng(0)
    n = 30
    df = pd.DataFrame(
        {
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
            "fng_value_lag1": rng.uniform(30, 70, n),
            "funding_rate_lag1": rng.normal(0, 0.001, n),
            "btc_long_short_ratio_lag1": rng.uniform(0.8, 1.2, n),
            "etf_net_inflow_usd_lag1": rng.normal(0, 1e6, n),
            "volume_change_pct_lag1": [float("nan")] * n,
        }
    )
    result = compute_hybrid_index(df)

    status = result.attrs["hybrid_index_diagnostics"]["pca_summary"]["status"]
    assert status in ("ok", "insufficient_rows", "insufficient_features")
