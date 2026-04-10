from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import btc_prices
from morning_brief.data.sources.http_client import HttpFetchError


def test_fetch_coingecko_range_resamples_hourly_prices() -> None:
    today = datetime.now(timezone.utc).date()
    day1 = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    day2 = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    payload = {
        "prices": [
            [int((day1 + timedelta(hours=1)).timestamp() * 1000), 100.0],
            [int((day1 + timedelta(hours=22)).timestamp() * 1000), 110.0],
            [int((day2 + timedelta(hours=1)).timestamp() * 1000), 120.0],
            [int((day2 + timedelta(hours=22)).timestamp() * 1000), 130.0],
        ]
    }

    df = btc_prices._coingecko_rows_to_frame(payload["prices"])

    assert list(df["date"]) == [(today - timedelta(days=1)).isoformat(), today.isoformat()]
    assert list(df["close"]) == [110.0, 130.0]


def test_fetch_coingecko_range_keeps_daily_prices() -> None:
    today = datetime.now(timezone.utc).date()
    payload = {
        "prices": [
            [
                int(
                    datetime.combine(
                        today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                ),
                200.0,
            ],
            [
                int(
                    datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp()
                    * 1000
                ),
                210.0,
            ],
        ]
    }

    df = btc_prices._coingecko_rows_to_frame(payload["prices"])

    assert list(df["close"]) == [200.0, 210.0]


def test_fetch_btc_close_uses_yfinance_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        btc_prices,
        "_fetch_coingecko_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(HttpFetchError("boom", provider="coingecko")),
    )
    fallback_df = pd.DataFrame({"date": ["2026-04-10"], "close": [123.4]})
    monkeypatch.setattr(btc_prices, "_download_with_yfinance", lambda *args, **kwargs: fallback_df)

    with caplog.at_level(logging.WARNING):
        df = btc_prices.fetch_btc_close("2026-04-09", "2026-04-10")

    assert df.equals(fallback_df)
    assert df.attrs["fallback_used"] is True
    assert any(getattr(record, "event", None) == "fallback.used" for record in caplog.records)


def test_fetch_btc_close_returns_empty_frame_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        btc_prices,
        "_fetch_coingecko_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(HttpFetchError("boom", provider="coingecko")),
    )
    monkeypatch.setattr(
        btc_prices,
        "_download_with_yfinance",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )

    df = btc_prices.fetch_btc_close("2026-04-09", "2026-04-10")

    assert df.empty
