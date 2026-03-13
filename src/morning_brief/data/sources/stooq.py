from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO

from morning_brief.data.sources.http_client import HttpFetchError, get_text_with_retry

STOOQ_DAILY_CSV_URL = "https://stooq.com/q/d/l/"


@dataclass(frozen=True)
class StooqDailyPoint:
    date: datetime
    close: float
    volume: int


def to_stooq_symbol(ticker: str) -> str:
    symbol = ticker.strip().lower()
    if symbol.endswith(".us"):
        return symbol
    return f"{symbol}.us"


def _parse_float(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text.upper() in {"N/D", "NA", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(raw: str) -> int:
    text = (raw or "").strip()
    if not text or text.upper() in {"N/D", "NA", "NULL"}:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _parse_date(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_stooq_csv(text: str) -> list[StooqDailyPoint]:
    reader = csv.DictReader(StringIO(text))
    points: list[StooqDailyPoint] = []

    for row in reader:
        date = _parse_date(row.get("Date", ""))
        close = _parse_float(row.get("Close", ""))
        if date is None or close is None:
            continue

        volume = _parse_int(row.get("Volume", "0"))
        points.append(StooqDailyPoint(date=date, close=close, volume=volume))

    points.sort(key=lambda x: x.date)
    return points


def fetch_close_change_and_volume(symbol: str) -> tuple[float, float, int]:
    csv_text = get_text_with_retry(
        STOOQ_DAILY_CSV_URL,
        params={
            "s": symbol,
            "i": "d",
        },
        provider="stooq",
        timeout=20,
    )

    points = _parse_stooq_csv(csv_text)
    if len(points) < 2:
        raise HttpFetchError(f"Stooq 일봉 데이터가 충분하지 않아요: {symbol}")

    latest = points[-1]
    previous = points[-2]
    if previous.close == 0:
        change_pct = 0.0
    else:
        change_pct = ((latest.close - previous.close) / previous.close) * 100

    return latest.close, change_pct, latest.volume


__all__ = [
    "HttpFetchError",
    "StooqDailyPoint",
    "to_stooq_symbol",
    "fetch_close_change_and_volume",
]
