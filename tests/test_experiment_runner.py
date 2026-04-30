"""Phase 3 — ExperimentRunner 통합 테스트.

Task 10: 축소 grid(2×2×2×1=8 cell)로 end-to-end 실행 검증.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.experiments import (
    FOLDS_SCHEMA_COLUMNS,
    ExperimentRunner,
    ExperimentSpec,
    _build_custom_specs,
    _frame_for_feature_set,
    _mask_cols_from,
    _outlier_mask_cols_for_policy,
    default_grid,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixture 생성: ExperimentRunner 가 요구하는 raw master DataFrame
# ─────────────────────────────────────────────────────────────────────────────


def _make_raw_master(days: int = 300, *, seed: int = 42) -> pd.DataFrame:
    """walk-forward (train=120, test=30) 가 최소 2 fold 생성되도록 300일 생성.

    필수 컬럼:
    - 날짜/메타: date, is_outlier, sentiment_status, btc_direction_label
    - 수치(mask 대상): btc_return, btc_log_return, funding_rate, oi_change_pct,
                       volume_change_pct, etf_net_inflow_usd, open_interest_usd,
                       btc_long_short_ratio, vix
    - lag1 feature (hybrid_index 입력): *_lag1 variants
    - forward targets: btc_fwd_ret_1d, btc_fwd_ret_3d, btc_fwd_ret_7d,
                       btc_fwd_vol_5d, btc_large_move_3d
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=days, freq="D").strftime("%Y-%m-%d").tolist()

    btc_log_return = rng.normal(0, 0.015, days)
    funding_rate = rng.normal(0.0001, 0.0005, days)
    volume_change_pct = rng.normal(0, 0.05, days)

    # lag1 feature 컬럼 (hybrid_index 계산에 필요)
    news_sentiment = rng.normal(0, 0.3, days)
    fng_value = rng.uniform(20, 80, days)
    btc_ls_ratio = rng.normal(1.0, 0.05, days)
    etf_inflow = rng.normal(0, 1e7, days)
    vix = rng.normal(18, 2, days)

    # forward target 컬럼 (시프트 계산)
    log_ret_series = pd.Series(btc_log_return)
    btc_fwd_ret_1d = log_ret_series.shift(-1)
    btc_fwd_ret_3d = log_ret_series.shift(-1) + log_ret_series.shift(-2) + log_ret_series.shift(-3)
    btc_fwd_ret_7d = sum(log_ret_series.shift(-k) for k in range(1, 8))  # type: ignore[assignment]
    btc_fwd_vol_5d = pd.Series(btc_log_return).rolling(5).std(ddof=1).shift(-5)
    btc_large_move_3d = (
        btc_fwd_ret_3d.abs() > btc_fwd_ret_3d.abs().rolling(60, min_periods=10).std() * 1.5
    ).astype("Int64")
    # 마지막 3행은 NaN
    btc_large_move_3d.iloc[-3:] = pd.NA

    return pd.DataFrame(
        {
            "date": dates,
            # 메타
            "is_outlier": False,
            "sentiment_status": "ok",
            "btc_direction_label": pd.Series(["up" if r > 0 else "down" for r in btc_log_return]),
            # 수치 컬럼
            "btc_return": btc_log_return,
            "btc_log_return": btc_log_return,
            "funding_rate": funding_rate,
            "oi_change_pct": rng.normal(0, 0.02, days),
            "btc_return_7d": pd.Series(btc_log_return).rolling(7, min_periods=7).sum(),
            "btc_return_7d_lag1": pd.Series(btc_log_return)
            .rolling(7, min_periods=7)
            .sum()
            .shift(1),
            "open_interest_change_7d": rng.normal(0, 0.03, days),
            "open_interest_change_7d_lag1": pd.Series(rng.normal(0, 0.03, days)).shift(1),
            "oi_price_divergence_flag_7d": rng.integers(0, 2, days).astype(float),
            "oi_price_divergence_flag_7d_lag1": pd.Series(
                rng.integers(0, 2, days).astype(float)
            ).shift(1),
            "oi_price_divergence_score_7d": rng.uniform(0, 0.01, days),
            "oi_price_divergence_score_7d_lag1": pd.Series(rng.uniform(0, 0.01, days)).shift(1),
            "volume_change_pct": volume_change_pct,
            "etf_net_inflow_usd": etf_inflow,
            "open_interest_usd": rng.uniform(5e9, 2e10, days),
            "btc_long_short_ratio": btc_ls_ratio,
            "vix": vix,
            # lag1 feature
            "news_sentiment_mean_lag1": pd.Series(news_sentiment).shift(1),
            "fng_value_lag1": pd.Series(fng_value).shift(1),
            "funding_rate_lag1": pd.Series(funding_rate).shift(1),
            "btc_long_short_ratio_lag1": pd.Series(btc_ls_ratio).shift(1),
            "etf_net_inflow_usd_lag1": pd.Series(etf_inflow).shift(1),
            "volume_change_pct_lag1": pd.Series(volume_change_pct).shift(1),
            "vix_lag1": pd.Series(vix).shift(1),
            # forward targets
            "btc_fwd_ret_1d": btc_fwd_ret_1d,
            "btc_fwd_ret_3d": btc_fwd_ret_3d,
            "btc_fwd_ret_7d": btc_fwd_ret_7d,
            "btc_fwd_vol_5d": btc_fwd_vol_5d,
            "btc_large_move_3d": btc_large_move_3d,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# 기본 그리드 검증
# ─────────────────────────────────────────────────────────────────────────────


def test_default_grid_cell_count() -> None:
    """2 scaler × 4 mask × 1 horizon × 2 index × 5 feature_set = 80."""
    grid = default_grid()
    assert len(grid) == 80


def test_default_grid_all_unique_spec_ids() -> None:
    grid = default_grid()
    ids = [s.spec_id for s in grid]
    assert len(ids) == len(set(ids))


# ─────────────────────────────────────────────────────────────────────────────
# ExperimentRunner — 빈 입력 거부
# ─────────────────────────────────────────────────────────────────────────────


def test_runner_rejects_empty_dataframe() -> None:
    with pytest.raises(ValueError, match="raw_master must not be empty"):
        ExperimentRunner(pd.DataFrame())


# ─────────────────────────────────────────────────────────────────────────────
# 축소 grid: 2×2×2×1 = 8 cell end-to-end
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def raw_master() -> pd.DataFrame:
    return _make_raw_master(days=300)


@pytest.fixture(scope="module")
def small_grid() -> list[ExperimentSpec]:
    return default_grid(
        scalers=("standard", "robust"),
        masks=("row", "column"),
        horizons=(1, 3),
        indices=("full",),
        feature_sets=("baseline",),
    )


@pytest.fixture(scope="module")
def folds_df(raw_master: pd.DataFrame, small_grid: list[ExperimentSpec]) -> pd.DataFrame:
    runner = ExperimentRunner(raw_master, train_days=120, test_days=30)
    return runner.run_many(small_grid)


def test_small_grid_cell_count(small_grid: list[ExperimentSpec]) -> None:
    assert len(small_grid) == 8  # 2×2×2×1


def test_folds_schema(folds_df: pd.DataFrame) -> None:
    """folds.parquet 스키마: 모든 필수 컬럼 존재."""
    for col in FOLDS_SCHEMA_COLUMNS:
        assert col in folds_df.columns, f"컬럼 누락: {col}"


def test_feature_set_spec_id_suffix() -> None:
    spec = ExperimentSpec(
        scaler="standard",
        mask="row",
        horizon_days=7,
        index_name="full",
        feature_set="oi_divergence_score_7d",
    )

    assert spec.spec_id == "standard-row-T7-full-oi_divergence_score_7d"


def test_build_custom_specs_adds_only_active_oi_feature() -> None:
    specs = _build_custom_specs("standard", "oi_divergence_flag_7d")
    full = next(spec for spec in specs if spec.name == "full")
    core = next(spec for spec in specs if spec.name == "core")

    assert "oi_price_divergence_flag_7d_lag1" in full.candidates
    assert "oi_price_divergence_flag_7d_lag1" in core.candidates
    assert "oi_price_divergence_score_7d_lag1" not in full.candidates


def test_inactive_oi_columns_do_not_enter_baseline_mask() -> None:
    raw = _make_raw_master(days=40)
    frame = _frame_for_feature_set(raw, "baseline")
    mask_cols = _mask_cols_from(frame, "baseline")

    assert "btc_return_7d_lag1" not in frame.columns
    assert "oi_price_divergence_score_7d_lag1" not in frame.columns
    assert not any(col.startswith("oi_price_divergence") for col in mask_cols)


def test_row_policy_uses_baseline_mask_cols_for_treatment() -> None:
    raw = _make_raw_master(days=40)
    frame = _frame_for_feature_set(raw, "oi_divergence_score_7d")

    row_cols = _outlier_mask_cols_for_policy(frame, "oi_divergence_score_7d", "row")
    column_cols = _outlier_mask_cols_for_policy(frame, "oi_divergence_score_7d", "column")

    assert "oi_price_divergence_score_7d_lag1" not in row_cols
    assert "oi_price_divergence_score_7d_lag1" in column_cols


def test_row_treatment_feature_does_not_change_masked_ratio(raw_master: pd.DataFrame) -> None:
    raw = raw_master.copy()
    raw.loc[200, "oi_price_divergence_score_7d_lag1"] = 999.0
    runner = ExperimentRunner(raw, train_days=120, test_days=30)

    baseline = runner.run(
        ExperimentSpec(
            scaler="standard", mask="row", horizon_days=1, index_name="full", feature_set="baseline"
        )
    )
    treatment = runner.run(
        ExperimentSpec(
            scaler="standard",
            mask="row",
            horizon_days=1,
            index_name="full",
            feature_set="oi_divergence_score_7d",
        )
    )

    assert treatment["masked_ratio"].iloc[0] == pytest.approx(baseline["masked_ratio"].iloc[0])


def test_folds_spec_ids_match_grid(
    folds_df: pd.DataFrame, small_grid: list[ExperimentSpec]
) -> None:
    """각 spec_id 가 grid 에 정의된 것과 일치."""
    expected_ids = {s.spec_id for s in small_grid}
    actual_ids = set(folds_df["spec_id"].dropna().unique())
    assert actual_ids == expected_ids


def test_folds_numeric_columns_in_range(folds_df: pd.DataFrame) -> None:
    """hit_rate: [0,1], coverage: [0,1], masked_ratio: [0,1]."""
    valid_hr = folds_df["hit_rate"].dropna()
    assert (valid_hr >= 0).all() and (valid_hr <= 1).all()

    valid_cov = folds_df["coverage"].dropna()
    assert (valid_cov >= 0).all() and (valid_cov <= 1).all()

    valid_mr = folds_df["masked_ratio"].dropna()
    assert (valid_mr >= 0).all() and (valid_mr <= 1).all()


def test_folds_has_multiple_folds_per_spec(folds_df: pd.DataFrame) -> None:
    """300일 / (train=120 + test=30) → 최소 2 fold 기대."""
    per_spec = folds_df[folds_df["fold"] >= 0].groupby("spec_id")["fold"].count()
    assert (per_spec >= 2).all(), f"fold 수 부족: {per_spec.to_dict()}"


# ─────────────────────────────────────────────────────────────────────────────
# 재현성: 동일 spec 2회 실행 → 수치 동등
# ─────────────────────────────────────────────────────────────────────────────


def test_reproducibility(raw_master: pd.DataFrame) -> None:
    """동일 ExperimentSpec 을 2회 실행하면 수치가 bit-exact 이어야 한다."""
    spec = ExperimentSpec(scaler="standard", mask="row", horizon_days=1, index_name="full")
    runner = ExperimentRunner(raw_master, train_days=120, test_days=30)

    result1 = runner.run(spec)
    result2 = runner.run(spec)

    pd.testing.assert_frame_equal(result1, result2, check_like=False)


# ─────────────────────────────────────────────────────────────────────────────
# 단일 spec run() 결과 타입 체크
# ─────────────────────────────────────────────────────────────────────────────


def test_single_run_returns_dataframe(raw_master: pd.DataFrame) -> None:
    spec = ExperimentSpec(scaler="standard", mask="row", horizon_days=1, index_name="full")
    runner = ExperimentRunner(raw_master, train_days=120, test_days=30)
    result = runner.run(spec)
    assert isinstance(result, pd.DataFrame)
    for col in FOLDS_SCHEMA_COLUMNS:
        assert col in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# 부분 실패 격리: 잘못된 spec 이 섞여도 나머지 cell 은 완료
# ─────────────────────────────────────────────────────────────────────────────


def test_cell_failure_isolated(raw_master: pd.DataFrame) -> None:
    """invalid index_name 이 포함된 cell 이 실패해도 나머지 cell 은 결과를 반환한다."""
    good_spec = ExperimentSpec(scaler="standard", mask="row", horizon_days=1, index_name="full")
    bad_spec = ExperimentSpec(
        scaler="standard", mask="row", horizon_days=1, index_name="nonexistent"
    )
    runner = ExperimentRunner(raw_master, train_days=120, test_days=30)
    result = runner.run_many([good_spec, bad_spec])

    # good spec 의 spec_id 가 결과에 있어야 한다
    assert good_spec.spec_id in result["spec_id"].values
    # 결과가 완전히 비어 있으면 안 된다
    assert len(result) >= 1
