from __future__ import annotations

import pytest

from morning_brief.data.market import fetch_us_index_points
from morning_brief.data.sources.alpha_vantage import (
    HttpFetchError,
    _extract_daily_series,
    fetch_daily_close_change_volume,
)


def test_extract_daily_series_rejects_rate_limit_note():
    with pytest.raises(HttpFetchError):
        _extract_daily_series({"Note": "Thank you for using Alpha Vantage."})


def test_fetch_daily_close_change_volume_parses_latest_two_days(monkeypatch):
    monkeypatch.setattr(
        "morning_brief.data.sources.alpha_vantage.get_json_with_retry",
        lambda *_, **__: {
            "Time Series (Daily)": {
                "2026-03-12": {
                    "4. close": "510.00",
                    "5. volume": "1234567",
                },
                "2026-03-11": {
                    "4. close": "500.00",
                    "5. volume": "1200000",
                },
            }
        },
    )

    close, change_pct, volume = fetch_daily_close_change_volume("NVDA", "demo")

    assert close == 510.0
    assert round(change_pct, 2) == 2.0
    assert volume == 1234567


def test_fetch_us_index_points_prefers_alpha_vantage_when_key_present(monkeypatch):
    monkeypatch.setattr(
        "morning_brief.data.market.fetch_daily_close_change_volume",
        lambda ticker, *_: (100.0 + len(ticker), 1.5, 1000),
    )

    points = fetch_us_index_points(alpha_vantage_api_key="demo")

    assert [point.ticker for point in points] == ["SPY", "QQQ", "SOXX"]
    assert all(point.change_pct == 1.5 for point in points)
