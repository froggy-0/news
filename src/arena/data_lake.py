"""Write-only capture layer for arena research data.

Trading decisions must keep running even if analytical capture tables are not
available yet, so every public writer logs and returns instead of raising.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import execution_rules, feature_registry, frequency, parameters, positions
from .execution_gate import ExecutionGateDecision
from .market_structure import MarketStructureSnapshot
from .realtime_risk import RealtimeRiskDecision
from .sleeves import AllocationDecision, SleeveSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureWriteResult:
    label: str
    ok: bool
    error: str | None = None


def new_run_id() -> str:
    return str(uuid4())


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def parse_binance_kline(
    kline: list[Any],
    *,
    run_id: str | None,
    fetched_at: datetime,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "exchange": "binance",
        "symbol": symbol,
        "interval": interval,
        "open_time": _ts(datetime.fromtimestamp(int(kline[0]) / 1000, tz=timezone.utc)),
        "open": float(kline[1]),
        "high": float(kline[2]),
        "low": float(kline[3]),
        "close": float(kline[4]),
        "volume": float(kline[5]),
        "close_time": _ts(datetime.fromtimestamp(int(kline[6]) / 1000, tz=timezone.utc)),
        "quote_volume": float(kline[7]) if len(kline) > 7 else None,
        "trade_count": int(kline[8]) if len(kline) > 8 else None,
        "taker_buy_base_volume": float(kline[9]) if len(kline) > 9 else None,
        "taker_buy_quote_volume": float(kline[10]) if len(kline) > 10 else None,
        "raw_payload": kline,
        "fetched_at": _ts(fetched_at),
    }


def _capture_health(results: list[CaptureWriteResult]) -> dict[str, Any]:
    warnings = [
        {"label": result.label, "error": result.error} for result in results if not result.ok
    ]
    return {
        "capture_status": "ok" if not warnings else "degraded",
        "capture_error_count": len(warnings),
        "capture_warnings": warnings,
    }


def _run_ohlcv_input_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": row["run_id"],
            "exchange": row["exchange"],
            "symbol": row["symbol"],
            "interval": row["interval"],
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "input_position": position,
            "fetched_at": row["fetched_at"],
        }
        for position, row in enumerate(rows)
    ]


async def _safe_execute(label: str, builder: Any) -> CaptureWriteResult:
    try:
        await builder.execute()
        return CaptureWriteResult(label=label, ok=True)
    except Exception as exc:
        logger.warning("Arena data lake write failed: %s (%s)", label, exc)
        return CaptureWriteResult(label=label, ok=False, error=str(exc))


async def _safe_execute_optional_constraint(
    label: str,
    builder: Any,
    *,
    constraint_name: str,
) -> CaptureWriteResult:
    try:
        await builder.execute()
        return CaptureWriteResult(label=label, ok=True)
    except Exception as exc:
        if constraint_name in str(exc):
            logger.info(
                "Arena optional write skipped by current DB constraint: %s (%s)",
                label,
                constraint_name,
            )
            return CaptureWriteResult(label=f"{label}.schema_skipped", ok=True)
        logger.warning("Arena data lake write failed: %s (%s)", label, exc)
        return CaptureWriteResult(label=label, ok=False, error=str(exc))


async def _safe_execute_optional_schema(
    label: str,
    builder: Any,
    *,
    object_name: str,
) -> CaptureWriteResult:
    try:
        await builder.execute()
        return CaptureWriteResult(label=label, ok=True)
    except Exception as exc:
        if object_name in str(exc):
            logger.info("Arena optional schema write skipped: %s (%s)", label, object_name)
            return CaptureWriteResult(label=f"{label}.schema_skipped", ok=True)
        logger.warning("Arena data lake write failed: %s (%s)", label, exc)
        return CaptureWriteResult(label=label, ok=False, error=str(exc))


async def _safe_execute_retryable_constraint(
    label: str,
    builder: Any,
    *,
    constraint_name: str,
) -> CaptureWriteResult:
    try:
        await builder.execute()
        return CaptureWriteResult(label=label, ok=True)
    except Exception as exc:
        if constraint_name in str(exc):
            logger.info(
                "Arena data lake write will retry with compatibility fallback: %s (%s)",
                label,
                constraint_name,
            )
        else:
            logger.warning("Arena data lake write failed: %s (%s)", label, exc)
        return CaptureWriteResult(label=label, ok=False, error=str(exc))


def _legacy_feature_registry_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**row, "layer": "raw_market"} if row.get("layer") == "market_structure" else row
        for row in rows
    ]


async def record_run_started(
    *,
    run_id: str,
    started_at: datetime,
    params_snapshot: dict[str, Any],
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    frequency_profile_id: str = frequency.LIVE_4H_PROFILE_ID,
    indicator_profile_id: str = frequency.DEFAULT_INDICATOR_PROFILE_ID,
    cost_model_version: str = frequency.COST_MODEL_VERSION,
    cost_scenario_id: str = frequency.DEFAULT_COST_SCENARIO_ID,
    product_type: str = parameters.TARGET_PRODUCT,
    position_semantics: str = parameters.POSITION_SEMANTICS,
) -> CaptureWriteResult:
    payload = {
        "run_id": run_id,
        "started_at": _ts(started_at),
        "status": "started",
        "runtime": parameters.RUNTIME,
        "symbol": symbol,
        "interval": interval,
        "strategy_version": parameters.STRATEGY_VERSION,
        "params_version": parameters.PARAMS_VERSION,
        "feature_set_version": parameters.FEATURE_SET_VERSION,
        "risk_model_version": parameters.RISK_MODEL_VERSION,
        "product_type": product_type,
        "position_semantics": position_semantics,
        "frequency_profile_id": frequency_profile_id,
        "indicator_profile_id": indicator_profile_id,
        "cost_model_version": cost_model_version,
        "cost_scenario_id": cost_scenario_id,
        "params_snapshot": params_snapshot,
    }
    result = await _safe_execute(
        "arena_runs.start", positions.db().table("arena_runs").insert(payload)
    )
    if not result.ok:
        legacy_payload = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "feature_set_version",
                "risk_model_version",
                "product_type",
                "position_semantics",
                "frequency_profile_id",
                "indicator_profile_id",
                "cost_model_version",
                "cost_scenario_id",
            }
        }
        return await _safe_execute(
            "arena_runs.start.legacy",
            positions.db().table("arena_runs").insert(legacy_payload),
        )
    return result


async def record_strategy_metadata(
    *,
    params_snapshot: dict[str, Any],
) -> list[CaptureWriteResult]:
    strategy_result = await _safe_execute(
        "arena_strategy_versions.upsert",
        positions.db()
        .table("arena_strategy_versions")
        .upsert(
            feature_registry.strategy_version_row(params_snapshot),
            on_conflict="strategy_version",
        ),
    )
    feature_rows = feature_registry.feature_registry_rows()
    feature_result = await _safe_execute_retryable_constraint(
        "arena_feature_registry.upsert",
        positions.db()
        .table("arena_feature_registry")
        .upsert(
            feature_rows,
            on_conflict="feature_set_version,feature_name",
        ),
        constraint_name="arena_feature_registry_layer_check",
    )
    if (
        not feature_result.ok
        and feature_result.error
        and "arena_feature_registry_layer_check" in feature_result.error
    ):
        feature_result = await _safe_execute(
            "arena_feature_registry.upsert.legacy_layer",
            positions.db()
            .table("arena_feature_registry")
            .upsert(
                _legacy_feature_registry_rows(feature_rows),
                on_conflict="feature_set_version,feature_name",
            ),
        )
    return [strategy_result, feature_result]


async def record_run_completed(
    *,
    run_id: str,
    completed_at: datetime,
    status: str,
    data_timestamp: datetime | None = None,
    error_message: str | None = None,
    capture_results: list[CaptureWriteResult] | None = None,
) -> CaptureWriteResult:
    payload = {
        "completed_at": _ts(completed_at),
        "status": status,
        "data_timestamp": _ts(data_timestamp),
        "error_message": error_message,
    }
    if capture_results is not None:
        payload.update(_capture_health(capture_results))

    result = await _safe_execute(
        "arena_runs.complete",
        positions.db().table("arena_runs").update(payload).eq("run_id", run_id),
    )
    if not result.ok and capture_results is not None:
        legacy_payload = {
            "completed_at": _ts(completed_at),
            "status": status,
            "data_timestamp": _ts(data_timestamp),
            "error_message": error_message,
        }
        return await _safe_execute(
            "arena_runs.complete.legacy",
            positions.db().table("arena_runs").update(legacy_payload).eq("run_id", run_id),
        )
    return result


async def record_ohlcv_bars(
    *,
    run_id: str,
    raw_klines: list[list[Any]],
    fetched_at: datetime,
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
) -> list[CaptureWriteResult]:
    rows = [
        parse_binance_kline(
            kline,
            run_id=run_id,
            fetched_at=fetched_at,
            symbol=symbol,
            interval=interval,
        )
        for kline in raw_klines
    ]
    if not rows:
        return []
    bar_result = await _safe_execute(
        "arena_ohlcv_bars.upsert",
        positions.db()
        .table("arena_ohlcv_bars")
        .upsert(rows, on_conflict="exchange,symbol,interval,open_time"),
    )
    input_result = await _safe_execute(
        "arena_run_ohlcv_bars.upsert",
        positions.db()
        .table("arena_run_ohlcv_bars")
        .upsert(
            _run_ohlcv_input_rows(rows),
            on_conflict="run_id,exchange,symbol,interval,open_time",
        ),
    )
    return [bar_result, input_result]


async def record_macro_snapshot(
    *,
    run_id: str,
    fetched_at: datetime,
    source_url: str,
    payload: dict[str, Any],
    signal: dict[str, Any],
) -> CaptureWriteResult:
    risk_overlay = payload.get("riskOverlay") if isinstance(payload, dict) else None
    row = {
        "run_id": run_id,
        "fetched_at": _ts(fetched_at),
        "source_url": source_url,
        "reference_date": signal.get("reference_date"),
        "stale_hours": signal.get("stale_hours"),
        "payload_hash": payload_hash(payload),
        "payload": payload,
        "risk_overlay": risk_overlay if isinstance(risk_overlay, dict) else {},
    }
    return await _safe_execute(
        "arena_macro_snapshots.insert",
        positions.db().table("arena_macro_snapshots").insert(row),
    )


async def record_indicator_snapshot(
    *,
    run_id: str,
    data_timestamp: datetime,
    indicators: dict[str, float],
    symbol: str = parameters.BINANCE_SYMBOL,
    interval: str = parameters.BINANCE_KLINE_INTERVAL,
    indicator_profile_id: str = frequency.DEFAULT_INDICATOR_PROFILE_ID,
    frequency_profile_id: str = frequency.LIVE_4H_PROFILE_ID,
) -> CaptureWriteResult:
    indicator_params = frequency.indicator_settings(
        interval=interval,
        indicator_profile_id=indicator_profile_id,
    ).as_dict()
    row = {
        "run_id": run_id,
        "symbol": symbol,
        "interval": interval,
        "data_timestamp": _ts(data_timestamp),
        "params_version": parameters.PARAMS_VERSION,
        "indicator_profile_id": indicator_profile_id,
        "indicator_params": indicator_params,
        "rsi": indicators.get("rsi"),
        "macd_hist": indicators.get("macd_hist"),
        "macd_hist_prev": indicators.get("macd_hist_prev"),
        "bb_pos": indicators.get("bb_pos"),
        "bb_width": indicators.get("bb_width"),
        "atr": indicators.get("atr"),
        "atr_pct": indicators.get("atr_pct"),
        "ema_fast": indicators.get("ema_fast"),
        "ema_slow": indicators.get("ema_slow"),
        "ema_fast_slope": indicators.get("ema_fast_slope"),
        "ema_slow_slope": indicators.get("ema_slow_slope"),
        "return_24h": indicators.get("return_24h"),
        "return_72h": indicators.get("return_72h"),
        "realized_vol_24h": indicators.get("realized_vol_24h"),
        "range_24h_atr": indicators.get("range_24h_atr"),
    }
    result = await _safe_execute(
        "arena_indicator_snapshots.insert",
        positions.db().table("arena_indicator_snapshots").insert(row),
    )
    if not result.ok and "column" in str(result.error):
        legacy_row = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "indicator_profile_id",
                "macd_hist_prev",
                "bb_width",
                "atr_pct",
                "ema_fast",
                "ema_slow",
                "ema_fast_slope",
                "ema_slow_slope",
                "return_24h",
                "return_72h",
                "realized_vol_24h",
                "range_24h_atr",
            }
        }
        return await _safe_execute(
            "arena_indicator_snapshots.insert.legacy",
            positions.db().table("arena_indicator_snapshots").insert(legacy_row),
        )
    return result


async def record_indicator_feature_bar(
    *,
    run_id: str,
    symbol: str,
    interval: str,
    data_timestamp: datetime,
    indicators: dict[str, float],
    indicator_profile_id: str,
    frequency_profile_id: str,
) -> CaptureWriteResult:
    row = {
        "symbol": symbol,
        "interval": interval,
        "indicator_profile_id": indicator_profile_id,
        "frequency_profile_id": frequency_profile_id,
        "data_timestamp": _ts(data_timestamp),
        "run_id": run_id,
        "params_version": parameters.PARAMS_VERSION,
        "indicator_params": frequency.indicator_settings(
            interval=interval,
            indicator_profile_id=indicator_profile_id,
        ).as_dict(),
        "features": indicators,
    }
    return await _safe_execute_optional_schema(
        "arena_indicator_feature_bars.upsert",
        positions.db()
        .table("arena_indicator_feature_bars")
        .upsert(row, on_conflict="symbol,interval,indicator_profile_id,data_timestamp"),
        object_name="arena_indicator_feature_bars",
    )


async def record_market_structure_snapshot(
    *,
    run_id: str,
    snapshot: MarketStructureSnapshot,
) -> list[CaptureWriteResult]:
    results: list[CaptureWriteResult] = []
    if snapshot.errors:
        results.append(
            CaptureWriteResult(
                label="arena_market_structure.fetch",
                ok=False,
                error="; ".join(snapshot.errors),
            )
        )

    if snapshot.funding_rates:
        results.append(
            await _safe_execute(
                "arena_funding_rates.upsert",
                positions.db()
                .table("arena_funding_rates")
                .upsert(
                    snapshot.funding_rates,
                    on_conflict="exchange,symbol,funding_time",
                ),
            )
        )
    if snapshot.open_interest:
        results.append(
            await _safe_execute(
                "arena_open_interest_snapshots.upsert",
                positions.db()
                .table("arena_open_interest_snapshots")
                .upsert(
                    snapshot.open_interest,
                    on_conflict="exchange,symbol,period,timestamp",
                ),
            )
        )
    if snapshot.basis:
        results.append(
            await _safe_execute(
                "arena_basis_snapshots.upsert",
                positions.db()
                .table("arena_basis_snapshots")
                .upsert(
                    snapshot.basis,
                    on_conflict="exchange,pair,contract_type,period,timestamp",
                ),
            )
        )

    if snapshot.mark_price_bars:
        results.append(
            await _safe_execute(
                "arena_mark_price_bars.upsert",
                positions.db()
                .table("arena_mark_price_bars")
                .upsert(
                    snapshot.mark_price_bars,
                    on_conflict="exchange,symbol,interval,price_type,open_time",
                ),
            )
        )
    if snapshot.premium_index_bars:
        results.append(
            await _safe_execute_optional_constraint(
                "arena_mark_price_bars.premium_index.upsert",
                positions.db()
                .table("arena_mark_price_bars")
                .upsert(
                    snapshot.premium_index_bars,
                    on_conflict="exchange,symbol,interval,price_type,open_time",
                ),
                constraint_name="arena_mark_price_bars_price_check",
            )
        )

    row = {
        "run_id": run_id,
        "symbol": snapshot.symbol,
        "interval": snapshot.interval,
        "data_timestamp": _ts(snapshot.data_timestamp),
        "fetched_at": _ts(snapshot.fetched_at),
        "quality_status": snapshot.quality_status,
        "quality_errors": snapshot.errors,
        "features": snapshot.features,
    }
    results.append(
        await _safe_execute(
            "arena_market_feature_snapshots.upsert",
            positions.db()
            .table("arena_market_feature_snapshots")
            .upsert(row, on_conflict="run_id"),
        )
    )
    return results


async def record_decision(
    *,
    run_id: str,
    algo_id: str,
    signal: str | None,
    action: str,
    reason: dict[str, Any],
    current_position_id: int | None = None,
    resulting_position_id: int | None = None,
    skipped_reason: str | None = None,
    risk_decision: dict[str, Any] | None = None,
    risk_snapshot: dict[str, Any] | None = None,
    raw_signal: str | None = None,
    executable_signal: str | None = None,
    product_policy_snapshot: dict[str, Any] | None = None,
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "algo_id": algo_id,
        "signal": signal,
        "raw_signal": raw_signal,
        "executable_signal": executable_signal,
        "action": action,
        "reason": reason,
        "current_position_id": current_position_id,
        "resulting_position_id": resulting_position_id,
        "skipped_reason": skipped_reason,
        "risk_decision": risk_decision or {},
        "risk_snapshot": risk_snapshot or {},
        "product_policy_snapshot": product_policy_snapshot or {},
    }
    result = await _safe_execute(
        "arena_decisions.upsert",
        positions.db().table("arena_decisions").upsert(row, on_conflict="run_id,algo_id"),
    )
    if not result.ok and any(
        key in str(result.error)
        for key in (
            "risk_decision",
            "risk_snapshot",
            "raw_signal",
            "executable_signal",
            "product_policy_snapshot",
            "arena_decisions_action_check",
        )
    ):
        legacy_action = action
        if action in {"spot_short_no_trade"}:
            legacy_action = "flat_skip"
        elif action in {"close_spot_risk_off", "close_legacy_short"}:
            legacy_action = "close_flat"
        legacy_row = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "risk_decision",
                "risk_snapshot",
                "raw_signal",
                "executable_signal",
                "product_policy_snapshot",
            }
        }
        legacy_row["action"] = legacy_action
        return await _safe_execute(
            "arena_decisions.upsert.legacy",
            positions.db()
            .table("arena_decisions")
            .upsert(legacy_row, on_conflict="run_id,algo_id"),
        )
    return result


async def record_shadow_decision(
    *,
    run_id: str,
    signal: SleeveSignal,
    allocation: AllocationDecision,
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "sleeve_id": signal.sleeve_id,
        "algo_id": signal.algo_id,
        "signal": signal.direction,
        "allowed": allocation.allowed,
        "target_weight": allocation.target_weight,
        "risk_budget": allocation.risk_budget,
        "action": allocation.action,
        "reason": signal.reason,
        "feature_snapshot": signal.feature_snapshot,
        "regime_snapshot": allocation.regime_snapshot,
        "risk_snapshot": allocation.risk_snapshot,
        "allocation_snapshot": allocation.as_dict(),
    }
    return await _safe_execute(
        "arena_shadow_decisions.upsert",
        positions.db()
        .table("arena_shadow_decisions")
        .upsert(row, on_conflict="run_id,sleeve_id,algo_id"),
    )


async def record_realtime_feature_bar(row: dict[str, Any]) -> CaptureWriteResult:
    result = await _safe_execute_optional_schema(
        "arena_realtime_feature_bars.upsert",
        positions.db()
        .table("arena_realtime_feature_bars")
        .upsert(row, on_conflict="symbol,window_start,window_seconds"),
        object_name="arena_realtime_feature_bars",
    )
    if result.ok:
        return result
    compatibility_row = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "aggressive_sell_ratio",
            "trade_quote_volume",
            "mid_return_1m",
            "short_drawdown_5m",
            "spread_widening_bps_per_min",
            "depth_collapse_ratio",
        }
    }
    return await _safe_execute_optional_schema(
        "arena_realtime_feature_bars.upsert.compat",
        positions.db()
        .table("arena_realtime_feature_bars")
        .upsert(compatibility_row, on_conflict="symbol,window_start,window_seconds"),
        object_name="arena_realtime_feature_bars",
    )


async def record_realtime_risk_state(decision: RealtimeRiskDecision) -> CaptureWriteResult:
    row = {
        "symbol": decision.symbol,
        "window_start": _ts(decision.window_start),
        "window_end": _ts(decision.window_end),
        "risk_state": decision.risk_state,
        "risk_score": decision.risk_score,
        "component_scores": decision.component_scores,
        "trigger_reasons": decision.trigger_reasons,
        "recommended_action": decision.recommended_action,
        "quality_status": decision.quality_status,
        "feature_snapshot": decision.feature_snapshot,
        "baseline_snapshot": decision.baseline_snapshot,
        "policy_snapshot": decision.as_dict()["policy"],
        "risk_snapshot": decision.as_dict(),
        "evaluated_at": _ts(decision.evaluated_at),
    }
    return await _safe_execute_optional_schema(
        "arena_realtime_risk_states.upsert",
        positions.db()
        .table("arena_realtime_risk_states")
        .upsert(row, on_conflict="symbol,window_start"),
        object_name="arena_realtime_risk_states",
    )


async def record_realtime_risk_event(
    *,
    decision: RealtimeRiskDecision,
    previous_state: str | None,
    event_type: str,
    run_id: str | None = None,
    position_id: int | None = None,
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "symbol": decision.symbol,
        "window_start": _ts(decision.window_start),
        "position_id": position_id,
        "event_type": event_type,
        "previous_state": previous_state,
        "risk_state": decision.risk_state,
        "severity": _risk_event_severity(decision.risk_state),
        "recommended_action": decision.recommended_action,
        "risk_score": decision.risk_score,
        "trigger_reasons": decision.trigger_reasons,
        "risk_snapshot": decision.as_dict(),
    }
    return await _safe_execute_optional_schema(
        "arena_realtime_risk_events.insert",
        positions.db().table("arena_realtime_risk_events").insert(row),
        object_name="arena_realtime_risk_events",
    )


async def fetch_latest_realtime_risk_state(
    *,
    symbol: str,
    now: datetime,
    max_age_seconds: int,
) -> dict[str, Any] | None:
    try:
        res = (
            await positions.db()
            .table("arena_realtime_risk_states")
            .select("*")
            .eq("symbol", symbol)
            .order("window_start", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if "arena_realtime_risk_states" in str(exc):
            logger.info("Arena realtime risk state read skipped: %s", exc)
            return None
        logger.warning("Arena realtime risk state read failed: %s", exc)
        return None
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    try:
        window_end = row.get("window_end") or row.get("window_start")
        age = (
            execution_rules.parse_utc_datetime(now) - execution_rules.parse_utc_datetime(window_end)
        ).total_seconds()
    except Exception:
        return None
    if age > max_age_seconds:
        return {**row, "fresh": False, "age_seconds": age}
    return {**row, "fresh": True, "age_seconds": age}


def _risk_event_severity(risk_state: str) -> str:
    if risk_state in {"FORCE_EXIT_CANDIDATE", "EXIT_CANDIDATE"}:
        return "high"
    if risk_state == "BLOCK_ENTRY":
        return "medium"
    return "low"


async def record_execution_gate(
    *,
    run_id: str,
    algo_id: str,
    signal: str | None,
    timeframe: str,
    decision: ExecutionGateDecision,
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "algo_id": algo_id,
        "signal": signal,
        "timeframe": timeframe,
        "signal_time": _ts(decision.evaluated_at),
        "signal_score": decision.expected_return_bps,
        "regime": decision.feature_snapshot.get("regime"),
        "expected_return_bps": decision.expected_return_bps,
        "expected_cost_bps": decision.expected_cost_bps,
        "spread_bps": decision.spread_bps,
        "expected_slippage_bps": decision.expected_slippage_bps,
        "depth_score": decision.depth_score,
        "volatility_score": decision.volatility_score,
        "api_latency_ms": decision.api_latency_ms,
        "decision": decision.decision,
        "reject_reason": decision.reject_reason,
        "feature_snapshot": decision.feature_snapshot,
        "risk_snapshot": decision.risk_snapshot,
        "gate_snapshot": decision.as_dict(),
    }
    return await _safe_execute_optional_schema(
        "arena_execution_gates.upsert",
        positions.db().table("arena_execution_gates").upsert(row, on_conflict="run_id,algo_id"),
        object_name="arena_execution_gates",
    )


async def record_shadow_tca_order(
    *,
    parent_order: dict[str, Any],
    execution_quality: dict[str, Any],
) -> list[CaptureWriteResult]:
    parent_result = await _safe_execute_optional_schema(
        "arena_parent_orders.insert",
        positions.db().table("arena_parent_orders").insert(parent_order),
        object_name="arena_parent_orders",
    )
    quality_result = await _safe_execute_optional_schema(
        "arena_execution_quality.insert",
        positions.db().table("arena_execution_quality").insert(execution_quality),
        object_name="arena_execution_quality",
    )
    return [parent_result, quality_result]


async def record_risk_event(
    *,
    run_id: str,
    algo_id: str,
    event_type: str,
    risk_decision: dict[str, Any],
    risk_snapshot: dict[str, Any],
    position_id: int | None = None,
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "algo_id": algo_id,
        "position_id": position_id,
        "event_type": event_type,
        "risk_decision": risk_decision,
        "risk_snapshot": risk_snapshot,
    }
    return await _safe_execute(
        "arena_risk_events.insert",
        positions.db().table("arena_risk_events").insert(row),
    )
