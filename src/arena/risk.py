"""Portfolio-level risk gate shared by live trading and backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from . import execution_rules, parameters


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    risk_model_version: str = parameters.RISK_MODEL_VERSION
    position_unit: float = parameters.POSITION_UNIT
    max_open_positions_total: int = parameters.MAX_OPEN_POSITIONS_TOTAL
    max_long_positions: int = parameters.MAX_LONG_POSITIONS
    max_short_positions: int = parameters.MAX_SHORT_POSITIONS
    max_net_long_exposure: float = parameters.MAX_NET_LONG_EXPOSURE
    max_net_short_exposure: float = parameters.MAX_NET_SHORT_EXPOSURE
    daily_loss_limit_pct: float = parameters.DAILY_LOSS_LIMIT_PCT
    algo_max_drawdown_kill_pct: float = parameters.ALGO_MAX_DRAWDOWN_KILL_PCT
    cooldown_after_kill_hours: float = parameters.COOLDOWN_AFTER_KILL_HOURS


@dataclass(frozen=True)
class PortfolioRiskState:
    daily_realized_ret_pct: float = 0.0
    algo_drawdown_pct: Mapping[str, float] = field(default_factory=dict)
    killed_algos: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExposureSnapshot:
    open_positions_total: int
    long_positions: int
    short_positions: int
    gross_exposure: float
    net_exposure: float
    net_long_exposure: float
    net_short_exposure: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "open_positions_total": self.open_positions_total,
            "long_positions": self.long_positions,
            "short_positions": self.short_positions,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "net_long_exposure": self.net_long_exposure,
            "net_short_exposure": self.net_short_exposure,
        }


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    policy: PortfolioRiskPolicy
    current_exposure: ExposureSnapshot
    proposed_exposure: ExposureSnapshot
    state: PortfolioRiskState
    evaluated_at: datetime

    @property
    def action(self) -> str:
        return "allow" if self.allowed else "block"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "reason": self.reason,
            "policy": policy_snapshot(self.policy),
            "current_exposure": self.current_exposure.as_dict(),
            "proposed_exposure": self.proposed_exposure.as_dict(),
            "state": {
                "daily_realized_ret_pct": self.state.daily_realized_ret_pct,
                "algo_drawdown_pct": dict(self.state.algo_drawdown_pct),
                "killed_algos": dict(self.state.killed_algos),
            },
            "evaluated_at": execution_rules.format_utc_timestamp(self.evaluated_at),
        }


def default_policy() -> PortfolioRiskPolicy:
    return PortfolioRiskPolicy()


def policy_snapshot(policy: PortfolioRiskPolicy | None = None) -> dict[str, Any]:
    policy = policy or default_policy()
    return {
        "risk_model_version": policy.risk_model_version,
        "position_unit": policy.position_unit,
        "max_open_positions_total": policy.max_open_positions_total,
        "max_long_positions": policy.max_long_positions,
        "max_short_positions": policy.max_short_positions,
        "max_net_long_exposure": policy.max_net_long_exposure,
        "max_net_short_exposure": policy.max_net_short_exposure,
        "daily_loss_limit_pct": policy.daily_loss_limit_pct,
        "algo_max_drawdown_kill_pct": policy.algo_max_drawdown_kill_pct,
        "cooldown_after_kill_hours": policy.cooldown_after_kill_hours,
    }


def active_positions(open_positions: Mapping[str, Any]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for algo_id, position in open_positions.items():
        if not position:
            continue
        if isinstance(position, Mapping):
            row = dict(position)
        elif hasattr(position, "as_live_position"):
            row = position.as_live_position()
        elif hasattr(position, "as_snapshot"):
            row = position.as_snapshot()
        else:
            row = {
                "algo_id": getattr(position, "algo_id", algo_id),
                "direction": getattr(position, "direction", None),
                "status": "open",
            }
        row.setdefault("algo_id", algo_id)
        if row.get("status", "open") == "open":
            positions.append(row)
    return positions


def exposure_snapshot(
    open_positions: Mapping[str, Any] | list[dict[str, Any]],
    *,
    position_unit: float = parameters.POSITION_UNIT,
) -> ExposureSnapshot:
    rows = (
        active_positions(open_positions)
        if isinstance(open_positions, Mapping)
        else [dict(row) for row in open_positions if row]
    )
    long_count = sum(1 for row in rows if row.get("direction") == "long")
    short_count = sum(1 for row in rows if row.get("direction") == "short")
    net = (long_count - short_count) * position_unit
    return ExposureSnapshot(
        open_positions_total=long_count + short_count,
        long_positions=long_count,
        short_positions=short_count,
        gross_exposure=(long_count + short_count) * position_unit,
        net_exposure=net,
        net_long_exposure=max(net, 0.0),
        net_short_exposure=max(-net, 0.0),
    )


def _with_candidate(
    open_positions: Mapping[str, Any],
    *,
    algo_id: str,
    direction: str,
) -> dict[str, Any]:
    candidate = {key: value for key, value in open_positions.items() if value}
    candidate[algo_id] = {"algo_id": algo_id, "direction": direction, "status": "open"}
    return candidate


def evaluate_open(
    *,
    algo_id: str,
    direction: str,
    open_positions: Mapping[str, Any],
    state: PortfolioRiskState,
    evaluated_at: datetime,
    policy: PortfolioRiskPolicy | None = None,
) -> RiskDecision:
    policy = policy or default_policy()
    current = exposure_snapshot(open_positions, position_unit=policy.position_unit)
    proposed = exposure_snapshot(
        _with_candidate(open_positions, algo_id=algo_id, direction=direction),
        position_unit=policy.position_unit,
    )

    killed_reason = state.killed_algos.get(algo_id)
    if killed_reason:
        return RiskDecision(False, killed_reason, policy, current, proposed, state, evaluated_at)

    drawdown = state.algo_drawdown_pct.get(algo_id, 0.0)
    if drawdown <= -abs(policy.algo_max_drawdown_kill_pct):
        return RiskDecision(
            False,
            "algo_drawdown_kill",
            policy,
            current,
            proposed,
            state,
            evaluated_at,
        )

    if state.daily_realized_ret_pct <= -abs(policy.daily_loss_limit_pct):
        return RiskDecision(
            False,
            "daily_loss_limit",
            policy,
            current,
            proposed,
            state,
            evaluated_at,
        )

    if proposed.open_positions_total > policy.max_open_positions_total:
        return RiskDecision(
            False, "max_open_positions_total", policy, current, proposed, state, evaluated_at
        )
    if proposed.long_positions > policy.max_long_positions:
        return RiskDecision(
            False, "max_long_positions", policy, current, proposed, state, evaluated_at
        )
    if proposed.short_positions > policy.max_short_positions:
        return RiskDecision(
            False, "max_short_positions", policy, current, proposed, state, evaluated_at
        )
    if proposed.net_long_exposure > policy.max_net_long_exposure:
        return RiskDecision(
            False, "max_net_long_exposure", policy, current, proposed, state, evaluated_at
        )
    if proposed.net_short_exposure > policy.max_net_short_exposure:
        return RiskDecision(
            False, "max_net_short_exposure", policy, current, proposed, state, evaluated_at
        )

    return RiskDecision(True, "allowed", policy, current, proposed, state, evaluated_at)
