from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from arena import data_lake, parameters
from arena.execution_gate import ExecutionGateDecision, ExecutionGatePolicy
from arena.market_structure import MarketStructureSnapshot


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


def test_record_ohlcv_bars_upserts_shared_bars_and_records_input_range(monkeypatch) -> None:
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

        def update(self, rows):
            self.rows = rows
            return self

        def eq(self, field: str, value: str):
            self.eq_filter = (field, value)
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

    input_builder = fake_db.builders["arena_runs"]
    assert input_builder.executed is True
    assert input_builder.eq_filter == ("run_id", "run-2")
    assert input_builder.rows == {
        "input_open_time": "2026-12-18T10:40:00Z",
        "input_close_time": "2026-12-18T14:39:59Z",
        "input_bar_count": 1,
    }


def test_record_execution_gate_drops_raw_depth_and_duplicate_snapshots(monkeypatch) -> None:
    class FakeBuilder:
        def __init__(self) -> None:
            self.row = None

        def upsert(self, row, *, on_conflict: str):
            self.row = row
            self.on_conflict = on_conflict
            return self

        async def execute(self) -> None:
            return None

    builder = FakeBuilder()

    class FakeDb:
        def table(self, table_name: str) -> FakeBuilder:
            assert table_name == "arena_execution_gates"
            return builder

    monkeypatch.setattr(data_lake.positions, "db", lambda: FakeDb())
    evaluated_at = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)
    decision = ExecutionGateDecision(
        allowed=True,
        decision="trade_allowed",
        reject_reason=None,
        expected_return_bps=30.0,
        expected_cost_bps=10.0,
        spread_bps=1.0,
        expected_slippage_bps=2.0,
        depth_score=1.0,
        volatility_score=0.5,
        api_latency_ms=20.0,
        policy=ExecutionGatePolicy(),
        evaluated_at=evaluated_at,
        feature_snapshot={
            "last_price": 100.0,
            "depth_10bp_bid_usd": 10_000.0,
            "depth_bids": [[99.0, 10.0]] * 1000,
            "depth_asks": [[101.0, 10.0]] * 1000,
            "realtime_risk_snapshot": {"large": "duplicate"},
        },
        risk_snapshot={"allowed": True},
    )

    result = asyncio.run(
        data_lake.record_execution_gate(
            run_id="run-3",
            algo_id="omnibus",
            signal="long",
            timeframe="4h",
            decision=decision,
        )
    )

    assert result.ok is True
    assert builder.on_conflict == "run_id,algo_id"
    assert builder.row["feature_snapshot"] == {
        "last_price": 100.0,
        "depth_10bp_bid_usd": 10_000.0,
    }
    assert builder.row["risk_snapshot"] == {"allowed": True}
    assert builder.row["gate_snapshot"] == {
        "policy": data_lake.execution_gate_policy_snapshot(decision.policy)
    }


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
    assert len(feature_builder.rows) == 16
    assert {row["feature_name"] for row in feature_builder.rows} >= {
        "rsi",
        "atr",
        "fng",
        "ema_fast",
        "funding_rate_24h",
    }


def test_record_strategy_metadata_falls_back_for_legacy_layer_constraint(monkeypatch) -> None:
    class FakeBuilder:
        def __init__(self, table_name: str, *, should_fail: bool = False) -> None:
            self.table_name = table_name
            self.should_fail = should_fail
            self.rows = None
            self.on_conflict = ""
            self.executed = False

        def upsert(self, rows, *, on_conflict: str):
            self.rows = rows
            self.on_conflict = on_conflict
            return self

        async def execute(self) -> None:
            self.executed = True
            if self.should_fail:
                raise RuntimeError("arena_feature_registry_layer_check")

    class FakeDb:
        def __init__(self) -> None:
            self.builders: dict[str, list[FakeBuilder]] = {}
            self.feature_attempts = 0

        def table(self, table_name: str) -> FakeBuilder:
            should_fail = table_name == "arena_feature_registry" and self.feature_attempts == 0
            if table_name == "arena_feature_registry":
                self.feature_attempts += 1
            builder = FakeBuilder(table_name, should_fail=should_fail)
            self.builders.setdefault(table_name, []).append(builder)
            return builder

    fake_db = FakeDb()
    monkeypatch.setattr(data_lake.positions, "db", lambda: fake_db)

    results = asyncio.run(
        data_lake.record_strategy_metadata(params_snapshot=parameters.base_params_snapshot())
    )

    assert [result.ok for result in results] == [True, True]
    feature_attempts = fake_db.builders["arena_feature_registry"]
    assert len(feature_attempts) == 2
    assert any(row["layer"] == "market_structure" for row in feature_attempts[0].rows)
    assert all(row["layer"] != "market_structure" for row in feature_attempts[1].rows)
    assert {
        row["layer"]
        for row in feature_attempts[1].rows
        if row["source_table"] == "arena_market_feature_snapshots"
    } == {"raw_market"}


def test_record_market_structure_snapshot_tolerates_legacy_premium_constraint(
    monkeypatch,
) -> None:
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
            rows = self.rows if isinstance(self.rows, list) else [self.rows]
            if (
                self.table_name == "arena_mark_price_bars"
                and rows
                and rows[0].get("price_type") == "premium_index"
            ):
                raise RuntimeError("arena_mark_price_bars_price_check")

    class FakeDb:
        def __init__(self) -> None:
            self.builders: dict[str, list[FakeBuilder]] = {}

        def table(self, table_name: str) -> FakeBuilder:
            builder = FakeBuilder(table_name)
            self.builders.setdefault(table_name, []).append(builder)
            return builder

    fake_db = FakeDb()
    monkeypatch.setattr(data_lake.positions, "db", lambda: fake_db)
    fetched_at = datetime(2026, 6, 19, 1, 2, 3, tzinfo=timezone.utc)
    snapshot = MarketStructureSnapshot(
        symbol="BTCUSDT",
        interval="4h",
        data_timestamp=fetched_at,
        fetched_at=fetched_at,
        funding_rates=[],
        open_interest=[],
        basis=[],
        mark_price_bars=[
            {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "price_type": "mark_price",
                "open_time": "2026-06-19T00:00:00Z",
                "close_time": "2026-06-19T03:59:59Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "raw_payload": [],
                "fetched_at": "2026-06-19T01:02:03Z",
            }
        ],
        premium_index_bars=[
            {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "price_type": "premium_index",
                "open_time": "2026-06-19T00:00:00Z",
                "close_time": "2026-06-19T03:59:59Z",
                "open": -0.001,
                "high": 0.001,
                "low": -0.002,
                "close": -0.0005,
                "raw_payload": [],
                "fetched_at": "2026-06-19T01:02:03Z",
            }
        ],
        features={"quality_status": "ok"},
        errors=[],
    )

    results = asyncio.run(
        data_lake.record_market_structure_snapshot(run_id="run-3", snapshot=snapshot)
    )

    assert all(result.ok for result in results)
    assert any(
        result.label == "arena_mark_price_bars.premium_index.upsert.schema_skipped"
        for result in results
    )
    # mark_price와 premium_index는 별도 upsert로 나가야 한다(premium이 레거시 제약으로
    # 실패해도 mark_price는 저장되도록). _rows_needing_write()의 사전 조회 builder는
    # upsert를 호출하지 않으므로 rows is None으로 구분한다.
    upserts = [b for b in fake_db.builders["arena_mark_price_bars"] if b.rows is not None]
    assert len(upserts) == 2


# =============================================================================
# _rows_needing_write — 윈도우 재업서트 중복 제거 (2026-08-16 Disk I/O 감사)
# =============================================================================


class _SelectFakeBuilder:
    """key 컬럼 조회만 지원하는 PostgREST 빌더 스텁."""

    def __init__(self, table_name: str, existing: list[dict]) -> None:
        self.table_name = table_name
        self._existing = existing
        self.selected: str | None = None
        self.gte_filter: tuple[str, str] | None = None
        self.lte_filter: tuple[str, str] | None = None
        self.eq_filters: list[tuple[str, object]] = []
        self.limit_value: int | None = None

    def select(self, columns: str):
        self.selected = columns
        return self

    def eq(self, column: str, value):
        self.eq_filters.append((column, value))
        self._existing = [r for r in self._existing if r.get(column) == value]
        return self

    def gte(self, column: str, value):
        self.gte_filter = (column, value)
        return self

    def lte(self, column: str, value):
        self.lte_filter = (column, value)
        return self

    def limit(self, n: int):
        self.limit_value = n
        self._existing = self._existing[:n]
        return self

    async def execute(self):
        return SimpleNamespace(data=self._existing)


def _mark_row(open_time: str, close: float = 100.0) -> dict:
    return {
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "price_type": "mark_price",
        "open_time": open_time,
        "close": close,
        "fetched_at": "2026-08-16T05:00:00Z",
    }


_MARK_KEY = ("exchange", "symbol", "interval", "price_type", "open_time")


def _run_filter(monkeypatch, rows, existing, *, hot_tail=3):
    class FakeDb:
        def table(self, table_name: str):
            return _SelectFakeBuilder(table_name, existing)

    monkeypatch.setattr(data_lake.positions, "db", FakeDb)
    return asyncio.run(
        data_lake._rows_needing_write(
            "arena_mark_price_bars",
            rows,
            key_columns=_MARK_KEY,
            time_column="open_time",
            hot_tail=hot_tail,
        )
    )


def test_rows_needing_write_skips_stored_closed_bars(monkeypatch) -> None:
    """이미 저장된 과거 봉은 건너뛰고, 최신 hot_tail개만 다시 쓴다."""
    rows = [_mark_row(f"2026-08-1{d}T00:00:00Z") for d in range(0, 6)]
    # DB에 전부 이미 있는 상태(PostgREST는 +00:00 표기로 돌려준다 — 파싱 비교 검증)
    existing = [{**_mark_row(f"2026-08-1{d}T00:00:00+00:00")} for d in range(0, 6)]

    kept = _run_filter(monkeypatch, rows, existing)

    # 최신 3봉(13,14,15일)만 남는다
    assert [r["open_time"] for r in kept] == [
        "2026-08-13T00:00:00Z",
        "2026-08-14T00:00:00Z",
        "2026-08-15T00:00:00Z",
    ]


def test_rows_needing_write_keeps_new_and_gap_rows(monkeypatch) -> None:
    """DB에 키가 없는 행은 과거 봉이라도 반드시 쓴다(구멍 메우기)."""
    rows = [_mark_row(f"2026-08-1{d}T00:00:00Z") for d in range(0, 6)]
    # 11일이 DB에 없다(과거 구멍)
    existing = [_mark_row(f"2026-08-1{d}T00:00:00+00:00") for d in (0, 2, 3, 4, 5)]

    kept = _run_filter(monkeypatch, rows, existing)

    assert "2026-08-11T00:00:00Z" in [r["open_time"] for r in kept]
    assert "2026-08-10T00:00:00Z" not in [r["open_time"] for r in kept]


def test_rows_needing_write_distinguishes_price_type(monkeypatch) -> None:
    """같은 테이블·같은 시각이라도 price_type이 다르면 별개 키다."""
    rows = [{**_mark_row("2026-08-10T00:00:00Z"), "price_type": "premium_index"}]
    existing = [_mark_row("2026-08-10T00:00:00+00:00")]  # mark_price만 저장돼 있음

    kept = _run_filter(monkeypatch, rows, existing, hot_tail=0)

    assert len(kept) == 1  # premium_index는 신규 키라 남아야 한다


def test_rows_needing_write_falls_back_to_all_rows_on_query_failure(monkeypatch) -> None:
    """조회 실패 시 전량 업서트(기존 동작)로 안전하게 되돌아간다."""

    class BrokenDb:
        def table(self, table_name: str):
            raise RuntimeError("postgrest down")

    monkeypatch.setattr(data_lake.positions, "db", BrokenDb)
    rows = [_mark_row(f"2026-08-1{d}T00:00:00Z") for d in range(0, 6)]

    kept = asyncio.run(
        data_lake._rows_needing_write(
            "arena_mark_price_bars",
            rows,
            key_columns=_MARK_KEY,
            time_column="open_time",
        )
    )

    assert kept == rows


def test_rows_needing_write_disabled_by_negative_hot_tail(monkeypatch) -> None:
    """롤백 스위치: hot_tail이 음수면 필터를 아예 타지 않는다."""
    rows = [_mark_row("2026-08-10T00:00:00Z")]
    existing = [_mark_row("2026-08-10T00:00:00+00:00")]

    assert _run_filter(monkeypatch, rows, existing, hot_tail=-1) == rows


def test_rows_needing_write_hot_tail_zero_writes_only_missing_keys(monkeypatch) -> None:
    """hot_tail=0이면 꼬리 재기록 없이 DB에 없는 키만 남긴다."""
    rows = [_mark_row(f"2026-08-1{d}T00:00:00Z") for d in range(0, 4)]
    existing = [_mark_row(f"2026-08-1{d}T00:00:00+00:00") for d in (0, 1, 2)]

    kept = _run_filter(monkeypatch, rows, existing, hot_tail=0)

    assert [r["open_time"] for r in kept] == ["2026-08-13T00:00:00Z"]


def test_rows_needing_write_scopes_query_to_single_valued_key_columns(monkeypatch) -> None:
    """한 테이블에 여러 심볼·price_type이 섞여 있어도 배치 대상만 조회해야 한다.

    2026-08-16 배포 직후 실측 회귀: arena_mark_price_bars는 3심볼×2price_type이 한 테이블에
    살아서 시각 범위만으로 조회하면 배치의 6배가 딸려오고 limit에 잘려 기존 키를 놓쳤다
    (사이클당 업데이트가 36건이 아니라 1,633건으로 안 줄어듦).
    """
    captured: list[_SelectFakeBuilder] = []
    rows = [_mark_row(f"2026-08-1{d}T00:00:00Z") for d in range(0, 4)]
    # DB엔 우리 배치(BTCUSDT/mark_price) 외에 다른 심볼·price_type 행도 잔뜩 있다.
    existing = [_mark_row(f"2026-08-1{d}T00:00:00+00:00") for d in range(0, 4)]
    for d in range(0, 4):
        existing.append({**_mark_row(f"2026-08-1{d}T00:00:00+00:00"), "symbol": "ETHUSDT"})
        existing.append(
            {**_mark_row(f"2026-08-1{d}T00:00:00+00:00"), "price_type": "premium_index"}
        )

    class FakeDb:
        def table(self, table_name: str):
            builder = _SelectFakeBuilder(table_name, list(existing))
            captured.append(builder)
            return builder

    monkeypatch.setattr(data_lake.positions, "db", FakeDb)
    kept = asyncio.run(
        data_lake._rows_needing_write(
            "arena_mark_price_bars",
            rows,
            key_columns=_MARK_KEY,
            time_column="open_time",
            hot_tail=1,
        )
    )

    # 배치에서 값이 하나뿐인 키 컬럼은 전부 eq 필터로 내려가야 한다.
    assert dict(captured[0].eq_filters) == {
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "price_type": "mark_price",
    }
    # 조회가 정확히 스코프됐으므로 최신 1봉만 남는다(전량 재기록 아님).
    assert [r["open_time"] for r in kept] == ["2026-08-13T00:00:00Z"]


def test_rows_needing_write_falls_back_when_existing_key_fetch_truncated(monkeypatch) -> None:
    """조회가 limit에 잘리면 기존 키를 신뢰할 수 없으므로 전량 업서트로 폴백한다."""
    rows = [_mark_row(f"2026-08-{d:02d}T00:00:00Z") for d in range(1, 6)]
    # limit(= len(rows)*4+100 = 120)만큼 꽉 채워 돌려준다 → 잘렸다고 판단해야 함
    existing = [_mark_row("2026-08-01T00:00:00+00:00") for _ in range(200)]

    kept = _run_filter(monkeypatch, rows, existing)

    assert kept == rows
