"""Shadow execution-quality gate for conditional Arena trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import execution_rules, frequency, parameters, risk


@dataclass(frozen=True)
class ExecutionGatePolicy:
    ecr_multiple: float = parameters.EXEC_GATE_ECR_MULTIPLE
    max_spread_bps: float = parameters.EXEC_GATE_MAX_SPREAD_BPS
    max_slippage_bps: float = parameters.EXEC_GATE_MAX_SLIPPAGE_BPS
    min_depth_score: float = parameters.EXEC_GATE_MIN_DEPTH_SCORE
    max_latency_ms: float = parameters.EXEC_GATE_MAX_LATENCY_MS
    vol_spike_max: float = parameters.EXEC_GATE_VOL_SPIKE_MAX
    min_depth_10bp_usd: float = parameters.EXEC_GATE_MIN_DEPTH_10BP_USD


@dataclass(frozen=True)
class ExecutionGateDecision:
    allowed: bool
    decision: str
    reject_reason: str | None
    expected_return_bps: float
    expected_cost_bps: float
    spread_bps: float | None
    expected_slippage_bps: float | None
    depth_score: float | None
    volatility_score: float | None
    api_latency_ms: float | None
    policy: ExecutionGatePolicy
    evaluated_at: datetime
    feature_snapshot: dict[str, Any]
    risk_snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "reject_reason": self.reject_reason,
            "expected_return_bps": self.expected_return_bps,
            "expected_cost_bps": self.expected_cost_bps,
            "spread_bps": self.spread_bps,
            "expected_slippage_bps": self.expected_slippage_bps,
            "depth_score": self.depth_score,
            "volatility_score": self.volatility_score,
            "api_latency_ms": self.api_latency_ms,
            "policy": policy_snapshot(self.policy),
            "evaluated_at": execution_rules.format_utc_timestamp(self.evaluated_at),
            "feature_snapshot": self.feature_snapshot,
            "risk_snapshot": self.risk_snapshot,
        }


def policy_snapshot(policy: ExecutionGatePolicy | None = None) -> dict[str, Any]:
    policy = policy or ExecutionGatePolicy()
    return {
        "ecr_multiple": policy.ecr_multiple,
        "max_spread_bps": policy.max_spread_bps,
        "max_slippage_bps": policy.max_slippage_bps,
        "min_depth_score": policy.min_depth_score,
        "max_latency_ms": policy.max_latency_ms,
        "vol_spike_max": policy.vol_spike_max,
        "min_depth_10bp_usd": policy.min_depth_10bp_usd,
    }


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_edge_bps(signal: str | None, indicators: dict[str, Any], close: float) -> float:
    if not signal or close <= 0:
        return 0.0
    macd_hist = abs(_float(indicators.get("macd_hist")) or 0.0)
    atr = _float(indicators.get("atr")) or 0.0
    edge_price = max(macd_hist, atr * parameters.MACD_ATR_THRESHOLD_MULTIPLE)
    return edge_price / close * 10_000.0


def _depth_score(features: dict[str, Any], policy: ExecutionGatePolicy) -> float | None:
    explicit = _float(features.get("depth_score"))
    if explicit is not None:
        return explicit
    bid_depth = _float(features.get("depth_10bp_bid_usd"))
    ask_depth = _float(features.get("depth_10bp_ask_usd"))
    if bid_depth is None or ask_depth is None:
        return None
    return min(bid_depth, ask_depth) / policy.min_depth_10bp_usd


def expected_cost_bps(
    cost_scenario: frequency.CostScenario,
    features: dict[str, Any],
) -> float:
    spread = _float(features.get("spread_bps_avg"))
    slippage = _float(features.get("expected_slippage_bps"))
    base_cost = cost_scenario.trading_cost_bps_round_trip
    if spread is not None or slippage is not None:
        return 2.0 * (cost_scenario.fee_bps + (slippage or cost_scenario.slippage_bps)) + (
            spread or cost_scenario.spread_bps_round_trip
        )
    return base_cost


def evaluate_execution_gate(
    *,
    algo_id: str,
    signal: str | None,
    indicators: dict[str, Any],
    realtime_features: dict[str, Any] | None,
    cost_scenario: frequency.CostScenario,
    risk_decision: risk.RiskDecision | None,
    evaluated_at: datetime,
    policy: ExecutionGatePolicy | None = None,
) -> ExecutionGateDecision:
    policy = policy or ExecutionGatePolicy()
    features = dict(realtime_features or {})
    close = _float(indicators.get("close")) or _float(features.get("last_price")) or 0.0
    expected_return = _price_edge_bps(signal, indicators, close)
    expected_cost = expected_cost_bps(cost_scenario, features)
    spread = _float(features.get("spread_bps_avg"))
    slippage = _float(features.get("expected_slippage_bps"))
    depth_score = _depth_score(features, policy)
    volatility_score = _float(features.get("volatility_score"))
    latency = _float(features.get("api_latency_ms_p95"))
    risk_snapshot = risk_decision.as_dict() if risk_decision else {}

    reject_reason: str | None = None
    if signal is None:
        reject_reason = "no_signal"
    elif risk_decision is not None and not risk_decision.allowed:
        reject_reason = f"risk_{risk_decision.reason}"
    elif expected_return < expected_cost * policy.ecr_multiple:
        reject_reason = "expected_return_below_cost_floor"
    elif spread is not None and spread > policy.max_spread_bps:
        reject_reason = "spread_too_wide"
    elif slippage is not None and slippage > policy.max_slippage_bps:
        reject_reason = "slippage_too_high"
    elif depth_score is not None and depth_score < policy.min_depth_score:
        reject_reason = "depth_too_thin"
    elif volatility_score is not None and volatility_score > policy.vol_spike_max:
        reject_reason = "volatility_spike"
    elif latency is not None and latency > policy.max_latency_ms:
        reject_reason = "latency_too_high"

    allowed = reject_reason is None
    features["algo_id"] = algo_id
    return ExecutionGateDecision(
        allowed=allowed,
        decision="trade_allowed" if allowed else "no_trade",
        reject_reason=reject_reason,
        expected_return_bps=expected_return,
        expected_cost_bps=expected_cost,
        spread_bps=spread,
        expected_slippage_bps=slippage,
        depth_score=depth_score,
        volatility_score=volatility_score,
        api_latency_ms=latency,
        policy=policy,
        evaluated_at=evaluated_at,
        feature_snapshot=features,
        risk_snapshot=risk_snapshot,
    )
