"""Validation rubric for arena backtest outputs."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import execution_rules, parameters, risk

EVALUATOR_VERSION = "arena-backtest-validation-v1"
RET_TOLERANCE = 1e-9
PRICE_TOLERANCE = 1e-8
MIN_RESEARCH_BARS = 180
MIN_TRADES_PER_ALGO = 30


@dataclass(frozen=True)
class ValidationCheck:
    check_name: str
    category: str
    status: str
    severity: str
    message: str
    observed: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    validation_run_id: str
    backtest_run_id: str
    checked_at: datetime
    status: str
    checks: list[ValidationCheck]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "pass": sum(1 for check in self.checks if check.status == "pass"),
            "warn": sum(1 for check in self.checks if check.status == "warn"),
            "fail": sum(1 for check in self.checks if check.status == "fail"),
            "na": sum(1 for check in self.checks if check.status == "na"),
        }


def _parse_dt(value: Any) -> datetime:
    return execution_rules.parse_utc_datetime(value)


def _iso(value: datetime) -> str:
    return execution_rules.format_utc_timestamp(value)


def _approx_equal(left: float, right: float, tolerance: float) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def _overall_status(checks: list[ValidationCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _settings_from_run(run: dict[str, Any]) -> dict[str, Any]:
    rules = run.get("rules_snapshot") or {}
    params = run.get("params_snapshot") or {}
    schedule = params.get("schedule") or {}
    risk_defaults = params.get("risk_defaults") or {}
    return {
        "fee_bps": float(run.get("fee_bps") or rules.get("fee_bps") or parameters.FEE_BPS),
        "slippage_bps": float(run.get("slippage_bps") or rules.get("slippage_bps") or 0.0),
        "macro_stale_hours": float(
            rules.get("macro_stale_hours")
            or risk_defaults.get("macro_stale_hours")
            or parameters.MACRO_STALE_HOURS
        ),
        "min_hold_hours": (
            rules.get("min_hold_hours")
            or schedule.get("min_hold_hours")
            or parameters.MIN_HOLD_HOURS
        ),
        "min_hold_fallback_hours": float(
            schedule.get("min_hold_fallback_hours") or parameters.MIN_HOLD_FALLBACK_HOURS
        ),
        "portfolio_risk": rules.get("portfolio_risk") or risk.policy_snapshot(),
    }


def _risk_policy_from_run(run: dict[str, Any]) -> risk.PortfolioRiskPolicy:
    policy = _settings_from_run(run)["portfolio_risk"]
    return risk.PortfolioRiskPolicy(
        risk_model_version=policy.get("risk_model_version", parameters.RISK_MODEL_VERSION),
        position_unit=float(policy.get("position_unit", parameters.POSITION_UNIT)),
        max_open_positions_total=int(
            policy.get("max_open_positions_total", parameters.MAX_OPEN_POSITIONS_TOTAL)
        ),
        max_long_positions=int(policy.get("max_long_positions", parameters.MAX_LONG_POSITIONS)),
        max_short_positions=int(policy.get("max_short_positions", parameters.MAX_SHORT_POSITIONS)),
        max_net_long_exposure=float(
            policy.get("max_net_long_exposure", parameters.MAX_NET_LONG_EXPOSURE)
        ),
        max_net_short_exposure=float(
            policy.get("max_net_short_exposure", parameters.MAX_NET_SHORT_EXPOSURE)
        ),
        daily_loss_limit_pct=float(
            policy.get("daily_loss_limit_pct", parameters.DAILY_LOSS_LIMIT_PCT)
        ),
        algo_max_drawdown_kill_pct=float(
            policy.get("algo_max_drawdown_kill_pct", parameters.ALGO_MAX_DRAWDOWN_KILL_PCT)
        ),
        cooldown_after_kill_hours=float(
            policy.get("cooldown_after_kill_hours", parameters.COOLDOWN_AFTER_KILL_HOURS)
        ),
    )


def _bars_by_close_time(bars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_iso(_parse_dt(row["close_time"])): row for row in bars}


def _check_equity_row_count(
    run: dict[str, Any],
    equity_rows: list[dict[str, Any]],
) -> ValidationCheck:
    algo_ids = run.get("algo_ids") or []
    expected = int(run.get("bar_count") or 0) * len(algo_ids)
    observed = len(equity_rows)
    return ValidationCheck(
        check_name="equity_row_count",
        category="integrity",
        status="pass" if observed == expected else "fail",
        severity="critical",
        message="equity_curve row count matches bar_count * algo_count"
        if observed == expected
        else "equity_curve row count mismatch",
        observed={"equity_rows": observed},
        expected={"equity_rows": expected},
    )


def _check_equity_unique_key(equity_rows: list[dict[str, Any]]) -> ValidationCheck:
    keys = {
        (row.get("backtest_run_id"), row.get("algo_id"), row.get("data_timestamp"))
        for row in equity_rows
    }
    duplicate_count = len(equity_rows) - len(keys)
    return ValidationCheck(
        check_name="equity_unique_key",
        category="integrity",
        status="pass" if duplicate_count == 0 else "fail",
        severity="critical",
        message="equity_curve has unique run/algo/timestamp rows"
        if duplicate_count == 0
        else "equity_curve has duplicate run/algo/timestamp rows",
        observed={"duplicate_count": duplicate_count},
        expected={"duplicate_count": 0},
    )


def _check_trade_time_and_price(trades: list[dict[str, Any]]) -> ValidationCheck:
    bad_rows = []
    for trade in trades:
        open_time = _parse_dt(trade["open_time"])
        close_time = _parse_dt(trade["close_time"])
        bad = (
            close_time < open_time
            or float(trade.get("hold_hours") or 0) < -1e-9
            or float(trade.get("open_price") or 0) <= 0
            or float(trade.get("close_price") or 0) <= 0
        )
        if bad:
            bad_rows.append(trade.get("id"))
    return ValidationCheck(
        check_name="trade_time_and_price_integrity",
        category="integrity",
        status="pass" if not bad_rows else "fail",
        severity="critical",
        message="trade time order, hold_hours, and prices are valid"
        if not bad_rows
        else "invalid trade time order, hold_hours, or prices detected",
        observed={"bad_trade_ids": bad_rows, "bad_count": len(bad_rows)},
        expected={"bad_count": 0},
    )


def _check_trade_snapshots(trades: list[dict[str, Any]]) -> ValidationCheck:
    bad_rows = [
        trade.get("id")
        for trade in trades
        if not trade.get("params_snapshot")
        or not trade.get("indicator_snapshot")
        or trade.get("macro_snapshot") is None
    ]
    return ValidationCheck(
        check_name="trade_snapshots_present",
        category="integrity",
        status="pass" if not bad_rows else "fail",
        severity="high",
        message="trade params/indicator/macro snapshots are present"
        if not bad_rows
        else "missing trade snapshots detected",
        observed={"bad_trade_ids": bad_rows, "bad_count": len(bad_rows)},
        expected={"bad_count": 0},
    )


def _check_risk_snapshots(
    run: dict[str, Any],
    trades: list[dict[str, Any]],
) -> ValidationCheck:
    has_policy = bool((run.get("rules_snapshot") or {}).get("portfolio_risk"))
    missing_trade_ids = [trade.get("id") for trade in trades if not trade.get("risk_snapshot")]
    strict = run.get("risk_model_version") == "portfolio-risk-v1"
    status = "pass"
    message = "portfolio risk policy and trade risk snapshots are present"
    if not has_policy or missing_trade_ids:
        status = "fail" if strict else "warn"
        message = "portfolio risk snapshot missing; older runs have weaker risk auditability"
    return ValidationCheck(
        check_name="portfolio_risk_snapshots_present",
        category="risk",
        status=status,
        severity="high" if strict else "medium",
        message=message,
        observed={
            "has_policy": has_policy,
            "missing_trade_risk_snapshots": len(missing_trade_ids),
        },
        expected={"has_policy": True, "missing_trade_risk_snapshots": 0},
        details={"missing_trade_ids": missing_trade_ids[:20]},
    )


def _check_portfolio_exposure_bounds(
    run: dict[str, Any],
    equity_rows: list[dict[str, Any]],
) -> ValidationCheck:
    if not (run.get("rules_snapshot") or {}).get("portfolio_risk"):
        return ValidationCheck(
            check_name="portfolio_exposure_bounds",
            category="risk",
            status="warn",
            severity="medium",
            message="portfolio risk policy missing; older runs cannot be exposure-audited",
            observed={"has_policy": False},
            expected={"has_policy": True},
        )

    policy = _risk_policy_from_run(run)
    positions_by_time: dict[str, list[dict[str, Any]]] = {}
    for row in equity_rows:
        position = row.get("open_position")
        if not position:
            continue
        positions_by_time.setdefault(row["data_timestamp"], []).append(position)

    bad_rows = []
    for data_timestamp, positions in positions_by_time.items():
        exposure = risk.exposure_snapshot(positions, position_unit=policy.position_unit)
        bad = (
            exposure.open_positions_total > policy.max_open_positions_total
            or exposure.long_positions > policy.max_long_positions
            or exposure.short_positions > policy.max_short_positions
            or exposure.net_long_exposure > policy.max_net_long_exposure
            or exposure.net_short_exposure > policy.max_net_short_exposure
        )
        if bad:
            bad_rows.append(
                {
                    "data_timestamp": data_timestamp,
                    "exposure": exposure.as_dict(),
                }
            )
    return ValidationCheck(
        check_name="portfolio_exposure_bounds",
        category="risk",
        status="pass" if not bad_rows else "fail",
        severity="critical",
        message="equity path respects portfolio exposure limits"
        if not bad_rows
        else "portfolio exposure limit violation detected",
        observed={"bad_count": len(bad_rows)},
        expected={"bad_count": 0},
        details={"bad_rows": bad_rows[:20]},
    )


def _check_risk_event_consistency(risk_events: list[dict[str, Any]]) -> ValidationCheck:
    if not risk_events:
        return ValidationCheck(
            check_name="risk_event_consistency",
            category="risk",
            status="na",
            severity="low",
            message="no risk gate block events in this backtest run",
            observed={"risk_events": 0},
            expected={"checked_when_events_exist": True},
        )
    bad_rows = []
    for event in risk_events:
        decision = event.get("risk_decision") or {}
        if decision.get("allowed") is not False or event.get("event_type") != decision.get(
            "reason"
        ):
            bad_rows.append(
                {
                    "algo_id": event.get("algo_id"),
                    "data_timestamp": event.get("data_timestamp"),
                    "event_type": event.get("event_type"),
                    "decision_reason": decision.get("reason"),
                    "allowed": decision.get("allowed"),
                }
            )
    return ValidationCheck(
        check_name="risk_event_consistency",
        category="risk",
        status="pass" if not bad_rows else "fail",
        severity="high",
        message="risk events match blocked risk decisions"
        if not bad_rows
        else "risk event does not match blocked risk decision",
        observed={"risk_events": len(risk_events), "bad_count": len(bad_rows)},
        expected={"bad_count": 0},
        details={"bad_rows": bad_rows[:20]},
    )


def _check_fee_recalculation(
    run: dict[str, Any],
    trades: list[dict[str, Any]],
) -> ValidationCheck:
    settings = _settings_from_run(run)
    bad_rows = []
    for trade in trades:
        fee_adjusted = execution_rules.fee_adjusted_return_pct(
            direction=trade["direction"],
            open_price=float(trade["open_price"]),
            close_price=float(trade["close_price"]),
            fee_bps=settings["fee_bps"],
            slippage_bps=settings["slippage_bps"],
        )
        expected = fee_adjusted + float(trade.get("funding_ret_pct") or 0.0)
        observed = float(trade["ret_pct"])
        if not _approx_equal(observed, expected, RET_TOLERANCE):
            bad_rows.append(
                {
                    "trade_id": trade.get("id"),
                    "observed_ret_pct": observed,
                    "expected_ret_pct": expected,
                }
            )
    return ValidationCheck(
        check_name="fee_adjusted_return_replay",
        category="execution",
        status="pass" if not bad_rows else "fail",
        severity="critical",
        message="stored ret_pct matches shared fee/slippage/funding return rule"
        if not bad_rows
        else "stored ret_pct does not match shared fee/slippage/funding return rule",
        observed={"bad_count": len(bad_rows)},
        expected={"bad_count": 0},
        details={"bad_rows": bad_rows[:20]},
    )


def _check_min_hold(run: dict[str, Any], trades: list[dict[str, Any]]) -> ValidationCheck:
    settings = _settings_from_run(run)
    bad_rows = []
    for trade in trades:
        if trade.get("exit_reason") not in {"signal_flat", "signal_reverse"}:
            continue
        threshold = float(
            settings["min_hold_hours"].get(
                trade["algo_id"],
                settings["min_hold_fallback_hours"],
            )
        )
        hold_hours = float(trade.get("hold_hours") or 0)
        if hold_hours + 1e-9 < threshold:
            bad_rows.append(
                {
                    "trade_id": trade.get("id"),
                    "algo_id": trade["algo_id"],
                    "hold_hours": hold_hours,
                    "required_hours": threshold,
                }
            )
    return ValidationCheck(
        check_name="min_hold_signal_exits",
        category="execution",
        status="pass" if not bad_rows else "fail",
        severity="high",
        message="signal-based exits respect min_hold"
        if not bad_rows
        else "signal-based exits violated min_hold",
        observed={"bad_count": len(bad_rows)},
        expected={"bad_count": 0},
        details={"bad_rows": bad_rows[:20]},
    )


def _check_stop_loss_fill(
    trades: list[dict[str, Any]],
    bars: list[dict[str, Any]],
) -> ValidationCheck:
    stop_trades = [trade for trade in trades if trade.get("exit_reason") == "stop_loss"]
    if not stop_trades:
        return ValidationCheck(
            check_name="stop_loss_fill_policy",
            category="execution",
            status="na",
            severity="low",
            message="no stop_loss trades in this backtest run",
            observed={"stop_loss_trades": 0},
            expected={"policy": "checked when stop_loss trades exist"},
        )

    bars_by_close = _bars_by_close_time(bars)
    bad_rows = []
    missing_bar_ids = []
    for trade in stop_trades:
        key = _iso(_parse_dt(trade["close_data_timestamp"]))
        bar = bars_by_close.get(key)
        if not bar:
            missing_bar_ids.append(trade.get("id"))
            continue
        direction = trade["direction"]
        stop_loss_price = float(trade["stop_loss_price"])
        bar_open = float(bar["open"])
        if direction == "long":
            triggered = float(bar["low"]) <= stop_loss_price
            expected_price = min(bar_open, stop_loss_price)
        else:
            triggered = float(bar["high"]) >= stop_loss_price
            expected_price = max(bar_open, stop_loss_price)
        if not triggered or not _approx_equal(
            float(trade["close_price"]), expected_price, PRICE_TOLERANCE
        ):
            bad_rows.append(
                {
                    "trade_id": trade.get("id"),
                    "direction": direction,
                    "close_price": trade["close_price"],
                    "expected_price": expected_price,
                    "triggered": triggered,
                }
            )

    status = "pass"
    message = "stop_loss trades are reachable by OHLC and use the configured fill policy"
    if bad_rows:
        status = "fail"
        message = "stop_loss fill policy mismatch detected"
    elif missing_bar_ids:
        status = "warn"
        message = "some stop_loss trades could not be joined to OHLC bars"
    return ValidationCheck(
        check_name="stop_loss_fill_policy",
        category="execution",
        status=status,
        severity="critical" if status == "fail" else "medium",
        message=message,
        observed={
            "stop_loss_trades": len(stop_trades),
            "bad_count": len(bad_rows),
            "missing_bar_count": len(missing_bar_ids),
        },
        expected={"bad_count": 0, "missing_bar_count": 0},
        details={"bad_rows": bad_rows[:20], "missing_bar_ids": missing_bar_ids[:20]},
    )


def _check_close_price_policy(
    trades: list[dict[str, Any]],
    bars: list[dict[str, Any]],
) -> ValidationCheck:
    checked_reasons = {"signal_flat", "signal_reverse", "end_of_data"}
    checked_trades = [trade for trade in trades if trade.get("exit_reason") in checked_reasons]
    bars_by_close = _bars_by_close_time(bars)
    bad_rows = []
    missing_bar_ids = []
    for trade in checked_trades:
        key = _iso(_parse_dt(trade["close_data_timestamp"]))
        bar = bars_by_close.get(key)
        if not bar:
            missing_bar_ids.append(trade.get("id"))
            continue
        expected_price = float(bar["close"])
        if not _approx_equal(float(trade["close_price"]), expected_price, PRICE_TOLERANCE):
            bad_rows.append(
                {
                    "trade_id": trade.get("id"),
                    "exit_reason": trade["exit_reason"],
                    "close_price": trade["close_price"],
                    "expected_close": expected_price,
                }
            )
    status = "pass"
    message = "signal/end exits use bar close price"
    if bad_rows:
        status = "fail"
        message = "signal/end exit close price mismatch detected"
    elif missing_bar_ids:
        status = "warn"
        message = "some signal/end exits could not be joined to OHLC bars"
    return ValidationCheck(
        check_name="signal_exit_close_price_policy",
        category="execution",
        status=status,
        severity="critical" if status == "fail" else "medium",
        message=message,
        observed={
            "checked_trades": len(checked_trades),
            "bad_count": len(bad_rows),
            "missing_bar_count": len(missing_bar_ids),
        },
        expected={"bad_count": 0, "missing_bar_count": 0},
        details={"bad_rows": bad_rows[:20], "missing_bar_ids": missing_bar_ids[:20]},
    )


def _check_macro_staleness(run: dict[str, Any], trades: list[dict[str, Any]]) -> ValidationCheck:
    threshold = _settings_from_run(run)["macro_stale_hours"]
    macro_trades = [trade for trade in trades if trade.get("macro_snapshot")]
    if not macro_trades:
        return ValidationCheck(
            check_name="macro_staleness",
            category="leakage",
            status="na",
            severity="low",
            message="no non-empty macro snapshots stored on trades",
            observed={"macro_trade_count": 0},
            expected={"macro_stale_hours_lte": threshold},
        )
    bad_rows = []
    for trade in macro_trades:
        stale_hours = trade["macro_snapshot"].get("stale_hours")
        if stale_hours is not None and float(stale_hours) > threshold:
            bad_rows.append(
                {
                    "trade_id": trade.get("id"),
                    "stale_hours": stale_hours,
                    "threshold": threshold,
                }
            )
    return ValidationCheck(
        check_name="macro_staleness",
        category="leakage",
        status="pass" if not bad_rows else "fail",
        severity="high",
        message="trade macro snapshots respect stale macro threshold"
        if not bad_rows
        else "stale macro snapshot used in trade",
        observed={"bad_count": len(bad_rows), "macro_trade_count": len(macro_trades)},
        expected={"bad_count": 0, "macro_stale_hours_lte": threshold},
        details={"bad_rows": bad_rows[:20]},
    )


def _check_macro_fetched_at_presence(trades: list[dict[str, Any]]) -> ValidationCheck:
    macro_trades = [trade for trade in trades if trade.get("macro_snapshot")]
    if not macro_trades:
        return ValidationCheck(
            check_name="macro_fetched_at_recorded",
            category="leakage",
            status="na",
            severity="low",
            message="no non-empty macro snapshots stored on trades",
            observed={"macro_trade_count": 0},
            expected={"macro_snapshot_field": "fetched_at"},
        )
    missing_ids = [
        trade.get("id") for trade in macro_trades if not trade["macro_snapshot"].get("fetched_at")
    ]
    return ValidationCheck(
        check_name="macro_fetched_at_recorded",
        category="leakage",
        status="pass" if not missing_ids else "warn",
        severity="medium",
        message="macro snapshots include fetched_at for temporal leakage audits"
        if not missing_ids
        else "some macro snapshots lack fetched_at; older runs have weaker leakage auditability",
        observed={"missing_count": len(missing_ids), "macro_trade_count": len(macro_trades)},
        expected={"missing_count": 0},
        details={"missing_trade_ids": missing_ids[:20]},
    )


def _check_end_of_data_impact(trades: list[dict[str, Any]]) -> ValidationCheck:
    end_trades = [trade for trade in trades if trade.get("exit_reason") == "end_of_data"]
    if not end_trades:
        return ValidationCheck(
            check_name="end_of_data_exit_impact",
            category="statistics",
            status="pass",
            severity="low",
            message="no forced end_of_data exits",
            observed={"end_of_data_trades": 0},
            expected={"end_of_data_ret_pct_flagged": True},
        )
    return ValidationCheck(
        check_name="end_of_data_exit_impact",
        category="statistics",
        status="warn",
        severity="medium",
        message="forced end_of_data exits exist; separate their PnL before judging strategy quality",
        observed={
            "end_of_data_trades": len(end_trades),
            "ret_pct_sum": sum(float(trade["ret_pct"]) for trade in end_trades),
        },
        expected={"interpretation": "do_not_treat_forced_exit_as_normal_signal_edge"},
    )


def _check_sample_size(run: dict[str, Any], trades: list[dict[str, Any]]) -> ValidationCheck:
    algo_ids = run.get("algo_ids") or []
    by_algo = {algo_id: 0 for algo_id in algo_ids}
    for trade in trades:
        by_algo[trade["algo_id"]] = by_algo.get(trade["algo_id"], 0) + 1
    sparse_algos = {
        algo_id: trade_count
        for algo_id, trade_count in by_algo.items()
        if trade_count < MIN_TRADES_PER_ALGO
    }
    bar_count = int(run.get("bar_count") or 0)
    too_few_bars = bar_count < MIN_RESEARCH_BARS
    status = "warn" if too_few_bars or sparse_algos else "pass"
    return ValidationCheck(
        check_name="research_sample_size",
        category="statistics",
        status=status,
        severity="medium" if status == "warn" else "info",
        message="sample size is sufficient for first-pass research"
        if status == "pass"
        else "sample size is too small for parameter tuning or strategy conclusions",
        observed={"bar_count": bar_count, "trade_count_by_algo": by_algo},
        expected={
            "min_bars": MIN_RESEARCH_BARS,
            "min_trades_per_algo": MIN_TRADES_PER_ALGO,
        },
        details={"sparse_algos": sparse_algos},
    )


def validate_backtest_bundle(
    *,
    run: dict[str, Any],
    trades: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    risk_events: list[dict[str, Any]] | None = None,
    validation_run_id: str | None = None,
) -> ValidationReport:
    risk_events = risk_events or []
    checks = [
        _check_equity_row_count(run, equity_rows),
        _check_equity_unique_key(equity_rows),
        _check_trade_time_and_price(trades),
        _check_trade_snapshots(trades),
        _check_risk_snapshots(run, trades),
        _check_fee_recalculation(run, trades),
        _check_min_hold(run, trades),
        _check_stop_loss_fill(trades, bars),
        _check_close_price_policy(trades, bars),
        _check_portfolio_exposure_bounds(run, equity_rows),
        _check_risk_event_consistency(risk_events),
        _check_macro_staleness(run, trades),
        _check_macro_fetched_at_presence(trades),
        _check_end_of_data_impact(trades),
        _check_sample_size(run, trades),
    ]
    return ValidationReport(
        validation_run_id=validation_run_id or str(uuid4()),
        backtest_run_id=run["backtest_run_id"],
        checked_at=datetime.now(timezone.utc),
        status=_overall_status(checks),
        checks=checks,
    )


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    counts = report.counts
    return {
        "validation_run_id": report.validation_run_id,
        "backtest_run_id": report.backtest_run_id,
        "checked_at": _iso(report.checked_at),
        "status": report.status,
        "counts": counts,
        "checks": [
            {
                "check_name": check.check_name,
                "category": check.category,
                "status": check.status,
                "severity": check.severity,
                "message": check.message,
                "observed": check.observed,
                "expected": check.expected,
                "details": check.details,
            }
            for check in report.checks
        ],
    }


def _run_row(report: ValidationReport) -> dict[str, Any]:
    counts = report.counts
    return {
        "validation_run_id": report.validation_run_id,
        "backtest_run_id": report.backtest_run_id,
        "checked_at": _iso(report.checked_at),
        "status": report.status,
        "evaluator_version": EVALUATOR_VERSION,
        "pass_count": counts["pass"],
        "warn_count": counts["warn"],
        "fail_count": counts["fail"],
        "na_count": counts["na"],
        "summary": {
            "status": report.status,
            "counts": counts,
            "failed_checks": [
                check.check_name for check in report.checks if check.status == "fail"
            ],
            "warning_checks": [
                check.check_name for check in report.checks if check.status == "warn"
            ],
        },
    }


def _check_rows(report: ValidationReport) -> list[dict[str, Any]]:
    return [
        {
            "validation_run_id": report.validation_run_id,
            "check_name": check.check_name,
            "category": check.category,
            "status": check.status,
            "severity": check.severity,
            "message": check.message,
            "observed": check.observed,
            "expected": check.expected,
            "details": check.details,
        }
        for check in report.checks
    ]


async def _fetch_all(builder: Any, *, chunk_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        res = await builder.range(offset, offset + chunk_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < chunk_size:
            return rows
        offset += chunk_size


async def latest_backtest_run_id(db: Any) -> str:
    res = (
        await db.table("arena_backtest_runs")
        .select("backtest_run_id")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RuntimeError("no arena_backtest_runs rows found")
    return res.data[0]["backtest_run_id"]


async def load_validation_bundle(db: Any, backtest_run_id: str) -> dict[str, Any]:
    run_res = (
        await db.table("arena_backtest_runs")
        .select("*")
        .eq("backtest_run_id", backtest_run_id)
        .single()
        .execute()
    )
    run = run_res.data
    trades = await _fetch_all(
        db.table("arena_backtest_trades")
        .select("*")
        .eq("backtest_run_id", backtest_run_id)
        .order("open_time")
    )
    equity_rows = await _fetch_all(
        db.table("arena_backtest_equity_curve")
        .select("*")
        .eq("backtest_run_id", backtest_run_id)
        .order("data_timestamp")
    )
    try:
        risk_events = await _fetch_all(
            db.table("arena_backtest_risk_events")
            .select("*")
            .eq("backtest_run_id", backtest_run_id)
            .order("data_timestamp")
        )
    except Exception:
        risk_events = []
    bars = await _fetch_all(
        db.table("arena_ohlcv_bars")
        .select("open_time,close_time,open,high,low,close")
        .eq("symbol", run["symbol"])
        .eq("interval", run["interval"])
        .gte("close_time", run["data_start"])
        .lte("close_time", run["data_end"])
        .order("close_time")
    )
    return {
        "run": run,
        "trades": trades,
        "equity_rows": equity_rows,
        "risk_events": risk_events,
        "bars": bars,
    }


async def save_validation_report(db: Any, report: ValidationReport) -> None:
    await db.table("arena_backtest_validation_runs").insert(_run_row(report)).execute()
    await db.table("arena_backtest_validation_checks").insert(_check_rows(report)).execute()


async def _amain(args: argparse.Namespace) -> int:
    from . import positions

    await positions.init()
    db = positions.db()
    backtest_run_id = args.run_id or await latest_backtest_run_id(db)
    bundle = await load_validation_bundle(db, backtest_run_id)
    report = validate_backtest_bundle(**bundle)
    if args.save:
        await save_validation_report(db, report)
    print(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2))
    if args.fail_on_critical:
        critical_fail = any(
            check.status == "fail" and check.severity in {"critical", "high"}
            for check in report.checks
        )
        return 1 if critical_fail else 0
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an arena backtest run.")
    parser.add_argument("--run-id", help="Backtest run id to validate. Defaults to latest run.")
    parser.add_argument("--latest", action="store_true", help="Explicitly validate latest run.")
    parser.add_argument(
        "--save", action="store_true", help="Persist validation results to Supabase."
    )
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit non-zero when a critical/high failure is found.",
    )
    args = parser.parse_args()
    if args.run_id and args.latest:
        parser.error("--run-id and --latest are mutually exclusive")
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
