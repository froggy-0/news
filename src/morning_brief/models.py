from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MarketPoint:
    label: str
    ticker: str
    price: float
    change_pct: float


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime | None


@dataclass
class BitcoinSnapshot:
    spot: MarketPoint
    etf_points: list[MarketPoint]
    etf_total_volume: int
    fear_greed_value: int | None
    fear_greed_label: str | None
