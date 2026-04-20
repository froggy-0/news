from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.feature_store import build_feature_store


def _frame(rows: int = 40) -> pd.DataFrame:
    idx = np.arange(rows)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "is_outlier": False,
            "btc_log_return": np.sin(idx / 5) * 0.01,
            "btc_direction_label": ["up"] * rows,
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "oi_change_pct_lag1": np.cos(idx / 10) * 0.02,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
            "vix_lag1": 18 + np.sin(idx / 10) * 3,
            "funding_source": "binance",
        }
    )


def test_feature_store_preserves_layers_and_order() -> None:
    df = _frame()
    bundle = build_feature_store(df, cache_key="unit")

    assert len(bundle.raw) == len(df)
    assert len(bundle.clean) == len(df)
    assert len(bundle.model) == len(df)
    assert bundle.raw["date"].tolist() == df["date"].tolist()
    assert bundle.manifest["cache_key"] == "unit"


def test_feature_store_writes_snapshots(tmp_path: Path) -> None:
    bundle = build_feature_store(_frame(), cache_key="unit", output_dir=tmp_path)

    assert bundle.output_dir == tmp_path
    assert (tmp_path / "features_raw.parquet").exists()
    assert (tmp_path / "features_clean.parquet").exists()
    assert (tmp_path / "features_model.parquet").exists()
    assert (tmp_path / "manifest.json").exists()
    assert bundle.manifest["lineage"]["funding_source"] == ["binance"]
