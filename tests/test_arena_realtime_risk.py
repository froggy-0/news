from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arena import realtime_risk


def _row(
    *,
    start: datetime,
    spread: float = 1.0,
    depth: float = 2_000_000.0,
    slippage: float = 1.0,
    sell_ratio: float = 0.45,
    volume: float = 100_000.0,
    vol_5m: float = 0.001,
    price: float = 100_000.0,
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "window_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end": (start + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_seconds": 60,
        "spread_bps_avg": spread,
        "expected_slippage_bps": slippage,
        "depth_10bp_bid_usd": depth,
        "depth_10bp_ask_usd": depth,
        "last_price": price,
        "realized_volatility_5m": vol_5m,
        "trade_quote_volume": volume,
        "aggressive_sell_ratio": sell_ratio,
        "orderbook_imbalance": 0.0,
        "quality_status": "ok",
        "quality_errors": [],
    }


def test_realtime_risk_scores_block_entry_without_short_signal() -> None:
    start = datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)
    history = [_row(start=start + timedelta(minutes=i)) for i in range(20)]
    stressed = _row(
        start=start + timedelta(minutes=21),
        spread=12.0,
        depth=250_000.0,
        slippage=12.0,
        sell_ratio=0.95,
        volume=2_000_000.0,
        vol_5m=0.03,
    )

    decision = realtime_risk.evaluate_realtime_risk(
        feature_row=stressed,
        history_rows=history,
        recent_scores=[0.6],
        evaluated_at=start,
    )

    assert decision.risk_state in {
        realtime_risk.STATE_BLOCK_ENTRY,
        realtime_risk.STATE_EXIT_CANDIDATE,
        realtime_risk.STATE_FORCE_EXIT_CANDIDATE,
    }
    assert decision.risk_score is not None and decision.risk_score >= 0.55
    assert decision.recommended_action != "open_short"
    assert decision.as_dict()["spot_execution_only"] is True


def test_realtime_risk_unknown_when_core_quality_missing() -> None:
    start = datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)
    row = _row(start=start)
    row["last_price"] = None

    decision = realtime_risk.evaluate_realtime_risk(feature_row=row, history_rows=[])

    assert decision.risk_state == realtime_risk.STATE_UNKNOWN
    assert decision.risk_score is None
    assert "missing_last_price" in decision.trigger_reasons
    assert decision.recommended_action == "ignore_for_live_decision"


def test_realtime_risk_requires_sustained_score_for_exit_candidate() -> None:
    start = datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)
    history = [_row(start=start + timedelta(minutes=i)) for i in range(20)]
    stressed = _row(
        start=start + timedelta(minutes=21),
        spread=12.0,
        depth=250_000.0,
        slippage=12.0,
        sell_ratio=0.95,
        volume=2_000_000.0,
        vol_5m=0.03,
    )

    first = realtime_risk.evaluate_realtime_risk(
        feature_row=stressed,
        history_rows=history,
        recent_scores=[],
        evaluated_at=start,
    )
    second = realtime_risk.evaluate_realtime_risk(
        feature_row=stressed,
        history_rows=history,
        recent_scores=[first.risk_score or 0.0],
        evaluated_at=start,
    )

    assert first.risk_state == realtime_risk.STATE_BLOCK_ENTRY
    assert second.risk_state in {
        realtime_risk.STATE_EXIT_CANDIDATE,
        realtime_risk.STATE_FORCE_EXIT_CANDIDATE,
    }
