"""macd_momentum 숏(v41, 근접 후보) — 신호 함수·사이징·등록·트랙 스코프 회귀 테스트.

배경: docs/arena/research/phase-b-full-evidence-reaudit-20260816.md — Phase B §8이
"❌기각"으로 표기했던 6셀 중 5셀이 실제로는 SR 양수(3자산 veto제거 전부 양수)인데
표본이 MinTRL 대비 2.8~5.3배 부족한 "판정 불가"였다. D017 사전게이트는 아직 통과
못 했으므로 meridian(D019)과 동일하게 라이브 관찰 축적 대상으로 승격.
"""

from __future__ import annotations

import pytest

from arena import algorithms, parameters, short_signals

TSMOM_KEY = f"tsmom_nl_return_{parameters.TSMOM_NL_LOOKBACK_BARS}"


def _base_macro(**overrides: object) -> dict:
    macro = {"arena_regime_state": "sideways"}
    macro.update(overrides)
    return macro


def _base_ind(*, ret: float, vol: float = 0.02, **overrides: object) -> dict:
    ind = {TSMOM_KEY: ret, "tsmom_nl_vol_ewma": vol, "realized_vol_24h": vol}
    ind.update(overrides)
    return ind


def test_macd_momentum_short_registered_in_perp_short_algorithms() -> None:
    assert short_signals.PERP_SHORT_ALGORITHMS["macd_momentum"] is algorithms.macd_momentum_short


def test_macd_momentum_perp_short_enabled_for_all_three_assets() -> None:
    for track in ("BTCUSDT-PERP", "ETHUSDT-PERP", "SOLUSDT-PERP"):
        assert (track, "macd_momentum") in parameters.PERP_SHORT_ENABLED_TRACKS


# ── macd_momentum_short 신호 함수 (Phase B §3.1/§8 veto제거 설계 그대로) ────


def test_macd_momentum_short_fires_on_negative_tsmom_signal() -> None:
    assert algorithms.macd_momentum_short(_base_macro(), _base_ind(ret=-0.5)) == "short"


def test_macd_momentum_short_none_on_positive_signal() -> None:
    assert algorithms.macd_momentum_short(_base_macro(), _base_ind(ret=0.5)) is None


def test_macd_momentum_short_none_when_signal_missing() -> None:
    ind = {"tsmom_nl_vol_ewma": 0.02}  # tsmom_nl_return_* 없음
    assert algorithms.macd_momentum_short(_base_macro(), ind) is None


def test_macd_momentum_short_not_vetoed_by_risk_off() -> None:
    # §8 veto제거 변형 채택 — risk-off(bear_trend/stress)에서도 숏 신호를 낸다.
    macro = _base_macro(arena_regime_state="bear_trend")
    assert algorithms.macd_momentum_short(macro, _base_ind(ret=-0.5)) == "short"


def test_macd_momentum_short_none_when_tsmom_nl_disabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)
    assert algorithms.macd_momentum_short(_base_macro(), _base_ind(ret=-0.5)) is None


# ── 사이징: 숏은 abs(f(s)) — 롱 전용 클립 함수를 쓰면 비중이 0이 되는 회귀 방지 ──


def test_tsmom_nl_position_multiplier_abs_nonzero_for_negative_signal() -> None:
    ind = _base_ind(ret=-0.5)
    assert algorithms.tsmom_nl_position_multiplier(_base_macro(), ind) == 0.0
    assert algorithms.tsmom_nl_position_multiplier_abs(_base_macro(), ind) > 0.0


def test_tsmom_nl_position_multiplier_abs_matches_long_multiplier_for_positive_signal() -> None:
    ind = _base_ind(ret=0.5)
    long_mult = algorithms.tsmom_nl_position_multiplier(_base_macro(), ind)
    abs_mult = algorithms.tsmom_nl_position_multiplier_abs(_base_macro(), ind)
    assert long_mult == abs_mult
    assert long_mult > 0.0


def test_tsmom_nl_position_multiplier_abs_respects_weight_cap() -> None:
    import math

    # f(s)=s/(s²+1)는 s=±1에서 정점(|f|=0.5)을 찍고 다시 0으로 수렴하는 종형 함수라
    # "극단적으로 큰 |s|"가 아니라 s=-1을 정확히 만들어야 클램프 상한에 걸린다.
    # vol=1/√126로 두면 s=ret가 되므로 ret=-1.0이 정확히 s=-1.
    vol = 1.0 / math.sqrt(parameters.TSMOM_NL_LOOKBACK_BARS)
    ind = _base_ind(ret=-1.0, vol=vol)
    assert algorithms.tsmom_nl_position_multiplier_abs(_base_macro(), ind) == pytest.approx(
        parameters.TSMOM_NL_WEIGHT_CAP
    )


def test_tsmom_nl_position_multiplier_abs_bounded_by_weight_cap_for_extreme_signal() -> None:
    # 종형 함수라 극단값에서는 오히려 0에 가까워진다 — 그래도 상한을 넘지 않아야 한다.
    ind = _base_ind(ret=-50.0, vol=0.01)
    result = algorithms.tsmom_nl_position_multiplier_abs(_base_macro(), ind)
    assert 0.0 <= result <= parameters.TSMOM_NL_WEIGHT_CAP


def test_tsmom_nl_position_multiplier_abs_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(parameters, "TSMOM_NL_ENABLED", False)
    assert algorithms.tsmom_nl_position_multiplier_abs(_base_macro(), _base_ind(ret=-0.5)) == 1.0


# ── short_signals.resolve() 통합 ────────────────────────────────────────


def test_resolve_produces_short_when_long_signal_is_none() -> None:
    decision = short_signals.resolve(
        algo_id="macd_momentum",
        long_signal=None,
        macro=_base_macro(),
        indicators=_base_ind(ret=-0.5),
        short_enabled=True,
    )
    assert decision.resolved_signal == "short"
    assert not decision.conflict
