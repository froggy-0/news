"""ETH/SOL 펀딩비 등 롤링 z스코어 계산기 검증.

설계: docs/arena/research/eth-sol-futures-baseline-design-20260731.md
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from arena import futures_baseline


def test_rolling_zscore_last_insufficient_data_returns_none() -> None:
    assert futures_baseline.rolling_zscore_last([1.0, 2.0], min_periods=15) is None


def test_rolling_zscore_last_zero_stdev_returns_none() -> None:
    values = [1.0] * 20
    assert futures_baseline.rolling_zscore_last(values, window=30, min_periods=15) is None


def test_rolling_zscore_last_computes_expected_value() -> None:
    # 마지막 window개(<=window) 관측치의 표본표준편차(ddof=1) 기준.
    values = [1.0, 2.0, 3.0, 4.0, 5.0] * 4  # 20개, min_periods=15 충족
    result = futures_baseline.rolling_zscore_last(values, window=30, min_periods=15)
    assert result is not None
    # 수동 계산과 일치하는지 확인
    import statistics

    tail = values[-30:] if len(values) > 30 else values
    mean = statistics.fmean(tail)
    stdev = statistics.stdev(tail)
    expected = (tail[-1] - mean) / stdev
    assert abs(result - expected) < 1e-9


def test_rolling_zscore_last_uses_only_trailing_window() -> None:
    # window=5 → 마지막 5개만 사용, 그 이전 값은 무시돼야 함.
    values = [100.0] * 50 + [1.0, 2.0, 3.0, 4.0, 5.0]
    result = futures_baseline.rolling_zscore_last(values, window=5, min_periods=5)
    assert result is not None
    import statistics

    tail = values[-5:]
    mean = statistics.fmean(tail)
    stdev = statistics.stdev(tail)
    expected = (tail[-1] - mean) / stdev
    assert abs(result - expected) < 1e-9


def _mock_table_response(rows: list[dict]) -> MagicMock:
    """Supabase 체이닝 쿼리(.table().select().eq()...).execute())를 흉내내는 mock."""
    response = MagicMock()
    response.data = rows
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute = AsyncMock(return_value=response)
    return query


def test_compute_funding_zscore_reads_symbol_scoped_history(
    monkeypatch,
) -> None:
    rows = [{"funding_time": f"t{i}", "funding_rate": 0.0001 * i} for i in range(20)]
    query = _mock_table_response(rows)
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr(futures_baseline.positions, "db", lambda: db)

    result = asyncio.run(futures_baseline.compute_funding_zscore("ETHUSDT"))

    db.table.assert_called_with("arena_funding_rates")
    query.eq.assert_any_call("symbol", "ETHUSDT")
    query.eq.assert_any_call("exchange", "binance")
    assert result is not None


def test_compute_funding_zscore_graceful_on_db_error(monkeypatch) -> None:
    db = MagicMock()

    def _raise(*args, **kwargs):
        raise RuntimeError("db down")

    db.table.side_effect = _raise
    monkeypatch.setattr(futures_baseline.positions, "db", lambda: db)

    result = asyncio.run(futures_baseline.compute_funding_zscore("SOLUSDT"))
    assert result is None


def test_compute_lsr_zscore_extracts_top_position_ratio_from_features(
    monkeypatch,
) -> None:
    rows = [
        {"data_timestamp": f"t{i}", "features": {"top_position_ls_ratio": 1.0 + i * 0.01}}
        for i in range(20)
    ]
    query = _mock_table_response(rows)
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr(futures_baseline.positions, "db", lambda: db)

    result = asyncio.run(futures_baseline.compute_lsr_zscore("SOLUSDT"))

    db.table.assert_called_with("arena_market_feature_snapshots")
    assert result is not None


def test_compute_lsr_zscore_skips_missing_feature_rows(monkeypatch) -> None:
    rows = [{"data_timestamp": "t0", "features": {}}] * 20
    query = _mock_table_response(rows)
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr(futures_baseline.positions, "db", lambda: db)

    result = asyncio.run(futures_baseline.compute_lsr_zscore("SOLUSDT"))
    assert result is None
