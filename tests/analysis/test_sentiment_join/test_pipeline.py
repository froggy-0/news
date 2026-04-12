from __future__ import annotations

import importlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
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
            "signal_sentiment_mean": [0.05] * len(main_dates),
            "signal_sentiment_std": [0.02] * len(main_dates),
            "n_signals": pd.array([6] * len(main_dates), dtype="Int64"),
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
    closes = [base + idx for idx in range(len(btc_dates))]
    if with_gap and len(closes) > 3:
        closes[2] = None
        closes[3] = None
        closes[4] = base + 4
    return pd.DataFrame({"date": btc_dates, "close": closes})


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
        "fetch_btc_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=100.0),
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_usdkrw_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=1300.0),
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
    monkeypatch.setattr(pipeline, "fetch_btc_close", lambda *args, **kwargs: _close_df(btc_dates))
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
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
    monkeypatch.setattr(pipeline, "fetch_btc_close", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: pd.DataFrame())

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
    monkeypatch.setattr(pipeline, "fetch_btc_close", lambda *args, **kwargs: _close_df(btc_dates))
    monkeypatch.setattr(
        pipeline, "fetch_usdkrw_close", lambda *args, **kwargs: _close_df(btc_dates, base=1300.0)
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
    import pyarrow.parquet as pq

    settings = _settings(tmp_path)
    _, _, _, main_dates, btc_dates = _core_dates(settings)

    monkeypatch.setattr(
        pipeline, "fetch_r2_sentiment", lambda *args, **kwargs: _sentiment_df(main_dates)
    )
    monkeypatch.setattr(pipeline, "fetch_fng", lambda *args, **kwargs: _fng_df(main_dates))
    monkeypatch.setattr(
        pipeline,
        "fetch_btc_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=100.0),
    )
    monkeypatch.setattr(
        pipeline,
        "fetch_usdkrw_close",
        lambda *args, **kwargs: _close_df(btc_dates, with_gap=True, base=1300.0),
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
