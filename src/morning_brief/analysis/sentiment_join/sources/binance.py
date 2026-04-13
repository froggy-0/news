from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from morning_brief.analysis.sentiment_join.sources import btc_prices
from morning_brief.data.sources.http_client import get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# data-api.binance.vision은 지역 제한(HTTP 451) 없이 공개 시세 데이터를 제공하는
# Binance 공식 미러 엔드포인트입니다. api.binance.com 실패 시 자동으로 시도합니다.
BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_KLINES_URL_FALLBACK = "https://api.binance.com/api/v3/klines"
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


def _call_klines(params: dict, api_key: str) -> list[list[Any]]:
    """단발 klines 호출. 두 엔드포인트 순서로 시도."""
    for url in (BINANCE_KLINES_URL, BINANCE_KLINES_URL_FALLBACK):
        try:
            return get_list_with_retry(
                url,
                params=params,
                headers=_binance_headers(api_key),
                provider="binance_spot",
                timeout=20,
            )
        except Exception:
            if url == BINANCE_KLINES_URL_FALLBACK:
                raise
            log_structured(
                logger,
                event="binance.mirror_fallback",
                message="data-api.binance.vision 실패, api.binance.com으로 재시도합니다.",
                level=logging.WARNING,
            )
    raise RuntimeError("unreachable")


def _fetch_klines(
    start_date: str,
    end_date: str,
    api_key: str,
) -> list[list[Any]]:
    import time

    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    total_days = (end_dt - start_dt).days + 2

    end_ms = int(end_dt.timestamp() * 1000) + 86_400_000 - 1

    if total_days <= 1000:
        # 기존 단발 호출 경로 (460일 포함) — 동작 변경 없음
        start_ms = int(start_dt.timestamp() * 1000)
        params = {
            "symbol": BINANCE_SYMBOL,
            "interval": BINANCE_INTERVAL,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": total_days,
        }
        return _call_klines(params, api_key)

    # 1000일 초과: startTime 커서 기반 while 루프 페이지네이션
    all_rows: list[list[Any]] = []
    cursor_ms = int(start_dt.timestamp() * 1000)

    while cursor_ms < end_ms:
        params = {
            "symbol": BINANCE_SYMBOL,
            "interval": BINANCE_INTERVAL,
            "startTime": cursor_ms,
            "limit": 1000,
        }
        batch = _call_klines(params, api_key)
        if not batch:
            break
        all_rows.extend(batch)
        last_open_time_ms = int(batch[-1][0])
        if last_open_time_ms >= end_ms:
            break
        cursor_ms = last_open_time_ms + 86_400_000  # 다음 날 자정
        time.sleep(0.05)

    return all_rows


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
