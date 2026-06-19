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

from . import config, feature_registry, parameters, positions
from .market_structure import MarketStructureSnapshot
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


def parse_binance_kline(kline: list[Any], *, run_id: str, fetched_at: datetime) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "exchange": "binance",
        "symbol": config.SYMBOL,
        "interval": parameters.BINANCE_KLINE_INTERVAL,
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
) -> CaptureWriteResult:
    payload = {
        "run_id": run_id,
        "started_at": _ts(started_at),
        "status": "started",
        "runtime": parameters.RUNTIME,
        "symbol": config.SYMBOL,
        "interval": parameters.BINANCE_KLINE_INTERVAL,
        "strategy_version": parameters.STRATEGY_VERSION,
        "params_version": parameters.PARAMS_VERSION,
        "feature_set_version": parameters.FEATURE_SET_VERSION,
        "risk_model_version": parameters.RISK_MODEL_VERSION,
        "params_snapshot": params_snapshot,
    }
    result = await _safe_execute(
        "arena_runs.start", positions.db().table("arena_runs").insert(payload)
    )
    if not result.ok:
        legacy_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"feature_set_version", "risk_model_version"}
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
) -> list[CaptureWriteResult]:
    rows = [
        parse_binance_kline(kline, run_id=run_id, fetched_at=fetched_at) for kline in raw_klines
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
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "symbol": config.SYMBOL,
        "interval": parameters.BINANCE_KLINE_INTERVAL,
        "data_timestamp": _ts(data_timestamp),
        "params_version": parameters.PARAMS_VERSION,
        "indicator_params": parameters.base_params_snapshot()["indicators"],
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
) -> CaptureWriteResult:
    row = {
        "run_id": run_id,
        "algo_id": algo_id,
        "signal": signal,
        "action": action,
        "reason": reason,
        "current_position_id": current_position_id,
        "resulting_position_id": resulting_position_id,
        "skipped_reason": skipped_reason,
        "risk_decision": risk_decision or {},
        "risk_snapshot": risk_snapshot or {},
    }
    result = await _safe_execute(
        "arena_decisions.upsert",
        positions.db().table("arena_decisions").upsert(row, on_conflict="run_id,algo_id"),
    )
    if not result.ok and (
        "risk_decision" in str(result.error) or "risk_snapshot" in str(result.error)
    ):
        legacy_row = {
            key: value
            for key, value in row.items()
            if key not in {"risk_decision", "risk_snapshot"}
        }
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
