"""Spot long/flat execution policy for live paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TARGET_PRODUCT = "spot"
POSITION_SEMANTICS = "spot_long_flat"
SHORT_SIGNAL_ACTION = "exit_or_no_trade"


@dataclass(frozen=True)
class SpotExecutionDecision:
    raw_signal: str | None
    executable_signal: str | None
    action: str
    close_reason: str | None = None
    skipped_reason: str | None = None
    should_open: bool = False
    should_close: bool = False
    legacy_short_close: bool = False

    def policy_snapshot(self) -> dict[str, Any]:
        return {
            "target_product": TARGET_PRODUCT,
            "position_semantics": POSITION_SEMANTICS,
            "short_signal_action": SHORT_SIGNAL_ACTION,
            "raw_signal": self.raw_signal,
            "executable_signal": self.executable_signal,
            "action": self.action,
            "close_reason": self.close_reason,
            "skipped_reason": self.skipped_reason,
            "allow_live_short": False,
            "spot_execution_only": True,
            "derivatives_data_usage": "research_features_only",
        }


def decide(raw_signal: str | None, current: dict[str, Any] | None) -> SpotExecutionDecision:
    """Map algorithm signals to spot-executable actions.

    Algorithms may still emit short for research signal quality. Live/paper spot
    execution can only be long or flat, so short becomes exit/no-trade.
    """
    current_direction = current.get("direction") if current else None

    if current_direction == "short":
        return SpotExecutionDecision(
            raw_signal=raw_signal,
            executable_signal=None,
            action="close_legacy_short",
            close_reason="spot_semantics_migration",
            should_close=True,
            legacy_short_close=True,
        )

    if raw_signal == "short":
        if current_direction == "long":
            return SpotExecutionDecision(
                raw_signal=raw_signal,
                executable_signal=None,
                action="close_spot_risk_off",
                close_reason="short_signal_spot_risk_off",
                should_close=True,
            )
        return SpotExecutionDecision(
            raw_signal=raw_signal,
            executable_signal=None,
            action="spot_short_no_trade",
            skipped_reason="spot_short_signal_no_position",
        )

    if raw_signal == "long":
        if current_direction == "long":
            return SpotExecutionDecision(
                raw_signal=raw_signal,
                executable_signal="long",
                action="hold",
            )
        return SpotExecutionDecision(
            raw_signal=raw_signal,
            executable_signal="long",
            action="open",
            should_open=True,
        )

    if current_direction == "long":
        return SpotExecutionDecision(
            raw_signal=raw_signal,
            executable_signal=None,
            action="close_flat",
            close_reason="flat_signal",
            should_close=True,
        )

    return SpotExecutionDecision(
        raw_signal=raw_signal,
        executable_signal=None,
        action="flat_skip",
    )
