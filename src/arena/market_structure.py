"""Binance futures market-structure capture for Arena shadow research."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import execution_rules, parameters

logger = logging.getLogger(__name__)

FAPI_BASE_URL = "https://fapi.binance.com"
FUNDING_RATE_PATH = "/fapi/v1/fundingRate"
OPEN_INTEREST_HIST_PATH = "/futures/data/openInterestHist"
BASIS_PATH = "/futures/data/basis"
MARK_PRICE_KLINES_PATH = "/fapi/v1/markPriceKlines"
PREMIUM_INDEX_KLINES_PATH = "/fapi/v1/premiumIndexKlines"

MARK_PRICE_TYPE = "mark_price"
PREMIUM_INDEX_TYPE = "premium_index"


@dataclass(frozen=True)
class MarketStructureSnapshot:
    symbol: str
    interval: str
    data_timestamp: datetime
    fetched_at: datetime
    funding_rates: list[dict[str, Any]] = field(default_factory=list)
    open_interest: list[dict[str, Any]] = field(default_factory=list)
    basis: list[dict[str, Any]] = field(default_factory=list)
    mark_price_bars: list[dict[str, Any]] = field(default_factory=list)
    premium_index_bars: list[dict[str, Any]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def quality_status(self) -> str:
        return "ok" if not self.errors else "degraded"


def _ms(dt: datetime) -> int:
    return int(execution_rules.parse_utc_datetime(dt).timestamp() * 1000)


def _ts_from_ms(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _ts(value: datetime) -> str:
    return execution_rules.format_utc_timestamp(value)


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def parse_funding_row(row: dict[str, Any], *, fetched_at: datetime) -> dict[str, Any] | None:
    funding_time = row.get("fundingTime")
    funding_rate = _safe_float(row.get("fundingRate"))
    if funding_time is None or funding_rate is None:
        return None
    parsed = {
        "exchange": "binance",
        "symbol": row.get("symbol") or parameters.BINANCE_SYMBOL,
        "funding_time": _ts(_ts_from_ms(funding_time)),
        "funding_rate": funding_rate,
        "raw_payload": row,
        "fetched_at": _ts(fetched_at),
    }
    mark_price = _safe_float(row.get("markPrice"))
    if mark_price is not None:
        parsed["mark_price"] = mark_price
    return parsed


def parse_open_interest_row(
    row: dict[str, Any], *, symbol: str, period: str, fetched_at: datetime
) -> dict[str, Any] | None:
    timestamp = row.get("timestamp")
    if timestamp is None:
        return None
    sum_open_interest = _safe_float(row.get("sumOpenInterest"))
    sum_open_interest_value = _safe_float(row.get("sumOpenInterestValue"))
    if sum_open_interest is None and sum_open_interest_value is None:
        return None
    return {
        "exchange": "binance",
        "symbol": symbol,
        "period": period,
        "timestamp": _ts(_ts_from_ms(timestamp)),
        "sum_open_interest": sum_open_interest,
        "sum_open_interest_value": sum_open_interest_value,
        "raw_payload": row,
        "fetched_at": _ts(fetched_at),
    }


def parse_basis_row(
    row: dict[str, Any], *, pair: str, contract_type: str, period: str, fetched_at: datetime
) -> dict[str, Any] | None:
    timestamp = row.get("timestamp")
    if timestamp is None:
        return None
    basis_rate = _safe_float(row.get("basisRate"))
    annualized_basis_rate = _safe_float(row.get("annualizedBasisRate"))
    basis = _safe_float(row.get("basis"))
    if basis_rate is None and annualized_basis_rate is None and basis is None:
        return None
    return {
        "exchange": "binance",
        "pair": pair,
        "contract_type": contract_type,
        "period": period,
        "timestamp": _ts(_ts_from_ms(timestamp)),
        "basis": basis,
        "basis_rate": basis_rate,
        "annualized_basis_rate": annualized_basis_rate,
        "raw_payload": row,
        "fetched_at": _ts(fetched_at),
    }


def parse_mark_price_kline(
    row: list[Any],
    *,
    symbol: str,
    interval: str,
    price_type: str,
    fetched_at: datetime,
) -> dict[str, Any] | None:
    if not isinstance(row, list) or len(row) < 7:
        return None
    try:
        open_time = _ts_from_ms(row[0])
        close_time = _ts_from_ms(row[6])
    except (TypeError, ValueError):
        return None
    open_price = _safe_float(row[1])
    high = _safe_float(row[2])
    low = _safe_float(row[3])
    close = _safe_float(row[4])
    if None in {open_price, high, low, close}:
        return None
    return {
        "exchange": "binance",
        "symbol": symbol,
        "interval": interval,
        "price_type": price_type,
        "open_time": _ts(open_time),
        "close_time": _ts(close_time),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "raw_payload": row,
        "fetched_at": _ts(fetched_at),
    }


async def _fetch_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: dict[str, Any],
    label: str,
) -> tuple[str, list[Any], str | None]:
    try:
        res = await client.get(f"{FAPI_BASE_URL}{path}", params=params)
        res.raise_for_status()
        payload = res.json()
        if not isinstance(payload, list):
            return label, [], f"{label}: unexpected payload type {type(payload).__name__}"
        return label, payload, None
    except Exception as exc:
        logger.warning("Arena market-structure fetch failed: %s (%s)", label, exc)
        return label, [], f"{label}: {exc}"


async def fetch_market_structure_snapshot(
    *,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    data_timestamp: datetime | None = None,
    spot_close: float | None = None,
    limit: int = parameters.BINANCE_KLINES_LIMIT,
) -> MarketStructureSnapshot:
    fetched_at = datetime.now(timezone.utc)
    data_ts = execution_rules.parse_utc_datetime(data_timestamp or fetched_at)
    end_ms = _ms(data_ts)
    start_ms = _ms(data_ts - timedelta(days=30))
    pair = symbol
    contract_type = "PERPETUAL"

    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        results = await asyncio.gather(
            _fetch_json(
                client,
                FUNDING_RATE_PATH,
                params={
                    "symbol": symbol,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": min(max(limit, 1), 1000),
                },
                label="funding",
            ),
            _fetch_json(
                client,
                OPEN_INTEREST_HIST_PATH,
                params={"symbol": symbol, "period": interval, "limit": min(max(limit, 1), 500)},
                label="open_interest",
            ),
            _fetch_json(
                client,
                BASIS_PATH,
                params={
                    "pair": pair,
                    "contractType": contract_type,
                    "period": interval,
                    "limit": min(max(limit, 1), 500),
                },
                label="basis",
            ),
            _fetch_json(
                client,
                MARK_PRICE_KLINES_PATH,
                params={"symbol": symbol, "interval": interval, "limit": min(max(limit, 1), 1000)},
                label=MARK_PRICE_TYPE,
            ),
            _fetch_json(
                client,
                PREMIUM_INDEX_KLINES_PATH,
                params={"symbol": symbol, "interval": interval, "limit": min(max(limit, 1), 1000)},
                label=PREMIUM_INDEX_TYPE,
            ),
        )

    payloads = {label: payload for label, payload, _ in results}
    errors = [error for _, _, error in results if error]
    funding_rows = [
        parsed
        for row in payloads.get("funding", [])
        if isinstance(row, dict)
        for parsed in [parse_funding_row(row, fetched_at=fetched_at)]
        if parsed is not None
    ]
    oi_rows = [
        parsed
        for row in payloads.get("open_interest", [])
        if isinstance(row, dict)
        for parsed in [
            parse_open_interest_row(row, symbol=symbol, period=interval, fetched_at=fetched_at)
        ]
        if parsed is not None
    ]
    basis_rows = [
        parsed
        for row in payloads.get("basis", [])
        if isinstance(row, dict)
        for parsed in [
            parse_basis_row(
                row,
                pair=pair,
                contract_type=contract_type,
                period=interval,
                fetched_at=fetched_at,
            )
        ]
        if parsed is not None
    ]
    mark_rows = [
        parsed
        for row in payloads.get(MARK_PRICE_TYPE, [])
        for parsed in [
            parse_mark_price_kline(
                row,
                symbol=symbol,
                interval=interval,
                price_type=MARK_PRICE_TYPE,
                fetched_at=fetched_at,
            )
        ]
        if parsed is not None
    ]
    premium_rows = [
        parsed
        for row in payloads.get(PREMIUM_INDEX_TYPE, [])
        for parsed in [
            parse_mark_price_kline(
                row,
                symbol=symbol,
                interval=interval,
                price_type=PREMIUM_INDEX_TYPE,
                fetched_at=fetched_at,
            )
        ]
        if parsed is not None
    ]

    features = build_market_features(
        data_timestamp=data_ts,
        spot_close=spot_close,
        funding_rates=funding_rows,
        open_interest=oi_rows,
        basis=basis_rows,
        mark_price_bars=mark_rows,
        premium_index_bars=premium_rows,
        errors=errors,
    )
    return MarketStructureSnapshot(
        symbol=symbol,
        interval=interval,
        data_timestamp=data_ts,
        fetched_at=fetched_at,
        funding_rates=funding_rows,
        open_interest=oi_rows,
        basis=basis_rows,
        mark_price_bars=mark_rows,
        premium_index_bars=premium_rows,
        features=features,
        errors=errors,
    )


def _latest_at_or_before(
    rows: list[dict[str, Any]], time_key: str, at: datetime
) -> dict[str, Any] | None:
    selected = None
    for row in rows:
        try:
            row_time = execution_rules.parse_utc_datetime(row[time_key])
        except (KeyError, TypeError, ValueError):
            continue
        if row_time <= at:
            selected = row
    return selected


def _sum_funding_between(
    rows: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> float | None:
    total = 0.0
    count = 0
    for row in rows:
        try:
            funding_time = execution_rules.parse_utc_datetime(row["funding_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < funding_time <= end:
            rate = _safe_float(row.get("funding_rate"))
            if rate is not None:
                total += rate
                count += 1
    return total if count else None


def build_market_features(
    *,
    data_timestamp: datetime,
    spot_close: float | None,
    funding_rates: list[dict[str, Any]],
    open_interest: list[dict[str, Any]],
    basis: list[dict[str, Any]],
    mark_price_bars: list[dict[str, Any]],
    premium_index_bars: list[dict[str, Any]],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    data_ts = execution_rules.parse_utc_datetime(data_timestamp)
    latest_funding = _latest_at_or_before(funding_rates, "funding_time", data_ts)
    funding_24h = _sum_funding_between(
        funding_rates,
        start=data_ts - timedelta(hours=24),
        end=data_ts,
    )
    latest_oi = _latest_at_or_before(open_interest, "timestamp", data_ts)
    oi_24h_ago = _latest_at_or_before(
        open_interest,
        "timestamp",
        data_ts - timedelta(hours=24),
    )
    latest_basis = _latest_at_or_before(basis, "timestamp", data_ts)
    latest_mark = _latest_at_or_before(mark_price_bars, "close_time", data_ts)
    latest_premium = _latest_at_or_before(premium_index_bars, "close_time", data_ts)

    oi_value = _safe_float(latest_oi.get("sum_open_interest_value")) if latest_oi else None
    oi_prev = _safe_float(oi_24h_ago.get("sum_open_interest_value")) if oi_24h_ago else None
    oi_change_24h = (oi_value / oi_prev - 1.0) if oi_value is not None and oi_prev else None
    mark_close = _safe_float(latest_mark.get("close")) if latest_mark else None
    mark_spot_basis = (
        mark_close / spot_close - 1.0
        if mark_close is not None and spot_close and spot_close > 0
        else None
    )

    return {
        "quality_status": "ok" if not errors else "degraded",
        "quality_errors": errors or [],
        "latest_funding_rate": _safe_float(latest_funding.get("funding_rate"))
        if latest_funding
        else None,
        "funding_rate_24h": funding_24h,
        "open_interest_usd": oi_value,
        "open_interest_change_24h": oi_change_24h,
        "basis_rate": _safe_float(latest_basis.get("basis_rate")) if latest_basis else None,
        "annualized_basis_rate": _safe_float(latest_basis.get("annualized_basis_rate"))
        if latest_basis
        else None,
        "mark_price": mark_close,
        "premium_index": _safe_float(latest_premium.get("close")) if latest_premium else None,
        "mark_spot_basis": mark_spot_basis,
        "source_counts": {
            "funding_rates": len(funding_rates),
            "open_interest": len(open_interest),
            "basis": len(basis),
            "mark_price_bars": len(mark_price_bars),
            "premium_index_bars": len(premium_index_bars),
        },
    }


def funding_return_pct(
    *,
    direction: str,
    funding_rates: list[dict[str, Any]],
    open_time: datetime,
    close_time: datetime,
) -> float:
    total_rate = _sum_funding_between(
        funding_rates,
        start=execution_rules.parse_utc_datetime(open_time),
        end=execution_rules.parse_utc_datetime(close_time),
    )
    if total_rate is None:
        return 0.0
    return -execution_rules.direction_sign(direction) * total_rate
