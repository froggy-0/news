from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arena import execution_gate, frequency, parameters, risk, scheduler


def _now() -> datetime:
    return datetime(2026, 6, 20, 1, 0, tzinfo=timezone.utc)


def test_execution_gate_allows_signal_when_edge_clears_cost_and_quality() -> None:
    cost = frequency.get_cost_scenario("live_4h", "base")
    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        # arena-cost-v3(FEE_BPS 10.0): cost floor = 2*(10+1)+1 = 23bps → macd_hist 300
        # (edge=30bps)로 여유있게 통과시킨다(이전 200/13bps에서 상향).
        indicators={"close": 100_000.0, "macd_hist": 300.0, "atr": 100.0},
        realtime_features={
            "spread_bps_avg": 1.0,
            "expected_slippage_bps": 1.0,
            "depth_score": 1.0,
            "volatility_score": 0.0,
            "api_latency_ms_p95": 100.0,
        },
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=1.0),
    )

    assert decision.allowed is True
    assert decision.decision == "trade_allowed"
    assert decision.reject_reason is None
    json.dumps(decision.as_dict())


def test_execution_gate_blocks_when_cost_floor_is_not_cleared() -> None:
    cost = frequency.get_cost_scenario("research_1h", "base")
    decision = execution_gate.evaluate_execution_gate(
        algo_id="trend_core_v1",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1.0, "atr": 1.0},
        realtime_features={"spread_bps_avg": 1.0, "expected_slippage_bps": 1.0},
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
    )

    assert decision.allowed is False
    assert decision.reject_reason == "expected_return_below_cost_floor"


@pytest.mark.parametrize(
    ("features", "reject_reason"),
    [
        ({"spread_bps_avg": 99.0}, "spread_too_wide"),
        ({"expected_slippage_bps": 99.0}, "slippage_too_high"),
        ({"depth_score": 0.1}, "depth_too_thin"),
        ({"volatility_score": 2.0}, "volatility_spike"),
        ({"api_latency_ms_p95": 9999.0}, "latency_too_high"),
    ],
)
def test_execution_gate_quality_reject_reasons(features, reject_reason) -> None:
    cost = frequency.get_cost_scenario("live_4h", "low")
    base_features = {
        "spread_bps_avg": 1.0,
        "expected_slippage_bps": 1.0,
        "depth_score": 1.0,
        "volatility_score": 0.0,
        "api_latency_ms_p95": 10.0,
    }
    base_features.update(features)

    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1_000.0, "atr": 1_000.0},
        realtime_features=base_features,
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=0.1),
    )

    assert decision.allowed is False
    assert decision.reject_reason == reject_reason


def test_execution_gate_blocks_when_portfolio_risk_blocks() -> None:
    cost = frequency.get_cost_scenario("live_4h", "low")
    policy = risk.PortfolioRiskPolicy(max_open_positions_total=0)
    risk_decision = risk.evaluate_open(
        algo_id="macd_momentum",
        direction="long",
        open_positions={},
        state=risk.PortfolioRiskState(),
        evaluated_at=_now(),
        policy=policy,
    )

    decision = execution_gate.evaluate_execution_gate(
        algo_id="macd_momentum",
        signal="long",
        indicators={"close": 100_000.0, "macd_hist": 1_000.0, "atr": 1_000.0},
        realtime_features={},
        cost_scenario=cost,
        risk_decision=risk_decision,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=0.1),
    )

    assert decision.allowed is False
    assert decision.reject_reason == "risk_max_open_positions_total"


def test_execution_gate_policy_uses_per_symbol_depth_threshold() -> None:
    """2026-08-14: SOL/ETH가 BTC 기준 전역 depth 임계값($1M)에 걸려 depth_too_thin
    오탐(실측 SOL 거부율 100%)을 내던 문제 — 자산별 임계값이 정확히 배선됐는지 확인.
    """
    btc_policy = scheduler._execution_gate_policy("BTCUSDT")
    eth_policy = scheduler._execution_gate_policy("ETHUSDT")
    sol_policy = scheduler._execution_gate_policy("SOLUSDT")
    unknown_policy = scheduler._execution_gate_policy("DOGEUSDT")

    assert (
        btc_policy.min_depth_10bp_usd
        == parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL["BTCUSDT"]
    )
    assert (
        eth_policy.min_depth_10bp_usd
        == parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL["ETHUSDT"]
    )
    assert (
        sol_policy.min_depth_10bp_usd
        == parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL["SOLUSDT"]
    )
    # SOL이 ETH/BTC보다 훨씬 얕은 시장이므로 임계값도 그만큼 낮아야 한다(순서 보존).
    assert (
        sol_policy.min_depth_10bp_usd
        < eth_policy.min_depth_10bp_usd
        < btc_policy.min_depth_10bp_usd
    )
    # 미등록 심볼은 기존 전역값(env-override 가능)으로 폴백.
    assert unknown_policy.min_depth_10bp_usd == parameters.EXEC_GATE_MIN_DEPTH_10BP_USD


def test_execution_gate_sol_depth_that_would_have_been_rejected_now_passes() -> None:
    """실측 SOL 정상 유동성(min $241K)이 신 임계값($80K)은 통과하되 구 전역값($1M)은
    걸리는지 회귀 확인 — 재보정의 핵심 효과.
    """
    cost = frequency.get_cost_scenario("live_4h", "base")
    sol_policy = scheduler._execution_gate_policy("SOLUSDT")

    decision = execution_gate.evaluate_execution_gate(
        algo_id="fng_contrarian",
        signal="long",
        indicators={"close": 75.0, "macd_hist": 5.0, "atr": 1.0},
        realtime_features={
            "spread_bps_avg": 1.0,
            "expected_slippage_bps": 1.0,
            "depth_10bp_bid_usd": 241_052.0,  # 실측 SOL 최소 관측치
            "depth_10bp_ask_usd": 300_000.0,
            "volatility_score": 0.0,
            "api_latency_ms_p95": 100.0,
        },
        cost_scenario=cost,
        risk_decision=None,
        evaluated_at=_now(),
        policy=execution_gate.ExecutionGatePolicy(
            ecr_multiple=0.01, min_depth_10bp_usd=sol_policy.min_depth_10bp_usd
        ),
    )

    assert decision.reject_reason != "depth_too_thin"


def test_book_execution_features_precomputes_depth_score_with_symbol_threshold() -> None:
    """2026-08-14 배포 직후 실측으로 발견: _book_execution_features()가 depth_score를
    선계산해 execution_gate._depth_score()의 explicit-value 분기로 넘기는데, 이게 여전히
    구 전역 임계값을 쓰면 scheduler._execution_gate_policy()의 자산별 값이 무시된다
    (SOL 실측 depth_score가 신 임계값이 아니라 $1M 기준으로 나온 게 그 증거).
    _book_execution_features()에 SOL 임계값을 명시로 넘겼을 때 depth_score가 그 값 기준으로
    나오는지 확인 — 회귀 시 이 테스트가 깨진다.
    """
    sol_threshold = scheduler._min_depth_10bp_usd_for_symbol("SOLUSDT")
    bids = [(75.58, 10_000.0)]  # notional ≈ 75.58*10_000 ≈ $755,800
    asks = [(75.60, 10_000.0)]

    features = scheduler._book_execution_features(
        bid=75.58,
        ask=75.60,
        bids=bids,
        asks=asks,
        price=75.59,
        data_timestamp=_now(),
        min_depth_10bp_usd=sol_threshold,
    )

    min_depth = min(features["depth_10bp_bid_usd"], features["depth_10bp_ask_usd"])
    assert features["depth_score"] == pytest.approx(min_depth / sol_threshold)
    # 구 전역값($1M) 기준으로 계산됐다면 훨씬 작은 값이 나왔을 것 — 혼동 방지 회귀 확인.
    assert features["depth_score"] != pytest.approx(
        min_depth / parameters.EXEC_GATE_MIN_DEPTH_10BP_USD
    )
