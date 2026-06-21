"""Realtime spot risk-state scoring for shadow conditional trading."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import execution_rules, parameters

STATE_NORMAL = "NORMAL"
STATE_CAUTION = "CAUTION"
STATE_BLOCK_ENTRY = "BLOCK_ENTRY"
STATE_EXIT_CANDIDATE = "EXIT_CANDIDATE"
STATE_FORCE_EXIT_CANDIDATE = "FORCE_EXIT_CANDIDATE"
STATE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RealtimeRiskPolicy:
    history_windows: int = parameters.REALTIME_RISK_HISTORY_WINDOWS
    sustained_windows: int = parameters.REALTIME_RISK_SUSTAINED_WINDOWS
    caution_threshold: float = parameters.REALTIME_RISK_CAUTION_THRESHOLD
    block_entry_threshold: float = parameters.REALTIME_RISK_BLOCK_ENTRY_THRESHOLD
    exit_candidate_threshold: float = parameters.REALTIME_RISK_EXIT_CANDIDATE_THRESHOLD
    force_exit_threshold: float = parameters.REALTIME_RISK_FORCE_EXIT_THRESHOLD
    volatility_weight: float = parameters.REALTIME_RISK_WEIGHT_VOLATILITY_SPIKE
    spread_weight: float = parameters.REALTIME_RISK_WEIGHT_SPREAD_WIDENING
    depth_weight: float = parameters.REALTIME_RISK_WEIGHT_DEPTH_COLLAPSE
    volume_weight: float = parameters.REALTIME_RISK_WEIGHT_VOLUME_SHOCK
    order_flow_weight: float = parameters.REALTIME_RISK_WEIGHT_ORDER_FLOW_IMBALANCE
    slippage_weight: float = parameters.REALTIME_RISK_WEIGHT_EXPECTED_SLIPPAGE
    futures_weight: float = parameters.REALTIME_RISK_WEIGHT_FUTURES_STRESS


@dataclass(frozen=True)
class RealtimeRiskDecision:
    symbol: str
    window_start: datetime
    window_end: datetime
    risk_state: str
    risk_score: float | None
    component_scores: dict[str, float | None]
    trigger_reasons: list[str]
    recommended_action: str
    quality_status: str
    feature_snapshot: dict[str, Any]
    baseline_snapshot: dict[str, Any]
    policy: RealtimeRiskPolicy
    evaluated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_model_version": parameters.REALTIME_RISK_MODEL_VERSION,
            "symbol": self.symbol,
            "window_start": execution_rules.format_utc_timestamp(self.window_start),
            "window_end": execution_rules.format_utc_timestamp(self.window_end),
            "risk_state": self.risk_state,
            "risk_score": self.risk_score,
            "component_scores": self.component_scores,
            "trigger_reasons": self.trigger_reasons,
            "recommended_action": self.recommended_action,
            "quality_status": self.quality_status,
            "feature_snapshot": self.feature_snapshot,
            "baseline_snapshot": self.baseline_snapshot,
            "policy": policy_snapshot(self.policy),
            "evaluated_at": execution_rules.format_utc_timestamp(self.evaluated_at),
            "spot_execution_only": True,
        }


def policy_snapshot(policy: RealtimeRiskPolicy | None = None) -> dict[str, Any]:
    policy = policy or RealtimeRiskPolicy()
    return {
        "risk_model_version": parameters.REALTIME_RISK_MODEL_VERSION,
        "history_windows": policy.history_windows,
        "sustained_windows": policy.sustained_windows,
        "thresholds": {
            "caution": policy.caution_threshold,
            "block_entry": policy.block_entry_threshold,
            "exit_candidate": policy.exit_candidate_threshold,
            "force_exit_candidate": policy.force_exit_threshold,
        },
        "weights": {
            "volatility_spike": policy.volatility_weight,
            "spread_widening": policy.spread_weight,
            "depth_collapse": policy.depth_weight,
            "volume_shock": policy.volume_weight,
            "order_flow_imbalance": policy.order_flow_weight,
            "expected_slippage": policy.slippage_weight,
            "futures_stress": policy.futures_weight,
        },
    }


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _quantile(values: list[float], quantile: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    index = (len(clean) - 1) * quantile
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return clean[lower]
    fraction = index - lower
    return clean[lower] * (1.0 - fraction) + clean[upper] * fraction


def _series(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [value for row in rows for value in [_float(row.get(field))] if value is not None]


def _min_depth(row: dict[str, Any]) -> float | None:
    bid = _float(row.get("depth_10bp_bid_usd"))
    ask = _float(row.get("depth_10bp_ask_usd"))
    if bid is None or ask is None:
        return None
    return min(bid, ask)


def _baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    min_depths = [value for row in rows for value in [_min_depth(row)] if value is not None]
    baseline: dict[str, Any] = {}
    for field in (
        "spread_bps_avg",
        "expected_slippage_bps",
        "realized_volatility_5m",
        "trade_quote_volume",
    ):
        values = _series(rows, field)
        baseline[field] = {
            "p05": _quantile(values, 0.05),
            "median": _quantile(values, 0.50),
            "p95": _quantile(values, 0.95),
            "count": len(values),
        }
    baseline["min_depth_usd"] = {
        "p05": _quantile(min_depths, 0.05),
        "median": _quantile(min_depths, 0.50),
        "p95": _quantile(min_depths, 0.95),
        "count": len(min_depths),
    }
    return baseline


def _high_bad_score(
    value: float | None, stats: dict[str, Any], fallback_scale: float
) -> float | None:
    if value is None:
        return None
    median = _float(stats.get("median"))
    p95 = _float(stats.get("p95"))
    if median is not None and p95 is not None and p95 > median:
        return _clamp((value - median) / (p95 - median))
    return _clamp(value / fallback_scale)


def _low_bad_score(value: float | None, stats: dict[str, Any]) -> float | None:
    if value is None:
        return None
    median = _float(stats.get("median"))
    p05 = _float(stats.get("p05"))
    if median is None or p05 is None:
        return None
    if median <= p05:
        return _clamp((median - value) / median) if median > 0 and value < median else 0.0
    return _clamp((median - value) / (median - p05))


def _futures_stress_score(market_features: dict[str, Any]) -> float | None:
    if not market_features:
        return None
    latest_funding = abs(_float(market_features.get("latest_funding_rate")) or 0.0)
    funding_24h = abs(_float(market_features.get("funding_rate_24h")) or 0.0)
    oi_change = abs(_float(market_features.get("open_interest_change_24h")) or 0.0)
    basis = abs(_float(market_features.get("mark_spot_basis")) or 0.0)
    if latest_funding == 0.0 and funding_24h == 0.0 and oi_change == 0.0 and basis == 0.0:
        return None
    return max(
        _clamp(latest_funding / 0.001),
        _clamp(funding_24h / 0.003),
        _clamp(oi_change / 0.10),
        _clamp(basis / 0.01),
    )


def _state_for_score(
    score: float,
    *,
    recent_scores: list[float],
    policy: RealtimeRiskPolicy,
) -> str:
    force_count = sum(value >= policy.force_exit_threshold for value in recent_scores)
    exit_count = sum(value >= policy.exit_candidate_threshold for value in recent_scores)
    if score >= policy.force_exit_threshold and force_count >= policy.sustained_windows:
        return STATE_FORCE_EXIT_CANDIDATE
    if score >= policy.exit_candidate_threshold and exit_count >= policy.sustained_windows:
        return STATE_EXIT_CANDIDATE
    if score >= policy.block_entry_threshold:
        return STATE_BLOCK_ENTRY
    if score >= policy.caution_threshold:
        return STATE_CAUTION
    return STATE_NORMAL


def _recommended_action(risk_state: str) -> str:
    return {
        STATE_NORMAL: "allow_4h_signal",
        STATE_CAUTION: "shadow_reduce_size_post_only",
        STATE_BLOCK_ENTRY: "shadow_block_new_spot_buy",
        STATE_EXIT_CANDIDATE: "shadow_tighten_stop_or_partial_exit_candidate",
        STATE_FORCE_EXIT_CANDIDATE: "shadow_force_exit_candidate",
        STATE_UNKNOWN: "ignore_for_live_decision",
    }[risk_state]


def evaluate_realtime_risk(
    *,
    feature_row: dict[str, Any],
    history_rows: list[dict[str, Any]] | None = None,
    market_features: dict[str, Any] | None = None,
    recent_scores: list[float] | None = None,
    evaluated_at: datetime | None = None,
    policy: RealtimeRiskPolicy | None = None,
) -> RealtimeRiskDecision:
    policy = policy or RealtimeRiskPolicy()
    evaluated_at = execution_rules.parse_utc_datetime(evaluated_at or datetime.now(timezone.utc))
    history = (history_rows or [])[-policy.history_windows :]
    baseline = _baseline(history or [feature_row])
    quality_errors = list(feature_row.get("quality_errors") or [])
    core_fields = {
        "spread_bps_avg": _float(feature_row.get("spread_bps_avg")),
        "expected_slippage_bps": _float(feature_row.get("expected_slippage_bps")),
        "depth_10bp_bid_usd": _float(feature_row.get("depth_10bp_bid_usd")),
        "depth_10bp_ask_usd": _float(feature_row.get("depth_10bp_ask_usd")),
        "last_price": _float(feature_row.get("last_price")),
    }
    missing_core = [key for key, value in core_fields.items() if value is None]
    if missing_core:
        quality_errors.extend(f"missing_{key}" for key in missing_core)

    symbol = str(feature_row.get("symbol") or parameters.BINANCE_SYMBOL)
    window_start = execution_rules.parse_utc_datetime(feature_row["window_start"])
    window_end = execution_rules.parse_utc_datetime(feature_row["window_end"])
    feature_snapshot = dict(feature_row)
    market_features = market_features or {}
    if market_features:
        feature_snapshot["futures_auxiliary_features"] = market_features

    if missing_core:
        return RealtimeRiskDecision(
            symbol=symbol,
            window_start=window_start,
            window_end=window_end,
            risk_state=STATE_UNKNOWN,
            risk_score=None,
            component_scores={},
            trigger_reasons=quality_errors,
            recommended_action=_recommended_action(STATE_UNKNOWN),
            quality_status="degraded",
            feature_snapshot=feature_snapshot,
            baseline_snapshot=baseline,
            policy=policy,
            evaluated_at=evaluated_at,
        )

    min_depth = _min_depth(feature_row)
    aggressive_sell_ratio = _float(feature_row.get("aggressive_sell_ratio"))
    orderbook_imbalance = _float(feature_row.get("orderbook_imbalance"))
    order_flow_score = None
    if aggressive_sell_ratio is not None or orderbook_imbalance is not None:
        sell_pressure = max(0.0, (aggressive_sell_ratio or 0.0) - 0.5) * 2.0
        thin_bid_pressure = max(0.0, -(orderbook_imbalance or 0.0))
        order_flow_score = _clamp(max(sell_pressure, thin_bid_pressure))

    component_scores = {
        "volatility_spike": _high_bad_score(
            _float(feature_row.get("realized_volatility_5m"))
            or _float(feature_row.get("realized_volatility_1m")),
            baseline["realized_volatility_5m"],
            0.01,
        ),
        "spread_widening": max(
            _high_bad_score(
                _float(feature_row.get("spread_bps_avg")),
                baseline["spread_bps_avg"],
                10.0,
            )
            or 0.0,
            _clamp((_float(feature_row.get("spread_widening_bps_per_min")) or 0.0) / 5.0),
        ),
        "depth_collapse": max(
            _low_bad_score(min_depth, baseline["min_depth_usd"]) or 0.0,
            _float(feature_row.get("depth_collapse_ratio")) or 0.0,
        ),
        "volume_shock": max(
            _high_bad_score(
                _float(feature_row.get("trade_quote_volume")),
                baseline["trade_quote_volume"],
                5_000_000.0,
            )
            or 0.0,
            _float(feature_row.get("volume_spike")) or 0.0,
        ),
        "order_flow_imbalance": order_flow_score,
        "expected_slippage": _high_bad_score(
            _float(feature_row.get("expected_slippage_bps")),
            baseline["expected_slippage_bps"],
            10.0,
        ),
        "futures_stress": _futures_stress_score(market_features),
    }

    weighted = {
        "volatility_spike": policy.volatility_weight,
        "spread_widening": policy.spread_weight,
        "depth_collapse": policy.depth_weight,
        "volume_shock": policy.volume_weight,
        "order_flow_imbalance": policy.order_flow_weight,
        "expected_slippage": policy.slippage_weight,
        "futures_stress": policy.futures_weight,
    }
    numerator = 0.0
    denominator = 0.0
    for name, weight in weighted.items():
        value = component_scores.get(name)
        if value is None:
            continue
        numerator += weight * value
        denominator += weight
    risk_score = numerator / denominator if denominator > 0 else 0.0
    recent = [value for value in (recent_scores or [])[-(policy.sustained_windows - 1) :]]
    recent.append(risk_score)
    risk_state = _state_for_score(risk_score, recent_scores=recent, policy=policy)
    trigger_reasons = [
        name for name, value in component_scores.items() if value is not None and value >= 0.75
    ]

    return RealtimeRiskDecision(
        symbol=symbol,
        window_start=window_start,
        window_end=window_end,
        risk_state=risk_state,
        risk_score=risk_score,
        component_scores=component_scores,
        trigger_reasons=trigger_reasons,
        recommended_action=_recommended_action(risk_state),
        quality_status="ok" if not quality_errors else "degraded",
        feature_snapshot=feature_snapshot,
        baseline_snapshot=baseline,
        policy=policy,
        evaluated_at=evaluated_at,
    )
