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

    assert list(df.columns) == ["date", "close", "btc_quote_volume"]
    assert str(df["close"].dtype) == "float64"
    assert str(df["btc_quote_volume"].dtype) == "float64"
    assert df.loc[0, "date"] == "2026-04-10"


def test_klines_to_frame_empty_returns_empty_frame() -> None:
    df = binance._klines_to_frame([])

    assert list(df.columns) == ["date", "close", "btc_quote_volume"]
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


def test_fetch_klines_raises_if_limit_exceeds_1000(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(binance, "get_list_with_retry", lambda *args, **kwargs: [])

    with pytest.raises(ValueError, match="단일 요청 한도를 초과"):
        binance._fetch_klines("2020-01-01", "2023-01-01", api_key="")
