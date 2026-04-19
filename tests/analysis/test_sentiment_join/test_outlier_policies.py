from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.join import detect_outliers_rolling_iqr
from morning_brief.analysis.sentiment_join.outlier_policy import (
    NON_MASK_COLS,
    ColumnMaskPolicy,
    NoMaskPolicy,
    OutlierPolicyFactory,
    RowMaskPolicy,
    WinsorizePolicy,
)

MASK_COLS = [
    "btc_return",
    "usdkrw_return",
    "funding_rate",
    "oi_change_pct",
    "volume_change_pct",
    "etf_net_inflow_usd",
]


def _make_base_df(days: int = 60, *, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-01", periods=days, freq="D").strftime("%Y-%m-%d").tolist()
    return pd.DataFrame(
        {
            "date": dates,
            "btc_return": rng.normal(0, 0.01, days),
            "btc_log_return": rng.normal(0, 0.01, days),
            "usdkrw_return": rng.normal(0, 0.002, days),
            "funding_rate": rng.normal(0.0001, 0.0005, days),
            "oi_change_pct": rng.normal(0, 0.01, days),
            "volume_change_pct": rng.normal(0, 0.05, days),
            "etf_net_inflow_usd": rng.normal(0, 1e7, days),
            "open_interest_usd": rng.normal(1e10, 1e8, days),
            "btc_long_short_ratio": rng.normal(1.0, 0.05, days),
            "news_sentiment_mean": rng.normal(0, 0.3, days),
            "fng_value": rng.integers(20, 80, days).astype(float),
            "vix": rng.normal(18, 2, days),
            "sentiment_status": ["ok"] * days,
        }
    )


def _inject_iqr_outlier(df: pd.DataFrame, row: int, col: str, magnitude: float = 100.0) -> None:
    """해당 (row, col) 을 rolling-IQR 기준 확실한 outlier 로 설정."""
    base_std = pd.to_numeric(df[col], errors="coerce").std()
    df.loc[row, col] = float(base_std * magnitude)


def _inject_data_error(df: pd.DataFrame, row: int, col: str) -> None:
    if col == "open_interest_usd":
        df.loc[row, col] = -1.0
    elif col == "funding_rate":
        df.loc[row, col] = 0.1
    else:
        raise ValueError(f"No data_error rule for {col}")


# ─────────────────────────────────────────────────────────────────────────────
# RowMaskPolicy — R9 회귀 보장
# ─────────────────────────────────────────────────────────────────────────────


def test_row_mask_matches_current_pipeline_behavior() -> None:
    """`RowMaskPolicy` 가 기존 detect_outliers_rolling_iqr + pipeline.py:408 마스킹 결과와 동등."""
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return")
    _inject_iqr_outlier(df, row=50, col="funding_rate")

    # 기준 경로(현재 pipeline.py 의 로직 재현)
    legacy = detect_outliers_rolling_iqr(df, MASK_COLS)
    expected = legacy.copy()
    mask_cols = [c for c in expected.columns if c not in NON_MASK_COLS]
    expected.loc[expected["is_outlier"], mask_cols] = np.nan

    result = RowMaskPolicy().apply(df, MASK_COLS)

    # data_error 주입이 없으므로 bit-exact 해야 함
    pd.testing.assert_frame_equal(
        result.df[mask_cols].reset_index(drop=True),
        expected[mask_cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_row_mask_stats_shape() -> None:
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return")
    result = RowMaskPolicy().apply(df, MASK_COLS)
    assert result.stats["masked_row_ratio"] > 0
    assert result.stats["masked_cells"] > 0
    assert result.stats["winsorized_cells"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 공통: data_error 는 모든 policy 에서 반드시 마스크
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "policy_name",
    ["row", "column", "winsorize", "none"],
)
def test_data_error_always_masked(policy_name: str) -> None:
    df = _make_base_df(days=60)
    _inject_data_error(df, row=40, col="open_interest_usd")
    _inject_data_error(df, row=41, col="funding_rate")
    policy = OutlierPolicyFactory.create(policy_name)  # type: ignore[arg-type]
    result = policy.apply(df, MASK_COLS)

    assert pd.isna(result.df.loc[40, "open_interest_usd"])
    assert pd.isna(result.df.loc[41, "funding_rate"])
    assert result.classification.loc[40, "open_interest_usd"] == "data_error"
    assert result.classification.loc[41, "funding_rate"] == "data_error"
    assert result.stats["data_error_cells"] >= 2


# ─────────────────────────────────────────────────────────────────────────────
# ColumnMaskPolicy — 행 보존 + regime_stress 분류
# ─────────────────────────────────────────────────────────────────────────────


def test_column_mask_preserves_other_columns_in_outlier_row() -> None:
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return")
    result = ColumnMaskPolicy().apply(df, MASK_COLS)

    # btc_return 셀만 NaN 이고 같은 행의 다른 수치 컬럼은 보존되어야 함
    assert pd.isna(result.df.loc[45, "btc_return"])
    assert not pd.isna(result.df.loc[45, "funding_rate"])
    assert not pd.isna(result.df.loc[45, "news_sentiment_mean"])


def test_column_mask_regime_stress_row_preserved() -> None:
    """변화율 3개 컬럼이 동시에 큰 점프를 보이는 행은 마스크되지 않고 regime_stress 로 분류."""
    df = _make_base_df(days=60, seed=1)
    # 45 행에 3개 변화율 컬럼 동시 점프 (regime stress 트리거)
    for col in ("btc_return", "funding_rate", "volume_change_pct"):
        _inject_iqr_outlier(df, row=45, col=col, magnitude=30.0)

    result = ColumnMaskPolicy().apply(df, MASK_COLS)

    # 셋 중 최소 2개 컬럼에 대해 regime_stress 사유 + 값 보존
    reasons = [
        result.classification.loc[45, c]
        for c in ("btc_return", "funding_rate", "volume_change_pct")
    ]
    assert reasons.count("regime_stress") >= 2
    # regime_stress 로 분류된 셀은 NaN 아님
    for col, reason in zip(
        ("btc_return", "funding_rate", "volume_change_pct"), reasons, strict=True
    ):
        if reason == "regime_stress":
            assert not pd.isna(result.df.loc[45, col]), f"{col} should be preserved"

    assert result.stats["regime_stress_rows"] >= 1


def test_column_mask_clears_is_outlier_for_pipeline_compat() -> None:
    """ColumnMaskPolicy 결과의 is_outlier 는 False 로 초기화되어 pipeline.py 의 row-mask 스킵을 유도."""
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return")
    result = ColumnMaskPolicy().apply(df, MASK_COLS)
    assert not result.df["is_outlier"].any()


# ─────────────────────────────────────────────────────────────────────────────
# WinsorizePolicy — 꼬리 clip + 값 보존
# ─────────────────────────────────────────────────────────────────────────────


def test_winsorize_clips_tails_and_preserves_values() -> None:
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return", magnitude=50.0)
    original_btc_return = float(df.loc[45, "btc_return"])
    result = WinsorizePolicy().apply(df, MASK_COLS)

    clipped_value = float(result.df.loc[45, "btc_return"])
    # clip 되었지만 NaN 은 아님
    assert not pd.isna(clipped_value)
    assert abs(clipped_value) < abs(original_btc_return)
    assert result.stats["winsorized_cells"] >= 1


def test_winsorize_below_q01_is_also_clipped() -> None:
    df = _make_base_df(days=60)
    df.loc[45, "btc_return"] = -50.0  # 극한 음수
    result = WinsorizePolicy().apply(df, MASK_COLS)
    clipped = float(result.df.loc[45, "btc_return"])
    assert clipped > -50.0
    assert not pd.isna(clipped)


# ─────────────────────────────────────────────────────────────────────────────
# NoMaskPolicy — data_error 외에는 모두 통과
# ─────────────────────────────────────────────────────────────────────────────


def test_no_mask_preserves_extreme_values() -> None:
    df = _make_base_df(days=60)
    _inject_iqr_outlier(df, row=45, col="btc_return", magnitude=50.0)
    original = float(df.loc[45, "btc_return"])
    result = NoMaskPolicy().apply(df, MASK_COLS)
    assert float(result.df.loc[45, "btc_return"]) == original
    assert result.stats["masked_cells"] == 0


def test_no_mask_still_applies_data_error() -> None:
    df = _make_base_df(days=60)
    _inject_data_error(df, row=40, col="funding_rate")
    result = NoMaskPolicy().apply(df, MASK_COLS)
    assert pd.isna(result.df.loc[40, "funding_rate"])


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,cls",
    [
        ("row", RowMaskPolicy),
        ("column", ColumnMaskPolicy),
        ("winsorize", WinsorizePolicy),
        ("none", NoMaskPolicy),
    ],
)
def test_factory_returns_correct_policy(name: str, cls: type) -> None:
    policy = OutlierPolicyFactory.create(name)  # type: ignore[arg-type]
    assert isinstance(policy, cls)
    assert policy.name == name


def test_factory_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown outlier policy"):
        OutlierPolicyFactory.create("bogus")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Empty / edge cases
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_df_all_policies_safe() -> None:
    df = pd.DataFrame({"date": [], "btc_return": [], "funding_rate": [], "oi_change_pct": []})
    for name in ("row", "column", "winsorize", "none"):
        policy = OutlierPolicyFactory.create(name)  # type: ignore[arg-type]
        result = policy.apply(df, MASK_COLS)
        assert len(result.df) == 0
        assert len(result.flags) == 0
