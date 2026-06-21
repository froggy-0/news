"""Supabase async CRUD — paper_positions 테이블. 신호 변경 기반 오픈/클로즈."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

from supabase import AsyncClient, acreate_client

from . import config, execution_rules, parameters, state
from .algorithms import ALGORITHMS

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


async def init() -> None:
    global _client
    supabase_url, supabase_key = config.require_supabase_config()
    _client = await acreate_client(supabase_url, supabase_key)
    logger.info("Supabase client initialized")


def _db() -> AsyncClient:
    if _client is None:
        raise RuntimeError("positions.init() not called")
    return _client


def db() -> AsyncClient:
    return _db()


async def refresh_open_positions() -> None:
    """DB에서 오픈 포지션 로드 → state.open_positions 갱신."""
    res = await _db().table("paper_positions").select("*").eq("status", "open").execute()
    by_algo: dict[str, dict | None] = {k: None for k in ALGORITHMS}
    for row in res.data:
        by_algo[row["algo_id"]] = row
    state.open_positions.update(by_algo)
    logger.info(
        "Open positions refreshed: %s", {k: v is not None for k, v in state.open_positions.items()}
    )


async def risk_metrics(now: datetime) -> dict[str, Any]:
    """Return realized daily PnL and per-algo max drawdown from closed paper trades."""
    now_utc = execution_rules.parse_utc_datetime(now)
    day_start = datetime.combine(now_utc.date(), time.min, tzinfo=timezone.utc)
    res = (
        await _db()
        .table("paper_positions")
        .select("algo_id,ret_pct,close_time")
        .eq("status", "closed")
        .order("close_time")
        .limit(10000)
        .execute()
    )

    daily_realized = 0.0
    equity_by_algo: dict[str, float] = {}
    peak_by_algo: dict[str, float] = {}
    drawdown_by_algo: dict[str, float] = {}
    for row in res.data or []:
        ret_pct = row.get("ret_pct")
        if ret_pct is None:
            continue
        algo_id = row.get("algo_id")
        if not algo_id:
            continue
        close_time = row.get("close_time")
        if close_time and execution_rules.parse_utc_datetime(close_time) >= day_start:
            daily_realized += float(ret_pct)

        equity = equity_by_algo.get(algo_id, 1.0) * (1.0 + float(ret_pct))
        peak = max(peak_by_algo.get(algo_id, 1.0), equity)
        drawdown = equity / peak - 1.0
        equity_by_algo[algo_id] = equity
        peak_by_algo[algo_id] = peak
        drawdown_by_algo[algo_id] = min(drawdown_by_algo.get(algo_id, 0.0), drawdown)

    return {
        "daily_realized_ret_pct": daily_realized,
        "algo_drawdown_pct": drawdown_by_algo,
    }


async def open_position(
    algo_id: str,
    direction: str,
    open_time: datetime,
    open_price: float,
    stop_loss_price: float,
    *,
    data_timestamp: datetime,
    strategy_version: str,
    params_version: str,
    position_weight: float = 1.0,
    slippage_bps: float = 0.0,
    spread_bps_round_trip: float = 0.0,
    params_snapshot: dict[str, Any],
    indicator_snapshot: dict[str, Any],
    macro_snapshot: dict[str, Any],
    market_snapshot: dict[str, Any],
    signal_reason: dict[str, Any],
    risk_snapshot: dict[str, Any] | None = None,
) -> dict:
    """포지션 오픈. stop_loss_price는 ATR 기반으로 계산된 절대 가격."""
    if direction == "short" and config.TARGET_PRODUCT == "spot" and not config.ALLOW_LIVE_SHORT:
        raise ValueError("spot paper/live execution cannot open short positions")
    payload = {
        "algo_id": algo_id,
        "direction": direction,
        "status": "open",
        "open_time": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_timestamp": data_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open_price": open_price,
        "stop_loss_price": stop_loss_price,
        "position_weight": position_weight,
        "fee_bps": config.FEE_BPS,
        "slippage_bps": slippage_bps,
        "spread_bps_round_trip": spread_bps_round_trip,
        "strategy_version": strategy_version,
        "params_version": params_version,
        "params_snapshot": params_snapshot,
        "indicator_snapshot": indicator_snapshot,
        "macro_snapshot": macro_snapshot,
        "market_snapshot": market_snapshot,
        "signal_reason": signal_reason,
        "risk_snapshot": risk_snapshot or {},
        "runtime": parameters.RUNTIME,
        "product_type": config.TARGET_PRODUCT,
        "position_semantics": config.POSITION_SEMANTICS,
    }
    # 아직 마이그레이션 전인 DB(컬럼 부재)에서도 안전하게 동작하도록 선택 컬럼 fallback.
    _optional_columns = (
        "risk_snapshot",
        "slippage_bps",
        "spread_bps_round_trip",
        "product_type",
        "position_semantics",
        "position_weight",
    )
    try:
        res = await _db().table("paper_positions").insert(payload).execute()
    except Exception as exc:
        if not any(col in str(exc) for col in _optional_columns):
            raise
        logger.warning(
            "paper_positions optional column unavailable (%s); retrying legacy insert", exc
        )
        for col in _optional_columns:
            payload.pop(col, None)
        res = await _db().table("paper_positions").insert(payload).execute()
    row = res.data[0]
    logger.info(
        "Opened: %s %s @ %.2f  SL=%.2f (id=%s)",
        algo_id,
        direction,
        open_price,
        stop_loss_price,
        row["id"],
    )
    return row


async def close_position(
    position_id: int,
    close_time: datetime,
    close_price: float,
    *,
    is_stop_loss: bool = False,
    close_reason: str | None = None,
) -> float:
    pos = await _db().table("paper_positions").select("*").eq("id", position_id).single().execute()
    row = pos.data
    # 풀 비용 적용: fee + slippage + spread(왕복). 레거시 행은 컬럼 부재 → 0.0 fallback.
    ret_pct = execution_rules.fee_adjusted_return_pct(
        direction=row["direction"],
        open_price=row["open_price"],
        close_price=close_price,
        fee_bps=row["fee_bps"],
        slippage_bps=float(row.get("slippage_bps") or 0.0),
        spread_bps_round_trip=float(row.get("spread_bps_round_trip") or 0.0),
    )
    hold_hours = execution_rules.hold_hours(row["open_time"], close_time)

    update_payload = {
        "status": "closed",
        "close_time": close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_price": close_price,
        "ret_pct": ret_pct,
        "hit": ret_pct > 0,
        "is_stop_loss": is_stop_loss,
        "hold_hours": round(hold_hours, 2),
    }
    if close_reason:
        update_payload["close_reason"] = close_reason

    try:
        await _db().table("paper_positions").update(update_payload).eq("id", position_id).execute()
    except Exception as exc:
        if "close_reason" not in str(exc):
            raise
        update_payload.pop("close_reason", None)
        await _db().table("paper_positions").update(update_payload).eq("id", position_id).execute()
    logger.info(
        "Closed: %s %s ret=%.2f%% hold=%.1fh stop_loss=%s",
        row["algo_id"],
        row["direction"],
        ret_pct * 100,
        hold_hours,
        is_stop_loss,
    )
    return ret_pct
