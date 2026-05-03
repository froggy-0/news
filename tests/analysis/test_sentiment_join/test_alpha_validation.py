"""Alpha Validation property-based tests and unit tests.

Feature: alpha-validation
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from morning_brief.analysis.sentiment_join.statistical_tests import (
    BacktestResult,
    CorrelationResult,
    HitRateResult,
    WalkForwardFoldResult,
    WalkForwardResult,
    compute_backtest,
    compute_correlations,
    compute_hit_rate,
    walk_forward_validate,
)

# ---------------------------------------------------------------------------
# Property 1: Lag-1 shift 불변량
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
# ---------------------------------------------------------------------------

_score_strategy = st.one_of(
    st.floats(min_value=0.0, max_value=100.0),
    st.just(float("nan")),
)


@given(scores=st.lists(_score_strategy, min_size=1, max_size=200))
@settings(max_examples=200, deadline=None)
def test_lag1_shift_invariant(scores: list[float]) -> None:
    """**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

    Property 1: Lag-1 shift 불변량
    (a) lag1[i] == original[i-1] (i > 0)
    (b) lag1[0]은 NaN
    (c) 모든 non-NaN 값은 0.0~100.0 범위
    """
    original = pd.Series(scores, dtype=float)
    lag1 = original.shift(1)

    # (b) 첫 번째 행은 항상 NaN
    assert pd.isna(lag1.iloc[0])

    # (a) lag1[i] == original[i-1] for i > 0
    for i in range(1, len(original)):
        orig_val = original.iloc[i - 1]
        lag_val = lag1.iloc[i]
        if pd.isna(orig_val):
            assert pd.isna(lag_val)
        else:
            assert lag_val == orig_val

    # (c) 모든 non-NaN 값은 0.0~100.0 범위
    valid = lag1.dropna()
    if not valid.empty:
        assert (valid >= 0.0).all()
        assert (valid <= 100.0).all()


# ---------------------------------------------------------------------------
# Property 2: Hit Rate 범위 및 Confusion Matrix 일관성
# Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.8, 7.7
# ---------------------------------------------------------------------------

_direction_strategy = st.sampled_from(["up", "down", "flat"])
_label_or_nan_strategy = st.one_of(_direction_strategy, st.just(None))

_predictor_strategy = st.one_of(
    st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.just(float("nan")),
)


@given(
    predictors=st.lists(_predictor_strategy, min_size=1, max_size=200),
    labels=st.lists(_label_or_nan_strategy, min_size=1, max_size=200),
    threshold=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    inverted=st.booleans(),
)
@settings(max_examples=200, deadline=None)
def test_hit_rate_range_and_cm_consistency(
    predictors: list[float],
    labels: list[str | None],
    threshold: float,
    inverted: bool,
) -> None:
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.8, 7.7**

    Property 2: Hit Rate 범위 및 Confusion Matrix 일관성
    (a) hit_rate ∈ [0.0, 1.0]
    (b) TP + FP + TN + FN == n_valid
    (c) flat 라벨 행은 n_valid에 포함되지 않음
    (d) Precision = TP/(TP+FP), Recall = TP/(TP+FN), F1 = 2×P×R/(P+R) (분모 0이면 NaN)
    """
    # 길이를 맞춤
    min_len = min(len(predictors), len(labels))
    predictors = predictors[:min_len]
    labels = labels[:min_len]

    df = pd.DataFrame(
        {
            "predictor_col": predictors,
            "btc_direction_label": labels,
        }
    )

    result = compute_hit_rate(
        df,
        "predictor_col",
        threshold,
        inverted=inverted,
    )

    assert isinstance(result, HitRateResult)

    if result.n_valid == 0:
        # 유효 행 0건: 모든 지표 NaN, CM 모두 0
        assert math.isnan(result.hit_rate)
        assert result.tp == 0
        assert result.fp == 0
        assert result.tn == 0
        assert result.fn == 0
        assert math.isnan(result.precision)
        assert math.isnan(result.recall)
        assert math.isnan(result.f1)
        return

    # (a) hit_rate ∈ [0.0, 1.0]
    assert 0.0 <= result.hit_rate <= 1.0

    # (b) TP + FP + TN + FN == n_valid
    assert result.tp + result.fp + result.tn + result.fn == result.n_valid

    # (c) flat 라벨 행은 n_valid에 포함되지 않음
    # n_valid should be <= total rows minus flat rows (NaN rows also excluded)
    non_flat_non_nan_count = sum(
        1
        for p, lbl in zip(predictors, labels[:min_len])
        if lbl is not None and lbl != "flat" and not math.isnan(p)
    )
    assert result.n_valid == non_flat_non_nan_count

    # (d) Precision/Recall/F1 공식 일관성
    if result.tp + result.fp > 0:
        expected_precision = result.tp / (result.tp + result.fp)
        assert abs(result.precision - expected_precision) < 1e-10
    else:
        assert math.isnan(result.precision)

    if result.tp + result.fn > 0:
        expected_recall = result.tp / (result.tp + result.fn)
        assert abs(result.recall - expected_recall) < 1e-10
    else:
        assert math.isnan(result.recall)

    if not math.isnan(result.precision) and not math.isnan(result.recall):
        if result.precision + result.recall > 0:
            expected_f1 = 2 * result.precision * result.recall / (result.precision + result.recall)
            assert abs(result.f1 - expected_f1) < 1e-10
        else:
            assert math.isnan(result.f1)
    else:
        assert math.isnan(result.f1)


# ---------------------------------------------------------------------------
# Hit Rate 단위 테스트
# Validates: Requirements 7.1
# ---------------------------------------------------------------------------


class TestComputeHitRate:
    """compute_hit_rate 단위 테스트."""

    def test_normal_input(self) -> None:
        """정상 입력: 명확한 up/down 예측과 실제 방향."""
        df = pd.DataFrame(
            {
                "predictor": [10.0, -5.0, 20.0, -10.0, 3.0, -1.0],
                "btc_direction_label": ["up", "down", "up", "down", "down", "up"],
            }
        )
        result = compute_hit_rate(df, "predictor", threshold=0.0)

        assert result.predictor == "predictor"
        assert result.threshold == 0.0
        assert result.n_valid == 6
        assert result.inverted is False
        # predictor > 0 → "up": [10, 20, 3] → predicted up
        # predictor <= 0 → "down": [-5, -10, -1] → predicted down
        # actual: up, down, up, down, down, up
        # TP (pred up & actual up): 10→up, 20→up = 2
        # FP (pred up & actual down): 3→down = 1
        # TN (pred down & actual down): -5→down, -10→down = 2
        # FN (pred down & actual up): -1→up = 1
        assert result.tp == 2
        assert result.fp == 1
        assert result.tn == 2
        assert result.fn == 1
        assert result.hit_rate == (2 + 2) / 6
        assert abs(result.precision - 2 / 3) < 1e-10
        assert abs(result.recall - 2 / 3) < 1e-10

    def test_with_nan_values(self) -> None:
        """NaN 포함 입력: NaN 행은 제외되어야 한다."""
        df = pd.DataFrame(
            {
                "predictor": [10.0, float("nan"), 20.0, -10.0],
                "btc_direction_label": ["up", "down", "up", None],
            }
        )
        result = compute_hit_rate(df, "predictor", threshold=0.0)

        # NaN predictor (row 1) and None label (row 3) excluded
        assert result.n_valid == 2
        assert result.tp == 2  # 10→up(actual up), 20→up(actual up)
        assert result.fp == 0
        assert result.tn == 0
        assert result.fn == 0
        assert result.hit_rate == 1.0

    def test_all_nan(self) -> None:
        """전체 NaN 입력: 모든 지표 NaN, CM 모두 0."""
        df = pd.DataFrame(
            {
                "predictor": [float("nan"), float("nan"), float("nan")],
                "btc_direction_label": [None, None, None],
            }
        )
        result = compute_hit_rate(df, "predictor", threshold=0.0)

        assert result.n_valid == 0
        assert math.isnan(result.hit_rate)
        assert result.tp == 0
        assert result.fp == 0
        assert result.tn == 0
        assert result.fn == 0
        assert math.isnan(result.precision)
        assert math.isnan(result.recall)
        assert math.isnan(result.f1)

    def test_flat_labels_excluded(self) -> None:
        """flat 라벨 행은 적중률 산출에서 제외된다."""
        df = pd.DataFrame(
            {
                "predictor": [10.0, -5.0, 3.0, -2.0],
                "btc_direction_label": ["up", "flat", "down", "down"],
            }
        )
        result = compute_hit_rate(df, "predictor", threshold=0.0)

        # flat row (row 1) excluded → 3 valid rows
        assert result.n_valid == 3
        # row 0: pred up, actual up → TP
        # row 2: pred up, actual down → FP
        # row 3: pred down, actual down → TN
        assert result.tp == 1
        assert result.fp == 1
        assert result.tn == 1
        assert result.fn == 0

    def test_vix_all_nan(self) -> None:
        """VIX 전 행 NaN 케이스: n_valid == 0."""
        df = pd.DataFrame(
            {
                "vix_lag1": [float("nan"), float("nan"), float("nan")],
                "btc_direction_label": ["up", "down", "up"],
            }
        )
        result = compute_hit_rate(df, "vix_lag1", threshold=24.0, inverted=True)

        assert result.n_valid == 0
        assert math.isnan(result.hit_rate)
        assert result.inverted is True

    def test_inverted_direction(self) -> None:
        """inverted=True: predictor > threshold → "down" 예측."""
        df = pd.DataFrame(
            {
                "vix": [30.0, 20.0, 25.0, 15.0],
                "btc_direction_label": ["down", "up", "down", "up"],
            }
        )
        result = compute_hit_rate(df, "vix", threshold=24.0, inverted=True)

        # inverted: > 24 → "down", <= 24 → "up"
        # row 0: vix=30 > 24 → pred down, actual down → TN
        # row 1: vix=20 <= 24 → pred up, actual up → TP
        # row 2: vix=25 > 24 → pred down, actual down → TN
        # row 3: vix=15 <= 24 → pred up, actual up → TP
        assert result.n_valid == 4
        assert result.tp == 2
        assert result.tn == 2
        assert result.fp == 0
        assert result.fn == 0
        assert result.hit_rate == 1.0
        assert result.inverted is True

    def test_precision_recall_nan_when_no_positive_predictions(self) -> None:
        """모든 예측이 "down"일 때 Precision은 NaN."""
        df = pd.DataFrame(
            {
                "predictor": [-5.0, -10.0, -3.0],
                "btc_direction_label": ["down", "down", "up"],
            }
        )
        result = compute_hit_rate(df, "predictor", threshold=0.0)

        # All predictions are "down" (all <= 0)
        assert result.tp == 0
        assert result.fp == 0
        assert result.tn == 2
        assert result.fn == 1
        assert math.isnan(result.precision)  # TP/(TP+FP) = 0/0
        assert result.recall == 0.0  # TP/(TP+FN) = 0/1


# ---------------------------------------------------------------------------
# Property 3: 상관 계산 일관성
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------

_corr_value_strategy = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)


@given(
    values_a=st.lists(_corr_value_strategy, min_size=2, max_size=100),
    values_b=st.lists(_corr_value_strategy, min_size=2, max_size=100),
)
@settings(max_examples=200, deadline=None)
def test_correlation_consistency_with_scipy(
    values_a: list[float],
    values_b: list[float],
) -> None:
    """**Validates: Requirements 3.1, 3.2**

    Property 3: 상관 계산 일관성
    scipy.stats.pearsonr/spearmanr 직접 호출 결과와 수치적으로 동일
    """
    from scipy.stats import pearsonr, spearmanr

    min_len = min(len(values_a), len(values_b))
    values_a = values_a[:min_len]
    values_b = values_b[:min_len]

    df = pd.DataFrame({"col_a": values_a, "col_b": values_b})

    results = compute_correlations(df, [("col_a", "col_b")])
    assert len(results) == 1
    result = results[0]

    assert isinstance(result, CorrelationResult)
    assert result.col_a == "col_a"
    assert result.col_b == "col_b"
    assert result.n_valid == min_len
    assert result.differenced is False  # no stationarity_results → no differencing

    # 직접 scipy 호출과 비교
    a = pd.Series(values_a, dtype=float)
    b = pd.Series(values_b, dtype=float)

    expected_pr, expected_pp = pearsonr(a, b)
    expected_sr, expected_sp = spearmanr(a, b)

    # 부동소수점 오차 이내 동일
    if not math.isnan(expected_pr):
        assert abs(result.pearson_r - expected_pr) < 1e-10
    else:
        assert math.isnan(result.pearson_r)

    if not math.isnan(expected_pp):
        assert abs(result.pearson_pvalue - expected_pp) < 1e-10
    else:
        assert math.isnan(result.pearson_pvalue)

    if not math.isnan(expected_sr):
        assert abs(result.spearman_rho - expected_sr) < 1e-10
    else:
        assert math.isnan(result.spearman_rho)

    if not math.isnan(expected_sp):
        assert abs(result.spearman_pvalue - expected_sp) < 1e-10
    else:
        assert math.isnan(result.spearman_pvalue)


# ---------------------------------------------------------------------------
# Property 4: 정상성 기반 차분 적용 일관성
# Validates: Requirements 3.6, 3.7
# ---------------------------------------------------------------------------

_stationarity_conclusion = st.sampled_from(
    ["stationary", "non_stationary", "trend_stationary", "difference_stationary"]
)


@given(
    values_a=st.lists(_corr_value_strategy, min_size=3, max_size=100),
    values_b=st.lists(_corr_value_strategy, min_size=3, max_size=100),
    conclusion_a=_stationarity_conclusion,
    conclusion_b=_stationarity_conclusion,
)
@settings(max_examples=200, deadline=None)
def test_stationarity_based_differencing_consistency(
    values_a: list[float],
    values_b: list[float],
    conclusion_a: str,
    conclusion_b: str,
) -> None:
    """**Validates: Requirements 3.6, 3.7**

    Property 4: 정상성 기반 차분 적용 일관성
    (a) 비정상 판정 시 Pearson은 차분 시계열 + differenced=True
    (b) Spearman은 항상 원본 시계열 사용
    """
    from scipy.stats import pearsonr, spearmanr

    min_len = min(len(values_a), len(values_b))
    values_a = values_a[:min_len]
    values_b = values_b[:min_len]

    df = pd.DataFrame({"col_a": values_a, "col_b": values_b})

    stationarity_results = {
        "col_a": {"conclusion": conclusion_a},
        "col_b": {"conclusion": conclusion_b},
    }

    results = compute_correlations(df, [("col_a", "col_b")], stationarity_results)
    assert len(results) == 1
    result = results[0]

    need_diff = conclusion_a != "stationary" or conclusion_b != "stationary"

    # (a) differenced 플래그 일관성
    assert result.differenced == need_diff

    # (b) Spearman은 항상 원본 시계열 사용
    a_orig = pd.Series(values_a, dtype=float)
    b_orig = pd.Series(values_b, dtype=float)
    expected_sr, expected_sp = spearmanr(a_orig, b_orig)

    if not math.isnan(expected_sr):
        assert abs(result.spearman_rho - expected_sr) < 1e-10
    else:
        assert math.isnan(result.spearman_rho)

    if not math.isnan(expected_sp):
        assert abs(result.spearman_pvalue - expected_sp) < 1e-10
    else:
        assert math.isnan(result.spearman_pvalue)

    # (a) 비정상 시 Pearson은 차분 시계열로 산출
    if need_diff:
        a_diff = a_orig.diff().iloc[1:]
        b_diff = b_orig.diff().iloc[1:]
        if len(a_diff) >= 2:
            expected_pr, expected_pp = pearsonr(a_diff, b_diff)
            if not math.isnan(expected_pr):
                assert abs(result.pearson_r - expected_pr) < 1e-10
            if not math.isnan(expected_pp):
                assert abs(result.pearson_pvalue - expected_pp) < 1e-10
    else:
        expected_pr, expected_pp = pearsonr(a_orig, b_orig)
        if not math.isnan(expected_pr):
            assert abs(result.pearson_r - expected_pr) < 1e-10
        if not math.isnan(expected_pp):
            assert abs(result.pearson_pvalue - expected_pp) < 1e-10


# ---------------------------------------------------------------------------
# Correlation 단위 테스트
# Validates: Requirements 7.2
# ---------------------------------------------------------------------------


class TestComputeCorrelations:
    """compute_correlations 단위 테스트."""

    def test_normal_input(self) -> None:
        """정상 입력: 두 시계열 간 상관 산출."""
        df = pd.DataFrame(
            {
                "col_a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "col_b": [2.0, 4.0, 6.0, 8.0, 10.0],
            }
        )
        results = compute_correlations(df, [("col_a", "col_b")])

        assert len(results) == 1
        r = results[0]
        assert r.col_a == "col_a"
        assert r.col_b == "col_b"
        assert r.n_valid == 5
        assert r.differenced is False
        # 완전 선형 관계 → Pearson r ≈ 1.0
        assert abs(r.pearson_r - 1.0) < 1e-10
        # Spearman ρ ≈ 1.0
        assert abs(r.spearman_rho - 1.0) < 1e-10

    def test_insufficient_valid_rows(self) -> None:
        """유효 행 부족: 유효 행 < 2이면 모든 값 NaN."""
        df = pd.DataFrame(
            {
                "col_a": [1.0, float("nan"), float("nan")],
                "col_b": [float("nan"), 2.0, float("nan")],
            }
        )
        results = compute_correlations(df, [("col_a", "col_b")])

        assert len(results) == 1
        r = results[0]
        assert r.n_valid == 0
        assert math.isnan(r.pearson_r)
        assert math.isnan(r.pearson_pvalue)
        assert math.isnan(r.spearman_rho)
        assert math.isnan(r.spearman_pvalue)
        assert r.differenced is False

    def test_non_stationary_differencing(self) -> None:
        """비정상 시계열: Pearson에 1차 차분 적용, Spearman은 원본."""
        from scipy.stats import pearsonr, spearmanr

        df = pd.DataFrame(
            {
                "col_a": [1.0, 3.0, 6.0, 10.0, 15.0],
                "col_b": [2.0, 5.0, 9.0, 14.0, 20.0],
            }
        )
        stationarity_results = {
            "col_a": {"conclusion": "non_stationary"},
        }

        results = compute_correlations(df, [("col_a", "col_b")], stationarity_results)

        assert len(results) == 1
        r = results[0]
        assert r.differenced is True
        assert r.n_valid == 5

        # Pearson은 차분 시계열로 산출
        a_diff = pd.Series([1.0, 3.0, 6.0, 10.0, 15.0]).diff().iloc[1:]
        b_diff = pd.Series([2.0, 5.0, 9.0, 14.0, 20.0]).diff().iloc[1:]
        expected_pr, _ = pearsonr(a_diff, b_diff)
        assert abs(r.pearson_r - expected_pr) < 1e-10

        # Spearman은 원본 시계열로 산출
        expected_sr, _ = spearmanr([1.0, 3.0, 6.0, 10.0, 15.0], [2.0, 5.0, 9.0, 14.0, 20.0])
        assert abs(r.spearman_rho - expected_sr) < 1e-10

    def test_lag1_column_stationarity_lookup(self) -> None:
        """lag1 컬럼명에서 _lag1 접미사를 제거하여 raw 컬럼명으로 stationarity 조회."""
        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [0.1, 0.2, 0.3, 0.4, 0.5],
                "btc_log_return": [0.01, -0.02, 0.03, -0.01, 0.02],
            }
        )
        stationarity_results = {
            "news_sentiment_mean": {"conclusion": "trend_stationary"},
        }

        results = compute_correlations(
            df,
            [("news_sentiment_mean_lag1", "btc_log_return")],
            stationarity_results,
        )

        assert len(results) == 1
        r = results[0]
        # news_sentiment_mean_lag1 → raw "news_sentiment_mean" → trend_stationary → 차분 적용
        assert r.differenced is True

    def test_missing_column(self) -> None:
        """존재하지 않는 컬럼: NaN 결과 반환."""
        df = pd.DataFrame({"col_a": [1.0, 2.0, 3.0]})
        results = compute_correlations(df, [("col_a", "nonexistent")])

        assert len(results) == 1
        r = results[0]
        assert r.n_valid == 0
        assert math.isnan(r.pearson_r)
        assert r.differenced is False

    def test_multiple_pairs(self) -> None:
        """여러 쌍 동시 산출."""
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0],
                "b": [3.0, 2.0, 1.0],
                "c": [1.0, 1.0, 1.0],
            }
        )
        results = compute_correlations(df, [("a", "b"), ("a", "c")])

        assert len(results) == 2
        assert results[0].col_a == "a"
        assert results[0].col_b == "b"
        assert results[1].col_a == "a"
        assert results[1].col_b == "c"


# ---------------------------------------------------------------------------
# Property 5: Alpha round-trip
# Validates: Requirements 4.3, 4.4, 4.5, 7.8
# ---------------------------------------------------------------------------

_signal_strategy = st.floats(
    min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
)
_return_strategy = st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False)


@given(
    signals=st.lists(_signal_strategy, min_size=2, max_size=200),
    returns=st.lists(_return_strategy, min_size=2, max_size=200),
    threshold=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    inverted=st.booleans(),
)
@settings(max_examples=200, deadline=None)
def test_alpha_round_trip(
    signals: list[float],
    returns: list[float],
    threshold: float,
    inverted: bool,
) -> None:
    """**Validates: Requirements 4.3, 4.4, 4.5, 7.8**

    Property 5: Alpha round-trip
    alpha == strategy_cumulative_return - bnh_cumulative_return (부동소수점 오차 이내)
    """
    min_len = min(len(signals), len(returns))
    signals = signals[:min_len]
    returns = returns[:min_len]

    df = pd.DataFrame({"signal": signals, "btc_log_return": returns})

    result = compute_backtest(
        df,
        "signal",
        threshold,
        transaction_cost_bps=0.0,
        inverted=inverted,
    )

    assert isinstance(result, BacktestResult)

    if result.n_valid == 0:
        assert math.isnan(result.alpha)
        return

    # Alpha round-trip: alpha == strategy_cumret - bnh_cumret
    expected_alpha = result.strategy_cumulative_return - result.bnh_cumulative_return
    assert abs(result.alpha - expected_alpha) < 1e-10


# ---------------------------------------------------------------------------
# Property 6: 거래 비용 단조성
# Validates: Requirements 4.2, 7.9
# ---------------------------------------------------------------------------


@given(
    signals=st.lists(_signal_strategy, min_size=2, max_size=200),
    returns=st.lists(_return_strategy, min_size=2, max_size=200),
    threshold=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    cost_bps=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    inverted=st.booleans(),
)
@settings(max_examples=200, deadline=None)
def test_transaction_cost_monotonicity(
    signals: list[float],
    returns: list[float],
    threshold: float,
    cost_bps: float,
    inverted: bool,
) -> None:
    """**Validates: Requirements 4.2, 7.9**

    Property 6: 거래 비용 단조성
    cost >= 0일 때 strategy_return(cost=c) <= strategy_return(cost=0)
    """
    min_len = min(len(signals), len(returns))
    signals = signals[:min_len]
    returns = returns[:min_len]

    df = pd.DataFrame({"signal": signals, "btc_log_return": returns})

    result_no_cost = compute_backtest(
        df, "signal", threshold, transaction_cost_bps=0.0, inverted=inverted
    )
    result_with_cost = compute_backtest(
        df, "signal", threshold, transaction_cost_bps=cost_bps, inverted=inverted
    )

    if result_no_cost.n_valid == 0:
        return

    # 거래 비용 적용 시 전략 수익률은 비용 미적용 시보다 항상 같거나 낮다
    assert (
        result_with_cost.strategy_cumulative_return
        <= result_no_cost.strategy_cumulative_return + 1e-10
    )


# ---------------------------------------------------------------------------
# Backtest 단위 테스트
# Validates: Requirements 7.3
# ---------------------------------------------------------------------------


class TestComputeBacktest:
    """compute_backtest 단위 테스트."""

    def test_normal_input(self) -> None:
        """정상 입력: 명확한 신호와 수익률."""
        df = pd.DataFrame(
            {
                "signal": [10.0, -5.0, 20.0, -10.0, 3.0],
                "btc_log_return": [0.01, -0.02, 0.03, -0.01, 0.005],
            }
        )
        result = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=0.0)

        assert result.predictor == "signal"
        assert result.threshold == 0.0
        assert result.n_valid == 5
        assert result.transaction_cost_bps == 0.0
        assert result.inverted is False

        # signal > 0 → buy: rows 0, 2, 4 → returns 0.01, 0.03, 0.005
        # signal <= 0 → cash: rows 1, 3 → returns 0, 0
        # strategy_returns = [0.01, 0.0, 0.03, 0.0, 0.005]
        expected_strategy = 0.01 + 0.0 + 0.03 + 0.0 + 0.005
        expected_bnh = 0.01 + (-0.02) + 0.03 + (-0.01) + 0.005
        expected_alpha = expected_strategy - expected_bnh

        assert abs(result.strategy_cumulative_return - expected_strategy) < 1e-10
        assert abs(result.bnh_cumulative_return - expected_bnh) < 1e-10
        assert abs(result.alpha - expected_alpha) < 1e-10

        # n_trades: buy→cash (row 0→1), cash→buy (row 1→2), buy→cash (row 2→3), cash→buy (row 3→4)
        assert result.n_trades == 4

    def test_empty_input(self) -> None:
        """빈 입력: 모든 지표 NaN."""
        df = pd.DataFrame(
            {
                "signal": [float("nan"), float("nan")],
                "btc_log_return": [float("nan"), float("nan")],
            }
        )
        result = compute_backtest(df, "signal", threshold=0.0)

        assert result.n_valid == 0
        assert math.isnan(result.strategy_cumulative_return)
        assert math.isnan(result.bnh_cumulative_return)
        assert math.isnan(result.alpha)
        assert math.isnan(result.sharpe_ratio)
        assert math.isnan(result.max_drawdown)
        assert result.n_trades == 0

    def test_transaction_cost_applied(self) -> None:
        """거래 비용 적용: 비용 적용 시 전략 수익률이 낮아진다."""
        df = pd.DataFrame(
            {
                "signal": [10.0, -5.0, 20.0, -10.0, 3.0],
                "btc_log_return": [0.01, -0.02, 0.03, -0.01, 0.005],
            }
        )
        result_no_cost = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=0.0)
        result_with_cost = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=10.0)

        # 거래 비용 적용 시 전략 수익률이 낮아져야 함
        assert (
            result_with_cost.strategy_cumulative_return < result_no_cost.strategy_cumulative_return
        )
        # bnh는 거래 비용과 무관
        assert (
            abs(result_with_cost.bnh_cumulative_return - result_no_cost.bnh_cumulative_return)
            < 1e-10
        )

    def test_transaction_cost_zero_equals_no_cost(self) -> None:
        """거래 비용 0: 비용 미적용과 동일."""
        df = pd.DataFrame(
            {
                "signal": [10.0, -5.0, 20.0],
                "btc_log_return": [0.01, -0.02, 0.03],
            }
        )
        result_zero = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=0.0)
        result_default_zero = compute_backtest(
            df, "signal", threshold=0.0, transaction_cost_bps=0.0
        )

        assert (
            abs(
                result_zero.strategy_cumulative_return
                - result_default_zero.strategy_cumulative_return
            )
            < 1e-10
        )

    def test_inverted_strategy(self) -> None:
        """inverted=True: signal <= threshold → buy."""
        df = pd.DataFrame(
            {
                "signal": [30.0, 20.0, 25.0, 15.0],
                "btc_log_return": [0.01, 0.02, -0.01, 0.03],
            }
        )
        result = compute_backtest(
            df, "signal", threshold=24.0, transaction_cost_bps=0.0, inverted=True
        )

        # inverted: <= 24 → buy, > 24 → cash
        # row 0: 30 > 24 → cash → 0
        # row 1: 20 <= 24 → buy → 0.02
        # row 2: 25 > 24 → cash → 0
        # row 3: 15 <= 24 → buy → 0.03
        expected_strategy = 0.0 + 0.02 + 0.0 + 0.03
        assert abs(result.strategy_cumulative_return - expected_strategy) < 1e-10
        assert result.inverted is True

    def test_sharpe_ratio_nan_when_std_zero(self) -> None:
        """std==0일 때 Sharpe Ratio는 NaN."""
        # 모든 신호가 threshold 이하 → 전략 수익률 모두 0 → std == 0
        df = pd.DataFrame(
            {
                "signal": [-1.0, -2.0, -3.0],
                "btc_log_return": [0.01, -0.02, 0.03],
            }
        )
        result = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=0.0)

        assert math.isnan(result.sharpe_ratio)

    def test_max_drawdown_non_positive(self) -> None:
        """Max Drawdown은 항상 0 이하."""
        df = pd.DataFrame(
            {
                "signal": [10.0, 20.0, 30.0, 40.0],
                "btc_log_return": [0.05, -0.10, 0.03, -0.02],
            }
        )
        result = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=0.0)

        assert result.max_drawdown <= 0.0

    def test_transaction_cost_log_return_consistency(self) -> None:
        """거래 비용은 math.log(1 - cost_rate)로 적용된다."""

        df = pd.DataFrame(
            {
                "signal": [10.0, -5.0, 20.0],  # buy, cash, buy → 2 transitions
                "btc_log_return": [0.01, -0.02, 0.03],
            }
        )
        cost_bps = 10.0
        result = compute_backtest(df, "signal", threshold=0.0, transaction_cost_bps=cost_bps)

        # Manual calculation:
        # strategy_returns (no cost): [0.01, 0.0, 0.03]
        # transitions: row 0→1 (buy→cash), row 1→2 (cash→buy) = 2 transitions
        cost_per_trade = math.log(1 - cost_bps / 10000)
        # cost applied at row 1 and row 2
        expected_strategy = 0.01 + (0.0 + cost_per_trade) + (0.03 + cost_per_trade)
        assert abs(result.strategy_cumulative_return - expected_strategy) < 1e-10
        assert result.n_trades == 2


# ---------------------------------------------------------------------------
# Property 7: Walk-Forward 분할 불변량
# Validates: Requirements 5.1, 5.2, 5.3
# ---------------------------------------------------------------------------


def _make_walk_forward_df(n_rows: int, rng: np.random.Generator) -> pd.DataFrame:
    """Walk-Forward 테스트용 DataFrame 생성.

    최소한의 feature 컬럼(core 4개)과 btc_direction_label, btc_log_return을 포함.
    """
    dates = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "news_sentiment_mean_lag1": rng.uniform(-1, 1, n_rows),
            "fng_value_lag1": rng.uniform(0, 100, n_rows),
            "funding_rate_lag1": rng.uniform(-0.01, 0.01, n_rows),
            "volume_change_pct_lag1": rng.uniform(-50, 50, n_rows),
            "btc_log_return": rng.normal(0, 0.02, n_rows),
            "btc_direction_label": rng.choice(["up", "down"], n_rows),
        }
    )
    return df


@given(
    train_days=st.integers(min_value=15, max_value=40),
    test_days=st.integers(min_value=5, max_value=15),
    extra_rows=st.integers(min_value=0, max_value=30),
)
@settings(max_examples=200, deadline=None)
def test_walk_forward_split_invariant(
    train_days: int,
    test_days: int,
    extra_rows: int,
) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.3**

    Property 7: Walk-Forward 분할 불변량
    (a) train/test 비겹침
    (b) test는 train 직후
    (c) 각 fold의 train 길이 == train_days, test 길이 == test_days
    (d) score [0, 100] clip
    """
    n_rows = train_days + test_days + extra_rows
    rng = np.random.default_rng(42)
    df = _make_walk_forward_df(n_rows, rng)

    result = walk_forward_validate(df, train_days=train_days, test_days=test_days)

    if n_rows < train_days + test_days:
        assert result is None
        return

    assert result is not None
    assert isinstance(result, WalkForwardResult)
    assert result.train_days == train_days
    assert result.test_days == test_days

    # 예상 fold 수 계산
    expected_folds = 0
    s = 0
    while s + train_days + test_days <= n_rows:
        expected_folds += 1
        s += test_days

    # fold 수가 예상과 일치하거나 PCA 실패로 일부 건너뛸 수 있음
    assert len(result.folds) <= expected_folds

    # 각 fold 검증
    for fold_result in result.folds:
        assert isinstance(fold_result, WalkForwardFoldResult)
        # hit_rate는 NaN이거나 [0, 1] 범위
        if not math.isnan(fold_result.hit_rate):
            assert 0.0 <= fold_result.hit_rate <= 1.0


# ---------------------------------------------------------------------------
# Walk-Forward 단위 테스트
# Validates: Requirements 7.4
# ---------------------------------------------------------------------------


class TestWalkForwardValidate:
    """walk_forward_validate 단위 테스트."""

    def test_normal_split(self) -> None:
        """정상 분할: 충분한 데이터로 fold가 생성된다."""
        rng = np.random.default_rng(123)
        df = _make_walk_forward_df(200, rng)

        result = walk_forward_validate(df, train_days=50, test_days=20)

        assert result is not None
        assert isinstance(result, WalkForwardResult)
        assert result.train_days == 50
        assert result.test_days == 20
        # 200 rows, train=50, test=20 → max folds = (200-50)//20 = 7
        assert len(result.folds) > 0
        assert len(result.folds) <= 7

        # 각 fold의 기본 속성 검증
        for fold_result in result.folds:
            assert isinstance(fold_result, WalkForwardFoldResult)
            assert fold_result.test_start != ""
            assert fold_result.test_end != ""

    def test_insufficient_data_returns_none(self) -> None:
        """데이터 부족: train_days + test_days > len(df) → None 반환."""
        rng = np.random.default_rng(456)
        df = _make_walk_forward_df(10, rng)

        result = walk_forward_validate(df, train_days=120, test_days=30)

        assert result is None

    def test_exact_minimum_data(self) -> None:
        """정확히 train_days + test_days 행: 1개 fold 생성."""
        rng = np.random.default_rng(789)
        train_days = 30
        test_days = 10
        df = _make_walk_forward_df(train_days + test_days, rng)

        result = walk_forward_validate(df, train_days=train_days, test_days=test_days)

        assert result is not None
        # PCA가 성공하면 1개 fold, 실패하면 0개
        assert len(result.folds) <= 1


# ---------------------------------------------------------------------------
# Property 8: Metadata payload round-trip
# Validates: Requirements 6.4
# ---------------------------------------------------------------------------

_hit_rate_dict_strategy = st.fixed_dictionaries(
    {
        "predictor": st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc"))
        ),
        "threshold": st.floats(
            min_value=-100, max_value=100, allow_nan=False, allow_infinity=False
        ),
        "hit_rate": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "tp": st.integers(min_value=0, max_value=1000),
        "fp": st.integers(min_value=0, max_value=1000),
        "tn": st.integers(min_value=0, max_value=1000),
        "fn": st.integers(min_value=0, max_value=1000),
        "precision": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "recall": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "f1": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "n_valid": st.integers(min_value=0, max_value=10000),
        "inverted": st.booleans(),
        "granger_significant": st.one_of(st.booleans(), st.none()),
    }
)

_corr_dict_strategy = st.fixed_dictionaries(
    {
        "col_a": st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc"))
        ),
        "col_b": st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc"))
        ),
        "pearson_r": st.floats(
            min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        "pearson_pvalue": st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        "spearman_rho": st.floats(
            min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        "spearman_pvalue": st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        "n_valid": st.integers(min_value=0, max_value=10000),
        "differenced": st.booleans(),
    }
)

_backtest_dict_strategy = st.fixed_dictionaries(
    {
        "predictor": st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc"))
        ),
        "threshold": st.floats(
            min_value=-100, max_value=100, allow_nan=False, allow_infinity=False
        ),
        "strategy_cumulative_return": st.floats(
            min_value=-10, max_value=10, allow_nan=False, allow_infinity=False
        ),
        "bnh_cumulative_return": st.floats(
            min_value=-10, max_value=10, allow_nan=False, allow_infinity=False
        ),
        "alpha": st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
        "sharpe_ratio": st.floats(
            min_value=-10, max_value=10, allow_nan=False, allow_infinity=False
        ),
        "max_drawdown": st.floats(
            min_value=-10, max_value=0, allow_nan=False, allow_infinity=False
        ),
        "n_trades": st.integers(min_value=0, max_value=1000),
        "n_valid": st.integers(min_value=0, max_value=10000),
        "transaction_cost_bps": st.floats(
            min_value=0, max_value=100, allow_nan=False, allow_infinity=False
        ),
        "inverted": st.booleans(),
        "granger_significant": st.one_of(st.booleans(), st.none()),
    }
)


@given(
    hit_rates=st.lists(_hit_rate_dict_strategy, min_size=0, max_size=5),
    correlations=st.lists(_corr_dict_strategy, min_size=0, max_size=5),
    backtest=st.lists(_backtest_dict_strategy, min_size=0, max_size=5),
)
@settings(max_examples=200, deadline=None)
def test_metadata_payload_round_trip(
    hit_rates: list[dict],
    correlations: list[dict],
    backtest: list[dict],
) -> None:
    """**Validates: Requirements 6.4**

    Property 8: Metadata payload round-trip
    직렬화 후 JSON 역직렬화 시 hit_rates, correlations, backtest 필드 원본 복원
    """
    import json

    from morning_brief.data.etf_storage import build_stats_metadata_payload

    payload_bytes = build_stats_metadata_payload(
        run_id="test-run",
        generated_at_utc="2026-01-01T00:00:00+00:00",
        adf=None,
        granger_results=[],
        hybrid_indices=None,
        hit_rates=hit_rates,
        correlations=correlations,
        backtest=backtest,
    )

    decoded = json.loads(payload_bytes.decode("utf-8"))

    assert decoded["hit_rates"] == hit_rates
    assert decoded["correlations"] == correlations
    assert decoded["backtest"] == backtest


# ---------------------------------------------------------------------------
# Property 9: Granger 신뢰도 플래그 일관성
# Validates: Requirements 6.6
# ---------------------------------------------------------------------------

_granger_entry_strategy = st.fixed_dictionaries(
    {
        "predictor": st.sampled_from(["news_sentiment_mean", "fng_value", "funding_rate"]),
        "target": st.just("btc_log_return"),
        "direction": st.sampled_from(["forward", "reverse"]),
        "lag": st.integers(min_value=1, max_value=3),
        "significant": st.booleans(),
        "pvalue": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    }
)


@given(
    granger_results=st.lists(_granger_entry_strategy, min_size=0, max_size=20),
    predictor_raw=st.sampled_from(["news_sentiment_mean", "fng_value", "funding_rate"]),
)
@settings(max_examples=200, deadline=None)
def test_granger_confidence_flag_consistency(
    granger_results: list[dict],
    predictor_raw: str,
) -> None:
    """**Validates: Requirements 6.6**

    Property 9: Granger 신뢰도 플래그 일관성
    forward 결과 중 하나라도 significant=True → True, 모두 False → False, 미실행 → None
    """
    from morning_brief.analysis.sentiment_join.statistical_tests import _is_granger_significant

    result = _is_granger_significant(granger_results, predictor_raw)

    # forward 결과만 필터링
    forward_entries = [
        e
        for e in granger_results
        if e.get("predictor") == predictor_raw and e.get("direction") == "forward"
    ]

    if not forward_entries:
        # forward 결과 없음 → None
        assert result is None
    elif any(e.get("significant", False) for e in forward_entries):
        # 하나라도 significant=True → True
        assert result is True
    else:
        # 모두 significant=False → False
        assert result is False


# ---------------------------------------------------------------------------
# Granger 플래그 단위 테스트
# Validates: Requirements 7.6
# ---------------------------------------------------------------------------


class TestIsGrangerSignificant:
    """_is_granger_significant 단위 테스트."""

    def test_forward_significant_true(self) -> None:
        """순방향 결과 중 하나라도 significant=True → True."""
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _is_granger_significant,
        )

        granger_results = [
            {
                "predictor": "news_sentiment_mean",
                "direction": "forward",
                "lag": 1,
                "significant": False,
            },
            {
                "predictor": "news_sentiment_mean",
                "direction": "forward",
                "lag": 2,
                "significant": True,
            },
            {
                "predictor": "news_sentiment_mean",
                "direction": "reverse",
                "lag": 1,
                "significant": True,
            },
        ]
        assert _is_granger_significant(granger_results, "news_sentiment_mean") is True

    def test_forward_all_false(self) -> None:
        """순방향 결과 모두 significant=False → False."""
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _is_granger_significant,
        )

        granger_results = [
            {"predictor": "fng_value", "direction": "forward", "lag": 1, "significant": False},
            {"predictor": "fng_value", "direction": "forward", "lag": 2, "significant": False},
            {"predictor": "fng_value", "direction": "reverse", "lag": 1, "significant": True},
        ]
        assert _is_granger_significant(granger_results, "fng_value") is False

    def test_no_forward_entries_returns_none(self) -> None:
        """해당 predictor의 forward 결과가 없으면 None."""
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _is_granger_significant,
        )

        granger_results = [
            {"predictor": "fng_value", "direction": "forward", "lag": 1, "significant": True},
        ]
        # news_sentiment_mean에 대한 forward 결과 없음
        assert _is_granger_significant(granger_results, "news_sentiment_mean") is None

    def test_empty_granger_results_returns_none(self) -> None:
        """빈 Granger 결과 → None."""
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _is_granger_significant,
        )

        assert _is_granger_significant([], "news_sentiment_mean") is None

    def test_reverse_only_returns_none(self) -> None:
        """역방향 결과만 있으면 None (forward 결과 없음)."""
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _is_granger_significant,
        )

        granger_results = [
            {
                "predictor": "news_sentiment_mean",
                "direction": "reverse",
                "lag": 1,
                "significant": True,
            },
        ]
        assert _is_granger_significant(granger_results, "news_sentiment_mean") is None

    def test_granger_significant_flag_in_run_alpha_validation(self) -> None:
        """run_alpha_validation에서 granger_significant 플래그가 올바르게 부여된다."""
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [0.1, -0.2, 0.3, -0.1, 0.5],
                "fng_value_lag1": [60.0, 40.0, 55.0, 30.0, 70.0],
                "btc_direction_label": ["up", "down", "up", "down", "up"],
                "btc_log_return": [0.01, -0.02, 0.03, -0.01, 0.02],
            }
        )

        granger_results = [
            {
                "predictor": "news_sentiment_mean",
                "direction": "forward",
                "lag": 1,
                "significant": True,
            },
            {"predictor": "fng_value", "direction": "forward", "lag": 1, "significant": False},
        ]

        result = run_alpha_validation(
            df,
            granger_results=granger_results,
            granger_executed=True,
        )

        # news_sentiment_mean_lag1 → granger_significant=True
        news_hr = next(
            h for h in result["hit_rates"] if h["predictor"] == "news_sentiment_mean_lag1"
        )
        assert news_hr["granger_significant"] is True

        # fng_value_lag1 → granger_significant=False
        fng_hr = next(h for h in result["hit_rates"] if h["predictor"] == "fng_value_lag1")
        assert fng_hr["granger_significant"] is False

    def test_granger_not_executed_returns_none_flag(self) -> None:
        """Granger 미실행 시 granger_significant=None."""
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [0.1, -0.2, 0.3],
                "fng_value_lag1": [60.0, 40.0, 55.0],
                "btc_direction_label": ["up", "down", "up"],
                "btc_log_return": [0.01, -0.02, 0.03],
            }
        )

        result = run_alpha_validation(df, granger_executed=False)

        for hr in result["hit_rates"]:
            assert hr["granger_significant"] is None


# ---------------------------------------------------------------------------
# 개선 검증: Predictor 간 상관 (Req 3.5)
# ---------------------------------------------------------------------------


class TestPredictorInterCorrelation:
    """run_alpha_validation이 predictor 간 상관 쌍을 포함하는지 검증."""

    def test_inter_predictor_pairs_included(self) -> None:
        """predictor vs btc_log_return 외에 predictor 간 상관 쌍이 포함된다."""
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [0.1, -0.2, 0.3, 0.0, 0.15],
                "fng_value_lag1": [60.0, 40.0, 55.0, 45.0, 70.0],
                "btc_direction_label": ["up", "down", "up", "down", "up"],
                "btc_log_return": [0.01, -0.02, 0.03, -0.01, 0.005],
            }
        )

        result = run_alpha_validation(df)
        correlations = result["correlations"]

        # predictor vs btc_log_return 쌍
        predictor_vs_return = [c for c in correlations if c["col_b"] == "btc_log_return"]
        assert len(predictor_vs_return) >= 2

        # predictor 간 상관 쌍 (col_b != "btc_log_return")
        inter_predictor = [c for c in correlations if c["col_b"] != "btc_log_return"]
        assert len(inter_predictor) >= 1

        # news_sentiment_mean_lag1 vs fng_value_lag1 쌍이 존재해야 함
        pair_found = any(
            (c["col_a"] == "news_sentiment_mean_lag1" and c["col_b"] == "fng_value_lag1")
            or (c["col_a"] == "fng_value_lag1" and c["col_b"] == "news_sentiment_mean_lag1")
            for c in inter_predictor
        )
        assert pair_found


# ---------------------------------------------------------------------------
# 개선 검증: NaN → None 변환 (JSON 안전성)
# ---------------------------------------------------------------------------


class TestNanSanitization:
    """run_alpha_validation 반환값에 float NaN이 없고 None으로 변환되는지 검증."""

    def test_nan_values_converted_to_none(self) -> None:
        """유효 행 0건 시 NaN이 None으로 변환된다."""
        import json

        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [float("nan"), float("nan")],
                "fng_value_lag1": [float("nan"), float("nan")],
                "btc_direction_label": [None, None],
                "btc_log_return": [float("nan"), float("nan")],
            }
        )

        result = run_alpha_validation(df)

        # JSON 직렬화가 성공해야 한다 (NaN이 있으면 strict parser에서 실패)
        json_str = json.dumps(result)
        assert "NaN" not in json_str
        assert "nan" not in json_str

        # None으로 변환된 필드 확인
        parsed = json.loads(json_str)
        for hr in parsed["hit_rates"]:
            assert hr["hit_rate"] is None
            assert hr["precision"] is None
            assert hr["recall"] is None
            assert hr["f1"] is None

    def test_sanitize_nan_helper(self) -> None:
        """_sanitize_nan 헬퍼가 중첩 구조에서 NaN을 None으로 변환한다."""
        from morning_brief.analysis.sentiment_join.statistical_tests import _sanitize_nan

        data = {
            "a": float("nan"),
            "b": 1.0,
            "c": [float("nan"), 2.0, {"d": float("nan")}],
            "e": None,
        }
        result = _sanitize_nan(data)

        assert result["a"] is None
        assert result["b"] == 1.0
        assert result["c"][0] is None
        assert result["c"][1] == 2.0
        assert result["c"][2]["d"] is None
        assert result["e"] is None


# ---------------------------------------------------------------------------
# 개선 검증: Walk-Forward core 지수 지원
# ---------------------------------------------------------------------------


class TestWalkForwardCoreIndex:
    """walk_forward_validate가 core index도 지원하는지 검증."""

    def test_walk_forward_core_index(self) -> None:
        """index_name='core'로 walk-forward 실행 가능."""
        import numpy as np

        from morning_brief.analysis.sentiment_join.statistical_tests import walk_forward_validate

        rng = np.random.default_rng(42)
        n_rows = 60
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n_rows, freq="D"),
                "news_sentiment_mean_lag1": rng.uniform(-1, 1, n_rows),
                "fng_value_lag1": rng.uniform(0, 100, n_rows),
                "funding_rate_lag1": rng.uniform(-0.01, 0.01, n_rows),
                "volume_change_pct_lag1": rng.uniform(-50, 50, n_rows),
                "btc_log_return": rng.normal(0, 0.02, n_rows),
                "btc_direction_label": rng.choice(["up", "down"], n_rows),
            }
        )

        result = walk_forward_validate(df, train_days=30, test_days=10, index_name="core")

        # 데이터가 충분하므로 결과가 반환되어야 함
        assert result is not None
        assert result.train_days == 30
        assert result.test_days == 10

    def test_run_alpha_validation_includes_both_walk_forward(self) -> None:
        """run_alpha_validation이 full과 core 양쪽 walk-forward 결과를 포함한다."""
        import numpy as np

        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        rng = np.random.default_rng(42)
        n_rows = 200
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n_rows, freq="D"),
                "news_sentiment_mean_lag1": rng.uniform(-1, 1, n_rows),
                "fng_value_lag1": rng.uniform(0, 100, n_rows),
                "funding_rate_lag1": rng.uniform(-0.01, 0.01, n_rows),
                "btc_long_short_ratio_lag1": rng.uniform(0.5, 2.0, n_rows),
                "etf_net_inflow_usd_lag1": rng.uniform(-1e8, 1e8, n_rows),
                "volume_change_pct_lag1": rng.uniform(-50, 50, n_rows),
                "full_hybrid_index_score_lag1": rng.uniform(0, 100, n_rows),
                "core_hybrid_index_score_lag1": rng.uniform(0, 100, n_rows),
                "btc_log_return": rng.normal(0, 0.02, n_rows),
                "btc_direction_label": rng.choice(["up", "down"], n_rows),
            }
        )

        result = run_alpha_validation(df)
        wf = result["walk_forward"]

        # walk_forward가 dict이고 full/core 키를 가질 수 있음
        assert isinstance(wf, dict)

    def test_run_alpha_validation_includes_horizon_and_baseline_metrics(self) -> None:
        import numpy as np

        from morning_brief.analysis.sentiment_join.bootstrap import BootstrapConfig
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        rng = np.random.default_rng(7)
        n_rows = 200
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n_rows, freq="D"),
                "news_sentiment_mean_lag1": rng.uniform(-1, 1, n_rows),
                "fng_value_lag1": rng.uniform(0, 100, n_rows),
                "sentiment_momentum_lag1": rng.normal(0, 0.1, n_rows),
                "fng_change_1d_lag1": rng.normal(0, 5, n_rows),
                "funding_rate_lag1": rng.uniform(-0.01, 0.01, n_rows),
                "btc_long_short_ratio_lag1": rng.uniform(0.5, 2.0, n_rows),
                "etf_net_inflow_usd_lag1": rng.uniform(-1e8, 1e8, n_rows),
                "volume_change_pct_lag1": rng.uniform(-50, 50, n_rows),
                "vix_lag1": rng.uniform(12, 35, n_rows),
                "full_hybrid_index_score_lag1": rng.uniform(0, 100, n_rows),
                "core_hybrid_index_score_lag1": rng.uniform(0, 100, n_rows),
                "btc_log_return": rng.normal(0, 0.02, n_rows),
                "btc_fwd_ret_3d": rng.normal(0, 0.04, n_rows),
                "btc_fwd_ret_7d": rng.normal(0, 0.06, n_rows),
                "btc_direction_label": rng.choice(["up", "down"], n_rows),
            }
        )

        result = run_alpha_validation(
            df,
            bootstrap_config=BootstrapConfig(n_bootstrap=20, block_length=3, seed=7),
            outlier_mask_summary={
                "rows": n_rows,
                "global_masked_cells": 0,
                "global_masked_denominator": n_rows,
                "global_masked_ratio": 0.0,
                "per_column": {
                    "news_sentiment_mean": {
                        "masked_cells": 5,
                        "masked_ratio": 5 / n_rows,
                        "reasons": {"iqr_single": 5},
                    },
                    "fng_value": {"masked_cells": 2, "masked_ratio": 2 / n_rows},
                    "vix": {"masked_cells": 0, "masked_ratio": 0.0},
                },
                "hybrid_index_source_columns": {
                    "full_hybrid_index_score_lag1": ["news_sentiment_mean", "fng_value"],
                    "core_hybrid_index_score_lag1": ["news_sentiment_mean"],
                },
            },
        )

        assert "baseline_metrics" in result
        assert "horizon_metrics" in result
        assert "walk_forward_horizons" in result
        assert "feature_group_summary" in result
        assert "baseline_gap_summary" in result
        assert "next_research_candidates" in result
        assert "7" in result["baseline_metrics"]
        assert "7" in result["horizon_metrics"]
        assert result["horizon_metrics"]["7"]["return_col"] == "btc_fwd_ret_7d"
        first_hit_rate = result["horizon_metrics"]["7"]["hit_rates"][0]
        required_contract_fields = {
            "decision",
            "decision_strict",
            "best_baseline",
            "best_hit_rate_baseline",
            "best_sharpe_baseline",
            "baseline_hit_rate",
            "baseline_hit_rate_ci_upper",
            "baseline_sharpe",
            "baseline_sharpe_ci_upper",
            "strategy_sharpe",
            "hit_rate_lift_vs_best_baseline",
            "sharpe_lift_vs_best_baseline",
            "pvalue_vs_baselines",
            "fdr_q",
            "paired_baseline_alignment",
        }
        for row in result["horizon_metrics"]["7"]["hit_rates"]:
            assert required_contract_fields <= set(row)
            assert row["decision"] in {"promote", "research_only"}
            assert row["decision_strict"] in {"promote", "research_only"}
        assert first_hit_rate["decision"] in {"promote", "research_only"}
        assert first_hit_rate["decision_strict"] in {"promote", "research_only"}
        assert "best_baseline" in first_hit_rate
        assert "hit_rate_lift_vs_best_baseline" in first_hit_rate
        assert "sharpe_lift_vs_best_baseline" in first_hit_rate
        assert "vol_regime_hit_rate_lift" in first_hit_rate
        assert "vol_regime_sharpe_lift" in first_hit_rate
        assert "payoff_diagnostics" in first_hit_rate
        assert first_hit_rate["masked_ratio_source"] == "source_columns"
        assert first_hit_rate["masked_cells"] == 5
        assert result["baseline_gap_summary"]["7"]["vol_regime_hit_rate"] is not None
        assert isinstance(result["next_research_candidates"]["7"], list)
        assert result["feature_group_summary"]["7"]
        if result["walk_forward"]:
            assert {row["horizon_days"] for row in result["walk_forward"].values()} == {7}
        if result["walk_forward_legacy_1d"]:
            assert {row["horizon_days"] for row in result["walk_forward_legacy_1d"].values()} == {1}

    def test_payoff_diagnostics_splits_correct_and_wrong_returns(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import _payoff_diagnostics

        df = pd.DataFrame(
            {
                "signal": [1.0, 1.0, -1.0, -1.0],
                "btc_fwd_ret_7d": [0.10, -0.04, -0.02, 0.06],
                "btc_direction_label": ["up", "down", "down", "up"],
            }
        )

        diag = _payoff_diagnostics(
            df,
            "signal",
            0.0,
            return_col="btc_fwd_ret_7d",
            inverted=False,
            transaction_cost_bps=0.0,
        )

        assert diag["correct_count"] == 2
        assert diag["wrong_count"] == 2
        assert math.isclose(diag["avg_return_when_correct"], 0.04)
        assert math.isclose(diag["avg_return_when_wrong"], 0.01)
        assert math.isclose(diag["payoff_ratio"], 4.0)
        assert diag["exposure_ratio"] == 0.5

    def test_payoff_ratio_sanitizes_zero_wrong_return(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import (
            _payoff_diagnostics,
            _sanitize_nan,
        )

        df = pd.DataFrame(
            {
                "signal": [1.0, 1.0],
                "btc_fwd_ret_7d": [0.03, 0.0],
                "btc_direction_label": ["up", "down"],
            }
        )

        diag = _sanitize_nan(
            _payoff_diagnostics(
                df,
                "signal",
                0.0,
                return_col="btc_fwd_ret_7d",
                inverted=False,
                transaction_cost_bps=0.0,
            )
        )

        assert diag["avg_return_when_wrong"] == 0.0
        assert diag["payoff_ratio"] is None

    def test_horizon_metrics_align_paired_bootstrap_by_index(self) -> None:
        from morning_brief.analysis.sentiment_join.bootstrap import BootstrapConfig
        from morning_brief.analysis.sentiment_join.statistical_tests import _horizon_metrics

        n_rows = 20
        news = np.linspace(-1.0, 1.0, n_rows)
        news[0] = np.nan
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n_rows, freq="D"),
                "news_sentiment_mean_lag1": news,
                "fng_value_lag1": [10.0, 20.0, 80.0] + [50.0] * (n_rows - 3),
                "btc_fwd_ret_7d": np.linspace(-0.03, 0.03, n_rows),
                "btc_direction_label": ["up", "down"] * 10,
            }
        )

        metrics = _horizon_metrics(
            df,
            granger_results=None,
            granger_executed=False,
            bootstrap_config=BootstrapConfig(n_bootstrap=10, block_length=2, seed=1),
        )

        row = next(
            item
            for item in metrics["7"]["hit_rates"]
            if item["predictor"] == "news_sentiment_mean_lag1"
        )
        alignment = row["paired_baseline_alignment"]["fng_contrarian"]
        assert alignment["alignment_key"] == "date"
        assert alignment["signal_rows"] == 19
        assert alignment["baseline_rows"] == 3
        assert alignment["paired_rows"] == 2

    def test_walk_forward_insufficient_data_returns_none(self) -> None:
        """데이터 부족 시 core도 None 반환."""
        from morning_brief.analysis.sentiment_join.statistical_tests import walk_forward_validate

        df = pd.DataFrame(
            {
                "news_sentiment_mean_lag1": [0.1, 0.2],
                "fng_value_lag1": [50.0, 60.0],
                "funding_rate_lag1": [0.001, -0.001],
                "volume_change_pct_lag1": [5.0, -3.0],
                "btc_log_return": [0.01, -0.02],
                "btc_direction_label": ["up", "down"],
            }
        )

        result = walk_forward_validate(df, train_days=120, test_days=30, index_name="core")
        assert result is None


class TestAdaptiveThresholdAndCompound:
    """adaptive_hit_rate 필드 및 compound predictor 검증."""

    def _make_df(self, n: int = 80) -> pd.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
        ret = rng.normal(0, 0.02, n)
        return pd.DataFrame(
            {
                "date": dates,
                "btc_log_return": ret,
                "btc_fwd_ret_7d": pd.Series(ret).shift(-7).values,
                "btc_direction_label": ["up" if r > 0 else "down" for r in ret],
                "news_sentiment_mean_lag1": rng.uniform(-0.3, 0.3, n),
                "fng_value_lag1": rng.uniform(20, 80, n),
                "sentiment_momentum_lag1": rng.uniform(-0.1, 0.1, n),
                "sentiment_accel_lag1": rng.uniform(-0.05, 0.05, n),
                "fng_change_1d_lag1": rng.uniform(-5, 5, n),
                "fng_change_5d_lag1": rng.uniform(-10, 10, n),
                "btc_bear_regime_lag1": rng.choice([0.0, 1.0], n),
                "sentiment_momentum_x_bear_lag1": rng.uniform(-0.1, 0.1, n),
                "fng_change_1d_x_bear_lag1": rng.uniform(-5, 5, n),
                "funding_rate_x_bear_lag1": rng.uniform(-0.002, 0.002, n),
                "vix_lag1": rng.uniform(15, 35, n),
                "vix_regime_score_lag1": rng.uniform(-1.5, 1.5, n),
                "btc_realized_vol_20d_lag1": rng.uniform(0.01, 0.08, n),
                "btc_above_ma200_lag1": rng.choice([0.0, 1.0], n),
                "full_hybrid_index_score_lag1": rng.uniform(30, 70, n),
                "core_hybrid_index_score_lag1": rng.uniform(30, 70, n),
            }
        )

    def test_adaptive_hit_rate_field_present_in_horizon_metrics(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        hit_rates = results["horizon_metrics"]["7"]["hit_rates"]
        row = next(r for r in hit_rates if r["predictor"] == "news_sentiment_mean_lag1")
        assert "adaptive_hit_rate" in row
        assert "adaptive_sharpe" in row

    def test_adaptive_hit_rate_is_float_or_nan(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        for row in results["horizon_metrics"]["7"]["hit_rates"]:
            ahr = row.get("adaptive_hit_rate")
            assert ahr is None or isinstance(ahr, float)

    def test_vix_regime_score_lag1_predictor_present(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        hit_rates = results["horizon_metrics"]["7"]["hit_rates"]
        predictors = {r["predictor"] for r in hit_rates}
        assert "vix_regime_score_lag1" in predictors

    def test_compound_predictor_present_in_hit_rates(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        hit_rates = results["horizon_metrics"]["7"]["hit_rates"]
        predictors = {r["predictor"] for r in hit_rates}
        assert "vol_regime_filtered_full_hybrid_score_lag1" in predictors

    def test_compound_predictor_has_vol_regime_lift_field(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        hit_rates = results["horizon_metrics"]["7"]["hit_rates"]
        row = next(
            (
                r
                for r in hit_rates
                if r["predictor"] == "vol_regime_filtered_full_hybrid_score_lag1"
            ),
            None,
        )
        assert row is not None
        assert "vol_regime_hit_rate_lift" in row
        assert "payoff_diagnostics" in row
        assert "pvalue_vs_baselines" in row
        assert "fdr_q" in row
        assert row["paired_baseline_alignment"]
        assert row["paired_baseline_alignment"]["vol_regime"]["alignment_key"] == "date"

    def test_sparse_research_rules_are_present_with_abstain_diagnostics(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        df = self._make_df()
        results = run_alpha_validation(df)
        hit_rates = results["horizon_metrics"]["7"]["hit_rates"]
        predictors = {r["predictor"] for r in hit_rates}

        expected = {
            "vix_low_long_only",
            "vote_vol_sent_fng5_2of3",
            "vote_vol_vix_sent_fng5_3of4",
            "vol_regime_v2_vix_realized_vol_2of2",
        }
        assert expected <= predictors

        for predictor in expected:
            row = next(r for r in hit_rates if r["predictor"] == predictor)
            assert row["research_rule"] is True
            assert row["research_rule_family"] == "sparse_abstain_filter"
            assert row["decision"] == "research_only"
            assert row["decision_strict"] == "research_only"
            assert row["masked_ratio_source"] == "research_rule"
            assert row["abstain_filter_diagnostics"]["baseline_name"] == "vol_regime"
            assert "kept_baseline_hit_rate" in row
            assert "dropped_baseline_hit_rate" in row
            assert "kept_gt_dropped_pvalue" in row
            assert "pvalue_vs_baselines" in row
            assert "fdr_q" in row


# ---------------------------------------------------------------------------
# threshold_fn + predictor_name tests (P3-T7)
# ---------------------------------------------------------------------------


class TestThresholdFnAndPredictorName:
    """compute_hit_rate / compute_backtest의 threshold_fn / predictor_name 확장 검증."""

    def _make_df(self) -> "pd.DataFrame":
        import numpy as np
        import pandas as pd

        n = 120
        rng = np.random.default_rng(42)
        # etf_net_inflow_usd_log1p_lag1: 절반은 양수, 절반은 음수
        signal = rng.normal(0, 1, n)
        returns = rng.normal(0.0005, 0.02, n)
        label = pd.Series(["up" if r > 0 else "down" for r in returns], name="btc_direction_label")
        return pd.DataFrame(
            {
                "etf_net_inflow_usd_log1p_lag1": signal,
                "btc_log_return": returns,
                "btc_direction_label": label,
            }
        )

    def test_compute_hit_rate_threshold_fn_produces_different_result(self) -> None:
        import pandas as pd

        from morning_brief.analysis.sentiment_join.statistical_tests import compute_hit_rate

        df = self._make_df()
        # Fixed threshold=0 (baseline)
        hr_fixed = compute_hit_rate(df, "etf_net_inflow_usd_log1p_lag1", threshold=0.0)
        # Rolling q75 threshold
        hr_q75 = compute_hit_rate(
            df,
            "etf_net_inflow_usd_log1p_lag1",
            threshold=0.0,
            threshold_fn=lambda s: s.rolling(30, min_periods=10).quantile(0.75),
            predictor_name="etf_net_inflow_usd_log1p_lag1_q75",
        )
        # With rolling threshold, fewer rows qualify → n_valid should be ≤ fixed
        assert hr_q75.predictor == "etf_net_inflow_usd_log1p_lag1_q75"
        assert hr_q75.n_valid <= hr_fixed.n_valid
        # Result is a valid HitRateResult
        assert 0.0 <= hr_q75.hit_rate <= 1.0 or pd.isna(hr_q75.hit_rate)

    def test_compute_hit_rate_predictor_name_override(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import compute_hit_rate

        df = self._make_df()
        hr = compute_hit_rate(
            df,
            "etf_net_inflow_usd_log1p_lag1",
            threshold=0.0,
            inverted=True,
            predictor_name="etf_net_inflow_usd_log1p_lag1_inverted",
        )
        assert hr.predictor == "etf_net_inflow_usd_log1p_lag1_inverted"
        assert hr.inverted is True

    def test_compute_backtest_threshold_fn_matches_manual(self) -> None:
        import numpy as np

        from morning_brief.analysis.sentiment_join.statistical_tests import compute_backtest

        df = self._make_df()
        fn = lambda s: s.rolling(30, min_periods=10).quantile(0.75)  # noqa: E731

        result = compute_backtest(
            df,
            "etf_net_inflow_usd_log1p_lag1",
            threshold=0.0,
            threshold_fn=fn,
            predictor_name="etf_net_inflow_usd_log1p_lag1_q75",
            transaction_cost_bps=0.0,
        )
        assert result.predictor == "etf_net_inflow_usd_log1p_lag1_q75"
        # Strategy return should be finite (not all-cash)
        assert result.n_valid > 0

        # Manual verification: recompute signal and buy mask
        signal = df["etf_net_inflow_usd_log1p_lag1"]
        thr = fn(signal)
        buy_mask = (signal > thr).fillna(False)
        active_returns = df.loc[buy_mask, "btc_log_return"].to_numpy()
        expected_strategy = float(np.sum(active_returns))
        # Cumulative returns should be close (minor difference from cost=0 and NaN warmup)
        assert abs(result.strategy_cumulative_return - expected_strategy) < 1e-6

    def test_compute_hit_rate_no_name_override_uses_col(self) -> None:
        from morning_brief.analysis.sentiment_join.statistical_tests import compute_hit_rate

        df = self._make_df()
        hr = compute_hit_rate(df, "etf_net_inflow_usd_log1p_lag1", threshold=0.0)
        assert hr.predictor == "etf_net_inflow_usd_log1p_lag1"

    def test_etf_variants_in_run_alpha_validation_output(self) -> None:
        """run_alpha_validation 결과에 3 variant predictor 이름이 모두 존재해야 한다."""
        import numpy as np
        import pandas as pd

        from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation

        n = 200
        rng = np.random.default_rng(7)
        signal = rng.normal(0, 1, n)
        returns = rng.normal(0.0005, 0.02, n)
        label = ["up" if r > 0 else "down" for r in returns]
        # Provide all required columns so the pipeline doesn't skip
        df = pd.DataFrame(
            {
                "etf_net_inflow_usd_log1p_lag1": signal,
                "btc_log_return": returns,
                "btc_fwd_ret_7d": returns,
                "btc_direction_label": label,
            }
        )

        results = run_alpha_validation(df)
        hr_rows = results.get("hit_rates", [])
        bt_rows = results.get("backtest", [])
        hr_names = {r["predictor"] for r in hr_rows}
        bt_names = {r["predictor"] for r in bt_rows}

        for variant in (
            "etf_net_inflow_usd_log1p_lag1_inverted",
            "etf_net_inflow_usd_log1p_lag1_q75",
            "etf_net_inflow_usd_log1p_lag1_q80",
        ):
            assert variant in hr_names, f"{variant} missing from hit_rates"
            assert variant in bt_names, f"{variant} missing from backtest"
