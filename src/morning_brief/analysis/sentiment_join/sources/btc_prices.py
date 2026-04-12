from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.data.sources.provider_runtime import execute_with_provider_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

COINGECKO_RANGE_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"


def _empty_close_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "close": pd.Series(dtype="float64"),
        }
    )


def _unix_range(start_date: str, end_date: str) -> tuple[int, int]:
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return int(start_dt.timestamp()), int(end_dt.timestamp()) - 1


def _coingecko_rows_to_frame(rows: list[Any]) -> pd.DataFrame:
    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        timestamp_ms, price = row[0], row[1]
        if not isinstance(timestamp_ms, (int, float)) or not isinstance(price, (int, float)):
            continue
        date = pd.to_datetime(timestamp_ms, unit="ms", utc=True).strftime("%Y-%m-%d")
        parsed_rows.append({"date": date, "close": float(price)})

    if not parsed_rows:
        raise HttpFetchError(
            "CoinGecko range 응답에서 유효한 가격을 찾지 못했어요.", provider="coingecko"
        )

    frame = pd.DataFrame(parsed_rows)
    return (
        frame.groupby("date", as_index=False)["close"]
        .last()
        .sort_values("date")
        .reset_index(drop=True)
    )


def _fetch_coingecko_range(unix_start: int, unix_end: int) -> pd.DataFrame:
    payload = get_json_with_retry(
        COINGECKO_RANGE_URL,
        params={
            "vs_currency": "usd",
            "from": str(unix_start),
            "to": str(unix_end),
        },
        provider="coingecko",
        timeout=20,
    )
    prices = payload.get("prices")
    if not isinstance(prices, list):
        raise HttpFetchError("CoinGecko range 응답에 prices 배열이 없어요.", provider="coingecko")
    return _coingecko_rows_to_frame(prices)


def _download_with_yfinance(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    end_exclusive = (datetime.fromisoformat(end_date) + timedelta(days=1)).date().isoformat()

    def _download() -> pd.DataFrame:
        history = yf.download(
            ticker,
            start=start_date,
            end=end_exclusive,
            auto_adjust=False,
            progress=False,
        )
        if history.empty:
            raise RuntimeError(f"{ticker} 이력 데이터가 비어 있어요.")
        return history

    history = execute_with_provider_retry(
        provider="yfinance",
        operation=_download,
        should_retry=lambda exc: True,
        max_attempts=3,
        base_backoff_seconds=1.0,
    )

    index = pd.to_datetime(history.index, utc=True)
    # yfinance 0.2.x에서 multi_level_index=True(기본값)이면
    # history["Close"]가 Series 대신 DataFrame을 반환합니다.
    close_col = history["Close"]
    if isinstance(close_col, pd.DataFrame):
        close_col = close_col.iloc[:, 0]
    frame = pd.DataFrame(
        {
            "date": index.strftime("%Y-%m-%d"),
            "close": close_col.astype(float).tolist(),
        }
    )
    return (
        frame.groupby("date", as_index=False)["close"]
        .last()
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_btc_close(start_date: str, end_date: str) -> pd.DataFrame:
    unix_start, unix_end = _unix_range(start_date, end_date)
    try:
        frame = _fetch_coingecko_range(unix_start, unix_end)
        frame.attrs["fallback_used"] = False
        return frame
    except Exception as exc:
        log_structured(
            logger,
            event="fallback.used",
            message="CoinGecko 수집에 실패해 yfinance로 전환합니다.",
            level=logging.WARNING,
            source="btc",
            reason=str(exc),
        )

    try:
        frame = _download_with_yfinance("BTC-USD", start_date, end_date)
        frame.attrs["fallback_used"] = True
        return frame
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="BTC 가격 수집이 모두 실패했습니다.",
            level=logging.WARNING,
            source="btc",
            reason=str(exc),
        )
        frame = _empty_close_frame()
        frame.attrs["fallback_used"] = True
        return frame


def fetch_btc_close_yfinance(start_date: str, end_date: str) -> pd.DataFrame:
    try:
        frame = _download_with_yfinance("BTC-USD", start_date, end_date)
        frame.attrs["fallback_used"] = True
        return frame
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="BTC 가격 yfinance 수집이 실패했습니다.",
            level=logging.WARNING,
            source="btc",
            reason=str(exc),
        )
        frame = _empty_close_frame()
        frame.attrs["fallback_used"] = True
        return frame


__all__ = ["fetch_btc_close", "fetch_btc_close_yfinance"]
