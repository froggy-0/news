from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from morning_brief.analysis.sentiment_join.storage import (
    cleanup_old_files,
    save_parquet,
    upload_to_r2,
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.1],
            "news_sentiment_std": [0.05],
            "n_articles": pd.array([3], dtype="Int64"),
            "fng_value": pd.array([55], dtype="Int64"),
            "btc_log_return": [0.01],
            "btc_return": [0.01],
            "usdkrw_log_return": [0.001],
            "usdkrw_return": [0.001],
            "is_outlier": [False],
        }
    )


def test_save_parquet_creates_snappy_file(tmp_path: Path) -> None:
    path = save_parquet(_sample_df(), tmp_path, "20260410", ffill_days=3)

    metadata = pq.read_metadata(path)
    assert path.exists()
    assert metadata.row_group(0).column(0).compression == "SNAPPY"
    assert metadata.metadata[b"ffill_days"] == b"3"


def test_save_parquet_overwrites_same_date(tmp_path: Path) -> None:
    first = _sample_df()
    second = _sample_df()
    second.loc[0, "news_sentiment_mean"] = 0.9

    path = save_parquet(first, tmp_path, "20260410")
    save_parquet(second, tmp_path, "20260410")

    files = list(tmp_path.glob("master_*.parquet"))
    reloaded = pd.read_parquet(path)
    assert len(files) == 1
    assert reloaded.loc[0, "news_sentiment_mean"] == 0.9


def test_save_parquet_round_trip_preserves_dtypes(tmp_path: Path) -> None:
    path = save_parquet(_sample_df(), tmp_path, "20260410")
    df_read = pd.read_parquet(path)

    assert df_read["n_articles"].dtype == pd.Int64Dtype()
    assert df_read["fng_value"].dtype == pd.Int64Dtype()
    assert df_read["is_outlier"].dtype == bool


def test_cleanup_old_files_removes_old_parquet(tmp_path: Path) -> None:
    today = datetime.now(timezone.utc).date()
    old_date = (today - timedelta(days=31)).strftime("%Y%m%d")
    recent_date = today.strftime("%Y%m%d")
    save_parquet(_sample_df(), tmp_path, old_date)
    save_parquet(_sample_df(), tmp_path, recent_date)

    cleanup_old_files(tmp_path, retain_days=30)

    assert not (tmp_path / f"master_{old_date}.parquet").exists()
    assert (tmp_path / f"master_{recent_date}.parquet").exists()


def test_cleanup_old_files_noop_when_zero(tmp_path: Path) -> None:
    save_parquet(_sample_df(), tmp_path, "20260410")

    cleanup_old_files(tmp_path, retain_days=0)

    assert (tmp_path / "master_20260410.parquet").exists()


def test_upload_to_r2_stub_returns_without_error(tmp_path: Path) -> None:
    path = save_parquet(_sample_df(), tmp_path, "20260410")
    upload_to_r2(
        path,
        "sentiment_join/master_20260410.parquet",
        r2_s3_endpoint="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_public_bucket="",
    )
