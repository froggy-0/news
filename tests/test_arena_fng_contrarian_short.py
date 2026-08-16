"""fng_contrarian 숏(v41, SOLUSDT-PERP 근접 후보) — 신호 함수·direction 게이팅
회귀 테스트.

배경: docs/arena/research/phase-b-full-evidence-reaudit-20260816.md — Phase B §13이
"❌기각"으로 표기했던 SOL 셀(veto유지)이 실제로는 SR 양수(PSR=0.878)인데 표본(21건)이
MinTRL(41건) 대비 1.9배 부족한 "판정 불가"였다. §13이 실측한 direction-blind 결함
(v22 물타기·목표가익절이 숏에 적용되면 손실 확정)은 이번에 실제로 수정했다 —
아래 direction 게이팅 테스트가 그 수정을 검증한다.
"""

from __future__ import annotations

from arena import algorithms, parameters, short_signals


def _base_macro(**overrides: object) -> dict:
    macro = {
        "arena_regime_state": "sideways",
        "fng": 80.0,
        "breadth_up_ratio": 0.60,
        "stablecoin_supply_zscore": 0.0,
    }
    macro.update(overrides)
    return macro


def _base_ind(**overrides: object) -> dict:
    ind = {"macd_hist": -0.1, "macd_hist_prev": -0.05}
    ind.update(overrides)
    return ind


def test_fng_contrarian_short_registered_in_perp_short_algorithms() -> None:
    assert short_signals.PERP_SHORT_ALGORITHMS["fng_contrarian"] is algorithms.fng_contrarian_short


def test_fng_contrarian_perp_short_enabled_only_for_sol_track() -> None:
    assert ("SOLUSDT-PERP", "fng_contrarian") in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("BTCUSDT-PERP", "fng_contrarian") not in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("ETHUSDT-PERP", "fng_contrarian") not in parameters.PERP_SHORT_ENABLED_TRACKS


# ── fng_contrarian_short 신호 함수 (Phase B §3.5/§13 veto유지 설계 그대로) ──


def test_fng_contrarian_short_fires_on_extreme_greed() -> None:
    # FNG=80 > FNG_SHORT_ABOVE(70) + 모멘텀 개선중 아님(mh<=mh_prev).
    assert algorithms.fng_contrarian_short(_base_macro(), _base_ind()) == "short"


def test_fng_contrarian_short_none_when_fng_not_greedy_enough() -> None:
    macro = _base_macro(fng=60.0)
    assert algorithms.fng_contrarian_short(macro, _base_ind()) is None


def test_fng_contrarian_short_blocked_when_momentum_still_improving() -> None:
    ind = _base_ind(macd_hist=0.2, macd_hist_prev=-0.1)
    assert algorithms.fng_contrarian_short(_base_macro(), ind) is None


def test_fng_contrarian_short_blocked_in_risk_off() -> None:
    macro = _base_macro(arena_regime_state="bear_trend")
    assert algorithms.fng_contrarian_short(macro, _base_ind()) is None


def test_fng_contrarian_short_none_when_fng_missing() -> None:
    macro = _base_macro(fng=None)
    assert algorithms.fng_contrarian_short(macro, _base_ind()) is None


def test_fng_contrarian_short_gated_by_environment_votes() -> None:
    macro = _base_macro(breadth_up_ratio=0.10, stablecoin_supply_zscore=-3.0)
    assert algorithms.fng_contrarian_short(macro, _base_ind()) is None


# ── short_signals.resolve() 통합 ────────────────────────────────────────


def test_resolve_produces_short_when_long_signal_is_none() -> None:
    decision = short_signals.resolve(
        algo_id="fng_contrarian",
        long_signal=None,
        macro=_base_macro(),
        indicators=_base_ind(),
        short_enabled=True,
    )
    assert decision.resolved_signal == "short"
    assert not decision.conflict
