from __future__ import annotations

import logging

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import r2_sentiment
from morning_brief.data.sources.http_client import HttpFetchError


def test_fetch_r2_sentiment_maps_count_to_n_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_json(url: str, *, provider: str, timeout: int):
        assert provider == "r2"
        assert timeout == 20
        return {
            "meta": {
                "sentimentStatus": "ok",
                "newsSentiment": {"mean": 0.25, "std": 0.1, "count": 3},
            }
        }

    monkeypatch.setattr(r2_sentiment, "get_json_with_retry", fake_get_json)

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert df.loc[0, "news_sentiment_mean"] == 0.25
    assert df.loc[0, "news_sentiment_std"] == 0.1
    assert df.loc[0, "n_articles"] == 3
    assert df["n_articles"].dtype == pd.Int64Dtype()


def test_fetch_r2_sentiment_sets_nan_for_skipped_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: {
            "meta": {
                "sentimentStatus": "skipped",
                "newsSentiment": {"mean": 0.25, "std": 0.1, "count": 4},
            }
        },
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert pd.isna(df.loc[0, "news_sentiment_mean"])
    assert pd.isna(df.loc[0, "news_sentiment_std"])
    assert pd.isna(df.loc[0, "n_articles"])


def test_fetch_r2_sentiment_keeps_degraded_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: {
            "meta": {
                "sentimentStatus": "degraded",
                "newsSentiment": {"mean": -0.4, "std": 0.3, "count": 2},
            }
        },
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert df.loc[0, "news_sentiment_mean"] == -0.4
    assert df.loc[0, "news_sentiment_std"] == 0.3
    assert df.loc[0, "n_articles"] == 2


def test_fetch_r2_sentiment_sets_nan_when_mean_is_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r2_sentiment,
        "get_json_with_retry",
        lambda *args, **kwargs: {
            "meta": {
                "sentimentStatus": "ok",
                "newsSentiment": {"mean": None, "std": 0.3, "count": 2},
            }
        },
    )

    df = r2_sentiment.fetch_r2_sentiment(["2026-04-10"], "https://bucket.example", 2)

    assert pd.isna(df.loc[0, "news_sentiment_mean"])
    assert pd.isna(df.loc[0, "news_sentiment_std"])
    assert pd.isna(df.loc[0, "n_articles"])


def test_fetch_r2_sentiment_handles_partial_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        "2026-04-10": {
            "meta": {
                "sentimentStatus": "ok",
                "newsSentiment": {"mean": 0.2, "std": 0.1, "count": 2},
            }
        }
    }

    def fake_get_json(url: str, *, provider: str, timeout: int):
        date = url.rsplit("/", 1)[-1].removesuffix(".json")
        if date not in payloads:
            raise HttpFetchError("missing", status_code=404, provider="r2")
        return payloads[date]

    monkeypatch.setattr(r2_sentiment, "get_json_with_retry", fake_get_json)

    df = r2_sentiment.fetch_r2_sentiment(
        ["2026-04-09", "2026-04-10"],
        "https://bucket.example",
        2,
    )

    missing_row = df.loc[df["date"] == "2026-04-09"].iloc[0]
    assert pd.isna(missing_row["news_sentiment_mean"])
    assert pd.isna(missing_row["n_articles"])
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
