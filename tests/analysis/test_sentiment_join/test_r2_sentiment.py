from __future__ import annotations

import logging

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import r2_sentiment
from morning_brief.data.sources.http_client import HttpFetchError


def _analytics_payload(
    *,
    mean: float | None = 0.25,
    std: float | None = 0.1,
    count: int = 3,
    status: str = "ok",
    backfill: bool = True,
    schema_version: str = "v1",
) -> dict:
    return {
        "schemaVersion": schema_version,
        "producer": "test",
        "generatedAt": "2026-04-10T00:00:00Z",
        "date": "2026-04-10",
        "symbol": "btc",
        "sentimentStatus": status,
        "newsSentiment": {"mean": mean, "std": std, "count": count},
        "_backfill": backfill,
    }


def test_fetch_r2_sentiment_reads_analytics_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 5.1: analytics/btc/{date}.json 경로만 읽는지 검증."""
    requested_urls: list[str] = []

    def fake_get_json(url: str, *, provider: str, timeout: int):
        requested_urls.append(url)
        return _analytics_payload()

    monkeypatch.setattr(r2_sentiment, "get_json_with_retry", fake_get_json)
    r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert len(requested_urls) == 1
    assert "/analytics/btc/2026-04-10.json" in requested_urls[0]
    assert "/briefs/" not in requested_urls[0]


def test_fetch_r2_sentiment_maps_count_to_n_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(mean=0.25, std=0.1, count=3),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert df.loc[0, "news_sentiment_mean"] == 0.25
    assert df.loc[0, "news_sentiment_std"] == 0.1
    assert df.loc[0, "n_articles"] == 3
    assert df["n_articles"].dtype == pd.Int64Dtype()
    assert bool(df.loc[0, "is_backfill_valid"]) is True
    assert df.loc[0, "ingest_validation_reason"] is None or pd.isna(
        df.loc[0, "ingest_validation_reason"]
    )


def test_fetch_r2_sentiment_sets_nan_for_skipped_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(status="skipped"),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert pd.isna(df.loc[0, "news_sentiment_mean"])
    assert pd.isna(df.loc[0, "n_articles"])
    # backfill은 유효하지만 sentiment는 skipped
    assert bool(df.loc[0, "is_backfill_valid"]) is True
    assert df.loc[0, "sentiment_status"] == "skipped"


def test_fetch_r2_sentiment_accepts_backfill_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-3: _backfill=False(라이브 파이프라인)도 키가 존재하면 수집 대상."""
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(backfill=False),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert bool(df.loc[0, "is_backfill_valid"]) is True


def test_fetch_r2_sentiment_rejects_absent_backfill_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 5.2: _backfill 키 자체가 없으면 해당 날짜 제외."""
    payload_without_key = _analytics_payload()
    del payload_without_key["_backfill"]

    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: payload_without_key,
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert bool(df.loc[0, "is_backfill_valid"]) is False
    assert df.loc[0, "ingest_validation_reason"] == "missing_backfill_marker"
    assert pd.isna(df.loc[0, "news_sentiment_mean"])


def test_fetch_r2_sentiment_rejects_unsupported_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 5.3: 지원되지 않는 schemaVersion은 제외."""
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(schema_version="v99"),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert bool(df.loc[0, "is_backfill_valid"]) is False
    assert "unsupported_schema_version" in (df.loc[0, "ingest_validation_reason"] or "")
    assert pd.isna(df.loc[0, "news_sentiment_mean"])


def test_fetch_r2_sentiment_rejects_invalid_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Req 5.4: 구조가 계약과 다르면 무효 입력."""
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: {
            "schemaVersion": "v1",
            "_backfill": True,
            # missing required fields
        },
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert bool(df.loc[0, "is_backfill_valid"]) is False
    assert "missing_field" in (df.loc[0, "ingest_validation_reason"] or "")


def test_fetch_r2_sentiment_keeps_degraded_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(mean=-0.4, std=0.3, count=2, status="degraded"),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert df.loc[0, "news_sentiment_mean"] == -0.4
    assert df.loc[0, "n_articles"] == 2
    assert df.loc[0, "sentiment_status"] == "degraded"


def test_fetch_r2_sentiment_sets_nan_when_mean_is_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: _analytics_payload(mean=None),
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert pd.isna(df.loc[0, "news_sentiment_mean"])
    assert bool(df.loc[0, "is_backfill_valid"]) is True


def test_fetch_r2_sentiment_handles_partial_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_json(url: str, *, provider: str, timeout: int):
        if "2026-04-09" in url:
            raise HttpFetchError("missing", status_code=404, provider="r2")
        return _analytics_payload(mean=0.2, std=0.1, count=2)

    monkeypatch.setattr(r2_sentiment, "get_json_with_retry", fake_get_json)

    df = r2_sentiment.fetch_r2_sentiment(
        ["2026-04-09", "2026-04-10"],
        "https://bucket.example",
        2,
    )

    missing_row = df.loc[df["date"] == "2026-04-09"].iloc[0]
    assert pd.isna(missing_row["news_sentiment_mean"])
    present_row = df.loc[df["date"] == "2026-04-10"].iloc[0]
    assert present_row["news_sentiment_mean"] == 0.2


def test_fetch_r2_sentiment_logs_warning_on_total_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_get_json(url: str, *, provider: str, timeout: int):
        raise HttpFetchError("boom", provider="r2", retryable=True)

    monkeypatch.setattr(r2_sentiment, "get_json_with_retry", fake_get_json)

    with caplog.at_level(logging.WARNING):
        df = r2_sentiment.fetch_r2_sentiment(
            ["2026-04-09", "2026-04-10"],
            "https://bucket.example",
            2,
        )

    assert df["news_sentiment_mean"].isna().all()
    assert any(getattr(record, "event", None) == "source.failed" for record in caplog.records)


def test_fetch_r2_sentiment_output_columns() -> None:
    """signal 컬럼이 제거되고 새 계약 컬럼이 존재하는지 검증."""
    frame = r2_sentiment._empty_sentiment_frame(["2026-04-10"])
    expected = {
        "date",
        "news_sentiment_mean",
        "news_sentiment_std",
        "n_articles",
        "sentiment_status",
        "is_backfill_valid",
        "ingest_validation_reason",
        "text_schema_version",  # §2: 텍스트 스키마 버전 추가
    }
    assert set(frame.columns) == expected
    # signal 컬럼이 없어야 한다
    assert "signal_sentiment_mean" not in frame.columns
    assert "n_signals" not in frame.columns
