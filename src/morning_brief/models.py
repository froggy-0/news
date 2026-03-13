from __future__ import annotations

from dataclasses import dataclass, field
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
    topic: str = ""
    provider: str = ""
    summary: str = ""
    why_it_matters: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class BitcoinEtfIssuerSnapshot:
    ticker: str
    issuer: str
    source_url: str
    as_of: str
    shares_outstanding: int
    daily_volume: int
    aum_usd: float
    total_btc: float
    bitcoin_per_share: float


@dataclass
class BitcoinSnapshot:
    spot: MarketPoint
    etf_points: list[MarketPoint]
    etf_total_volume: int
    fear_greed_value: int | None
    fear_greed_label: str | None
    official_etf_snapshots: list[BitcoinEtfIssuerSnapshot]
    official_etf_total_btc: float | None
    official_etf_total_aum_usd: float | None
    official_etf_daily_flow_btc: float | None
    official_etf_daily_flow_usd: float | None
    official_etf_supported_tickers: list[str]
    official_etf_compared_tickers: list[str]
