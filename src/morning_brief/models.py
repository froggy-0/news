from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class MarketPoint:
    label: str
    ticker: str
    price: float | None
    change_pct: float | None
    change_bps: float | None = None
    canonical_key: str = ""
    is_previous_value: bool = False
    validation_status: str = "ok"
    raw_value: float | None = None
    resolved_value: float | None = None
    resolution_reason: str = ""


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
    sentiment_score: float | None = None
    sentiment_label: str = ""
    sentiment_confidence: float | None = None


@dataclass
class SilverNormalizedFieldRecord:
    run_id: str
    ticker: str
    issuer: str
    field_name: str
    field_value: str | float | int | None
    value_type: str
    unit: str | None
    as_of_date: date
    collected_at: datetime
    source_url: str
    source_type: str
    source_format: str
    parse_method: str
    source_file_url: str | None = None
    quality_status: str = "ok"
    raw_label: str | None = None
    raw_text: str | None = None
    schema_version: str = "v1"


@dataclass
class BitcoinEtfIssuerSnapshot:
    ticker: str
    issuer: str
    source_url: str
    as_of_date: date
    shares_outstanding: int
    daily_volume: int
    aum_usd: float
    total_btc: float
    bitcoin_per_share: float
    source_type: str = "official_html"  # official_json / official_csv / official_html
    quality_status: str = "ok"  # ok / degraded / critical
    collected_at: datetime | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class BitcoinSnapshot:
    spot: MarketPoint
    etf_points: list[MarketPoint]
    fear_greed_value: int | None
    fear_greed_label: str | None
    official_etf_snapshots: list[BitcoinEtfIssuerSnapshot]
    official_etf_total_btc: float | None
    official_etf_total_aum_usd: float | None
