from __future__ import annotations

from datetime import datetime, timezone

import pytest

from morning_brief.analysis.sentiment_join.sources import futures


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def test_aggregate_daily_funding_sums_three_intraday_rows() -> None:
    rows = [
        {"fundingTime": _ms(2026, 4, 10, 0), "fundingRate": "0.001"},
        {"fundingTime": _ms(2026, 4, 10, 8), "fundingRate": "0.002"},
        {"fundingTime": _ms(2026, 4, 10, 16), "fundingRate": "0.003"},
    ]

    assert futures._aggregate_daily_funding(rows) == {"2026-04-10": 0.006}


def test_extract_daily_oi_uses_sum_open_interest_value() -> None:
    rows = [{"timestamp": _ms(2026, 4, 10), "sumOpenInterestValue": "123456.7"}]

    assert futures._extract_daily_oi(rows) == {"2026-04-10": 123456.7}


def test_fetch_futures_data_returns_nan_grid_when_all_requests_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(futures, "_fetch_funding_rate_history", lambda start_ms: [])
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda start_ms: [])

    df = futures.fetch_futures_data(lookback_days=2)

    assert list(df.columns) == ["date", "funding_rate", "open_interest_usd"]
    assert df["funding_rate"].isna().all()
    assert df["open_interest_usd"].isna().all()
