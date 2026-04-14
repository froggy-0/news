from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
from pandera.errors import SchemaError

from morning_brief.analysis.sentiment_join import pipeline
from morning_brief.analysis.sentiment_join.config import SentimentJoinSettings


def _settings(tmp_path: Path) -> SentimentJoinSettings:
    return SentimentJoinSettings(
        lookback_days=30,
        output_dir=tmp_path,
        r2_public_bucket="news-data",
        r2_base_url="https://bucket.example",
        r2_max_concurrency=10,
        retain_days=30,
        kis_app_key="",
        kis_app_secret="",
        binance_api_key="",
        futures_lambda_arn="",
    )


def _core_dates(settings: SentimentJoinSettings) -> tuple[str, str, str, list[str], list[str]]:
    today = datetime.now(timezone.utc).date()
    end_date = today.isoformat()
    start_date = (today - timedelta(days=settings.lookback_days)).isoformat()
    btc_start = (today - timedelta(days=settings.lookback_days + 1)).isoformat()
    main_dates = pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d").tolist()
    btc_dates = pd.date_range(btc_start, end_date, freq="D").strftime("%Y-%m-%d").tolist()
    return start_date, end_date, btc_start, main_dates, btc_dates


def _sentiment_df(main_dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": main_dates,
            "news_sentiment_mean": [0.1] * len(main_dates),
            "news_sentiment_std": [0.05] * len(main_dates),
            "n_articles": pd.array([3] * len(main_dates), dtype="Int64"),
            "sentiment_status": ["ok"] * len(main_dates),
            "is_backfill_valid": [True] * len(main_dates),
            "ingest_validation_reason": [None] * len(main_dates),
        }
    )


def _fng_df(main_dates: list[str], *, fill_value: object = 55) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": main_dates,
            "fng_value": pd.array([fill_value] * len(main_dates), dtype="Int64"),
        }
    )


def _close_df(btc_dates: list[str], *, with_gap: bool = False, base: float = 100.0) -> pd.DataFrame:
    """usdkrw 등 일반 close DataFrame (btc_quote_volume 없음)."""
    closes = [base + idx for idx in range(len(btc_dates))]
    if with_gap and len(closes) > 3:
        closes[2] = None
        closes[3] = None
        closes[4] = base + 4
    return pd.DataFrame({"date": btc_dates, "close": closes})


def _btc_close_df(
    btc_dates: list[str], *, with_gap: bool = False, base: float = 100.0
) -> pd.DataFrame:
    """Binance klines 응답을 시뮬레이션하는 BTC close DataFrame."""
    closes = [base + idx for idx in range(len(btc_dates))]
    if with_gap and len(closes) > 3:
        closes[2] = None
        closes[3] = None
        closes[4] = base + 4
    df = pd.DataFrame(
        {"date": btc_dates, "close": closes, "btc_quote_volume": [1e9] * len(btc_dates)}
    )
    df.attrs["btc_source"] = "binance"
    df.attrs["fallback_used"] = False
    return df


def _etf_df(main_dates: list[str]) -> pd.DataFrame:
    totals = [1000.0 + idx * 10.0 for idx in range(len(main_dates))]
    return pd.DataFrame(
        {
            "date": main_dates,
            "etf_total_btc": totals,
            "etf_total_aum_usd": [value * 85000 for value in totals],
        }
    )


def test_run_sentiment_join_success_creates_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, with_gap=True, base=100.0),
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_usdkrw_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=1300.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    exit_code = pipeline.run_sentiment_join(settings)

    files = list(tmp_path.glob("master_*.parquet"))
    assert exit_code == 0
    assert len(files) == 1
    metadata = pd.read_parquet(files[0])
    assert not metadata.empty


def test_run_sentiment_join_allows_single_source_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_fng",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "date": main_dates,
                "fng_value": pd.array([pd.NA] * len(main_dates), dtype="Int64"),
            }
        ),
    )
    monkeypatch.setattr(
        pipeline, "fetch_btc_close_binance", lambda *args, **kwargs: _btc_close_df(btc_dates)
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    exit_code = pipeline.run_sentiment_join(settings)
    file_path = next(tmp_path.glob("master_*.parquet"))
    saved = pd.read_parquet(file_path)

    assert exit_code == 0
    assert saved["fng_value"].isna().all()


def test_run_sentiment_join_returns_one_when_all_sources_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, _ = _core_dates(settings)
    monkeypatch.setattr(
        pipeline,
        "fetch_r2_sentiment",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "date": main_dates,
                "news_sentiment_mean": [float("nan")] * len(main_dates),
                "news_sentiment_std": [float("nan")] * len(main_dates),
                "n_articles": pd.array([pd.NA] * len(main_dates), dtype="Int64"),
            }
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_fng",
        lambda *args, **kwargs: pd.DataFrame(
            {"date": main_dates, "fng_value": pd.array([pd.NA] * len(main_dates), dtype="Int64")}
        ),
    )
    monkeypatch.setattr(pipeline, "fetch_btc_close_binance", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: pd.DataFrame())

    exit_code = pipeline.run_sentiment_join(settings)

    assert exit_code == 1
    assert not list(tmp_path.glob("master_*.parquet"))


def test_run_sentiment_join_returns_one_on_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline, "fetch_btc_close_binance", lambda *args, **kwargs: _btc_close_df(btc_dates)
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )
    monkeypatch.setattr(
        pipeline,
        "validate_master",
        lambda df: (_ for _ in ()).throw(SchemaError("bad", schema=None, data=df)),
    )

    exit_code = pipeline.run_sentiment_join(settings)

    assert exit_code == 1
    assert not list(tmp_path.glob("master_*.parquet"))


def test_run_sentiment_join_records_ffill_days_in_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, with_gap=True, base=100.0),
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_usdkrw_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=1300.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    metadata = pq.read_metadata(file_path).metadata
    assert int(metadata[b"ffill_days"]) >= 2
    assert b"sentiment_join_stats" in metadata


def test_pipeline_does_not_import_main_pipeline() -> None:
    mod = importlib.import_module("morning_brief.analysis.sentiment_join.pipeline")
    source = inspect.getsource(mod)
    assert "from morning_brief.pipeline" not in source
    assert "from morning_brief.config import Settings" not in source


def test_run_sentiment_join_btc_quote_volume_passes_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """btc_quote_volume이 pipeline 전체를 통과해 Parquet에 저장되는지 확인."""
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, base=100.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    saved = pd.read_parquet(file_path)
    assert "btc_quote_volume" in saved.columns


def test_run_sentiment_join_btc_source_recorded_in_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """btc_source가 Parquet 메타데이터에 기록되는지 확인."""
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, base=100.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    meta = pq.read_metadata(file_path).metadata
    assert b"btc_source" in meta
    assert meta[b"btc_source"].decode() == "binance"


def test_run_sentiment_join_adf_dict_structure_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADF 결과가 dict[str, dict] 구조일 때 pipeline이 정상 직렬화하는지 확인."""
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, base=100.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )
    # 다중 ADF 구조 mock
    monkeypatch.setattr(
        pipeline,
        "run_statistical_tests",
        lambda df: {
            "adf": {"btc_log_return": {"statistic": -3.2, "pvalue": 0.02, "stationary": True}},
            "granger": [],
        },
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    meta = pq.read_metadata(file_path).metadata
    assert b"sentiment_join_stats" in meta
    import json

    stats = json.loads(meta[b"sentiment_join_stats"].decode())
    assert "btc_log_return" in stats["adf"]


def test_run_sentiment_join_records_etf_columns_and_outlier_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close_binance",
        lambda *args, **kwargs: _btc_close_df(btc_dates, base=100.0),
    )
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    saved = pd.read_parquet(file_path)
    stats = json.loads(pq.read_metadata(file_path).metadata[b"sentiment_join_stats"].decode())

    assert "etf_total_btc" in saved.columns
    assert "etf_total_aum_usd" in saved.columns
    assert "etf_net_inflow_usd" in saved.columns
    assert "etf_net_inflow_usd_lag1" in saved.columns
    assert "rows_before_outlier_filter" in stats
    assert "rows_after_outlier_filter" in stats
    assert "hybrid_signal_label" in stats
    assert "granger_eligible_rows" in stats
    assert "granger_executed" in stats
    assert "exclusion_counts" in stats
    assert isinstance(stats["exclusion_counts"], dict)
