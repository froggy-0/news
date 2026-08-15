from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from arena import algorithms, backtest, parameters, realtime_risk


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _frame(
    index: int,
    *,
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    atr: float = 1.0,
    macro: dict | None = None,
    market_features: dict | None = None,
) -> backtest.ReplayFrame:
    open_time = _dt(0) + timedelta(hours=4 * index)
    close_time = open_time + timedelta(hours=4)
    return backtest.ReplayFrame(
        bar=backtest.ReplayBar(
            open_time=open_time,
            close_time=close_time,
            open=open_price,
            high=high,
            low=low,
            close=close,
        ),
        indicators={"rsi": 50.0, "macd_hist": 0.0, "bb_pos": 0.5, "atr": atr},
        macro=macro or {},
        market_features=market_features or {},
    )


def test_backtest_stop_loss_uses_intrabar_ohlc_and_live_cost_rule() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(close_open_at_end=False)
    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, open_price=99.0, high=100.0, low=97.0, close=98.0),
        ],
        strategy_fns={"test_algo": always_long},
        settings=settings,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.close_price == pytest.approx(97.5)
    assert trade.ret_pct == pytest.approx(-0.0273)  # arena-cost-v3: 기본 왕복비용 13bps→23bps
    assert result.equity_curve[-1].open_position["direction"] == "long"


def test_backtest_min_hold_blocks_early_reverse_then_allows_later_reverse() -> None:
    signals = iter(["long", "short", "short"])

    def scripted(macro, indicators):
        return next(signals)

    settings = backtest.BacktestSettings(
        close_open_at_end=False,
        min_hold_hours={"test_algo": 8.0},
        product_type="usdm_perp_paper",
        position_semantics="perp_long_short_sim",
    )
    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, close=101.0),
            _frame(2, close=102.0),
        ],
        strategy_fns={"test_algo": scripted},
        settings=settings,
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "signal_reverse"
    assert result.trades[0].hold_hours == pytest.approx(8.0)
    assert result.equity_curve[-1].open_position["direction"] == "short"


def test_backtest_disables_stale_macro_before_strategy_call() -> None:
    def macro_long_only(macro, indicators):
        return "long" if macro.get("regime_state") == "BullQuiet" else None

    settings = backtest.BacktestSettings(close_open_at_end=False, macro_stale_hours=36.0)
    result = backtest.run_replay(
        [
            _frame(
                0,
                macro={
                    "regime_state": "BullQuiet",
                    "reference_date": "2026-06-17",
                    "stale_hours": 1.0,
                },
            )
        ],
        strategy_fns={"macro_algo": macro_long_only},
        settings=settings,
    )

    assert result.trades == []
    assert result.equity_curve[0].open_position is None


def test_backtest_run_row_is_json_ready_and_versioned() -> None:
    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [_frame(0), _frame(1, close=101.0)],
        strategy_fns={"test_algo": always_long},
        settings=backtest.BacktestSettings(close_open_at_end=True),
        backtest_run_id="00000000-0000-0000-0000-000000000001",
    )

    row = backtest._run_row(result)

    assert row["backtest_run_id"] == "00000000-0000-0000-0000-000000000001"
    assert row["strategy_version"] == "arena-spot-v4"
    assert row["rules_snapshot"]["fee_bps"] == 10.0
    assert row["frequency_profile_id"] == "live_4h"
    assert row["indicator_profile_id"] == "time_normalized_v1"
    assert row["cost_model_version"] == "arena-cost-v3"
    assert row["cost_scenario_id"] == "base"
    assert row["rules_snapshot"]["portfolio_risk"]["max_open_positions_total"] == 7  # v36: meridian
    assert row["rules_snapshot"]["regime_variant"] == "strict_v1"
    assert row["params_snapshot"]["regime_research"]["regime_variant"] == "strict_v1"
    assert row["rules_snapshot"]["live_gate_replay"]["replay_execution_gate_blocks"] is False
    assert row["rules_snapshot"]["execution_product"]["target_product"] == "spot"
    assert row["rules_snapshot"]["execution_product"]["spot_execution_only"] is True
    assert row["rules_snapshot"]["execution_product"]["allow_live_short"] is False
    assert row["bar_count"] == 2
    assert row["metrics"]["by_algo"]["test_algo"]["trade_count"] == 1


def test_spot_backtest_maps_short_to_exit_or_no_trade() -> None:
    signals = iter(["short", "long", "short"])

    def scripted(macro, indicators):
        return next(signals)

    result = backtest.run_replay(
        [
            _frame(0, close=100.0),
            _frame(1, close=101.0),
            _frame(2, close=102.0),
        ],
        strategy_fns={"test_algo": scripted},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="spot",
            position_semantics="spot_long_flat",
        ),
    )

    assert len(result.trades) == 1
    assert result.trades[0].direction == "long"
    assert result.trades[0].exit_reason == "short_signal_spot_risk_off"


def _spot_settings(**kw) -> "backtest.BacktestSettings":
    return backtest.BacktestSettings(
        close_open_at_end=False,
        product_type="spot",
        position_semantics="spot_long_flat",
        **kw,
    )


def test_fng_contrarian_scales_in_and_skips_price_stop(monkeypatch) -> None:
    # 물타기·가격손절 제외 메커니즘 격리 검증 — P-A 이익포착은 별도 테스트(off로 격리).
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)

    # 가격 기준 물타기(트랜치 0%/-3%/-6%)·가격손절 제외 인프라를 결정적으로 검증.
    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25}),  # 진입: 1차 트랜치 w=0.15 @100, ref=100
            _frame(
                1, close=98.0, low=96.5, macro={"fng": 15}
            ),  # 저가 -3.5% → -3% 체결 @97 → w=0.40
            _frame(2, close=95.0, low=93.0, macro={"fng": 5}),  # 저가 -7% → -6% 체결 @94 → w=0.70
            # 30% 폭락이지만 가격 손절 제외 → 청산 안 됨, 트랜치 소진 → 추가 없음.
            _frame(3, close=70.0, low=65.0, macro={"fng": 5}),
            # 보유(min_hold 48h 전엔 flat 불가). fng<30 지속 → long hold.
            *[_frame(i, close=72.0, macro={"fng": 20}) for i in range(4, 12)],
            _frame(12, close=95.0, macro={"fng": 60}),  # 48h 경과(min_hold) + 공포 해소 → flat 청산
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    # 폭락 구간에도 가격 손절 트레이드가 없어야 함 — 단 1건(flat 청산)만.
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "flat_signal"
    # 누적 비중 0.15+0.25+0.30 = 0.70 (상한), 한계가 가중평균 진입가.
    assert trade.position_weight == pytest.approx(0.70)
    # avg = (100*0.15 + 97*0.25 + 94*0.30)/0.70 = (15+24.25+28.2)/0.7 = 96.3571
    assert trade.open_price == pytest.approx(96.3571, abs=1e-3)


def test_fng_contrarian_scale_in_has_parity_under_non_spot_product_type(monkeypatch) -> None:
    # spot→perp 전환 Phase A(2026-08-15) 발견·수정: run_replay()의 비-spot 분기(else:
    # signal=raw_signal)엔 원래 fng_contrarian 물타기(_maybe_scale_in_fng_sim) 호출이
    # 없었음 — product_type="spot"이 아닌 설정(perp 검증 백테스트)으로 fng_contrarian을
    # 돌리면 트랜치가 하나도 안 쌓여 거래수·비중이 spot과 달라지는 조용한 격차였음.
    # 위 test_fng_contrarian_scales_in_and_skips_price_stop와 동일 시나리오를 non-spot
    # settings로 재현해 이제 동일 결과(단일 거래·비중 0.70·가중평균 진입가)가 나오는지 확인.
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25}),
            _frame(1, close=98.0, low=96.5, macro={"fng": 15}),
            _frame(2, close=95.0, low=93.0, macro={"fng": 5}),
            _frame(3, close=70.0, low=65.0, macro={"fng": 5}),
            *[_frame(i, close=72.0, macro={"fng": 20}) for i in range(4, 12)],
            _frame(12, close=95.0, macro={"fng": 60}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            product_type="usdm_perp",
            position_semantics="usdm_perp_long_short",
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "signal_flat"
    assert trade.position_weight == pytest.approx(0.70)
    assert trade.open_price == pytest.approx(96.3571, abs=1e-3)


def test_fng_contrarian_unknown_regime_multiplier_scales_first_tranche_only(monkeypatch) -> None:
    # P4(2026-07-21, 신규·미검증): UNKNOWN_REGIME_SIZE_MULT_BY_ALGO가 최초 1차 트랜치에만
    # 적용되고, 이후 가격 기준 물타기(fill_price_tranches)는 정상 절대비중·정상 상한대로
    # 진행돼야 한다 — "진입 시점 확신도"만 낮추고 물타기 스케줄 자체는 건드리지 않는 설계.
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)
    monkeypatch.setattr(parameters, "UNKNOWN_REGIME_SIZE_MULT_BY_ALGO", {"fng_contrarian": 0.5})

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25, "arena_regime_state": "unknown"}),
            _frame(1, close=98.0, low=96.5, macro={"fng": 15, "arena_regime_state": "unknown"}),
            *[
                _frame(i, close=98.0, macro={"fng": 20, "arena_regime_state": "unknown"})
                for i in range(2, 12)
            ],
            _frame(12, close=98.0, macro={"fng": 60, "arena_regime_state": "unknown"}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    # 1차 트랜치 0.15×0.5=0.075 + 2차 트랜치(정상 0.25, 배수 미적용) = 0.325.
    assert trade.position_weight == pytest.approx(0.325)


def test_fng_contrarian_unknown_regime_multiplier_defaults_off(monkeypatch) -> None:
    # 빈 dict(기본값)면 unknown 레짐이어도 기존 동작(0.15 첫 트랜치)과 완전히 동일.
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)
    assert parameters.UNKNOWN_REGIME_SIZE_MULT_BY_ALGO == {}

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25, "arena_regime_state": "unknown"}),
            *[
                _frame(i, close=100.0, macro={"fng": 20, "arena_regime_state": "unknown"})
                for i in range(1, 12)
            ],
            _frame(12, close=100.0, macro={"fng": 60, "arena_regime_state": "unknown"}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    assert len(result.trades) == 1
    assert result.trades[0].position_weight == pytest.approx(0.15)


def test_fng_contrarian_duration_sizing_scales_all_tranches_uniformly(monkeypatch) -> None:
    # P3(2026-07-21, 신규·미검증): 공포 1일차(fng_days_below_30<=1) 진입은 스케줄 전체
    # (1차 트랜치 + 물타기 트랜치 + 상한)가 균일하게 축소돼야 한다.
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)
    monkeypatch.setattr(parameters, "FNG_DURATION_FEATURE_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_DURATION_MODE", "sizing")
    monkeypatch.setattr(parameters, "FNG_DAY1_SIZE_MULT", 0.5)

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25, "fng_days_below_30": 1}),
            _frame(1, close=98.0, low=96.5, macro={"fng": 15, "fng_days_below_30": 2}),
            _frame(2, close=95.0, low=93.0, macro={"fng": 5, "fng_days_below_30": 3}),
            _frame(3, close=70.0, low=65.0, macro={"fng": 5, "fng_days_below_30": 4}),
            *[
                _frame(i, close=72.0, macro={"fng": 20, "fng_days_below_30": 5})
                for i in range(4, 12)
            ],
            _frame(12, close=95.0, macro={"fng": 60, "fng_days_below_30": 0}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    # 스케일 0.5 적용 시 누적 비중 0.70×0.5=0.35(상한도 스케일), 평단은 동일 비율이라 불변.
    assert trade.position_weight == pytest.approx(0.35)
    assert trade.open_price == pytest.approx(96.3571, abs=1e-3)


def test_fng_contrarian_duration_sizing_defaults_off(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)
    assert parameters.FNG_DURATION_FEATURE_ENABLED is False

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, macro={"fng": 25, "fng_days_below_30": 1}),
            _frame(1, close=98.0, low=96.5, macro={"fng": 15, "fng_days_below_30": 2}),
            *[
                _frame(i, close=98.0, macro={"fng": 20, "fng_days_below_30": 5})
                for i in range(2, 12)
            ],
            _frame(12, close=98.0, macro={"fng": 60, "fng_days_below_30": 0}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    assert len(result.trades) == 1
    # 기본 off → 스케일 미적용, 기존 동작(0.15+0.25=0.40, 3차 트랜치 미도달) 그대로.
    assert result.trades[0].position_weight == pytest.approx(0.40)


def test_fng_contrarian_time_stop_closes_after_max_hold(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", False)  # 시간손절 격리 검증

    def always_fear(macro, indicators):
        return "long"  # 공포 지속 — 익절 신호 없음

    frames = [_frame(i, close=100.0, macro={"fng": 20}) for i in range(20)]
    result = backtest.run_replay(
        frames,
        strategy_fns={"fng_contrarian": always_fear},
        settings=_spot_settings(),
    )

    # 72h(18봉) 경과 시 시간 손절 청산.
    assert any(t.exit_reason == "time_stop" for t in result.trades)


def test_omnibus_regime_for_wraps_omnibus_regime() -> None:
    # 공개 래퍼가 내부 _omnibus_regime과 동일하게 동작(backtest.py/stream.py 앵커).
    macro = {"arena_regime_state": "bear_trend"}
    assert algorithms.omnibus_regime_for(macro, {}) == "DOWN_TREND"
    assert algorithms.omnibus_regime_for({"arena_regime_state": "bull_trend"}, {}) == "UP_TREND"


def _force_local_regime(monkeypatch, regime_state: str) -> None:
    """run_replay 루프는 매 bar `regime.classify_regime_variant()`로 arena_regime_state를
    지표에서 직접 재계산해 macro에 주입한다(backtest.py — 라이브 로컬레짐 패리티, 테스트
    프레임이 macro에 직접 넣은 arena_regime_state는 이 재계산으로 덮어써진다). 레그를
    결정적으로 통제하려면 분류기 자체를 고정해야 한다."""
    from arena import regime as regime_module

    def _fixed(
        indicators, market_features=None, macro=None, *, variant=regime_module.REGIME_VARIANT_STRICT
    ):
        return regime_module.RegimeDecision(
            regime_state=regime_state, confidence=1.0, reason={}, feature_snapshot={}
        )

    monkeypatch.setattr(regime_module, "classify_regime_variant", _fixed)
    monkeypatch.setattr(backtest.regime, "classify_regime_variant", _fixed)


def test_omnibus_leg_price_stop_disabled_skips_stop_loss(monkeypatch) -> None:
    # P1 후속: DOWN_TREND 레그만 가격손절 제외 시, 손절가를 뚫는 폭락에도 청산 안 됨.
    _force_local_regime(monkeypatch, "bear_trend")
    monkeypatch.setattr(parameters, "OMNIBUS_PRICE_STOP_DISABLED_LEGS", ("DOWN_TREND",))
    monkeypatch.setattr(parameters, "OMNIBUS_TARGET_EXIT_ENABLED", False)

    def always_long(macro, indicators):
        return "long"

    frames = [
        _frame(0, close=100.0),  # 진입
        # 정상이면 손절가(≈97.5, ATR=1×2.5 clamp)를 뚫는 폭락 — 그러나 제외돼야 함.
        _frame(1, open_price=99.0, high=100.0, low=80.0, close=98.0),
        *[_frame(i, close=98.0) for i in range(2, 4)],
    ]
    result = backtest.run_replay(
        frames, strategy_fns={"omnibus": always_long}, settings=_spot_settings()
    )

    assert not any(t.exit_reason in ("stop_loss", "trailing_stop") for t in result.trades)


def test_omnibus_leg_price_stop_disabled_does_not_affect_other_legs(monkeypatch) -> None:
    # 특이성 검증: DOWN_TREND만 제외했을 때 UP_TREND 레그는 기존처럼 정상 손절돼야 함
    # — 2026-07-25 "레그 혼합" 가설(omnibus-stop-distance-design-20260804.md §3)의
    # 핵심 전제(레그를 분리하면 다른 레그는 안 건드림)를 코드 레벨에서 보증.
    _force_local_regime(monkeypatch, "bull_trend")
    monkeypatch.setattr(parameters, "OMNIBUS_PRICE_STOP_DISABLED_LEGS", ("DOWN_TREND",))
    monkeypatch.setattr(parameters, "OMNIBUS_TARGET_EXIT_ENABLED", False)

    def always_long(macro, indicators):
        return "long"

    frames = [
        _frame(0, close=100.0),  # UP_TREND 진입
        _frame(1, open_price=99.0, high=100.0, low=80.0, close=98.0),
    ]
    result = backtest.run_replay(
        frames, strategy_fns={"omnibus": always_long}, settings=_spot_settings()
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason in ("stop_loss", "trailing_stop")


def test_omnibus_leg_time_stop_hours_override(monkeypatch) -> None:
    _force_local_regime(monkeypatch, "bear_trend")
    monkeypatch.setattr(parameters, "OMNIBUS_LEG_TIME_STOP_HOURS", {"DOWN_TREND": 12.0})
    monkeypatch.setattr(parameters, "OMNIBUS_TARGET_EXIT_ENABLED", False)

    def always_long(macro, indicators):
        return "long"

    # 가격 변동 없음(손절/익절 미발동) — 12h(3봉) 경과 시 레그별 시간손절만으로 청산돼야 함.
    frames = [_frame(i, close=100.0) for i in range(6)]
    result = backtest.run_replay(
        frames, strategy_fns={"omnibus": always_long}, settings=_spot_settings()
    )

    assert any(t.exit_reason == "time_stop" for t in result.trades)


def test_omnibus_leg_overrides_default_off(monkeypatch) -> None:
    # 빈 튜플/빈 dict(기본값)면 omnibus도 기존 전역 ATR 손절 그대로 — 무회귀.
    assert parameters.OMNIBUS_PRICE_STOP_DISABLED_LEGS == ()
    assert parameters.OMNIBUS_LEG_TIME_STOP_HOURS == {}
    _force_local_regime(monkeypatch, "bear_trend")
    monkeypatch.setattr(parameters, "OMNIBUS_TARGET_EXIT_ENABLED", False)

    def always_long(macro, indicators):
        return "long"

    frames = [
        _frame(0, close=100.0),
        _frame(1, open_price=99.0, high=100.0, low=80.0, close=98.0),
    ]
    result = backtest.run_replay(
        frames, strategy_fns={"omnibus": always_long}, settings=_spot_settings()
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason in ("stop_loss", "trailing_stop")


def test_fng_contrarian_profit_target_exit(monkeypatch) -> None:
    # P-A: 진입가+ATR×1.0 도달 시 target_exit 익절. 물타기 없이 단순 상승 시나리오.
    monkeypatch.setattr(parameters, "FNG_TARGET_EXIT_ENABLED", True)
    monkeypatch.setattr(parameters, "FNG_TARGET_MODE", "atr")
    monkeypatch.setattr(parameters, "FNG_TARGET_ATR_MULT", 1.0)

    def fng_long(macro, indicators):
        return "long" if macro.get("fng", 100) < 30 else None

    result = backtest.run_replay(
        [
            _frame(0, close=100.0, high=100.0, atr=1.0, macro={"fng": 20}),  # 진입 @100, 목표=101
            _frame(1, close=100.5, high=101.5, atr=1.0, macro={"fng": 20}),  # high 101.5≥101 → 익절
            _frame(2, close=100.0, high=100.0, atr=1.0, macro={"fng": 20}),
        ],
        strategy_fns={"fng_contrarian": fng_long},
        settings=_spot_settings(),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "target_exit"
    assert trade.close_price == pytest.approx(101.0)  # 한계가(진입가×1.01) 체결


def test_backtest_can_replay_live_execution_gate_blocks() -> None:
    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [
            _frame(
                0,
                market_features={
                    "execution_gate_allowed": False,
                    "execution_gate_reject_reason": "spread_too_wide",
                },
            ),
            _frame(1, close=101.0),
        ],
        strategy_fns={"test_algo": always_long},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            replay_execution_gate_blocks=True,
        ),
    )

    assert result.trades == []
    assert result.risk_events[0].event_type == "spread_too_wide"
    assert result.risk_events[0].risk_snapshot["source"] == "live_gate_replay"


def test_backtest_can_replay_live_realtime_risk_blocks() -> None:
    def always_long(macro, indicators):
        return "long"

    result = backtest.run_replay(
        [
            _frame(
                0,
                market_features={
                    "realtime_risk_fresh": True,
                    "realtime_risk_state": realtime_risk.STATE_BLOCK_ENTRY,
                },
            ),
            _frame(1, close=101.0),
        ],
        strategy_fns={"test_algo": always_long},
        settings=backtest.BacktestSettings(
            close_open_at_end=False,
            replay_realtime_risk_blocks=True,
        ),
    )

    assert result.trades == []
    assert result.risk_events[0].event_type == "realtime_risk:BLOCK_ENTRY"
    assert all(
        point.open_position is None or point.open_position["direction"] == "long"
        for point in result.equity_curve
    )


def test_backtest_frequency_metrics_include_cost_and_turnover() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(
        close_open_at_end=True,
        fee_bps=5.0,
        slippage_bps=2.0,
        spread_bps_round_trip=3.0,
    )
    result = backtest.run_replay(
        [_frame(0, close=100.0), _frame(1, close=101.0)],
        strategy_fns={"test_algo": always_long},
        settings=settings,
    )

    trade = result.trades[0]
    metrics = result.metrics["by_algo"]["test_algo"]

    assert trade.gross_ret_pct == pytest.approx(0.01)
    assert trade.trading_cost_pct == pytest.approx(0.0017)
    assert trade.net_ret_pct == pytest.approx(0.0083)
    assert metrics["gross_return_pct"] == pytest.approx(0.01)
    assert metrics["trading_cost_drag_pct"] == pytest.approx(-0.0017)
    assert metrics["cost_to_gross_ratio"] == pytest.approx(0.17)
    assert metrics["trades_per_day"] == pytest.approx(6.0)
    assert metrics["turnover_per_day"] == pytest.approx(12.0)
    assert metrics["avg_hold_hours"] == pytest.approx(4.0)
    assert metrics["total_return_ex_end_of_data_pct"] == 0.0


def test_backtest_portfolio_risk_blocks_excess_long_exposure() -> None:
    def always_long(macro, indicators):
        return "long"

    settings = backtest.BacktestSettings(
        close_open_at_end=False,
        max_long_positions=1,
        max_open_positions_total=5,
    )
    result = backtest.run_replay(
        [_frame(0), _frame(1)],
        strategy_fns={"first": always_long, "second": always_long},
        settings=settings,
    )

    assert result.equity_curve[0].open_position["algo_id"] == "first"
    assert result.equity_curve[1].open_position is None
    assert len(result.risk_events) == 2
    assert {event.event_type for event in result.risk_events} == {"max_long_positions"}


def test_omnibus_range_entry_applies_live_size_multiplier() -> None:
    # W2(2026-07-15): omnibus_position_multiplier(RANGE=0.40)가 backtest _open_position에도
    # 적용돼야 live(scheduler.py:925)와 사이징이 일치한다 — 이전엔 combined_position_weight
    # 그대로 써서 RANGE/REBOUND 가중수익이 과대계상되던 패리티 버그.
    range_macro = {"arena_regime_state": "sideways"}
    range_ind = {
        "rsi": 20.0,
        "macd_hist": 0.0,
        "macd_hist_prev": 0.0,
        "bb_pos": 0.2,  # < OMNIBUS_BB_POS_RANGE_ENTRY(0.30) → NEAR_LOW
        "adx": 10.0,
        "atr": 1.0,
        "atr_pct": 0.01,
        "ema_fast": 100.0,
        "ema_slow": 100.0,
    }
    frames = [
        backtest.ReplayFrame(
            bar=backtest.ReplayBar(
                open_time=_dt(0),
                close_time=_dt(4),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            ),
            indicators=range_ind,
            macro=range_macro,
        ),
        backtest.ReplayFrame(
            bar=backtest.ReplayBar(
                open_time=_dt(4),
                close_time=_dt(8),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            ),
            indicators=range_ind,
            macro=range_macro,
        ),
    ]
    result = backtest.run_replay(
        frames,
        strategy_fns={"omnibus": algorithms.omnibus},
        settings=backtest.BacktestSettings(
            close_open_at_end=True,
            product_type="spot",
            position_semantics="spot_long_flat",
        ),
    )

    assert len(result.trades) == 1
    # combined_position_weight는 항상 VOL_WEIGHT_MIN(0.25) 이상으로 클램프되므로, RANGE 배수
    # (0.40) 미적용 버그가 재발하면 이 값이 절대 0.25 밑으로 못 내려간다 — 엄격히 미만이어야
    # 배수가 실제로 곱해졌다는 증거. 지표 조합이 결정적이라 정확한 기대값(0.10)도 함께 고정.
    assert result.trades[0].position_weight == pytest.approx(0.10)
    assert result.trades[0].position_weight < parameters.VOL_WEIGHT_MIN


def test_load_frames_from_supabase_paginates_ohlcv_rows() -> None:
    rows = [
        {
            "open_time": (_dt(0) + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
            "close_time": (_dt(0) + timedelta(hours=index + 1)).isoformat().replace("+00:00", "Z"),
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.0 + index,
            "volume": 1.0,
        }
        for index in range(1200)
    ]

    class FakeResult:
        def __init__(self, data):
            self.data = data

    class FakeBuilder:
        def __init__(self, table_name: str) -> None:
            self.table_name = table_name
            self.start = 0
            self.end = 0
            self.range_calls: list[tuple[int, int]] = []

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args):
            return self

        def gte(self, *_args):
            return self

        def lte(self, *_args):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, start: int, end: int):
            self.start = start
            self.end = end
            self.range_calls.append((start, end))
            return self

        async def execute(self):
            if self.table_name == "arena_macro_snapshots":
                return FakeResult([])
            return FakeResult(rows[self.start : self.end + 1])

    class FakeDb:
        def __init__(self) -> None:
            self.ohlcv_builders: list[FakeBuilder] = []

        def table(self, table_name: str):
            builder = FakeBuilder(table_name)
            if table_name == "arena_ohlcv_bars":
                self.ohlcv_builders.append(builder)
            return builder

    db = FakeDb()
    frames = asyncio.run(backtest.load_frames_from_supabase(db, limit=1200, warmup_bars=1))

    assert len(frames) == 1200
    assert [builder.range_calls[0] for builder in db.ohlcv_builders] == [
        (0, 999),
        (1000, 1199),
    ]
