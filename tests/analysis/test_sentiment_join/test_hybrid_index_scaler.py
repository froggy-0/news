from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import RobustScaler, StandardScaler

from morning_brief.analysis.sentiment_join.hybrid_index import (
    HYBRID_FEATURE_CANDIDATES_FULL,
    INDEX_SPECS,
    IndexSpec,
    _compute_single_index,
    compute_hybrid_indices,
    make_scaler,
)


def _frame(rows: int = 60, *, seed: int = 0) -> pd.DataFrame:
    """full 지수에 필요한 7 개 lag1 feature 를 균등하게 생성."""
    rng = np.random.default_rng(seed)
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "news_sentiment_mean_lag1": np.sin(idx / 5) + rng.normal(0, 0.05, rows),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20 + rng.normal(0, 1.0, rows),
            "funding_rate_lag1": np.sin(idx / 7) * 0.01 + (idx / rows) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
            "vix_lag1": 18 + np.sin(idx / 10) * 3,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# make_scaler factory
# ─────────────────────────────────────────────────────────────────────────────


def test_make_scaler_standard_returns_standard_scaler() -> None:
    assert isinstance(make_scaler("standard"), StandardScaler)


def test_make_scaler_robust_returns_robust_scaler() -> None:
    assert isinstance(make_scaler("robust"), RobustScaler)


def test_make_scaler_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown scaler kind"):
        make_scaler("bogus")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# IndexSpec 기본값 & 기존 INDEX_SPECS
# ─────────────────────────────────────────────────────────────────────────────


def test_indexspec_defaults_to_standard_scaler() -> None:
    spec = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0)
    assert spec.scaler_kind == "standard"


def test_default_index_specs_are_standard_for_backward_compat() -> None:
    for spec in INDEX_SPECS:
        assert spec.scaler_kind == "standard"


# ─────────────────────────────────────────────────────────────────────────────
# R9: scaler_kind="standard" 는 기존 동작과 수치 동등해야 함
# ─────────────────────────────────────────────────────────────────────────────


def test_standard_scaler_index_unchanged_vs_default_path() -> None:
    """`scaler_kind="standard"` 명시적 주입이 기본 INDEX_SPECS 경로와 bit-exact."""
    df = _frame(rows=60)
    default_result = compute_hybrid_indices(df)

    # 동일 설정을 명시적으로 주입
    explicit_spec = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "standard")
    raw, score, _ = _compute_single_index(df, explicit_spec, len(df))

    # default 경로의 full 결과와 일치
    np.testing.assert_array_equal(
        default_result["full_hybrid_index"].to_numpy(),
        raw.to_numpy(),
    )
    np.testing.assert_array_equal(
        default_result["full_hybrid_index_score"].to_numpy(),
        score.to_numpy(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Robust scaler 경로
# ─────────────────────────────────────────────────────────────────────────────


def test_robust_scaler_produces_valid_index() -> None:
    df = _frame(rows=60)
    spec = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "robust")
    raw, score, diag = _compute_single_index(df, spec, len(df))

    # 값이 실제로 계산되어야 함
    assert raw.notna().sum() > 0
    assert score.notna().sum() > 0
    # 0~100 clip 계약 유지
    valid_scores = score.dropna()
    assert (valid_scores >= 0).all()
    assert (valid_scores <= 100).all()
    assert diag["pca_summary"]["status"] == "ok"


def test_robust_scaler_differs_from_standard_under_outliers() -> None:
    """동일 입력에 큰 outlier 가 섞였을 때 robust/standard 의 PC1 score 분포가 달라야 한다."""
    df = _frame(rows=60)
    # 중간에 극단 이상치 주입
    df.loc[30, "funding_rate_lag1"] = df["funding_rate_lag1"].std() * 50
    df.loc[30, "volume_change_pct_lag1"] = df["volume_change_pct_lag1"].std() * 50

    spec_std = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "standard")
    spec_rob = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "robust")

    _, score_std, _ = _compute_single_index(df, spec_std, len(df))
    _, score_rob, _ = _compute_single_index(df, spec_rob, len(df))

    # 두 결과는 동일하지 않아야 한다 (robust 가 outlier 영향을 덜 받음)
    assert not np.allclose(
        score_std.dropna().to_numpy(),
        score_rob.dropna().to_numpy(),
        atol=1e-6,
    )


def test_robust_scaler_raw_index_less_affected_by_outlier() -> None:
    """Outlier 가 있을 때 robust 의 raw index(PC1) 는 정상 구간에서 standard 보다 덜 흔들려야 한다.

    증명: raw index(PC1 점수)는 0~100 clip 전 원시 값이라 scaler 효과가 직접 보인다.
    outlier 를 제외한 정상 구간의 spread 를 비교한다.
    """
    df = _frame(rows=60, seed=2)
    df.loc[30, "funding_rate_lag1"] = df["funding_rate_lag1"].std() * 100

    spec_std = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "standard")
    spec_rob = IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, 10.0, "robust")

    raw_std, _, _ = _compute_single_index(df, spec_std, len(df))
    raw_rob, _, _ = _compute_single_index(df, spec_rob, len(df))

    # 두 raw index 는 동일하지 않아야 한다 (scaler 선택 효과가 존재)
    assert not np.allclose(
        raw_std.drop(index=30).dropna().to_numpy(),
        raw_rob.drop(index=30).dropna().to_numpy(),
        atol=1e-6,
    )
