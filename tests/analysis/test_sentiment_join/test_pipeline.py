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


def test_build_outlier_mask_summary_preserves_column_and_hybrid_sources() -> None:
    flags = pd.DataFrame(
        {
            "news_sentiment_mean": [True, False, True],
            "fng_value": [False, False, False],
        }
    )
    classification = pd.DataFrame(
        {
            "news_sentiment_mean": ["iqr_single", None, "data_error"],
            "fng_value": [None, None, None],
        }
    )

    summary = pipeline._build_outlier_mask_summary(
        flags,
        classification,
        hybrid_diagnostics={
            "full": {"pca_summary": {"selected_features": ["news_sentiment_mean", "fng_value"]}}
        },
    )

    assert summary["rows"] == 3
    assert summary["per_column"]["news_sentiment_mean"]["masked_cells"] == 2
    assert summary["per_column"]["news_sentiment_mean"]["reasons"] == {
        "iqr_single": 1,
        "data_error": 1,
    }
    assert summary["hybrid_index_source_columns"]["full_hybrid_index_score_lag1"] == [
        "news_sentiment_mean",
        "fng_value",
    ]


def _etf_df(main_dates: list[str]) -> pd.DataFrame:
    totals = [1000.0 + idx * 10.0 for idx in range(len(main_dates))]
    df = pd.DataFrame(
        {
            "date": main_dates,
            "etf_total_btc": totals,
            "etf_total_aum_usd": [value * 85000 for value in totals],
        }
    )
    df.attrs["source_mode"] = "gold_history"
    df.attrs["history_non_null_days"] = len(main_dates)
    df.attrs["requested_days"] = len(main_dates)
    df.attrs["history_coverage_ratio"] = 1.0
    df.attrs["history_quality_status"] = "ok"
    df.attrs["history_quality_reasons"] = []
    return df


def _futures_df(
    main_dates: list[str],
    *,
    funding_quality: str = "ok",
    oi_quality: str = "ok",
    lsr_quality: str = "ok",
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "date": main_dates,
            "funding_rate": [0.001] * len(main_dates),
            "open_interest_usd": [1000.0 + idx for idx in range(len(main_dates))],
            "btc_long_short_ratio": [1.0 + idx * 0.01 for idx in range(len(main_dates))],
        }
    )
    df.attrs["fallback_used"] = False
    df.attrs["futures_source"] = "binance"
    df.attrs["requested_days"] = len(main_dates)
    df.attrs["requested_start_date"] = main_dates[0]
    df.attrs["requested_end_date"] = main_dates[-1]
    df.attrs["funding_days"] = len(main_dates) if funding_quality == "ok" else 1
    df.attrs["oi_days"] = len(main_dates) if oi_quality == "ok" else 1
    df.attrs["lsr_days"] = len(main_dates) if lsr_quality == "ok" else 1
    df.attrs["funding_coverage_ratio"] = (
        1.0 if funding_quality == "ok" else round(1 / len(main_dates), 4)
    )
    df.attrs["oi_coverage_ratio"] = 1.0 if oi_quality == "ok" else round(1 / len(main_dates), 4)
    df.attrs["lsr_coverage_ratio"] = 1.0 if lsr_quality == "ok" else round(1 / len(main_dates), 4)
    df.attrs["funding_quality_status"] = funding_quality
    df.attrs["funding_quality_reasons"] = (
        [] if funding_quality == "ok" else ["coverage_below_threshold"]
    )
    df.attrs["oi_quality_status"] = oi_quality
    df.attrs["oi_quality_reasons"] = [] if oi_quality == "ok" else ["coverage_below_threshold"]
    df.attrs["lsr_quality_status"] = lsr_quality
    df.attrs["lsr_quality_reasons"] = [] if lsr_quality == "ok" else ["coverage_below_threshold"]
    df.attrs["quality_status"] = (
        "ok"
        if funding_quality == "ok" and oi_quality == "ok" and lsr_quality == "ok"
        else "degraded"
    )
    df.attrs["quality_reasons"] = []
    df.attrs["returned_min_date"] = {
        "funding_rate": main_dates[0],
        "open_interest_usd": main_dates[0],
        "btc_long_short_ratio": main_dates[0],
    }
    df.attrs["returned_max_date"] = {
        "funding_rate": main_dates[-1],
        "open_interest_usd": main_dates[-1] if oi_quality == "ok" else main_dates[0],
        "btc_long_short_ratio": main_dates[-1] if lsr_quality == "ok" else main_dates[0],
    }
    return df


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
    stats = json.loads(metadata[b"sentiment_join_stats"].decode())
    assert stats["ffill_breakdown"]["btc"]["filled_days"] >= 2
    assert stats["ffill_breakdown"]["usdkrw"]["max_periods"] == 3


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
    # 다중 stationarity 구조 mock (run_statistical_tests는 "stationarity_results" 키를 반환)
    monkeypatch.setattr(
        pipeline,
        "run_statistical_tests",
        lambda df: {
            "stationarity_results": {
                "btc_log_return": {"adf_statistic": -3.2, "adf_pvalue": 0.02, "stationary": True}
            },
            "granger": [],
            "granger_eligible_rows": 0,
            "granger_executed": False,
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
    assert "btc_large_move_3d_vol_adj" in saved.columns
    assert "btc_bear_regime_lag1" in saved.columns
    assert "rows_before_outlier_filter" in stats
    assert "rows_after_outlier_filter" in stats
    assert "hybrid_indices" in stats
    assert "full" in stats["hybrid_indices"]
    assert "core" in stats["hybrid_indices"]
    assert "granger_eligible_rows" in stats
    assert "granger_executed" in stats
    assert "granger_skips" in stats
    assert "granger_skip_summary" in stats
    assert "target_diagnostics" in stats
    assert "exclusion_counts" in stats
    assert isinstance(stats["exclusion_counts"], dict)


def test_run_sentiment_join_creates_hybrid_score_lag1_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4 v4: hybrid index score lag1 컬럼이 pipeline에서 생성되고 MASTER_SCHEMA를 통과하는지 확인."""
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

    # lag1 컬럼이 존재해야 한다
    assert "full_hybrid_index_score_lag1" in saved.columns
    assert "core_hybrid_index_score_lag1" in saved.columns

    # 첫 번째 행은 NaN이어야 한다 (shift(1) 결과)
    assert pd.isna(saved["full_hybrid_index_score_lag1"].iloc[0])
    assert pd.isna(saved["core_hybrid_index_score_lag1"].iloc[0])

    # lag1 값은 원본 score의 shift(1)과 일치해야 한다
    for prefix in ("full", "core"):
        score_col = f"{prefix}_hybrid_index_score"
        lag1_col = f"{score_col}_lag1"
        expected = saved[score_col].shift(1)
        pd.testing.assert_series_equal(
            saved[lag1_col], expected, check_names=False, check_dtype=False
        )


def test_run_sentiment_join_records_structured_sources_metadata(
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
        pipeline, "fetch_futures_data", lambda *args, **kwargs: _futures_df(main_dates)
    )
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    stats = json.loads(pq.read_metadata(file_path).metadata[b"sentiment_join_stats"].decode())

    assert stats["structured_sources"]["btc_etf"]["mode"] == "gold_history"
    assert stats["structured_sources"]["btc_etf"]["quality_status"] == "ok"
    assert stats["structured_sources"]["futures"]["mode"] == "binance"
    assert stats["structured_sources"]["futures"]["oi_quality_status"] == "ok"
    assert stats["structured_sources"]["futures"]["lsr_quality_status"] == "ok"


def test_run_sentiment_join_gates_degraded_structured_features_from_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    degraded_etf = _etf_df(main_dates)
    degraded_etf.attrs["source_mode"] = "latest_snapshot_fallback"
    degraded_etf.attrs["history_non_null_days"] = 1
    degraded_etf.attrs["history_coverage_ratio"] = round(1 / len(main_dates), 4)
    degraded_etf.attrs["history_quality_status"] = "degraded"
    degraded_etf.attrs["history_quality_reasons"] = [
        "source_mode:latest_snapshot_fallback",
        "history_coverage_below_threshold",
    ]
    degraded_futures = _futures_df(main_dates, oi_quality="degraded", lsr_quality="degraded")

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
    monkeypatch.setattr(pipeline, "fetch_futures_data", lambda *args, **kwargs: degraded_futures)
    monkeypatch.setattr(pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: degraded_etf)

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    saved = pd.read_parquet(file_path)
    stats = json.loads(pq.read_metadata(file_path).metadata[b"sentiment_join_stats"].decode())
    excluded = stats["hybrid_indices"]["full"]["excluded_features"]

    assert saved["etf_net_inflow_usd"].notna().any()
    assert saved["btc_long_short_ratio"].notna().any()
    assert {
        "feature": "etf_net_inflow_usd_lag1",
        "reason": "btc_etf_history_unavailable",
    } in excluded
    assert {"feature": "btc_long_short_ratio_lag1", "reason": "futures_lsr_incomplete"} in excluded
    assert stats["structured_sources"]["btc_etf"]["quality_status"] == "degraded"
    assert stats["structured_sources"]["futures"]["oi_quality_status"] == "degraded"
    assert stats["structured_sources"]["futures"]["lsr_quality_status"] == "degraded"


def test_run_sentiment_join_gates_degraded_funding_from_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    degraded_futures = _futures_df(main_dates, funding_quality="degraded")

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
    monkeypatch.setattr(pipeline, "fetch_futures_data", lambda *args, **kwargs: degraded_futures)
    monkeypatch.setattr(
        pipeline, "fetch_etf_flow_features", lambda *args, **kwargs: _etf_df(main_dates)
    )

    assert pipeline.run_sentiment_join(settings) == 0

    file_path = next(tmp_path.glob("master_*.parquet"))
    saved = pd.read_parquet(file_path)
    stats = json.loads(pq.read_metadata(file_path).metadata[b"sentiment_join_stats"].decode())

    assert saved["funding_rate"].notna().any()  # master_df는 원본 보존
    assert {
        "feature": "funding_rate_lag1",
        "reason": "futures_funding_incomplete",
    } in stats["hybrid_indices"]["full"]["excluded_features"]
    assert {
        "feature": "funding_rate_lag1",
        "reason": "futures_funding_incomplete",
    } in stats["hybrid_indices"]["core"]["excluded_features"]
    assert stats["structured_sources"]["futures"]["funding_quality_status"] == "degraded"
