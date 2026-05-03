from __future__ import annotations

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import binance, btc_prices

# open_time=1775779200000 → 2026-04-10 00:00:00 UTC
SAMPLE_ROW: list = [
    1775779200000,  # [0] open_time (ms)
    "72000.00",  # [1] open
    "73500.00",  # [2] high
    "71500.00",  # [3] low
    "72962.70",  # [4] close (str)
    "1234.56",  # [5] volume
    1775865599999,  # [6] close_time
    "90123456789.12",  # [7] quote_asset_volume (str)
    1000,  # [8] number_of_trades
    "600.00",  # [9] taker_buy_base_asset_volume
    "45000000.00",  # [10] taker_buy_quote_asset_volume
    "0",  # [11] ignore
]


def test_parse_kline_row_converts_str_to_float() -> None:
    result = binance._parse_kline_row(SAMPLE_ROW)

    assert result["close"] == pytest.approx(72962.70)
    assert isinstance(result["close"], float)
    assert result["btc_quote_volume"] == pytest.approx(90123456789.12)
    assert isinstance(result["btc_quote_volume"], float)


def test_parse_kline_row_open_time_as_date() -> None:
    result = binance._parse_kline_row(SAMPLE_ROW)

    assert result["date"] == "2026-04-10"


def test_klines_to_frame_structure() -> None:
    df = binance._klines_to_frame([SAMPLE_ROW])

    assert list(df.columns) == ["date", "close", "btc_quote_volume", "btc_taker_buy_quote_volume"]
    assert str(df["close"].dtype) == "float64"
    assert str(df["btc_quote_volume"].dtype) == "float64"
    assert str(df["btc_taker_buy_quote_volume"].dtype) == "float64"
    assert df.loc[0, "date"] == "2026-04-10"


def test_klines_to_frame_empty_returns_empty_frame() -> None:
    df = binance._klines_to_frame([])

    assert list(df.columns) == ["date", "close", "btc_quote_volume", "btc_taker_buy_quote_volume"]
    assert df.empty


def test_klines_to_frame_deduplicates_same_date() -> None:
    row_a = list(SAMPLE_ROW)
    row_b = list(SAMPLE_ROW)
    row_b[4] = "99999.00"
    row_b[7] = "111111.00"

    df = binance._klines_to_frame([row_a, row_b])

    assert len(df) == 1
    assert df.loc[0, "close"] == pytest.approx(99999.0)


def test_fetch_btc_close_binance_sets_attrs_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(binance, "_fetch_klines", lambda *args, **kwargs: [SAMPLE_ROW])

    df = binance.fetch_btc_close_binance("2026-04-10", "2026-04-10")

    assert df.attrs["btc_source"] == "binance"
    assert df.attrs["fallback_used"] is False
    assert "btc_quote_volume" in df.columns


def test_fetch_btc_close_binance_falls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        binance,
        "_fetch_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network error")),
    )

    fallback_df = pd.DataFrame({"date": ["2026-04-10"], "close": [70000.0]})
    fallback_df.attrs["fallback_used"] = True

    monkeypatch.setattr(btc_prices, "fetch_btc_close_yfinance", lambda *args, **kwargs: fallback_df)

    df = binance.fetch_btc_close_binance("2026-04-10", "2026-04-10")

    assert df.attrs["fallback_used"] is True
    assert df.attrs["btc_source"] == "yfinance"
    assert "btc_quote_volume" in df.columns
    assert df["btc_quote_volume"].isna().all()


def test_fetch_btc_close_binance_fallback_yfinance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        binance,
        "_fetch_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("binance down")),
    )

    fallback_df = pd.DataFrame({"date": ["2026-04-10"], "close": [70000.0]})
    fallback_df.attrs["fallback_used"] = True

    monkeypatch.setattr(btc_prices, "fetch_btc_close_yfinance", lambda *args, **kwargs: fallback_df)

    df = binance.fetch_btc_close_binance("2026-04-10", "2026-04-10")

    assert df.attrs["btc_source"] == "yfinance"


def test_fetch_klines_single_call_for_460_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """total_days=460 → 단발 호출 경로, _call_klines 1회 호출."""
    call_count = 0

    def mock_call_klines(params, api_key):
        nonlocal call_count
        call_count += 1
        return [SAMPLE_ROW]

    monkeypatch.setattr(binance, "_call_klines", mock_call_klines)

    # 460일 범위: 2024-12-09 ~ 2026-04-13
    binance._fetch_klines("2024-12-09", "2026-04-13", api_key="")

    assert call_count == 1, "460일은 단발 호출이어야 함"


def test_fetch_klines_single_call_for_730_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """total_days=730 → 단발 호출 경로 (≤1000)."""
    call_count = 0

    def mock_call_klines(params, api_key):
        nonlocal call_count
        call_count += 1
        return [SAMPLE_ROW]

    monkeypatch.setattr(binance, "_call_klines", mock_call_klines)

    binance._fetch_klines("2024-01-01", "2026-01-01", api_key="")

    assert call_count == 1


def test_fetch_klines_single_call_boundary_1000_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """total_days=1000 → 단발 호출 경로 (경계값)."""
    call_count = 0

    def mock_call_klines(params, api_key):
        nonlocal call_count
        call_count += 1
        return [SAMPLE_ROW]

    monkeypatch.setattr(binance, "_call_klines", mock_call_klines)

    # 998일 범위 + 2 = 1000
    from datetime import date, timedelta

    start = date(2023, 1, 1)
    end = start + timedelta(days=998)
    binance._fetch_klines(str(start), str(end), api_key="")

    assert call_count == 1


def test_fetch_klines_pagination_for_over_1000_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """total_days=1001 → 페이지네이션 루프, _call_klines 2회 이상 호출."""
    import time as time_module

    sleep_calls: list[float] = []
    monkeypatch.setattr(time_module, "sleep", lambda s: sleep_calls.append(s))

    # 1회차: 1000개 반환 (open_time이 end_ms보다 작아서 루프 계속)
    # 2회차: 빈 리스트 → 루프 종료
    batch1 = [list(SAMPLE_ROW) for _ in range(3)]
    # open_time(ms)를 작게 설정해서 end_ms를 초과하지 않도록 함
    batch1[0][0] = 1_000_000_000_000
    batch1[1][0] = 1_000_086_400_000
    batch1[2][0] = 1_000_172_800_000  # 마지막 행의 open_time

    call_count = 0
    responses = [batch1, []]

    def mock_call_klines(params, api_key):
        nonlocal call_count
        r = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return r

    monkeypatch.setattr(binance, "_call_klines", mock_call_klines)

    from datetime import date, timedelta

    start = date(2020, 1, 1)
    end = start + timedelta(days=1001)
    binance._fetch_klines(str(start), str(end), api_key="")

    assert call_count >= 2, "1001일 초과 시 페이지네이션 루프 진입"
    assert len(sleep_calls) >= 1, "페이지 간 time.sleep 호출 확인"
