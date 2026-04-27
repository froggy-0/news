from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaError, SchemaErrorReason, SchemaErrors

from morning_brief.analysis.sentiment_join import validate as validate_module
from morning_brief.analysis.sentiment_join.validate import MASTER_SCHEMA, validate_master


def _valid_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.1],
            "news_sentiment_std": [0.05],
            "n_articles": pd.array([3], dtype="Int64"),
            "sentiment_status": ["ok"],
            "is_backfill_valid": [True],
            "ingest_validation_reason": [None],
            "fng_value": pd.array([55], dtype="Int64"),
            "btc_log_return": [0.01],
            "btc_return": [0.01],
            "btc_quote_volume": [float("nan")],
            "usdkrw_log_return": [0.001],
            "usdkrw_return": [0.001],
            "is_outlier": [False],
            # Req 11: 선물 시장 지표 (NaN 허용)
            "funding_rate": [float("nan")],
            "open_interest_usd": [float("nan")],
            "funding_rate_lag1": [float("nan")],
            "oi_change_pct": [float("nan")],
            "oi_change_pct_lag1": [float("nan")],
            "btc_long_short_ratio": [float("nan")],
            "btc_long_short_ratio_lag1": [float("nan")],
            "etf_total_btc": [float("nan")],
            "etf_total_aum_usd": [float("nan")],
            "etf_net_inflow_usd": [float("nan")],
            "etf_net_inflow_usd_lag1": [float("nan")],
            # §3: Granger raw predictors (NaN 허용)
            "volume_change_pct": [float("nan")],
            # §5: PCA / correlation용 lag1 (NaN 허용)
            "usdkrw_log_return_lag1": [float("nan")],
            "volume_change_pct_lag1": [float("nan")],
            # Req 8: BTC 방향 라벨
            "btc_direction_label": ["up"],
            # Multi-horizon forward targets (마지막 k개 행은 NaN — lookahead 차단)
            "btc_fwd_ret_1d": [float("nan")],
            "btc_fwd_ret_3d": [float("nan")],
            "btc_fwd_ret_7d": [float("nan")],
            "btc_fwd_vol_5d": [float("nan")],
            "btc_large_move_3d": pd.array([pd.NA], dtype="Int64"),
            "btc_realized_vol_20d_lag1": [float("nan")],
            "btc_large_move_3d_vol_adj": pd.array([pd.NA], dtype="Int64"),
            # §4 v4: full / core 하이브리드 지수 + 0~100 score (NaN 허용)
            "full_hybrid_index": [float("nan")],
            "full_hybrid_index_score": [float("nan")],
            "core_hybrid_index": [float("nan")],
            "core_hybrid_index_score": [float("nan")],
            # §4 v4: hybrid index score Lag-1 (alpha validation용)
            "full_hybrid_index_score_lag1": [float("nan")],
            "core_hybrid_index_score_lag1": [float("nan")],
            # §1: 감성·공포지수 Lag-1 (첫 행은 NaN 허용)
            "news_sentiment_mean_lag1": [float("nan")],
            "fng_value_lag1": [float("nan")],
            # §2: 텍스트 스키마 버전 (없으면 None 허용)
            "text_schema_version": [None],
            # §4 3-4: VIX optional (수집 실패 시 NaN)
            "vix": [float("nan")],
            "vix_lag1": [float("nan")],
            "funding_source": ["empty"],
            "oi_source": ["empty"],
            "lsr_source": ["empty"],
            "etf_source": ["empty"],
            "vix_source": ["empty"],
            # 1-A: Level→Delta 피처 (NaN 허용)
            "fng_change_1d": [float("nan")],
            "fng_change_5d": [float("nan")],
            "fng_change_1d_lag1": [float("nan")],
            "fng_change_5d_lag1": [float("nan")],
            "sentiment_momentum": [float("nan")],
            "sentiment_accel": [float("nan")],
            "sentiment_momentum_lag1": [float("nan")],
            "sentiment_accel_lag1": [float("nan")],
            # 1-B: BTC 레짐 피처 (NaN 허용)
            "btc_ma_200d": [float("nan")],
            "btc_drawdown_90d": [float("nan")],
            "btc_above_ma200": [float("nan")],
            "btc_above_ma200_lag1": [float("nan")],
            "btc_bear_regime_lag1": [float("nan")],
            "sentiment_momentum_x_bear_lag1": [float("nan")],
            "fng_change_1d_x_bear_lag1": [float("nan")],
            "funding_rate_x_bear_lag1": [float("nan")],
        }
    )


def test_validate_master_accepts_valid_frame() -> None:
    validate_master(_valid_df())


def test_validate_master_rejects_sentiment_out_of_range() -> None:
    df = _valid_df()
    df.loc[0, "news_sentiment_mean"] = 1.5
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_fng_out_of_range() -> None:
    df = _valid_df()
    df.loc[0, "fng_value"] = 101
    df["fng_value"] = pd.array(df["fng_value"], dtype="Int64")
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_negative_n_articles() -> None:
    df = _valid_df()
    df.loc[0, "n_articles"] = -1
    df["n_articles"] = pd.array(df["n_articles"], dtype="Int64")
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_duplicate_dates() -> None:
    df = pd.concat([_valid_df(), _valid_df()], ignore_index=True)
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_null_is_outlier() -> None:
    df = _valid_df()
    df["is_outlier"] = pd.Series([pd.NA], dtype="object")
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_non_nullable_int64_dtype() -> None:
    df = _valid_df()
    df["n_articles"] = pd.Series([3], dtype="int64")
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_extra_columns() -> None:
    df = _valid_df()
    df["close"] = [100.0]
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_normalizes_schema_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _valid_df()

    def raise_schema_errors(frame: pd.DataFrame) -> None:
        raise SchemaErrors(
            schema=MASTER_SCHEMA,
            schema_errors=[
                SchemaError(
                    schema=MASTER_SCHEMA,
                    data=frame,
                    message="column 'close' not in DataFrameSchema",
                    failure_cases="close",
                    check="column_in_schema",
                    reason_code=SchemaErrorReason.COLUMN_NOT_IN_SCHEMA,
                )
            ],
            data=frame,
        )

    monkeypatch.setattr(validate_module.MASTER_SCHEMA, "validate", raise_schema_errors)

    with pytest.raises(SchemaError, match="column 'close' not in DataFrameSchema"):
        validate_master(df)


def test_validate_master_accepts_new_nullable_columns() -> None:
    df = _valid_df()
    # btc_quote_volume, btc_long_short_ratio, btc_long_short_ratio_lag1 모두 NaN 허용
    validate_master(df)


def test_validate_master_rejects_negative_quote_volume() -> None:
    df = _valid_df()
    df["btc_quote_volume"] = [-1.0]
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_rejects_negative_long_short_ratio() -> None:
    df = _valid_df()
    df["btc_long_short_ratio"] = [-0.1]
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_strict_requires_all_new_columns() -> None:
    for missing_col in (
        "btc_quote_volume",
        "btc_long_short_ratio",
        "btc_long_short_ratio_lag1",
        "etf_total_btc",
        "etf_total_aum_usd",
        "etf_net_inflow_usd",
        "etf_net_inflow_usd_lag1",
        # §1: 신규 lag1 컬럼
        "news_sentiment_mean_lag1",
        "fng_value_lag1",
        # §2: 텍스트 스키마 버전
        "text_schema_version",
        # §3, §5: task 03 신규 raw / lag1 컬럼
        "oi_change_pct",
        "volume_change_pct",
        "usdkrw_log_return_lag1",
        "volume_change_pct_lag1",
        "funding_source",
        "oi_source",
        "lsr_source",
        "etf_source",
        "vix_source",
    ):
        df = _valid_df().drop(columns=[missing_col])
        with pytest.raises(SchemaError):
            validate_master(df)


def test_validate_master_accepts_valid_sentiment_lag1() -> None:
    """§1: 유효 범위 내 lag1 값은 통과해야 한다."""
    df = _valid_df()
    df["news_sentiment_mean_lag1"] = [0.5]
    df["fng_value_lag1"] = [60.0]
    validate_master(df)


def test_validate_master_rejects_sentiment_lag1_out_of_range() -> None:
    """§1: lag1 값이 [-1, 1] 범위를 벗어나면 거부해야 한다."""
    df = _valid_df()
    df["news_sentiment_mean_lag1"] = [1.5]
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_accepts_text_schema_version_str() -> None:
    """§2: text_schema_version이 문자열이면 통과해야 한다."""
    df = _valid_df()
    df["text_schema_version"] = ["title_summary"]
    validate_master(df)


def test_validate_master_accepts_hybrid_score_lag1_nan() -> None:
    """§4 v4: hybrid index score lag1 컬럼이 NaN(nullable float)으로 통과해야 한다."""
    df = _valid_df()
    validate_master(df)
    assert pd.isna(df["full_hybrid_index_score_lag1"].iloc[0])
    assert pd.isna(df["core_hybrid_index_score_lag1"].iloc[0])


def test_validate_master_accepts_hybrid_score_lag1_valid_range() -> None:
    """§4 v4: hybrid index score lag1 값이 0~100 범위이면 통과해야 한다."""
    df = _valid_df()
    df["full_hybrid_index_score_lag1"] = [55.0]
    df["core_hybrid_index_score_lag1"] = [72.3]
    validate_master(df)


def test_validate_master_rejects_hybrid_score_lag1_out_of_range() -> None:
    """§4 v4: hybrid index score lag1 값이 0~100 범위를 벗어나면 거부해야 한다."""
    df = _valid_df()
    df["full_hybrid_index_score_lag1"] = [101.0]
    with pytest.raises(SchemaError):
        validate_master(df)


def test_validate_master_strict_requires_hybrid_score_lag1_columns() -> None:
    """§4 v4: strict 모드에서 lag1 컬럼이 누락되면 거부해야 한다."""
    for missing_col in ("full_hybrid_index_score_lag1", "core_hybrid_index_score_lag1"):
        df = _valid_df().drop(columns=[missing_col])
        with pytest.raises(SchemaError):
            validate_master(df)


def _two_row_df_from_valid() -> pd.DataFrame:
    """`_valid_df()` 1-row 를 복제해 t=0(NaN), t=1(값) 2-row 로 확장."""
    base = _valid_df()
    second = base.copy()
    second.loc[0, "date"] = "2026-04-11"
    return pd.concat([base, second], ignore_index=True)


def test_validate_master_rejects_lag1_non_nan_at_first_row() -> None:
    """다중 행 master DF 의 첫 행(가장 이른 date) 에 lag1 값이 채워져 있으면 거부해야 한다."""
    df = _two_row_df_from_valid()
    df.loc[0, "news_sentiment_mean_lag1"] = 0.42  # t=0 에 lag1 값 → lookahead
    with pytest.raises(SchemaError, match="lag1 columns must have NaN at first date"):
        validate_master(df)


def test_validate_master_accepts_lag1_value_at_second_row() -> None:
    """t=0 NaN, t=1 값 채움 — 정상 시계열 시작 패턴."""
    df = _two_row_df_from_valid()
    df.loc[1, "news_sentiment_mean_lag1"] = 0.42
    df.loc[1, "fng_value_lag1"] = 55.0
    validate_master(df)
