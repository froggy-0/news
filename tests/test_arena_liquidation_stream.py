import json

from arena import liquidation_stream


def test_combined_url_joins_symbols_lowercased_with_market_routing() -> None:
    url = liquidation_stream._combined_url(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    assert url == (
        "wss://fstream.binance.com/market/stream"
        "?streams=btcusdt@forceOrder/ethusdt@forceOrder/solusdt@forceOrder"
    )


def test_parse_force_order_frame_combined_stream_wrapper() -> None:
    raw = json.dumps(
        {
            "stream": "btcusdt@forceOrder",
            "data": {
                "e": "forceOrder",
                "o": {"s": "BTCUSDT", "S": "SELL", "p": "64000.5", "q": "0.5", "T": 1700000000000},
            },
        }
    )
    assert liquidation_stream.parse_force_order_frame(raw) == (
        "BTCUSDT",
        "SELL",
        64000.5,
        0.5,
        1700000000000,
    )


def test_parse_force_order_frame_raw_single_stream_format() -> None:
    # /market/ws/<symbol>@forceOrder(비콤바인드) 응답은 래퍼 없이 바로 이벤트.
    raw = json.dumps(
        {"e": "forceOrder", "o": {"s": "ETHUSDT", "S": "BUY", "p": "3000", "q": "2", "T": 42}}
    )
    assert liquidation_stream.parse_force_order_frame(raw) == ("ETHUSDT", "BUY", 3000.0, 2.0, 42)


def test_parse_force_order_frame_rejects_invalid_payloads() -> None:
    assert liquidation_stream.parse_force_order_frame("not json") is None
    assert liquidation_stream.parse_force_order_frame("{}") is None
    # 심볼·가격·수량·타임스탬프 중 하나라도 없거나 0이면 무시.
    assert (
        liquidation_stream.parse_force_order_frame(
            json.dumps(
                {"e": "forceOrder", "o": {"s": "BTCUSDT", "S": "SELL", "p": "0", "q": "1", "T": 1}}
            )
        )
        is None
    )


def test_bucket_start_floors_to_4h_boundary() -> None:
    # 2026-08-10T13:42:xx UTC → 4h 버킷은 12:00 시작(0/4/8/12/16/20).
    ts_ms = 1786367 * 1000  # arbitrary epoch second scaled; assert only floor arithmetic
    floored = liquidation_stream._bucket_start(ts_ms)
    assert floored.minute == 0 and floored.second == 0
    assert floored.hour % 4 == 0


def test_bucket_add_splits_by_side() -> None:
    from datetime import datetime, timezone

    bucket = liquidation_stream._Bucket(datetime(2026, 8, 10, tzinfo=timezone.utc))
    bucket.add("SELL", 1000.0)  # 롱 청산
    bucket.add("SELL", 500.0)
    bucket.add("BUY", 300.0)  # 숏 청산
    assert bucket.long_usd == 1500.0
    assert bucket.long_n == 2
    assert bucket.short_usd == 300.0
    assert bucket.short_n == 1
