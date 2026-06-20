from __future__ import annotations

import asyncio

from scripts import backfill_arena_ohlcv as backfill


def test_backfill_parser_uses_symbol_and_interval() -> None:
    row = backfill._parse_kline(
        [
            1_797_590_400_000,
            "101000.1",
            "102000.2",
            "100000.3",
            "101500.4",
            "123.45",
            1_797_604_799_999,
        ],
        symbol="BTCUSDT",
        interval="1h",
    )

    assert row["exchange"] == "binance"
    assert row["symbol"] == "BTCUSDT"
    assert row["interval"] == "1h"
    assert row["close"] == 101500.4


def test_backfill_dry_run_does_not_require_supabase_env(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    saved = asyncio.run(backfill.save_to_supabase([{"symbol": "BTCUSDT"}], dry_run=True))

    assert saved == 1


def test_fetch_klines_skips_incomplete_current_bar() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[list]:
            return [
                [0, "1", "2", "0.5", "1.5", "10", 1_000],
                [1_001, "2", "3", "1.5", "2.5", "11", 10_000],
            ]

    class FakeClient:
        async def get(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    rows = asyncio.run(
        backfill.fetch_klines(
            FakeClient(),
            0,
            5_000,
            symbol="BTCUSDT",
            interval="1h",
        )
    )

    assert len(rows) == 1
    assert rows[0]["close_time"] == "1970-01-01T00:00:01Z"
