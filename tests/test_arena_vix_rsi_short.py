"""vix_rsi 숏(v37, ETHUSDT-PERP 전용) — 신호 함수·등록·트랙 스코프 회귀 테스트.

배경: docs/arena/research/evidence-criteria-framework-20260816.md 재검증으로
Phase B §12("근접 미달")가 정정됨 — 사전등록 단일가설에는 PSR이 맞는 지표이고
ETH는 PSR=0.970·MinTRL 37≤48로 채택 기준을 통과했다(D017 경로 첫 승격).
"""

from __future__ import annotations

from arena import algorithms, parameters, short_signals


def test_vix_rsi_short_registered_in_perp_short_algorithms() -> None:
    assert short_signals.PERP_SHORT_ALGORITHMS["vix_rsi"] is algorithms.vix_rsi_short


def test_vix_rsi_perp_short_enabled_only_for_eth_track() -> None:
    # v41(2026-08-16): SOL도 근접 후보로 추가 승격(Phase B 전체 재감사) — BTC만
    # SR 자체가 음수로 확인돼 계속 제외.
    assert ("ETHUSDT-PERP", "vix_rsi") in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("SOLUSDT-PERP", "vix_rsi") in parameters.PERP_SHORT_ENABLED_TRACKS
    assert ("BTCUSDT-PERP", "vix_rsi") not in parameters.PERP_SHORT_ENABLED_TRACKS


# ── vix_rsi_short 신호 함수 (Phase B §3.5/§12 veto유지 설계 그대로) ────────


def _base_macro(**overrides: object) -> dict:
    macro = {
        "arena_regime_state": "sideways",
        "vix_now": 30.0,
        "vix_q40": 20.0,
        "breadth_up_ratio": 0.60,
        "stablecoin_supply_zscore": 0.0,
    }
    macro.update(overrides)
    return macro


def _base_ind(**overrides: object) -> dict:
    ind = {"rsi": 60.0, "macd_hist": -0.1, "macd_hist_prev": -0.05}
    ind.update(overrides)
    return ind


def test_vix_rsi_short_fires_on_elevated_vix_and_overheated_rsi() -> None:
    # VIX 고조(30 >= 20*1.05 밴드) + RSI>50(=100-VIX_RSI_LONG_MAX 대칭) + 모멘텀 개선중 아님.
    assert algorithms.vix_rsi_short(_base_macro(), _base_ind()) == "short"


def test_vix_rsi_short_none_when_vix_calm() -> None:
    macro = _base_macro(vix_now=10.0)
    assert algorithms.vix_rsi_short(macro, _base_ind()) is None


def test_vix_rsi_short_none_when_rsi_not_overheated() -> None:
    ind = _base_ind(rsi=40.0)
    assert algorithms.vix_rsi_short(_base_macro(), ind) is None


def test_vix_rsi_short_blocked_when_momentum_still_improving() -> None:
    # macd_hist가 직전봉보다 커지는 중(상승 가속 안 멈춤) → 고점추격매도 회피.
    ind = _base_ind(macd_hist=0.2, macd_hist_prev=-0.1)
    assert algorithms.vix_rsi_short(_base_macro(), ind) is None


def test_vix_rsi_short_blocked_in_risk_off() -> None:
    macro = _base_macro(arena_regime_state="bear_trend")
    assert algorithms.vix_rsi_short(macro, _base_ind()) is None


def test_vix_rsi_short_none_when_vix_missing() -> None:
    macro = _base_macro(vix_now=None)
    assert algorithms.vix_rsi_short(macro, _base_ind()) is None


def test_vix_rsi_short_gated_by_environment_votes() -> None:
    # breadth 붕괴 + stablecoin 수축이 동시에 걸리면(둘 다 False) 완화모드에서도
    # min_secondary_votes(1)를 못 채워 진입 안 함.
    macro = _base_macro(breadth_up_ratio=0.10, stablecoin_supply_zscore=-3.0)
    assert algorithms.vix_rsi_short(macro, _base_ind()) is None


# ── short_signals.resolve() 통합 — 스케줄러가 실제로 호출하는 경로 ────────


def test_resolve_produces_short_for_eth_track_when_long_signal_is_none() -> None:
    decision = short_signals.resolve(
        algo_id="vix_rsi",
        long_signal=None,  # 롱 조건(VIX calm)은 실패한 상태
        macro=_base_macro(),
        indicators=_base_ind(),
        short_enabled=True,  # scheduler._short_enabled_for(ETHUSDT-PERP, "vix_rsi")
    )
    assert decision.resolved_signal == "short"
    assert not decision.conflict


def test_resolve_stays_long_only_when_short_not_enabled_for_track() -> None:
    # BTC/SOL-PERP은 PERP_SHORT_ENABLED_TRACKS에 없으므로 scheduler가 short_enabled=False로 호출.
    decision = short_signals.resolve(
        algo_id="vix_rsi",
        long_signal=None,
        macro=_base_macro(),
        indicators=_base_ind(),
        short_enabled=False,
    )
    assert decision.resolved_signal is None
    assert decision.short_signal is None
