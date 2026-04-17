from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from morning_brief.analysis.sentiment_join.join import (
    _add_btc_direction_label,
    _add_sentiment_lag_columns,
    _apply_sentiment_quality_gate,
    detect_outliers_rolling_iqr,
    merge_sources,
)


def _date_range(days: int) -> list[str]:
    return pd.date_range("2026-03-01", periods=days, freq="D").strftime("%Y-%m-%d").tolist()


def _sentiment_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "news_sentiment_mean": [0.1] * days,
            "news_sentiment_std": [0.05] * days,
            "n_articles": pd.array([3] * days, dtype="Int64"),
            "sentiment_status": ["ok"] * days,
            "is_backfill_valid": [True] * days,
            "ingest_validation_reason": [None] * days,
        }
    )


def _fng_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame({"date": dates, "fng_value": pd.array([55] * days, dtype="Int64")})


def _btc_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    returns = [0.01] * days
    returns[-1] = 0.5
    return pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": [0.01] * days,
            "btc_return": returns,
            "btc_quote_volume": [1e9] * days,
        }
    )


def _futures_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "funding_rate": [0.001] * days,
            "open_interest_usd": [1000.0 + idx for idx in range(days)],
            "btc_long_short_ratio": [0.9] * days,
        }
    )


def _usdkrw_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    return pd.DataFrame(
        {
            "date": dates,
            "usdkrw_log_return": [0.001] * days,
            "usdkrw_return": [0.001] * days,
        }
    )


def _etf_df(days: int) -> pd.DataFrame:
    dates = _date_range(days)
    totals = [1000.0 + idx * 10.0 for idx in range(days)]
    return pd.DataFrame(
        {
            "date": dates,
            "etf_total_btc": totals,
            "etf_total_aum_usd": [value * 85000 for value in totals],
            "etf_net_inflow_usd": [float("nan")] + [850000.0] * (days - 1),
        }
    )


def test_merge_sources_inner_join_and_drop_missing_sentiment(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentiment_df = _sentiment_df(35)
    sentiment_df.loc[0, "news_sentiment_mean"] = np.nan
    fng_df = _fng_df(34).iloc[1:].reset_index(drop=True)
    btc_df = _btc_df(35)
    usdkrw_df = _usdkrw_df(35)

    with caplog.at_level(logging.WARNING):
        merged = merge_sources(sentiment_df, fng_df, btc_df, usdkrw_df)

    assert "close" not in merged.columns
    assert merged["news_sentiment_mean"].notna().all()
    # btc_direction_label이 존재해야 한다
    assert "btc_direction_label" in merged.columns


def test_detect_outliers_flags_extreme_value() -> None:
    df = _btc_df(40).merge(_usdkrw_df(40), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"])
    assert bool(detected.iloc[-1]["is_outlier"]) is True


def test_detect_outliers_cold_start_is_false() -> None:
    df = _btc_df(10).merge(_usdkrw_df(10), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"], min_periods=15)
    assert not detected["is_outlier"].any()


def test_detect_outliers_window_length_equal_dataset_returns_false() -> None:
    df = _btc_df(30).merge(_usdkrw_df(30), on="date")
    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"], window=30)
    assert not detected["is_outlier"].any()


def test_merge_sources_warns_when_rows_under_minimum(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        merge_sources(_sentiment_df(20), _fng_df(20), _btc_df(20), _usdkrw_df(20))

    assert any(
        getattr(record, "event", None) == "join.insufficient_rows" for record in caplog.records
    )


def test_merge_sources_sources_used_excludes_all_nan_btc() -> None:
    btc_df = _btc_df(35)
    btc_df["btc_log_return"] = np.nan
    btc_df["btc_return"] = np.nan

    merged = merge_sources(_sentiment_df(35), _fng_df(35), btc_df, _usdkrw_df(35))

    assert "is_outlier" in merged.columns


def test_merge_sources_adds_lagged_futures_columns() -> None:
    merged = merge_sources(
        _sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35), _futures_df(35)
    )

    assert pd.isna(merged.loc[0, "funding_rate_lag1"])
    assert merged.loc[1, "funding_rate_lag1"] == pytest.approx(0.001)
    assert pd.isna(merged.loc[0, "oi_change_pct_lag1"])


def test_merge_sources_adds_btc_long_short_ratio_lag1() -> None:
    merged = merge_sources(
        _sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35), _futures_df(35)
    )

    assert "btc_long_short_ratio_lag1" in merged.columns
    assert pd.isna(merged.loc[0, "btc_long_short_ratio_lag1"])
    assert merged.loc[1, "btc_long_short_ratio_lag1"] == pytest.approx(0.9)


def test_merge_sources_adds_etf_flow_lag1() -> None:
    merged = merge_sources(
        _sentiment_df(35),
        _fng_df(35),
        _btc_df(35),
        _usdkrw_df(35),
        _futures_df(35),
        _etf_df(35),
    )

    assert "etf_net_inflow_usd_lag1" in merged.columns
    assert pd.isna(merged.loc[0, "etf_net_inflow_usd_lag1"])
    assert merged.loc[2, "etf_net_inflow_usd_lag1"] == pytest.approx(850000.0)


def test_merge_sources_outlier_detection_includes_long_short_ratio() -> None:
    futures_df = _futures_df(40)
    futures_df.loc[39, "btc_long_short_ratio"] = 999.0

    merged = merge_sources(_sentiment_df(40), _fng_df(40), _btc_df(40), _usdkrw_df(40), futures_df)

    assert bool(merged.iloc[-1]["is_outlier"]) is True


def test_merge_sources_btc_quote_volume_preserved() -> None:
    merged = merge_sources(_sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35))

    assert "btc_quote_volume" in merged.columns


@settings(max_examples=100)
@given(length=st.integers(min_value=31, max_value=60))
def test_detect_outliers_constant_series_is_false(length: int) -> None:
    dates = _date_range(length)
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_return": [0.01] * length,
            "usdkrw_return": [0.001] * length,
        }
    )

    detected = detect_outliers_rolling_iqr(df, ["btc_return", "usdkrw_return"])

    assert not detected["is_outlier"].any()


@settings(max_examples=100)
@given(length=st.integers(min_value=35, max_value=60))
def test_merge_sources_never_returns_nan_sentiment(length: int) -> None:
    sentiment_df = _sentiment_df(length)
    sentiment_df.loc[0, "news_sentiment_mean"] = np.nan

    merged = merge_sources(sentiment_df, _fng_df(length), _btc_df(length), _usdkrw_df(length))

    assert merged["news_sentiment_mean"].notna().all()


# ── 감성 품질 게이트 테스트 ──


def test_quality_gate_removes_insufficient_article_count() -> None:
    """Req 6.1: count <= 1인 날짜 제거."""
    df = _sentiment_df(3)
    df.loc[0, "n_articles"] = 1
    df.loc[1, "n_articles"] = 0

    filtered, counts = _apply_sentiment_quality_gate(df)

    assert len(filtered) == 1
    assert counts["insufficient_article_count"] == 2


def test_quality_gate_removes_skipped_sentiment() -> None:
    """Req 6.2: sentimentStatus == 'skipped' 제거."""
    df = _sentiment_df(3)
    df.loc[1, "sentiment_status"] = "skipped"

    filtered, counts = _apply_sentiment_quality_gate(df)

    assert len(filtered) == 2
    assert counts["skipped_sentiment"] == 1


def test_quality_gate_removes_invalid_backfill() -> None:
    """Req 6.3: _backfill 검증 실패 제거."""
    df = _sentiment_df(3)
    df.loc[0, "is_backfill_valid"] = False
    df.loc[0, "ingest_validation_reason"] = "missing_backfill_marker"

    filtered, counts = _apply_sentiment_quality_gate(df)

    assert len(filtered) == 2
    assert counts["missing_backfill_marker"] == 1


def test_quality_gate_exclusion_reasons_are_standard() -> None:
    """Req 6.4: 제외 사유가 표준값인지 검증."""
    df = _sentiment_df(1)
    _, counts = _apply_sentiment_quality_gate(df)

    expected_reasons = {
        "missing_backfill_marker",
        "insufficient_article_count",
        "skipped_sentiment",
        "invalid_contract",
        "no_sentiment",
    }
    assert set(counts.keys()) == expected_reasons


# ── btc_direction_label 테스트 ──


def test_btc_direction_label_matches_sign() -> None:
    """Property 5: btc_direction_label은 btc_log_return 부호와 일치."""
    df = pd.DataFrame(
        {
            "btc_log_return": [0.05, -0.03, 0.0, np.nan],
        }
    )
    result = _add_btc_direction_label(df)

    assert result.loc[0, "btc_direction_label"] == "up"
    assert result.loc[1, "btc_direction_label"] == "down"
    assert result.loc[2, "btc_direction_label"] == "flat"
    assert pd.isna(result.loc[3, "btc_direction_label"])


def test_merge_sources_includes_direction_label() -> None:
    merged = merge_sources(_sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35))

    assert "btc_direction_label" in merged.columns
    # btc_log_return이 0.01이면 label은 "up"
    assert (merged["btc_direction_label"] == "up").all()


def test_merge_sources_exclusion_counts_in_attrs() -> None:
    merged = merge_sources(_sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35))

    assert "exclusion_counts" in merged.attrs
    counts = merged.attrs["exclusion_counts"]
    assert isinstance(counts, dict)
    assert "missing_backfill_marker" in counts


# ── §1: 감성·공포지수 Lag-1 테스트 ──


def test_merge_sources_adds_sentiment_lag1_columns() -> None:
    """§1: merge_sources 결과에 news_sentiment_mean_lag1, fng_value_lag1이 존재해야 한다."""
    merged = merge_sources(_sentiment_df(35), _fng_df(35), _btc_df(35), _usdkrw_df(35))

    assert "news_sentiment_mean_lag1" in merged.columns
    assert "fng_value_lag1" in merged.columns


def test_add_sentiment_lag_columns_first_row_is_nan() -> None:
    """§1: 첫 행은 NaN이어야 한다 (shift(1) 특성)."""
    df = _sentiment_df(5).merge(_fng_df(5), on="date")
    result = _add_sentiment_lag_columns(df)

    assert pd.isna(result.loc[0, "news_sentiment_mean_lag1"])
    assert pd.isna(result.loc[0, "fng_value_lag1"])


def test_add_sentiment_lag_columns_second_row_equals_first_value() -> None:
    """§1: 두 번째 행은 이전 날 원본 값과 동일해야 한다."""
    df = _sentiment_df(5).merge(_fng_df(5), on="date")
    result = _add_sentiment_lag_columns(df)

    assert result.loc[1, "news_sentiment_mean_lag1"] == pytest.approx(
        df.loc[0, "news_sentiment_mean"]
    )
    assert result.loc[1, "fng_value_lag1"] == pytest.approx(float(df.loc[0, "fng_value"]))


def test_merge_sources_sentiment_lag1_is_t_minus_1() -> None:
    """§1: lag1 값이 실제로 T-1 시점의 원본 값과 일치해야 한다."""
    sentiment_df = _sentiment_df(10)
    # 날짜별로 다른 값 설정
    for i in range(10):
        sentiment_df.loc[i, "news_sentiment_mean"] = round(0.1 * (i + 1), 2)

    merged = merge_sources(sentiment_df, _fng_df(10), _btc_df(10), _usdkrw_df(10))

    for i in range(1, len(merged)):
        assert merged.loc[i, "news_sentiment_mean_lag1"] == pytest.approx(
            merged.loc[i - 1, "news_sentiment_mean"]
        )


# ── §8-A: NaN 마스킹 동작 테스트 ──


def _make_master_with_outlier(rows: int = 10) -> pd.DataFrame:
    """is_outlier=True 행이 포함된 최소 master_df 픽스처."""
    merged = merge_sources(_sentiment_df(rows), _fng_df(rows), _btc_df(rows), _usdkrw_df(rows))
    # 마지막 행을 이상치로 표시
    merged.loc[rows - 1, "is_outlier"] = True
    return merged


def test_nan_masking_preserves_row_count() -> None:
    """Property B-1: NaN 마스킹 후 len(analysis_df) == len(master_df)이어야 한다."""
    master_df = _make_master_with_outlier(10)
    _NON_MASK_COLS = frozenset(
        {
            "date",
            "is_outlier",
            "sentiment_status",
            "is_backfill_valid",
            "ingest_validation_reason",
            "btc_direction_label",
            "text_schema_version",
        }
    )
    analysis_df = master_df.copy()
    _mask_cols = [c for c in analysis_df.columns if c not in _NON_MASK_COLS]
    analysis_df.loc[analysis_df["is_outlier"], _mask_cols] = np.nan

    # Property B-1: 행 수 보존
    assert len(analysis_df) == len(master_df)


def test_nan_masking_sets_numeric_cols_to_nan_for_outliers() -> None:
    """Property B-2: is_outlier=True인 행의 btc_log_return은 NaN이어야 한다."""
    master_df = _make_master_with_outlier(10)
    _NON_MASK_COLS = frozenset(
        {
            "date",
            "is_outlier",
            "sentiment_status",
            "is_backfill_valid",
            "ingest_validation_reason",
            "btc_direction_label",
            "text_schema_version",
        }
    )
    analysis_df = master_df.copy()
    _mask_cols = [c for c in analysis_df.columns if c not in _NON_MASK_COLS]
    analysis_df.loc[analysis_df["is_outlier"], _mask_cols] = np.nan

    outlier_rows = analysis_df[analysis_df["is_outlier"]]
    # Property B-2: 이상치 행의 수치 컬럼은 NaN
    assert outlier_rows["btc_log_return"].isna().all()
    # 날짜·플래그 컬럼은 보존
    assert not outlier_rows["date"].isna().any()
    assert not outlier_rows["is_outlier"].isna().any()


def test_nan_masking_non_outlier_rows_unchanged() -> None:
    """이상치가 아닌 행의 수치값은 마스킹 후에도 원본과 동일해야 한다."""
    master_df = _make_master_with_outlier(10)
    _NON_MASK_COLS = frozenset(
        {
            "date",
            "is_outlier",
            "sentiment_status",
            "is_backfill_valid",
            "ingest_validation_reason",
            "btc_direction_label",
            "text_schema_version",
        }
    )
    analysis_df = master_df.copy()
    _mask_cols = [c for c in analysis_df.columns if c not in _NON_MASK_COLS]
    analysis_df.loc[analysis_df["is_outlier"], _mask_cols] = np.nan

    non_outlier_orig = master_df[~master_df["is_outlier"]]["btc_log_return"]
    non_outlier_masked = analysis_df[~analysis_df["is_outlier"]]["btc_log_return"]
    pd.testing.assert_series_equal(non_outlier_orig, non_outlier_masked)
