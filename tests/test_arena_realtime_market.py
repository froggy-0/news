from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arena import realtime_market


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_parse_realtime_trade_message() -> None:
    event_time = datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)
    raw = json.dumps(
        {
            "stream": "btcusdt@trade",
            "data": {
                "e": "trade",
                "E": _ms(event_time),
                "p": "100000.5",
                "q": "0.01",
                "m": False,
            },
        }
    )

    event = realtime_market.parse_realtime_message(raw, received_at=event_time)

    assert event is not None
    assert event.event_type == "trade"
    assert event.payload["price"] == "100000.5"
    assert event.payload["buyer_is_maker"] is False


def test_realtime_aggregator_builds_execution_features() -> None:
    event_time = datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)
    aggregator = realtime_market.RealtimeFeatureAggregator(symbol="BTCUSDT", window_seconds=60)
    messages = [
        {
            "stream": "btcusdt@bookTicker",
            "data": {"e": "bookTicker", "E": _ms(event_time), "b": "99990", "a": "100010"},
        },
        {
            "stream": "btcusdt@depth20@100ms",
            "data": {
                "e": "depthUpdate",
                "E": _ms(event_time),
                "b": [["99990", "20"], ["99950", "10"]],
                "a": [["100010", "20"], ["100050", "10"]],
            },
        },
        {
            "stream": "btcusdt@trade",
            "data": {"e": "trade", "E": _ms(event_time), "p": "100000", "q": "1", "m": False},
        },
        {
            "stream": "btcusdt@trade",
            "data": {"e": "trade", "E": _ms(event_time), "p": "100000", "q": "1", "m": True},
        },
    ]
    for message in messages:
        event = realtime_market.parse_realtime_message(json.dumps(message), received_at=event_time)
        assert event is not None
        aggregator.add(event)

    row = aggregator.flush(datetime(2026, 6, 20, 1, 1, tzinfo=timezone.utc))

    assert row is not None
    assert row["symbol"] == "BTCUSDT"
    assert row["spread_bps_avg"] == pytest.approx(2.0)
    assert row["depth_10bp_bid_usd"] == pytest.approx(2_999_300.0)
    assert row["depth_10bp_ask_usd"] == pytest.approx(3_000_700.0)
    assert row["taker_buy_sell_ratio"] == pytest.approx(0.5)
    assert row["expected_slippage_bps"] is not None
    assert row["quality_status"] == "ok"
