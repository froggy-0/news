from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arena import execution_rules


def test_risk_targeted_weight_fixes_loss_per_trade() -> None:
    # 손절거리 3% → 1.5% 예산 / 3% = 0.5 비중. 손절 시 손실 ≈ 0.5 × 3% = 1.5%.
    w = execution_rules.risk_targeted_weight(
        100.0, 97.0, risk_budget_pct=0.015, weight_min=0.25, weight_max=0.7
    )
    assert w == pytest.approx(0.5)
    # 좁은 손절(1.5%) → 1.0 요구되지만 상한 0.7로 클램핑.
    tight = execution_rules.risk_targeted_weight(
        100.0, 98.5, risk_budget_pct=0.015, weight_min=0.25, weight_max=0.7
    )
    assert tight == pytest.approx(0.7)
    # 넓은 손절(8%) → 0.1875 요구되지만 하한 0.25로 클램핑.
    wide = execution_rules.risk_targeted_weight(
        100.0, 92.0, risk_budget_pct=0.015, weight_min=0.25, weight_max=0.7
    )
    assert wide == pytest.approx(0.25)


def test_combined_position_weight_takes_more_conservative_lever() -> None:
    # 저변동(realized 0.01): 변동성타깃 = clamp(0.02/0.01)=상한 0.7, 리스크타깃(3% 손절)=0.5
    #   → min = 0.5 (리스크타깃 바인딩, 올인 방지).
    low_vol = execution_rules.combined_position_weight(
        0.01,
        100.0,
        97.0,
        target_vol=0.02,
        risk_budget_pct=0.015,
        weight_min=0.25,
        weight_max=0.7,
    )
    assert low_vol == pytest.approx(0.5)
    # 고변동(realized 0.08): 변동성타깃 = 0.02/0.08=0.25, 리스크타깃=0.5 → min = 0.25.
    high_vol = execution_rules.combined_position_weight(
        0.08,
        100.0,
        97.0,
        target_vol=0.02,
        risk_budget_pct=0.015,
        weight_min=0.25,
        weight_max=0.7,
    )
    assert high_vol == pytest.approx(0.25)


def test_time_stop_triggered_after_max_hold() -> None:
    open_t = datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc)
    assert not execution_rules.time_stop_triggered(
        open_t, datetime(2026, 6, 26, 23, 0, tzinfo=timezone.utc), 48.0
    )
    assert execution_rules.time_stop_triggered(
        open_t, datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc), 48.0
    )
    # max_hold_hours<=0 → 비활성.
    assert not execution_rules.time_stop_triggered(
        open_t, datetime(2026, 7, 1, tzinfo=timezone.utc), 0.0
    )


def test_pending_price_tranches_returns_newly_eligible_unfilled() -> None:
    tranches = ((0.00, 0.15), (-0.03, 0.25), (-0.06, 0.30))
    ref = 100.0
    # 1단계 체결 상태(filled=1), 가격 96.5 → -3% 트랜치만 충족(96.5≤97, 96.5>94).
    assert execution_rules.pending_price_tranches(96.5, ref, 1, tranches) == [(1, 0.25)]
    # 가격 88 → -3%·-6% 두 단계 한 번에(갭다운).
    assert execution_rules.pending_price_tranches(88.0, ref, 1, tranches) == [(1, 0.25), (2, 0.30)]
    # 모두 체결(filled=3) → 없음.
    assert execution_rules.pending_price_tranches(50.0, ref, 3, tranches) == []
    # ref 미상정 → 없음(graceful).
    assert execution_rules.pending_price_tranches(50.0, 0.0, 1, tranches) == []


def test_fill_price_tranches_fills_at_limit_prices_and_caps_weight() -> None:
    tranches = ((0.00, 0.15), (-0.03, 0.25), (-0.06, 0.30))
    ref = 100.0
    pending = [(1, 0.25), (2, 0.30)]
    # 한계가 체결: -3%→97, -6%→94. 누적 0.15+0.25+0.30=0.70(상한).
    new_avg, new_weight, applied = execution_rules.fill_price_tranches(
        100.0, 0.15, ref, pending, tranches, weight_cap=0.70
    )
    assert applied == 2
    assert new_weight == pytest.approx(0.70)
    # avg = (100*0.15 + 97*0.25 + 94*0.30)/0.70
    assert new_avg == pytest.approx((15 + 24.25 + 28.2) / 0.70, abs=1e-4)
    # 상한에 막히면 마지막 트랜치는 cap까지 부분 체결 — cap 0.50이면 -3% 전량(0.25)
    # 후 -6%는 잔여 0.10만 들어가 누적 정확히 0.50.
    _, capped_weight, capped_applied = execution_rules.fill_price_tranches(
        100.0, 0.15, ref, pending, tranches, weight_cap=0.50
    )
    assert capped_applied == 2
    assert capped_weight == pytest.approx(0.50)


# ── 피라미딩(승자 불타기) — pending_price_tranches/fill_price_tranches의 방향
# 일반화판. 물타기(위)는 롱·불리한 방향(하락) 전용이지만, 피라미딩은 롱=유리한
# 방향(상승)/숏=유리한 방향(하락) 양쪽을 다뤄야 해 direction 매개변수를 받는다.


def test_pending_pyramid_tranches_long_direction_checks_upside() -> None:
    tranches = ((0.03, 0.15), (0.06, 0.15))
    ref = 100.0
    # 102 → +3% 레벨(103) 미달, 아직 없음.
    assert execution_rules.pending_pyramid_tranches(102.0, ref, "long", 0, tranches) == []
    # 104 → +3% 레벨만 충족(+6%=106은 미달).
    assert execution_rules.pending_pyramid_tranches(104.0, ref, "long", 0, tranches) == [(0, 0.15)]
    # 108 → 두 레벨 모두(갭업).
    assert execution_rules.pending_pyramid_tranches(108.0, ref, "long", 0, tranches) == [
        (0, 0.15),
        (1, 0.15),
    ]
    # 이미 0번 체결(filled=1) → 1번만 재평가.
    assert execution_rules.pending_pyramid_tranches(108.0, ref, "long", 1, tranches) == [(1, 0.15)]


def test_pending_pyramid_tranches_short_direction_checks_downside() -> None:
    tranches = ((0.03, 0.15), (0.06, 0.15))
    ref = 100.0
    # 숏은 하락이 유리한 방향 — 97 이하에서 +3% 레벨(=97) 충족.
    assert execution_rules.pending_pyramid_tranches(97.0, ref, "short", 0, tranches) == [(0, 0.15)]
    assert execution_rules.pending_pyramid_tranches(99.0, ref, "short", 0, tranches) == []


def test_pending_pyramid_tranches_graceful_on_missing_ref() -> None:
    tranches = ((0.03, 0.15),)
    assert execution_rules.pending_pyramid_tranches(100.0, 0.0, "long", 0, tranches) == []


def test_fill_pyramid_tranches_long_fills_above_ref_and_caps_weight() -> None:
    tranches = ((0.03, 0.15), (0.06, 0.15))
    ref = 100.0
    pending = [(0, 0.15), (1, 0.15)]
    new_avg, new_weight, applied = execution_rules.fill_pyramid_tranches(
        100.0, 0.40, ref, "long", pending, tranches, weight_cap=0.70
    )
    assert applied == 2
    assert new_weight == pytest.approx(0.70)
    # avg = (100*0.40 + 103*0.15 + 106*0.15)/0.70
    assert new_avg == pytest.approx((40 + 15.45 + 15.9) / 0.70, abs=1e-4)


def test_fill_pyramid_tranches_short_fills_below_ref() -> None:
    tranches = ((0.03, 0.15),)
    ref = 100.0
    new_avg, new_weight, applied = execution_rules.fill_pyramid_tranches(
        100.0, 0.40, ref, "short", [(0, 0.15)], tranches, weight_cap=0.70
    )
    assert applied == 1
    assert new_weight == pytest.approx(0.55)
    # 숏 체결가 = ref*(1-0.03) = 97
    assert new_avg == pytest.approx((100 * 0.40 + 97 * 0.15) / 0.55, abs=1e-4)


def test_fill_pyramid_tranches_partial_fill_at_weight_cap() -> None:
    tranches = ((0.03, 0.15), (0.06, 0.30))
    ref = 100.0
    # 0.40+0.15(0번 전량)=0.55로 정확히 상한 도달 — 1번은 잔여 0이라 미체결(applied=1).
    _, capped_weight, capped_applied = execution_rules.fill_pyramid_tranches(
        100.0, 0.40, ref, "long", [(0, 0.15), (1, 0.30)], tranches, weight_cap=0.55
    )
    assert capped_applied == 1
    assert capped_weight == pytest.approx(0.55)
    # 상한 0.70이면 0번 전량 + 1번 중 잔여 0.15만 부분 체결.
    _, capped_weight2, capped_applied2 = execution_rules.fill_pyramid_tranches(
        100.0, 0.40, ref, "long", [(0, 0.15), (1, 0.30)], tranches, weight_cap=0.70
    )
    assert capped_applied2 == 2
    assert capped_weight2 == pytest.approx(0.70)


def test_averaged_entry_price_is_weight_weighted() -> None:
    # 0.15@100 + 0.25@90 → (15+22.5)/0.4 = 93.75
    assert execution_rules.averaged_entry_price(100.0, 0.15, 90.0, 0.25) == pytest.approx(93.75)
    assert execution_rules.averaged_entry_price(100.0, 0.0, 90.0, 0.0) == 100.0


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


def test_trail_distance_from_stop_mult_scales_distance_default_unchanged() -> None:
    # mult 기본값 1.0 = 기존 동작과 완전히 동일(하위호환).
    assert execution_rules.trail_distance_from_stop(100.0, 97.0, mult=1.0) == pytest.approx(3.0)
    # mult<1.0이면 손절폭은 그대로 두고 트레일링 거리만 좁힘 (2026-08-10, vix_rsi/multi_factor
    # 실험용 TRAIL_DISTANCE_MULT_BY_ALGO 배선).
    assert execution_rules.trail_distance_from_stop(100.0, 97.0, mult=0.5) == pytest.approx(1.5)


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
