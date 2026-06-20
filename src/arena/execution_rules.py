"""Pure execution rules shared by live trading and backtest replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def parse_utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    return parse_utc_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def hold_hours(open_time: datetime | str, now: datetime) -> float:
    return (parse_utc_datetime(now) - parse_utc_datetime(open_time)).total_seconds() / 3600.0


def min_hold_ok(
    current_position: dict[str, Any],
    now: datetime,
    algo_id: str,
    min_hold_hours: dict[str, float],
    fallback_hours: float,
) -> bool:
    try:
        return hold_hours(current_position["open_time"], now) >= min_hold_hours.get(
            algo_id, fallback_hours
        )
    except (KeyError, ValueError, TypeError):
        return True


def direction_sign(direction: str) -> float:
    if direction == "long":
        return 1.0
    if direction == "short":
        return -1.0
    raise ValueError(f"unsupported direction: {direction}")


def calc_stop_loss_price(
    direction: str,
    entry_price: float,
    atr_value: float,
    *,
    atr_multiple: float,
    stop_loss_min_pct: float,
    stop_loss_max_pct: float,
) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    raw_pct = (atr_value * atr_multiple) / entry_price
    pct = max(stop_loss_min_pct, min(stop_loss_max_pct, raw_pct))
    if direction == "long":
        return entry_price * (1.0 - pct)
    if direction == "short":
        return entry_price * (1.0 + pct)
    raise ValueError(f"unsupported direction: {direction}")


def stop_loss_triggered(
    *,
    direction: str,
    open_price: float,
    current_price: float,
    stop_loss_price: float | None,
    fallback_stop_loss_pct: float,
) -> bool:
    if stop_loss_price is not None:
        if direction == "long":
            return current_price <= stop_loss_price
        if direction == "short":
            return current_price >= stop_loss_price
        raise ValueError(f"unsupported direction: {direction}")

    if open_price <= 0:
        raise ValueError("open_price must be positive")
    if direction == "long":
        loss = (open_price - current_price) / open_price
    elif direction == "short":
        loss = (current_price - open_price) / open_price
    else:
        raise ValueError(f"unsupported direction: {direction}")
    return loss >= fallback_stop_loss_pct


def fee_adjusted_return_pct(
    *,
    direction: str,
    open_price: float,
    close_price: float,
    fee_bps: float,
    slippage_bps: float = 0.0,
    spread_bps_round_trip: float = 0.0,
    legs: float = 2.0,
) -> float:
    """순수익률 = gross − 왕복 거래비용.

    거래비용 = legs × (fee + slippage) + spread_bps_round_trip (왕복 1회 적용).
    backtest.py의 net_ret 비용식과 동일하게 유지(live·backtest·검증 공용).
    """
    if open_price <= 0:
        raise ValueError("open_price must be positive")
    gross = direction_sign(direction) * (close_price / open_price - 1.0)
    trading_cost = (legs * (fee_bps + slippage_bps) + spread_bps_round_trip) / 10_000.0
    return gross - trading_cost


def build_params_snapshot(
    *,
    base_snapshot: dict[str, Any],
    algo_id: str,
    stop_loss_fallback_pct: float,
    fee_bps: float,
    atr_multiple: float,
    stop_loss_min_pct: float,
    stop_loss_max_pct: float,
    macro_stale_hours: float,
    slippage_bps: float = 0.0,
    portfolio_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = deepcopy(base_snapshot)
    snapshot["algo_id"] = algo_id
    snapshot["risk"] = {
        "stop_loss_fallback_pct": stop_loss_fallback_pct,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "atr_multiple": atr_multiple,
        "stop_loss_min_pct": stop_loss_min_pct,
        "stop_loss_max_pct": stop_loss_max_pct,
        "macro_stale_hours": macro_stale_hours,
    }
    if portfolio_risk is not None:
        snapshot["portfolio_risk"] = portfolio_risk
    return snapshot


def quoted_spread_bps(bid: float | None, ask: float | None) -> float | None:
    """의사결정 시점 호가 스프레드(bps). bid/ask 미수집 시 None."""
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return 10_000.0 * (ask - bid) / mid


def build_market_snapshot(
    *,
    symbol: str,
    interval: str,
    klines_limit: int,
    price: float,
    high: float | None,
    low: float | None,
    closes_count: int,
    data_timestamp: datetime,
    bid: float | None = None,
    ask: float | None = None,
) -> dict[str, Any]:
    spread_bps = quoted_spread_bps(bid, ask)
    return {
        "symbol": symbol,
        "interval": interval,
        "klines_limit": klines_limit,
        "data_timestamp": format_utc_timestamp(data_timestamp),
        "close": price,
        "high": high,
        "low": low,
        "closes_count": closes_count,
        # 의사결정 시점 호가 스냅샷 (Tier 1 TCA 선행 데이터)
        "bid": bid,
        "ask": ask,
        "quoted_spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
    }


def build_signal_reason(
    *,
    algo_id: str,
    signal: str | None,
    indicators: dict[str, Any],
    macro: dict[str, Any],
) -> dict[str, Any]:
    return {
        "algo_id": algo_id,
        "signal": signal,
        "inputs": {
            "regime_state": macro.get("regime_state"),
            "fng": macro.get("fng"),
            "vix_now": macro.get("vix_now"),
            "vix_q40": macro.get("vix_q40"),
            "rsi": indicators.get("rsi"),
            "macd_hist": indicators.get("macd_hist"),
            "bb_pos": indicators.get("bb_pos"),
            "atr": indicators.get("atr"),
        },
    }
