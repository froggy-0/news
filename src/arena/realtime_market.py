"""Real-time market observation and 1m execution feature aggregation."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import websockets

from . import config, data_lake, execution_rules, market_structure, parameters, realtime_risk

logger = logging.getLogger(__name__)

STREAMS = ("trade", "bookTicker", "depth20@100ms", "kline_1m")


@dataclass(frozen=True)
class ParsedRealtimeEvent:
    event_type: str
    event_time: datetime
    payload: dict[str, Any]
    observed_latency_ms: float | None = None


@dataclass
class RealtimeFeatureAggregator:
    symbol: str
    window_seconds: int = parameters.REALTIME_FEATURE_WINDOW_SECONDS
    window_start: datetime | None = None
    spreads_bps: list[float] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    trade_buy_quote: float = 0.0
    trade_sell_quote: float = 0.0
    kline_closes: list[float] = field(default_factory=list)
    kline_volumes: list[float] = field(default_factory=list)
    latest_bid: float | None = None
    latest_ask: float | None = None
    latest_bid_qty: float | None = None
    latest_ask_qty: float | None = None
    latest_bids: list[tuple[float, float]] = field(default_factory=list)
    latest_asks: list[tuple[float, float]] = field(default_factory=list)
    raw_counts: dict[str, int] = field(default_factory=dict)
    quality_errors: list[str] = field(default_factory=list)
    recent_rows: list[dict[str, Any]] = field(default_factory=list)
    recent_risk_scores: list[float] = field(default_factory=list)
    previous_risk_state: str | None = None

    def add(self, event: ParsedRealtimeEvent) -> None:
        self.window_start = self.window_start or _floor_time(event.event_time, self.window_seconds)
        self.raw_counts[event.event_type] = self.raw_counts.get(event.event_type, 0) + 1
        if event.observed_latency_ms is not None:
            self.latencies_ms.append(event.observed_latency_ms)
        if event.event_type == "book_ticker":
            self._add_book_ticker(event.payload)
        elif event.event_type == "trade":
            self._add_trade(event.payload)
        elif event.event_type == "depth":
            self._add_depth(event.payload)
        elif event.event_type == "kline_1m":
            self._add_kline(event.payload)

    def should_flush(self, now: datetime) -> bool:
        if self.window_start is None:
            return False
        return now >= self.window_start + timedelta(seconds=self.window_seconds)

    def flush(self, now: datetime | None = None) -> dict[str, Any] | None:
        if self.window_start is None:
            return None
        now = now or datetime.now(timezone.utc)
        window_end = self.window_start + timedelta(seconds=self.window_seconds)
        if now < window_end and not self.raw_counts:
            return None
        row = build_feature_row(
            symbol=self.symbol,
            window_start=self.window_start,
            window_end=window_end,
            window_seconds=self.window_seconds,
            spreads_bps=self.spreads_bps,
            latencies_ms=self.latencies_ms,
            trade_buy_quote=self.trade_buy_quote,
            trade_sell_quote=self.trade_sell_quote,
            kline_closes=self.kline_closes,
            kline_volumes=self.kline_volumes,
            bid=self.latest_bid,
            ask=self.latest_ask,
            bids=self.latest_bids,
            asks=self.latest_asks,
            raw_counts=dict(self.raw_counts),
            quality_errors=list(self.quality_errors),
        )
        enrich_feature_row_with_history(row, self.recent_rows)
        self.recent_rows.append(row)
        self.recent_rows = self.recent_rows[-config.REALTIME_RISK_HISTORY_WINDOWS :]
        self._reset(window_end)
        return row

    def _reset(self, next_start: datetime) -> None:
        self.window_start = next_start
        self.spreads_bps.clear()
        self.latencies_ms.clear()
        self.trade_buy_quote = 0.0
        self.trade_sell_quote = 0.0
        self.kline_closes.clear()
        self.kline_volumes.clear()
        self.raw_counts.clear()
        self.quality_errors.clear()

    def _add_book_ticker(self, payload: dict[str, Any]) -> None:
        bid = _float(payload.get("bid_price"))
        ask = _float(payload.get("ask_price"))
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            self.quality_errors.append("bad_book_ticker")
            return
        self.latest_bid = bid
        self.latest_ask = ask
        self.latest_bid_qty = _float(payload.get("bid_qty"))
        self.latest_ask_qty = _float(payload.get("ask_qty"))
        mid = (bid + ask) / 2.0
        self.spreads_bps.append((ask - bid) / mid * 10_000.0)

    def _add_trade(self, payload: dict[str, Any]) -> None:
        price = _float(payload.get("price"))
        qty = _float(payload.get("qty"))
        if price is None or qty is None:
            self.quality_errors.append("bad_trade")
            return
        quote = price * qty
        if payload.get("buyer_is_maker"):
            self.trade_sell_quote += quote
        else:
            self.trade_buy_quote += quote

    def _add_depth(self, payload: dict[str, Any]) -> None:
        self.latest_bids = _levels(payload.get("bids"))
        self.latest_asks = _levels(payload.get("asks"))

    def _add_kline(self, payload: dict[str, Any]) -> None:
        close = _float(payload.get("close"))
        volume = _float(payload.get("volume"))
        if close is not None:
            self.kline_closes.append(close)
        if volume is not None:
            self.kline_volumes.append(volume)


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _event_time(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _floor_time(dt: datetime, window_seconds: int) -> datetime:
    ts = int(dt.timestamp())
    return datetime.fromtimestamp(ts - (ts % window_seconds), tz=timezone.utc)


def _levels(rows: Any) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _float(row[0])
        qty = _float(row[1])
        if price is not None and qty is not None:
            levels.append((price, qty))
    return levels


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(len(ordered) * percentile)) - 1))
    return ordered[index]


def _depth_within_bps(
    levels: list[tuple[float, float]],
    *,
    mid: float,
    side: str,
    bps: float = 10.0,
) -> float | None:
    if mid <= 0 or not levels:
        return None
    if side == "bid":
        threshold = mid * (1.0 - bps / 10_000.0)
        included = [(price, qty) for price, qty in levels if price >= threshold]
    else:
        threshold = mid * (1.0 + bps / 10_000.0)
        included = [(price, qty) for price, qty in levels if price <= threshold]
    return sum(price * qty for price, qty in included)


def _realized_vol(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    returns = [
        math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0
    ]
    if not returns:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return math.sqrt(variance)


def _min_depth(row: dict[str, Any]) -> float | None:
    bid_depth = _float(row.get("depth_10bp_bid_usd"))
    ask_depth = _float(row.get("depth_10bp_ask_usd"))
    if bid_depth is None or ask_depth is None:
        return None
    return min(bid_depth, ask_depth)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def enrich_feature_row_with_history(
    row: dict[str, Any],
    history_rows: list[dict[str, Any]],
) -> None:
    recent = [*history_rows[-4:], row]
    prices = [value for item in recent for value in [_float(item.get("last_price"))] if value]
    row["realized_volatility_5m"] = _realized_vol(prices)
    if len(prices) >= 2 and prices[-2] > 0:
        row["mid_return_1m"] = prices[-1] / prices[-2] - 1.0
    else:
        row["mid_return_1m"] = None
    if prices:
        peak = max(prices)
        row["short_drawdown_5m"] = prices[-1] / peak - 1.0 if peak > 0 else None
    else:
        row["short_drawdown_5m"] = None

    previous_spread = _float(history_rows[-1].get("spread_bps_avg")) if history_rows else None
    current_spread = _float(row.get("spread_bps_avg"))
    row["spread_widening_bps_per_min"] = (
        current_spread - previous_spread
        if current_spread is not None and previous_spread is not None
        else None
    )

    current_depth = _min_depth(row)
    baseline_depth = _median(
        [value for item in history_rows[-20:] for value in [_min_depth(item)] if value is not None]
    )
    row["depth_collapse_ratio"] = (
        max(0.0, 1.0 - current_depth / baseline_depth)
        if current_depth is not None and baseline_depth and baseline_depth > 0
        else None
    )


def parse_realtime_message(
    raw: str, *, received_at: datetime | None = None
) -> ParsedRealtimeEvent | None:
    received_at = received_at or datetime.now(timezone.utc)
    data = json.loads(raw)
    payload = data.get("data", data)
    stream = str(data.get("stream", ""))
    event_type = payload.get("e")
    event_time_ms = payload.get("E")
    observed_latency_ms = None
    if event_time_ms is not None:
        observed_latency_ms = max(0.0, received_at.timestamp() * 1000.0 - float(event_time_ms))

    if event_type == "trade" or stream.endswith("@trade"):
        return ParsedRealtimeEvent(
            event_type="trade",
            event_time=_event_time(event_time_ms or payload.get("T")),
            observed_latency_ms=observed_latency_ms,
            payload={
                "price": payload.get("p"),
                "qty": payload.get("q"),
                "buyer_is_maker": bool(payload.get("m")),
            },
        )
    if event_type == "bookTicker" or stream.endswith("@bookTicker"):
        return ParsedRealtimeEvent(
            event_type="book_ticker",
            event_time=_event_time(event_time_ms),
            observed_latency_ms=observed_latency_ms,
            payload={
                "bid_price": payload.get("b"),
                "bid_qty": payload.get("B"),
                "ask_price": payload.get("a"),
                "ask_qty": payload.get("A"),
            },
        )
    if event_type == "depthUpdate" or "@depth" in stream:
        return ParsedRealtimeEvent(
            event_type="depth",
            event_time=_event_time(event_time_ms),
            observed_latency_ms=observed_latency_ms,
            payload={
                "bids": payload.get("b", payload.get("bids")),
                "asks": payload.get("a", payload.get("asks")),
            },
        )
    if event_type == "kline" or stream.endswith("@kline_1m"):
        kline = payload.get("k", {})
        return ParsedRealtimeEvent(
            event_type="kline_1m",
            event_time=_event_time(event_time_ms or kline.get("T")),
            observed_latency_ms=observed_latency_ms,
            payload={"close": kline.get("c"), "volume": kline.get("v")},
        )
    return None


def build_feature_row(
    *,
    symbol: str,
    window_start: datetime,
    window_end: datetime,
    window_seconds: int,
    spreads_bps: list[float],
    latencies_ms: list[float],
    trade_buy_quote: float,
    trade_sell_quote: float,
    kline_closes: list[float],
    kline_volumes: list[float],
    bid: float | None,
    ask: float | None,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    raw_counts: dict[str, int],
    quality_errors: list[str],
) -> dict[str, Any]:
    mid = (bid + ask) / 2.0 if bid and ask else None
    bid_depth = _depth_within_bps(bids, mid=mid, side="bid") if mid else None
    ask_depth = _depth_within_bps(asks, mid=mid, side="ask") if mid else None
    depth_total = (bid_depth or 0.0) + (ask_depth or 0.0)
    imbalance = ((bid_depth or 0.0) - (ask_depth or 0.0)) / depth_total if depth_total > 0 else None
    taker_total = trade_buy_quote + trade_sell_quote
    taker_ratio = trade_buy_quote / taker_total if taker_total > 0 else None
    aggressive_sell_ratio = trade_sell_quote / taker_total if taker_total > 0 else None
    spread_avg = sum(spreads_bps) / len(spreads_bps) if spreads_bps else None
    realized_vol_1m = _realized_vol(kline_closes)
    volume_spike = 1.0 if kline_volumes and kline_volumes[-1] > 2.0 * _mean(kline_volumes) else 0.0
    expected_slippage = _expected_slippage_bps(spread_avg, bid_depth, ask_depth)
    latency_p95 = _percentile(latencies_ms, 0.95)
    return {
        "symbol": symbol,
        "window_start": execution_rules.format_utc_timestamp(window_start),
        "window_end": execution_rules.format_utc_timestamp(window_end),
        "window_seconds": window_seconds,
        "spread_bps_avg": spread_avg,
        "spread_bps_p95": _percentile(spreads_bps, 0.95),
        "depth_10bp_bid_usd": bid_depth,
        "depth_10bp_ask_usd": ask_depth,
        "orderbook_imbalance": imbalance,
        "taker_buy_sell_ratio": taker_ratio,
        "aggressive_sell_ratio": aggressive_sell_ratio,
        "trade_quote_volume": taker_total if taker_total > 0 else None,
        "realized_volatility_1m": realized_vol_1m,
        "realized_volatility_5m": None,
        "volume_spike": volume_spike,
        "volatility_score": volume_spike,
        "expected_slippage_bps": expected_slippage,
        "api_latency_ms_p95": latency_p95,
        "last_bid": bid,
        "last_ask": ask,
        "last_price": mid,
        "raw_counts": raw_counts,
        "quality_status": "ok" if not quality_errors else "degraded",
        "quality_errors": quality_errors,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _expected_slippage_bps(
    spread_bps: float | None,
    bid_depth: float | None,
    ask_depth: float | None,
) -> float | None:
    half_spread = (spread_bps or 0.0) / 2.0
    min_depth = (
        min(value for value in (bid_depth, ask_depth) if value is not None)
        if (bid_depth is not None or ask_depth is not None)
        else None
    )
    if min_depth is None:
        return half_spread if spread_bps is not None else None
    depth_penalty = max(0.0, parameters.EXEC_GATE_MIN_DEPTH_10BP_USD / max(min_depth, 1.0) - 1.0)
    return half_spread + depth_penalty


def _stream_url(symbol: str) -> str:
    prefix = symbol.lower()
    streams = "/".join(f"{prefix}@{stream}" for stream in STREAMS)
    return f"{config.BINANCE_COMBINED_WS_URL}?streams={streams}"


async def run(*, symbol: str = parameters.BINANCE_SYMBOL) -> None:
    if not config.ENABLE_ARENA_REALTIME_COLLECTOR:
        logger.info("Arena realtime collector disabled")
        while True:
            await asyncio.sleep(parameters.SERVER_IDLE_SLEEP_SECONDS)
    aggregator = RealtimeFeatureAggregator(
        symbol=symbol,
        window_seconds=config.REALTIME_FEATURE_WINDOW_SECONDS,
    )
    while True:
        try:
            async with websockets.connect(
                _stream_url(symbol),
                ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
            ) as ws:
                logger.info("Arena realtime collector connected")
                async for raw in ws:
                    event = parse_realtime_message(raw)
                    if event is not None:
                        aggregator.add(event)
                    if aggregator.should_flush(datetime.now(timezone.utc)):
                        row = aggregator.flush()
                        if row:
                            await _record_feature_and_risk(aggregator, row)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Arena realtime collector error: %s; reconnecting in %ss",
                exc,
                parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(parameters.WEBSOCKET_RECONNECT_DELAY_SECONDS)


async def run_for_seconds(
    *,
    symbol: str,
    seconds: int,
    dry_run: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    aggregator = RealtimeFeatureAggregator(
        symbol=symbol,
        window_seconds=min(config.REALTIME_FEATURE_WINDOW_SECONDS, max(1, seconds)),
    )
    deadline = time.monotonic() + seconds
    async with websockets.connect(
        _stream_url(symbol),
        ping_interval=parameters.WEBSOCKET_PING_INTERVAL_SECONDS,
    ) as ws:
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(1.0, deadline - time.monotonic()),
                )
            except TimeoutError:
                break
            event = parse_realtime_message(raw)
            if event is not None:
                aggregator.add(event)
            if aggregator.should_flush(datetime.now(timezone.utc)):
                row = aggregator.flush()
                if row:
                    rows.append(row)
                    if not dry_run:
                        await data_lake.record_realtime_feature_bar(row)
    row = aggregator.flush(
        datetime.now(timezone.utc) + timedelta(seconds=aggregator.window_seconds)
    )
    if row:
        rows.append(row)
        if not dry_run:
            await data_lake.record_realtime_feature_bar(row)
    return rows


async def _record_feature_and_risk(
    aggregator: RealtimeFeatureAggregator,
    row: dict[str, Any],
) -> None:
    await data_lake.record_realtime_feature_bar(row)
    if not config.ENABLE_ARENA_REALTIME_RISK:
        return
    decision = realtime_risk.evaluate_realtime_risk(
        feature_row=row,
        history_rows=aggregator.recent_rows[:-1],
        market_features=market_structure.get_latest_market_features(),
        recent_scores=aggregator.recent_risk_scores,
        evaluated_at=datetime.now(timezone.utc),
    )
    await data_lake.record_realtime_risk_state(decision)
    if decision.risk_score is not None:
        aggregator.recent_risk_scores.append(decision.risk_score)
        aggregator.recent_risk_scores = aggregator.recent_risk_scores[
            -config.REALTIME_RISK_HISTORY_WINDOWS :
        ]
    if aggregator.previous_risk_state != decision.risk_state:
        await data_lake.record_realtime_risk_event(
            decision=decision,
            previous_state=aggregator.previous_risk_state,
            event_type="state_transition",
        )
        aggregator.previous_risk_state = decision.risk_state


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Arena realtime execution features.")
    parser.add_argument("--symbol", default=parameters.BINANCE_SYMBOL)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true", help="Capture a short dry-run sample.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seconds = 5 if args.once else args.seconds
    dry_run = True if args.once else args.dry_run
    rows = asyncio.run(run_for_seconds(symbol=args.symbol, seconds=seconds, dry_run=dry_run))
    print(json.dumps(rows, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
