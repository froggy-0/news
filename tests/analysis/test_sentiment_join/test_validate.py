from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaError

from morning_brief.analysis.sentiment_join.validate import validate_master


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
            "oi_change_pct_lag1": [float("nan")],
            "btc_long_short_ratio": [float("nan")],
            "btc_long_short_ratio_lag1": [float("nan")],
            "etf_total_btc": [float("nan")],
            "etf_total_aum_usd": [float("nan")],
            "etf_net_inflow_usd": [float("nan")],
            "etf_net_inflow_usd_lag1": [float("nan")],
            # Req 8: BTC 방향 라벨
            "btc_direction_label": ["up"],
            # Req 13: 하이브리드 지수 (NaN 허용)
            "hybrid_index": [float("nan")],
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
    ):
        df = _valid_df().drop(columns=[missing_col])
        with pytest.raises(SchemaError):
            validate_master(df)
