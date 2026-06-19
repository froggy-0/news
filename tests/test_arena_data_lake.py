from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from arena import data_lake, parameters


def test_parse_binance_kline_preserves_raw_ohlcv_contract() -> None:
    fetched_at = datetime(2026, 6, 19, 1, 2, 3, tzinfo=timezone.utc)
    kline = [
        1_797_590_400_000,
        "101000.1",
        "102000.2",
        "100000.3",
        "101500.4",
        "123.45",
        1_797_604_799_999,
        "12500000.67",
        54321,
        "60.1",
        "6100000.2",
        "0",
    ]

    row = data_lake.parse_binance_kline(kline, run_id="run-1", fetched_at=fetched_at)

    assert row["run_id"] == "run-1"
    assert row["exchange"] == "binance"
    assert row["symbol"] == "BTCUSDT"
    assert row["interval"] == "4h"
    assert row["open_time"] == "2026-12-18T10:40:00Z"
    assert row["close_time"] == "2026-12-18T14:39:59Z"
    assert row["open"] == 101000.1
    assert row["high"] == 102000.2
    assert row["low"] == 100000.3
    assert row["close"] == 101500.4
    assert row["volume"] == 123.45
    assert row["quote_volume"] == 12500000.67
    assert row["trade_count"] == 54321
    assert row["taker_buy_base_volume"] == 60.1
    assert row["taker_buy_quote_volume"] == 6100000.2
    assert row["raw_payload"] == kline
    assert row["fetched_at"] == "2026-06-19T01:02:03Z"


def test_payload_hash_is_stable_for_key_order() -> None:
    left = {"b": 2, "a": {"x": 1}}
    right = {"a": {"x": 1}, "b": 2}

    assert data_lake.payload_hash(left) == data_lake.payload_hash(right)


def test_safe_execute_logs_and_suppresses_write_errors(caplog) -> None:
    class FailingBuilder:
        async def execute(self) -> None:
            raise RuntimeError("table missing")

    caplog.set_level(logging.WARNING)

    result = asyncio.run(data_lake._safe_execute("arena_runs.start", FailingBuilder()))

    assert result.ok is False
    assert result.label == "arena_runs.start"
    assert result.error == "table missing"
    assert "Arena data lake write failed: arena_runs.start" in caplog.text
    assert "table missing" in caplog.text


def test_capture_health_summarizes_write_results() -> None:
    health = data_lake._capture_health(
        [
            data_lake.CaptureWriteResult(label="ok", ok=True),
            data_lake.CaptureWriteResult(label="failed", ok=False, error="boom"),
        ]
    )

    assert health == {
        "capture_status": "degraded",
        "capture_error_count": 1,
        "capture_warnings": [{"label": "failed", "error": "boom"}],
    }


def test_record_ohlcv_bars_upserts_raw_and_run_inputs(monkeypatch) -> None:
    class FakeBuilder:
        def __init__(self, table_name: str) -> None:
            self.table_name = table_name
            self.rows = []
            self.on_conflict = ""
            self.executed = False

        def upsert(self, rows, *, on_conflict: str):
            self.rows = rows
            self.on_conflict = on_conflict
            return self

        async def execute(self) -> None:
            self.executed = True

    class FakeDb:
        def __init__(self) -> None:
            self.builders: dict[str, FakeBuilder] = {}

        def table(self, table_name: str) -> FakeBuilder:
            builder = FakeBuilder(table_name)
            self.builders[table_name] = builder
            return builder

    fake_db = FakeDb()
    monkeypatch.setattr(data_lake.positions, "db", lambda: fake_db)

    results = asyncio.run(
        data_lake.record_ohlcv_bars(
            run_id="run-2",
            raw_klines=[
                [
                    1_797_590_400_000,
                    "101000.1",
                    "102000.2",
                    "100000.3",
                    "101500.4",
                    "123.45",
                    1_797_604_799_999,
                ]
            ],
            fetched_at=datetime(2026, 6, 19, 1, 2, 3, tzinfo=timezone.utc),
        )
    )

    assert [result.ok for result in results] == [True, True]

    raw_builder = fake_db.builders["arena_ohlcv_bars"]
    assert raw_builder.on_conflict == "exchange,symbol,interval,open_time"
    assert raw_builder.executed is True
    assert raw_builder.rows[0]["run_id"] == "run-2"
    assert raw_builder.rows[0]["close"] == 101500.4

    input_builder = fake_db.builders["arena_run_ohlcv_bars"]
    assert input_builder.on_conflict == "run_id,exchange,symbol,interval,open_time"
    assert input_builder.executed is True
    assert input_builder.rows == [
        {
            "run_id": "run-2",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "open_time": "2026-12-18T10:40:00Z",
            "close_time": "2026-12-18T14:39:59Z",
            "input_position": 0,
            "fetched_at": "2026-06-19T01:02:03Z",
        }
    ]


def test_record_strategy_metadata_upserts_strategy_and_features(monkeypatch) -> None:
    class FakeBuilder:
        def __init__(self, table_name: str) -> None:
            self.table_name = table_name
            self.rows = None
            self.on_conflict = ""
            self.executed = False

        def upsert(self, rows, *, on_conflict: str):
            self.rows = rows
            self.on_conflict = on_conflict
            return self

        async def execute(self) -> None:
            self.executed = True

    class FakeDb:
        def __init__(self) -> None:
            self.builders: dict[str, FakeBuilder] = {}

        def table(self, table_name: str) -> FakeBuilder:
            builder = FakeBuilder(table_name)
            self.builders[table_name] = builder
            return builder

    fake_db = FakeDb()
    monkeypatch.setattr(data_lake.positions, "db", lambda: fake_db)

    results = asyncio.run(
        data_lake.record_strategy_metadata(params_snapshot=parameters.base_params_snapshot())
    )

    assert [result.ok for result in results] == [True, True]

    strategy_builder = fake_db.builders["arena_strategy_versions"]
    assert strategy_builder.on_conflict == "strategy_version"
    assert strategy_builder.executed is True
    assert strategy_builder.rows["strategy_version"] == parameters.STRATEGY_VERSION
    assert strategy_builder.rows["feature_set_version"] == parameters.FEATURE_SET_VERSION

    feature_builder = fake_db.builders["arena_feature_registry"]
    assert feature_builder.on_conflict == "feature_set_version,feature_name"
    assert feature_builder.executed is True
    assert len(feature_builder.rows) == 10
    assert {row["feature_name"] for row in feature_builder.rows} >= {"rsi", "atr", "fng"}
