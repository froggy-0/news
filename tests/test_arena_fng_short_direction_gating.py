"""fng_contrarian 숏 direction-blind 결함 수정 회귀 테스트 (2026-08-16, v41).

배경: Phase B §13(docs/arena/research/spot-to-perp-phase-b-short-entry-design-
20260815.md)이 실측한 결함 — v22 물타기(FNG_CONTRARIAN_SCALE_IN_ENABLED)·P-A
목표가익절(FNG_TARGET_EXIT_ENABLED)·PRICE_STOP_DISABLED_ALGOS 가격손절 면제,
세 메커니즘 전부 algo_id로만 게이팅되고 position.direction을 보지 않아 숏에
적용되면 (1) 사이징이 롱 전용 트랜치로 잘못 계산되고 (2) 목표가가 진입가
"위"에 잡혀 거의 즉시 손실 확정되고 (3) 가격손절까지 면제돼 무방비 노출됐다.
당시엔 "현재 도달 불가능한 코드 경로"라 방치했으나, v41이 fng_contrarian_short를
SOLUSDT-PERP에 실제로 배선하면서 이 경로가 도달 가능해져 실제로 고쳤다
(backtest.py/scheduler.py/stream.py, direction=="long" 게이팅 추가).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arena import backtest, execution_rules, parameters


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 19, hour, 0, tzinfo=timezone.utc)


def _frame(
    index: int,
    *,
    open_price: float = 100.0,
    high: float = 100.5,
    low: float = 99.5,
    close: float = 100.0,
    atr: float = 1.0,
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
        indicators={"rsi": 80.0, "macd_hist": -0.1, "macd_hist_prev": -0.05, "atr": atr},
        macro={"arena_regime_state": "sideways", "fng": 80.0},
    )


def _short_once():
    signals = iter(["short", None, None, None])

    def scripted(macro, indicators):
        return next(signals, None)

    return scripted


def test_fng_contrarian_short_uses_standard_sizing_not_long_tranche() -> None:
    """direction=="long" 게이팅(scheduler.py 동등 로직 검증 — backtest 사이징 경로).

    fng_contrarian 숏은 물타기 1차 트랜치(0.15)가 아니라 표준
    combined_position_weight()를 받아야 한다.
    """
    settings = backtest.BacktestSettings(
        close_open_at_end=True, product_type="usdm_perp", max_trades_per_day_per_algo=99.0
    )
    result = backtest.run_replay(
        [_frame(0)],
        strategy_fns={"fng_contrarian": _short_once()},
        settings=settings,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "short"
    expected_weight = execution_rules.combined_position_weight(
        0.0,
        100.0,
        execution_rules.calc_stop_loss_price(
            "short",
            100.0,
            1.0,
            atr_multiple=settings.atr_multiple,
            stop_loss_min_pct=settings.stop_loss_min_pct,
            stop_loss_max_pct=settings.stop_loss_max_pct,
        ),
        target_vol=parameters.VOL_TARGET_PER_BAR,
        risk_budget_pct=parameters.RISK_PER_TRADE_PCT,
        weight_min=parameters.VOL_WEIGHT_MIN,
        weight_max=parameters.VOL_WEIGHT_MAX,
    )
    assert trade.position_weight == pytest.approx(expected_weight)
    # 물타기 1차 트랜치(FNG_CONTRARIAN_PRICE_TRANCHES[0][1]=0.15)와는 달라야 한다.
    assert trade.position_weight != pytest.approx(0.15)


def test_fng_contrarian_short_gets_price_stop_not_immune() -> None:
    """PRICE_STOP_DISABLED_ALGOS 면제는 롱 전용 — 숏은 표준 ATR 손절을 받아야 하고,
    가격이 손절선을 크게 벗어나면 stop_loss로 청산돼야 한다(target_exit이 아니라).
    """
    settings = backtest.BacktestSettings(close_open_at_end=False, product_type="usdm_perp")
    result = backtest.run_replay(
        [
            _frame(0),
            _frame(1, high=130.0, low=99.0, close=115.0),  # 숏에 크게 불리한 급등
        ],
        strategy_fns={"fng_contrarian": _short_once()},
        settings=settings,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "short"
    assert trade.exit_reason == "stop_loss"
    # 숏 손절가 = open + ATR*multiple(2.5%, min/max 클램프 내) = 102.5
    assert trade.close_price == pytest.approx(102.5)


def test_fng_contrarian_short_does_not_close_prematurely_via_target_exit() -> None:
    """P-A 목표가익절 버그(§13) 회귀 방지 — 가격이 손절선 근처도 안 갔는데 숏
    포지션이 목표가 도달(잘못된 방향)로 즉시 청산되면 안 된다.
    """
    settings = backtest.BacktestSettings(close_open_at_end=False, product_type="usdm_perp")
    result = backtest.run_replay(
        [
            _frame(0),
            _frame(1),  # 가격 거의 무변화 — 손절·시간손절 전부 미도달
            _frame(2),
        ],
        strategy_fns={"fng_contrarian": _short_once()},
        settings=settings,
    )

    assert result.trades == []
    assert result.equity_curve[-1].open_position is not None
    assert result.equity_curve[-1].open_position["direction"] == "short"
