from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arena import execution_rules


def test_calc_stop_loss_price_uses_atr_with_min_and_max_clamps() -> None:
    assert (
        execution_rules.calc_stop_loss_price(
            "long",
            100.0,
            1.0,
            atr_multiple=2.5,
            stop_loss_min_pct=0.02,
            stop_loss_max_pct=0.08,
        )
        == 97.5
    )
    assert execution_rules.calc_stop_loss_price(
        "short",
        100.0,
        1.0,
        atr_multiple=2.5,
        stop_loss_min_pct=0.02,
        stop_loss_max_pct=0.08,
    ) == pytest.approx(102.5)
    assert (
        execution_rules.calc_stop_loss_price(
            "long",
            100.0,
            10.0,
            atr_multiple=2.5,
            stop_loss_min_pct=0.02,
            stop_loss_max_pct=0.08,
        )
        == 92.0
    )


def test_stop_loss_triggered_prefers_persisted_price_and_fallback_pct() -> None:
    assert execution_rules.stop_loss_triggered(
        direction="long",
        open_price=100.0,
        current_price=97.0,
        stop_loss_price=97.5,
        fallback_stop_loss_pct=0.05,
    )
    assert execution_rules.stop_loss_triggered(
        direction="short",
        open_price=100.0,
        current_price=103.0,
        stop_loss_price=102.5,
        fallback_stop_loss_pct=0.05,
    )
    assert execution_rules.stop_loss_triggered(
        direction="long",
        open_price=100.0,
        current_price=94.9,
        stop_loss_price=None,
        fallback_stop_loss_pct=0.05,
    )
    assert execution_rules.stop_loss_triggered(
        direction="short",
        open_price=100.0,
        current_price=105.1,
        stop_loss_price=None,
        fallback_stop_loss_pct=0.05,
    )


def test_trail_distance_from_stop_is_absolute_atr_distance() -> None:
    # 진입가 100, 초기 손절 97 (long) → 거리 3.0
    assert execution_rules.trail_distance_from_stop(100.0, 97.0) == pytest.approx(3.0)
    # short: 진입가 100, 초기 손절 103 → 거리 3.0
    assert execution_rules.trail_distance_from_stop(100.0, 103.0) == pytest.approx(3.0)


def test_ratchet_trailing_stop_is_monotonic_in_profit_direction() -> None:
    # long: 가격 상승 → 손절가 끌어올림(price − distance), 하락해도 안 내려감
    stop = 97.0  # 진입 100, 거리 3
    stop = execution_rules.ratchet_trailing_stop(
        direction="long", current_price=110.0, current_stop=stop, trail_distance=3.0
    )
    assert stop == pytest.approx(107.0)  # 110 − 3, 이익 고정
    # 가격이 다시 105로 내려도 손절가는 단조(안 내려감)
    stop2 = execution_rules.ratchet_trailing_stop(
        direction="long", current_price=105.0, current_stop=stop, trail_distance=3.0
    )
    assert stop2 == pytest.approx(107.0)
    # short: 가격 하락 → 손절가 끌어내림
    s = execution_rules.ratchet_trailing_stop(
        direction="short", current_price=90.0, current_stop=103.0, trail_distance=3.0
    )
    assert s == pytest.approx(93.0)


def test_ratchet_no_op_at_entry_and_with_zero_distance() -> None:
    # 진입 시점: price=open=100, stop=97, distance=3 → max(97, 100−3)=97 변화 없음
    assert (
        execution_rules.ratchet_trailing_stop(
            direction="long", current_price=100.0, current_stop=97.0, trail_distance=3.0
        )
        == 97.0
    )
    # 거리 0/음수면 그대로 반환 (legacy 행 graceful)
    assert (
        execution_rules.ratchet_trailing_stop(
            direction="long", current_price=200.0, current_stop=97.0, trail_distance=0.0
        )
        == 97.0
    )


def test_is_trailing_exit_distinguishes_ratcheted_from_initial_stop() -> None:
    # long 진입 100, 거리 3 → 초기 손절 97. 손절가가 97이면 트레일링 아님
    assert not execution_rules.is_trailing_exit(
        direction="long", open_price=100.0, stop_loss_price=97.0, trail_distance=3.0
    )
    # 손절가가 105로 래칫됐으면(이익 고정) 트레일링 청산
    assert execution_rules.is_trailing_exit(
        direction="long", open_price=100.0, stop_loss_price=105.0, trail_distance=3.0
    )
    # short 진입 100, 거리 3 → 초기 103. 손절가 95면 트레일링
    assert execution_rules.is_trailing_exit(
        direction="short", open_price=100.0, stop_loss_price=95.0, trail_distance=3.0
    )


def test_fee_adjusted_return_pct_matches_live_round_trip_costs() -> None:
    assert execution_rules.fee_adjusted_return_pct(
        direction="long",
        open_price=100.0,
        close_price=110.0,
        fee_bps=5.0,
    ) == pytest.approx(0.099)
    assert execution_rules.fee_adjusted_return_pct(
        direction="short",
        open_price=100.0,
        close_price=90.0,
        fee_bps=5.0,
    ) == pytest.approx(0.099)
    assert execution_rules.fee_adjusted_return_pct(
        direction="long",
        open_price=100.0,
        close_price=110.0,
        fee_bps=5.0,
        slippage_bps=2.0,
    ) == pytest.approx(0.0986)


def test_min_hold_ok_uses_algo_threshold_and_fails_open_on_bad_legacy_rows() -> None:
    now = datetime(2026, 6, 19, 4, 0, tzinfo=timezone.utc)
    min_hold_hours = {"macd_momentum": 4.0}

    assert execution_rules.min_hold_ok(
        {"open_time": "2026-06-19T00:00:00Z"},
        now,
        "macd_momentum",
        min_hold_hours,
        12.0,
    )
    assert not execution_rules.min_hold_ok(
        {"open_time": "2026-06-19T00:01:00Z"},
        now,
        "macd_momentum",
        min_hold_hours,
        12.0,
    )
    assert execution_rules.min_hold_ok({}, now, "macd_momentum", min_hold_hours, 12.0)


def test_build_params_snapshot_is_replayable_and_does_not_mutate_base() -> None:
    base = {
        "params_version": "params-v1",
        "indicators": {"rsi_period": 14},
    }

    snapshot = execution_rules.build_params_snapshot(
        base_snapshot=base,
        algo_id="macd_momentum",
        stop_loss_fallback_pct=0.05,
        fee_bps=5.0,
        atr_multiple=2.5,
        stop_loss_min_pct=0.02,
        stop_loss_max_pct=0.08,
        macro_stale_hours=48.0,
        slippage_bps=1.0,
    )

    assert snapshot["algo_id"] == "macd_momentum"
    assert snapshot["risk"] == {
        "stop_loss_fallback_pct": 0.05,
        "fee_bps": 5.0,
        "slippage_bps": 1.0,
        "atr_multiple": 2.5,
        "stop_loss_min_pct": 0.02,
        "stop_loss_max_pct": 0.08,
        "macro_stale_hours": 48.0,
    }
    assert "risk" not in base
    json.dumps(snapshot)


def test_build_market_snapshot_and_signal_reason_are_json_safe() -> None:
    market = execution_rules.build_market_snapshot(
        symbol="BTCUSDT",
        interval="4h",
        klines_limit=150,
        price=100.0,
        high=101.0,
        low=99.0,
        closes_count=150,
        data_timestamp=datetime(2026, 6, 19, 0, 0, tzinfo=timezone.utc),
    )
    reason = execution_rules.build_signal_reason(
        algo_id="multi_factor",
        signal="short",
        indicators={"rsi": 56.0, "macd_hist": -0.1, "bb_pos": 0.7, "atr": 1200.0},
        macro={"regime_state": "BearPanic", "fng": 20, "vix_now": 35.0, "vix_q40": 25.0},
    )

    assert market["data_timestamp"] == "2026-06-19T00:00:00Z"
    assert market["close"] == 100.0
    assert reason["algo_id"] == "multi_factor"
    assert reason["signal"] == "short"
    assert reason["inputs"]["regime_state"] == "BearPanic"
    assert reason["inputs"]["fng"] == 20
    assert reason["inputs"]["vix_now"] == 35.0
    assert reason["inputs"]["vix_q40"] == 25.0
    assert reason["inputs"]["rsi"] == 56.0
    assert reason["inputs"]["macd_hist"] == -0.1
    assert reason["inputs"]["bb_pos"] == 0.7
    assert reason["inputs"]["atr"] == 1200.0
    assert "funding_zscore" in reason["inputs"]
    assert "donchian_upper" in reason["inputs"]
    json.dumps({"market": market, "reason": reason})
