"""멀티자산 확장 P1-4 — 경량 shadow 사이클(_run_asset_shadow_cycle) 검증.

계획: docs/arena/research/multi-asset-implementation-plan-20260731.md
설계: docs/arena/research/structural-priority-multi-asset-expansion-20260730.md §3.1/§3.3
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from arena import algorithms, data_lake, scheduler


def _fake_ohlcv() -> scheduler.OHLCV:
    # sideways 레짐을 유도하는 지표(atr_pct=0.02, bb_width=1.0<=3.5, |return_24h|<=atr_pct):
    # BTC 공유 macro의 arena_regime_state("bull_trend")와 달라야 로컬 재계산 검증 가능.
    closes = [100.0] * 40
    highs = [100.5] * 40
    lows = [99.5] * 40
    volumes = [10.0] * 40
    return scheduler.OHLCV(
        highs=highs,
        lows=lows,
        closes=closes,
        last_close_time=datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
        raw_klines=[],
        volumes=volumes,
    )


def test_asset_shadow_cycle_records_all_six_algos_without_touching_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_ohlcv = _fake_ohlcv()
    fake_macro = scheduler.MacroData(
        {
            # BTC 전용 R2 파이프라인 값 — 공유 유지 확인용(설계문서 §3.1).
            "arena_regime_state": "bull_trend",
            "regime_state": "BullQuiet",
            "etf_flow_zscore": -2.0,
            "funding_zscore": 0.5,
            "fng": 42.0,
        },
        {},
        datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
        "https://example.invalid/latest.json",
    )

    async def _mock_fetch_ohlcv(*, symbol: str, interval: str, limit: int) -> scheduler.OHLCV:
        assert symbol == "ETHUSDT"
        return fake_ohlcv

    async def _mock_fetch_macro() -> scheduler.MacroData:
        return fake_macro

    monkeypatch.setattr(scheduler, "_fetch_ohlcv", _mock_fetch_ohlcv)
    monkeypatch.setattr(scheduler, "_fetch_macro", _mock_fetch_macro)
    monkeypatch.setattr(data_lake, "new_run_id", lambda: "test-run-id")

    record_run_started = AsyncMock(
        return_value=data_lake.CaptureWriteResult(label="arena_runs.start", ok=True)
    )
    record_run_completed = AsyncMock(
        return_value=data_lake.CaptureWriteResult(label="arena_runs.complete", ok=True)
    )
    record_shadow_decision = AsyncMock(
        return_value=data_lake.CaptureWriteResult(label="arena_shadow_decisions.upsert", ok=True)
    )
    monkeypatch.setattr(scheduler.data_lake, "record_run_started", record_run_started)
    monkeypatch.setattr(scheduler.data_lake, "record_run_completed", record_run_completed)
    monkeypatch.setattr(scheduler.data_lake, "record_shadow_decision", record_shadow_decision)

    # paper_positions에 절대 접촉하지 않아야 함 — 호출되면 즉시 실패시켜 검증.
    def _forbidden(*args, **kwargs):  # pragma: no cover - 호출되면 안 됨
        raise AssertionError("multi-asset shadow cycle must not touch paper_positions")

    monkeypatch.setattr(scheduler.positions, "open_position", _forbidden, raising=False)
    monkeypatch.setattr(scheduler.positions, "close_position", _forbidden, raising=False)
    monkeypatch.setattr(scheduler.positions, "refresh_open_positions", _forbidden, raising=False)

    asyncio.run(scheduler._run_asset_shadow_cycle("ETHUSDT"))

    # run_started가 ETHUSDT 심볼로 기록됐는지
    assert record_run_started.call_args.kwargs["symbol"] == "ETHUSDT"

    # 6개 알고 전부 기록됐는지 (sleeve_id로 vNext 단일-sleeve 경로와 구분됨)
    assert record_shadow_decision.call_count == len(algorithms.ALGORITHMS)
    recorded_algo_ids = {
        call.kwargs["signal"].algo_id for call in record_shadow_decision.call_args_list
    }
    assert recorded_algo_ids == set(algorithms.ALGORITHMS)
    for call in record_shadow_decision.call_args_list:
        assert call.kwargs["signal"].sleeve_id == "multi_asset_shadow"
        macro_snapshot = call.kwargs["signal"].feature_snapshot["macro"]
        # arena_regime_state는 이 자산(sideways 유도 지표) 기준으로 로컬 재계산 —
        # 공유 macro의 BTC 값("bull_trend")을 덮어썼는지가 핵심 검증 포인트.
        assert macro_snapshot["arena_regime_state"] == "sideways"
        # BTC 전용 글로벌 피처는 공유값 그대로 유지(Phase1 설계 확정 — 재계산 경로 없음).
        assert macro_snapshot["etf_flow_zscore"] == -2.0
        assert macro_snapshot["funding_zscore"] == 0.5

    assert record_run_completed.call_args.kwargs["status"] == "completed"


def test_multi_asset_shadow_skips_when_ohlcv_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    empty_ohlcv = scheduler.OHLCV(highs=[], lows=[], closes=[], last_close_time=None, raw_klines=[])
    fake_macro = scheduler.MacroData({}, {}, None, "")

    monkeypatch.setattr(scheduler, "_fetch_ohlcv", AsyncMock(return_value=empty_ohlcv))
    monkeypatch.setattr(scheduler, "_fetch_macro", AsyncMock(return_value=fake_macro))
    monkeypatch.setattr(data_lake, "new_run_id", lambda: "test-run-id-2")
    monkeypatch.setattr(
        scheduler.data_lake,
        "record_run_started",
        AsyncMock(return_value=data_lake.CaptureWriteResult(label="x", ok=True)),
    )
    record_shadow_decision = AsyncMock()
    monkeypatch.setattr(scheduler.data_lake, "record_shadow_decision", record_shadow_decision)
    record_run_completed = AsyncMock(return_value=data_lake.CaptureWriteResult(label="x", ok=True))
    monkeypatch.setattr(scheduler.data_lake, "record_run_completed", record_run_completed)

    asyncio.run(scheduler._run_asset_shadow_cycle("SOLUSDT"))

    record_shadow_decision.assert_not_called()
    assert record_run_completed.call_args.kwargs["status"] == "data_failed"
