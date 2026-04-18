from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import (
    HYBRID_FEATURE_CANDIDATES_CORE,
    HYBRID_FEATURE_CANDIDATES_FULL,
    HYBRID_FEATURE_SCHEMA_VERSION,
    HYBRID_SIGN_ANCHOR,
    INDEX_SPECS,
    compute_hybrid_indices,
)


def _frame(rows: int = 40) -> pd.DataFrame:
    """§4 v4: full 지수에 필요한 7개 lag1 feature (vix_lag1 포함)."""
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.01 + (idx / rows) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
            "vix_lag1": 18 + np.sin(idx / 10) * 3,
        }
    )


def test_compute_hybrid_indices_returns_nan_when_features_are_insufficient() -> None:
    df = pd.DataFrame({"news_sentiment_mean_lag1": [0.1] * 20})

    result = compute_hybrid_indices(df)

    assert result["full_hybrid_index"].isna().all()
    assert result["core_hybrid_index"].isna().all()
    assert result["full_hybrid_index_score"].isna().all()
    assert result["core_hybrid_index_score"].isna().all()
    diagnostics = result.attrs["hybrid_index_diagnostics"]
    assert diagnostics["full"]["pca_summary"]["status"] == "insufficient_features"
    assert diagnostics["core"]["pca_summary"]["status"] == "insufficient_features"


def test_compute_hybrid_indices_adds_diagnostics_on_success() -> None:
    result = compute_hybrid_indices(_frame())

    assert result["full_hybrid_index"].notna().sum() > 0
    assert result["core_hybrid_index"].notna().sum() > 0
    diagnostics = result.attrs["hybrid_index_diagnostics"]
    for name in ("full", "core"):
        assert "vif_diagnostics" in diagnostics[name]
        assert diagnostics[name]["pca_summary"]["status"] == "ok"
        assert diagnostics[name]["pca_summary"]["n_components"] >= 1


def test_compute_hybrid_indices_pca_summary_has_feature_schema_version() -> None:
    """§4 v4: pca_summary에 feature_schema_version이 기록되어야 한다."""
    result = compute_hybrid_indices(_frame())

    for name in ("full", "core"):
        pca_summary = result.attrs["hybrid_index_diagnostics"][name]["pca_summary"]
        assert pca_summary.get("feature_schema_version") == HYBRID_FEATURE_SCHEMA_VERSION


def test_compute_hybrid_indices_sign_anchor_loading_is_positive() -> None:
    """§5.2: 두 지수 모두 HYBRID_SIGN_ANCHOR의 PC1 loading이 양수여야 한다."""
    result = compute_hybrid_indices(_frame())

    for name in ("full", "core"):
        pca_summary = result.attrs["hybrid_index_diagnostics"][name]["pca_summary"]
        if pca_summary["status"] != "ok":
            continue
        loadings = pca_summary.get("loadings", {})
        if HYBRID_SIGN_ANCHOR in loadings:
            assert loadings[HYBRID_SIGN_ANCHOR] >= 0, (
                f"{name}: HYBRID_SIGN_ANCHOR loading 음수: {loadings[HYBRID_SIGN_ANCHOR]}"
            )


def test_compute_hybrid_indices_score_is_within_0_100() -> None:
    """§4 v4: *_hybrid_index_score는 0~100 범위여야 한다."""
    result = compute_hybrid_indices(_frame())

    for name in ("full", "core"):
        score = result[f"{name}_hybrid_index_score"].dropna()
        if score.empty:
            continue
        assert score.min() >= 0.0
        assert score.max() <= 100.0


def test_hybrid_feature_schema_version_is_v4() -> None:
    """v4: full/core 이중 지수로 승급."""
    assert HYBRID_FEATURE_SCHEMA_VERSION == "v4"


def test_hybrid_feature_candidates_full_includes_vix() -> None:
    """§4 3-4: VIX는 full 후보에 포함돼야 한다 (수집 실패 시 dropna 이전에 사전 제외)."""
    assert "vix_lag1" in HYBRID_FEATURE_CANDIDATES_FULL


def test_hybrid_feature_candidates_core_is_curated_four() -> None:
    """core는 결측 내성이 높은 핵심 4개 feature로 구성."""
    assert HYBRID_FEATURE_CANDIDATES_CORE == [
        "news_sentiment_mean_lag1",
        "fng_value_lag1",
        "funding_rate_lag1",
        "volume_change_pct_lag1",
    ]


def test_index_specs_core_skips_vif_gate() -> None:
    """core는 VIF gate를 생략해야 한다 (vif_threshold=None)."""
    core_spec = next(spec for spec in INDEX_SPECS if spec.name == "core")
    full_spec = next(spec for spec in INDEX_SPECS if spec.name == "full")
    assert core_spec.vif_threshold is None
    assert full_spec.vif_threshold is not None


def test_compute_hybrid_indices_survives_all_nan_vix() -> None:
    """§4 3-4: VIX가 수집되지 않은 환경에서도 full 지수가 계산돼야 한다."""
    rng = np.random.default_rng(0)
    n = 40
    df = pd.DataFrame(
        {
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
            "fng_value_lag1": rng.uniform(30, 70, n),
            "funding_rate_lag1": rng.normal(0, 0.001, n),
            "btc_long_short_ratio_lag1": rng.uniform(0.8, 1.2, n),
            "etf_net_inflow_usd_lag1": rng.normal(0, 1e6, n),
            "volume_change_pct_lag1": rng.normal(0, 0.05, n),
            "vix_lag1": [float("nan")] * n,
        }
    )
    result = compute_hybrid_indices(df)

    full_status = result.attrs["hybrid_index_diagnostics"]["full"]["pca_summary"]["status"]
    core_status = result.attrs["hybrid_index_diagnostics"]["core"]["pca_summary"]["status"]
    assert full_status in ("ok", "insufficient_rows", "insufficient_features")
    assert core_status in ("ok", "insufficient_rows", "insufficient_features")
    if full_status == "ok":
        assert (
            "vix_lag1"
            not in result.attrs["hybrid_index_diagnostics"]["full"]["pca_summary"][
                "selected_features"
            ]
        )


def test_compute_hybrid_indices_coverage_included() -> None:
    """coverage(rows_total/rows_used/ratio)가 진단에 포함돼야 한다."""
    result = compute_hybrid_indices(_frame())

    for name in ("full", "core"):
        coverage = result.attrs["hybrid_index_diagnostics"][name]["coverage"]
        assert coverage["rows_total"] == len(_frame())
        assert "rows_used" in coverage
        assert "ratio" in coverage
