"""Shadow parent-order and execution-quality estimates for Arena TCA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from . import execution_rules, frequency, parameters
from .execution_gate import ExecutionGateDecision


@dataclass(frozen=True)
class ShadowTcaRows:
    parent_order: dict[str, Any]
    execution_quality: dict[str, Any]


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_depth_levels(rows: Any) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _float(row[0])
        qty = _float(row[1])
        if price is not None and qty is not None and price > 0 and qty > 0:
            levels.append((price, qty))
    return levels


def depth_within_bps(
    levels: list[tuple[float, float]],
    *,
    mid: float,
    side: str,
    bps: float = 10.0,
) -> float | None:
    if mid <= 0 or not levels:
        return None
    if side == "bid":
        threshold = mid * (1.0 - bps / 10_000.0)
        included = [(price, qty) for price, qty in levels if price >= threshold]
    else:
        threshold = mid * (1.0 + bps / 10_000.0)
        included = [(price, qty) for price, qty in levels if price <= threshold]
    return sum(price * qty for price, qty in included)


def _arrival(features: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    bid = _float(features.get("last_bid"))
    ask = _float(features.get("last_ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None, bid, ask
    return (bid + ask) / 2.0, bid, ask


def _spread_bps(mid: float | None, bid: float | None, ask: float | None) -> float | None:
    if mid is None or bid is None or ask is None or mid <= 0:
        return None
    return (ask - bid) / mid * 10_000.0


def _sweep_slippage_bps(
    *,
    direction: str,
    mid: float | None,
    target_notional_usd: float,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> tuple[float | None, float | None, float | None]:
    if mid is None or mid <= 0 or target_notional_usd <= 0:
        return None, None, None
    target_qty = target_notional_usd / mid
    remaining = target_qty
    filled_qty = 0.0
    filled_quote = 0.0
    levels = asks if direction == "long" else bids
    for price, qty in levels:
        take_qty = min(remaining, qty)
        if take_qty <= 0:
            continue
        filled_qty += take_qty
        filled_quote += take_qty * price
        remaining -= take_qty
        if remaining <= 1e-12:
            break
    if filled_qty <= 0:
        return None, target_qty, 0.0
    avg_price = filled_quote / filled_qty
    sign = execution_rules.direction_sign(direction)
    slippage = sign * (avg_price / mid - 1.0) * 10_000.0
    fill_ratio = min(filled_qty / target_qty, 1.0)
    return max(slippage, 0.0), target_qty, fill_ratio


def build_shadow_tca_rows(
    *,
    run_id: str,
    algo_id: str,
    signal: str,
    timeframe: str,
    evaluated_at: datetime,
    gate_decision: ExecutionGateDecision,
    cost_scenario: frequency.CostScenario,
    target_notional_usd: float = parameters.SHADOW_ORDER_NOTIONAL_USD,
    timeout_sec: int = parameters.SHADOW_ORDER_TIMEOUT_SEC,
    arrival_benchmark_sec: int = parameters.SHADOW_ARRIVAL_BENCHMARK_SEC,
) -> ShadowTcaRows:
    features = dict(gate_decision.feature_snapshot)
    mid, bid, ask = _arrival(features)
    spread = gate_decision.spread_bps
    if spread is None:
        spread = _spread_bps(mid, bid, ask)
    bids = normalize_depth_levels(features.get("depth_bids"))
    asks = normalize_depth_levels(features.get("depth_asks"))
    sweep_slippage, target_qty, fill_ratio = _sweep_slippage_bps(
        direction=signal,
        mid=mid,
        target_notional_usd=target_notional_usd,
        bids=bids,
        asks=asks,
    )
    fallback_slippage = gate_decision.expected_slippage_bps
    estimated_slippage = sweep_slippage if sweep_slippage is not None else fallback_slippage
    quality_status = "ok" if mid is not None and sweep_slippage is not None else "degraded"
    estimated_total_cost = (
        2.0 * cost_scenario.fee_bps
        + (spread or 0.0)
        + (estimated_slippage or 0.0)
        + cost_scenario.funding_buffer_bps_per_8h
    )
    parent_order_id = str(uuid4())
    side = "buy" if signal == "long" else "sell"
    order_intent = "marketable_limit" if gate_decision.allowed else "no_trade"
    snapshot = {
        "mode": "shadow",
        "signal_time": execution_rules.format_utc_timestamp(evaluated_at),
        "timeframe": timeframe,
        "arrival_mid": mid,
        "arrival_bid": bid,
        "arrival_ask": ask,
        "arrival_spread_bps": spread,
        "arrival_benchmark_sec": arrival_benchmark_sec,
        "target_notional_usd": target_notional_usd,
        "target_qty": target_qty,
        "timeout_sec": timeout_sec,
        "gate_decision": gate_decision.as_dict(),
        "cost_scenario": cost_scenario.as_dict(),
    }
    quality_snapshot = {
        "mode": "shadow",
        "quality_status": quality_status,
        "order_intent": order_intent,
        "estimated_sweep_slippage_bps": sweep_slippage,
        "estimated_total_cost_bps": estimated_total_cost,
        "fallback_expected_slippage_bps": fallback_slippage,
        "target_notional_usd": target_notional_usd,
        "target_qty": target_qty,
        "fill_ratio": fill_ratio,
        "depth_levels": {
            "bid_count": len(bids),
            "ask_count": len(asks),
            "depth_10bp_bid_usd": features.get("depth_10bp_bid_usd"),
            "depth_10bp_ask_usd": features.get("depth_10bp_ask_usd"),
        },
    }
    return ShadowTcaRows(
        parent_order={
            "parent_order_id": parent_order_id,
            "run_id": run_id,
            "algo_id": algo_id,
            "symbol": features.get("symbol", parameters.BINANCE_SYMBOL),
            "side": side,
            "order_intent": order_intent,
            "target_weight": None,
            "decision_snapshot": snapshot,
            "status": "shadow",
        },
        execution_quality={
            "parent_order_id": parent_order_id,
            "run_id": run_id,
            "algo_id": algo_id,
            "expected_cost_bps": gate_decision.expected_cost_bps,
            "realized_cost_bps": estimated_total_cost,
            "realized_slippage_bps": estimated_slippage,
            "spread_at_entry_bps": spread,
            "fill_ratio": fill_ratio,
            "maker_taker_ratio": 0.0 if order_intent == "marketable_limit" else None,
            "partial_fill_ratio": (1.0 - fill_ratio) if fill_ratio is not None else None,
            "api_latency_ms": gate_decision.api_latency_ms,
            "quality_snapshot": quality_snapshot,
        },
    )
