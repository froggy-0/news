from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from morning_brief.analysis.sentiment_join.sources import btc_prices
from morning_brief.data.sources.http_client import get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_INTERVAL = "1d"


def _binance_headers(api_key: str) -> dict[str, str]:
    if api_key:
        return {"X-MBX-APIKEY": api_key}
    return {}


def _parse_kline_row(row: list[Any]) -> dict[str, Any]:
    """Binance klines 배열 행 하나를 파싱합니다.

    Binance klines 응답 인덱스:
      [0] open_time (int, ms, UTC 자정) → date
      [4] close (str) → float
      [7] quote_asset_volume (str) → float (btc_quote_volume)
    """
    open_time_ms = int(row[0])
    date = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    close = float(row[4])
    btc_quote_volume = float(row[7])
    return {"date": date, "close": close, "btc_quote_volume": btc_quote_volume}


def _empty_binance_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "close": pd.Series(dtype="float64"),
            "btc_quote_volume": pd.Series(dtype="float64"),
        }
    )


def _klines_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_binance_frame()

    parsed = [_parse_kline_row(row) for row in rows]
    df = pd.DataFrame(parsed)
    df["close"] = df["close"].astype("float64")
    df["btc_quote_volume"] = df["btc_quote_volume"].astype("float64")

    # 중복 날짜: 같은 날짜의 마지막 항목 사용
    df = df.groupby("date", as_index=False).last().sort_values("date").reset_index(drop=True)
    return df


def _fetch_klines(
    start_date: str,
    end_date: str,
    api_key: str,
) -> list[list[Any]]:
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    limit = (end_dt - start_dt).days + 2

    if limit > 1000:
        raise ValueError(f"lookback이 klines 단일 요청 한도를 초과합니다: limit={limit} > 1000")

    start_ms = int(start_dt.timestamp() * 1000)

    return get_list_with_retry(
        BINANCE_KLINES_URL,
        params={
            "symbol": BINANCE_SYMBOL,
            "interval": BINANCE_INTERVAL,
            "startTime": str(start_ms),
            "limit": str(limit),
        },
        headers=_binance_headers(api_key),
        provider="binance_spot",
        timeout=20,
    )


def fetch_btc_close_binance(
    start_date: str,
    end_date: str,
    api_key: str = "",
) -> pd.DataFrame:
    """BTC 현물 종가를 Binance Spot klines API에서 수집합니다.

    성공 시: attrs["btc_source"] = "binance", attrs["fallback_used"] = False
    실패 시: yfinance로 즉시 폴백
             attrs["btc_source"] = "yfinance"
             attrs["fallback_used"] = True
             btc_quote_volume 컬럼은 NaN으로 채움
    """
    try:
        rows = _fetch_klines(start_date, end_date, api_key)
        df = _klines_to_frame(rows)
        df.attrs["btc_source"] = "binance"
        df.attrs["fallback_used"] = False
        return df
    except Exception as exc:
        log_structured(
            logger,
            event="fallback.used",
            message="Binance Spot klines 수집에 실패해 폴백 소스로 전환합니다.",
            level=logging.WARNING,
            source="btc",
            reason=str(exc),
        )

    fallback_df = btc_prices.fetch_btc_close_yfinance(start_date, end_date)
    fallback_df["btc_quote_volume"] = float("nan")
    fallback_df.attrs["btc_source"] = "yfinance"
    fallback_df.attrs["fallback_used"] = True
    return fallback_df


__all__ = ["fetch_btc_close_binance"]
