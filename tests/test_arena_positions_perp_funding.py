from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from arena import data_lake, positions


class _FakeQuery:
    """paper_positions에 대한 select(single)/update 체인을 흉내내는 최소 스텁."""

    def __init__(self, row: dict) -> None:
        self._row = dict(row)
        self._mode: str | None = None
        self._update_payload: dict | None = None

    def select(self, *_args, **_kwargs) -> "_FakeQuery":
        self._mode = "select"
        return self

    def update(self, payload: dict) -> "_FakeQuery":
        self._mode = "update"
        self._update_payload = payload
        return self

    def eq(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def single(self) -> "_FakeQuery":
        return self

    async def execute(self):
        if self._mode == "update":
            self._row.update(self._update_payload or {})
            return SimpleNamespace(data=[dict(self._row)])
        return SimpleNamespace(data=dict(self._row))


class _FakeDb:
    def __init__(self, row: dict) -> None:
        self._row = row

    def table(self, name: str) -> _FakeQuery:
        assert name == "paper_positions"
        return _FakeQuery(self._row)


def _base_row(**overrides) -> dict:
    row = {
        "id": 1,
        "algo_id": "macd_momentum",
        "status": "open",
        "direction": "long",
        "open_price": 100.0,
        "open_time": "2026-08-15T00:00:00Z",
        "fee_bps": 10.0,
        "slippage_bps": 1.0,
        "spread_bps_round_trip": 1.0,
        "symbol": "BTCUSDT",
    }
    row.update(overrides)
    return row


def test_close_position_spot_has_no_funding_term(monkeypatch) -> None:
    row = _base_row(product_type="spot")
    monkeypatch.setattr(positions, "_client", _FakeDb(row))

    called = False

    async def fail_if_called(**_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(data_lake, "fetch_funding_rates", fail_if_called)

    ret_pct = asyncio.run(
        positions.close_position(1, datetime(2026, 8, 15, 12, tzinfo=timezone.utc), 101.0)
    )

    assert called is False
    # gross 1% − 왕복비용 23bps, 펀딩 없음.
    assert ret_pct == pytest.approx(0.01 - 0.0023, abs=1e-9)


def test_close_position_perp_long_accrues_funding_cost(monkeypatch) -> None:
    row = _base_row(product_type="usdm_perp", direction="long")
    monkeypatch.setattr(positions, "_client", _FakeDb(row))

    async def fake_fetch(*, symbol, since, until):
        assert symbol == "BTCUSDT"
        return [{"funding_time": "2026-08-15T08:00:00Z", "funding_rate": 0.0004}]

    monkeypatch.setattr(data_lake, "fetch_funding_rates", fake_fetch)

    ret_pct = asyncio.run(
        positions.close_position(1, datetime(2026, 8, 15, 12, tzinfo=timezone.utc), 101.0)
    )

    # 롱은 양의 펀딩비를 지불 → 손익에서 차감.
    assert ret_pct == pytest.approx(0.01 - 0.0023 - 0.0004, abs=1e-9)


def test_close_position_perp_short_receives_funding(monkeypatch) -> None:
    row = _base_row(product_type="usdm_perp", direction="short", open_price=100.0)
    monkeypatch.setattr(positions, "_client", _FakeDb(row))

    async def fake_fetch(*, symbol, since, until):
        return [{"funding_time": "2026-08-15T08:00:00Z", "funding_rate": 0.0004}]

    monkeypatch.setattr(data_lake, "fetch_funding_rates", fake_fetch)

    ret_pct = asyncio.run(
        positions.close_position(1, datetime(2026, 8, 15, 12, tzinfo=timezone.utc), 99.0)
    )

    # 숏은 가격하락 1%가 이익, 양의 펀딩비를 수취 → 손익에 가산.
    assert ret_pct == pytest.approx(0.01 - 0.0023 + 0.0004, abs=1e-9)


def test_close_position_perp_track_resolves_real_ticker_for_funding(monkeypatch) -> None:
    # spot→perp Phase A2(2026-08-15): 트랙 심볼이 "BTCUSDT-PERP"일 때도
    # arena_funding_rates 조회는 실제 티커("BTCUSDT")로 나가야 한다 — 안 그러면 항상
    # 0건 조회돼 펀딩이 조용히 0 취급되는 회귀.
    row = _base_row(product_type="usdm_perp", direction="long", symbol="BTCUSDT-PERP")
    monkeypatch.setattr(positions, "_client", _FakeDb(row))

    seen_symbol = {}

    async def fake_fetch(*, symbol, since, until):
        seen_symbol["value"] = symbol
        return [{"funding_time": "2026-08-15T08:00:00Z", "funding_rate": 0.0004}]

    monkeypatch.setattr(data_lake, "fetch_funding_rates", fake_fetch)

    ret_pct = asyncio.run(
        positions.close_position(1, datetime(2026, 8, 15, 12, tzinfo=timezone.utc), 101.0)
    )

    assert seen_symbol["value"] == "BTCUSDT"
    assert ret_pct == pytest.approx(0.01 - 0.0023 - 0.0004, abs=1e-9)


def test_close_position_perp_funding_fetch_failure_is_graceful(monkeypatch, caplog) -> None:
    row = _base_row(product_type="usdm_perp", direction="long")
    monkeypatch.setattr(positions, "_client", _FakeDb(row))

    async def broken_fetch(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(data_lake, "fetch_funding_rates", broken_fetch)

    ret_pct = asyncio.run(
        positions.close_position(1, datetime(2026, 8, 15, 12, tzinfo=timezone.utc), 101.0)
    )

    # 펀딩 조회 실패 시 펀딩 0 취급(청산 자체는 계속 진행) — 트레이딩 경로 무영향 원칙.
    assert ret_pct == pytest.approx(0.01 - 0.0023, abs=1e-9)
