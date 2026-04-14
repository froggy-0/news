from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    # Binance fapi 전부 실패
    monkeypatch.setattr(futures, "_fetch_funding_rate_history", lambda start_ms: [])
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda limit_days: [])
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda limit_days: [])
    # Lambda ARN 미설정 → Lambda 경로 skip
    monkeypatch.delenv("FUTURES_LAMBDA_ARN", raising=False)
    # Bybit도 전부 실패
    monkeypatch.setattr(futures, "_fetch_bybit_funding_rows", lambda *a, **kw: [])
    monkeypatch.setattr(futures, "_fetch_bybit_oi_rows", lambda *a, **kw: [])
    monkeypatch.setattr(futures, "_fetch_bybit_lsr_rows", lambda *a, **kw: [])

    df = futures.fetch_futures_data(lookback_days=2)

    assert list(df.columns) == ["date", "funding_rate", "open_interest_usd", "btc_long_short_ratio"]
    assert df["funding_rate"].isna().all()
    assert df["open_interest_usd"].isna().all()
    assert df["btc_long_short_ratio"].isna().all()


def test_extract_daily_long_short_ratio_parses_str_fields() -> None:
    rows = [
        {"timestamp": _ms(2026, 4, 10), "longShortRatio": "0.8829"},
        {"timestamp": _ms(2026, 4, 11), "longShortRatio": "1.0305"},
    ]

    result = futures._extract_daily_long_short_ratio(rows)

    assert result["2026-04-10"] == pytest.approx(0.8829)
    assert result["2026-04-11"] == pytest.approx(1.0305)


def test_extract_daily_long_short_ratio_value_above_one_is_valid() -> None:
    rows = [{"timestamp": _ms(2026, 4, 10), "longShortRatio": "2.5"}]

    result = futures._extract_daily_long_short_ratio(rows)

    assert result["2026-04-10"] == pytest.approx(2.5)


def test_fetch_futures_data_lsr_failure_does_not_block_funding_oi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    funding_rows = [
        {
            "fundingTime": _ms(target_day.year, target_day.month, target_day.day, 0),
            "fundingRate": "0.001",
        },
    ]
    oi_rows = [
        {
            "timestamp": _ms(target_day.year, target_day.month, target_day.day),
            "sumOpenInterestValue": "1000.0",
        }
    ]

    monkeypatch.setattr(futures, "_fetch_funding_rate_history", lambda start_ms: funding_rows)
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda start_ms: oi_rows)
    monkeypatch.setattr(
        futures,
        "_fetch_long_short_ratio",
        lambda start_ms: (_ for _ in ()).throw(RuntimeError("LSR network error")),
    )

    df = futures.fetch_futures_data(lookback_days=2)

    assert df["funding_rate"].notna().any()
    assert df["open_interest_usd"].notna().any()
    assert "btc_long_short_ratio" in df.columns


def test_oi_and_lsr_requests_use_limit_without_start_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_list_with_retry(url: str, *, params: dict[str, str], **kwargs):
        calls.append((url, params))
        return []

    monkeypatch.setattr(futures, "get_list_with_retry", fake_get_list_with_retry)

    futures._fetch_oi_history(32)
    futures._fetch_long_short_ratio(32)

    assert calls[0][0] == futures.BINANCE_OI_URL
    assert calls[0][1] == {"symbol": "BTCUSDT", "period": "1d", "limit": "32"}
    assert calls[1][0] == futures.BINANCE_LSR_URL
    assert calls[1][1] == {"symbol": "BTCUSDT", "period": "1d", "limit": "32"}
