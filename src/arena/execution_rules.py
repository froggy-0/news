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


def trail_distance_from_stop(open_price: float, stop_loss_price: float) -> float:
    """진입 시 트레일링 거리 = |진입가 − 초기 손절가| (절대 가격 단위).

    초기 손절가가 이미 ATR×multiple(클램핑 포함) 거리이므로 이를 그대로 재사용해
    래칫 첫 시점에 손절가가 변하지 않도록(self-consistent) 한다.
    """
    return abs(open_price - stop_loss_price)


def ratchet_trailing_stop(
    *,
    direction: str,
    current_price: float,
    current_stop: float,
    trail_distance: float,
) -> float:
    """래칫 트레일링 스톱: S_t = max(S_{t-1}, P_t − d) (long) / min(S_{t-1}, P_t + d) (short).

    수익 방향으로만 손절가를 단조 이동(절대 손실 방향으로 안 움직임).
    arxiv 2602.11708 "Systematic Trend-Following with Adaptive Portfolio Construction"
    의 동적 트레일링 스톱 공식(α=2.5 ATR plateau, ablation 시 Sharpe −0.73 악화) 적용.
    trail_distance(=진입 시 ATR 거리)는 호출자가 고정 보관. backtest·live 공용 순수 함수.
    """
    if trail_distance <= 0:
        return current_stop
    if direction == "long":
        return max(current_stop, current_price - trail_distance)
    if direction == "short":
        return min(current_stop, current_price + trail_distance)
    raise ValueError(f"unsupported direction: {direction}")


def is_trailing_exit(
    *,
    direction: str,
    open_price: float,
    stop_loss_price: float,
    trail_distance: float,
    eps: float = 1e-9,
) -> bool:
    """손절가가 진입 시 초기 위치보다 수익 방향으로 래칫됐는지 여부.

    True면 트레일링이 작동해 잠긴 손절(때로는 이익 고정), False면 초기 손절 그대로.
    close_reason 라벨링용(trailing_stop vs stop_loss).
    """
    if trail_distance <= 0:
        return False
    initial_stop = (
        open_price - trail_distance if direction == "long" else open_price + trail_distance
    )
    if direction == "long":
        return stop_loss_price > initial_stop + eps
    if direction == "short":
        return stop_loss_price < initial_stop - eps
    return False


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


def vol_target_weight(
    realized_vol: float,
    *,
    target_vol: float,
    weight_min: float,
    weight_max: float,
) -> float:
    """변동성 타깃 포지션 가중치 = clamp(target_vol / realized_vol, min, max).

    realized_vol(4h 봉 로그수익률 표준편차)이 목표보다 크면 노출 축소,
    작으면 확대. realized_vol 미수집(<=0) 시 보수적으로 weight_min 적용.
    backtest·live 공용 순수 함수.
    """
    if realized_vol <= 0:
        return weight_min
    raw = target_vol / realized_vol
    return max(weight_min, min(weight_max, raw))


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
            "regime_state": macro.get("arena_regime_state") or macro.get("regime_state"),
            "overlay_regime_state": macro.get("regime_state"),
            "fng": macro.get("fng"),
            "vix_now": macro.get("vix_now"),
            "vix_q40": macro.get("vix_q40"),
            "funding_zscore": macro.get("funding_zscore"),
            "oi_divergence_flag": macro.get("oi_divergence_flag"),
            "etf_flow_zscore": macro.get("etf_flow_zscore"),
            "rsi": indicators.get("rsi"),
            "macd_hist": indicators.get("macd_hist"),
            "bb_pos": indicators.get("bb_pos"),
            "bb_width": indicators.get("bb_width"),
            "atr": indicators.get("atr"),
            "adx": indicators.get("adx"),
            "donchian_upper": indicators.get("donchian_upper"),
            "donchian_lower": indicators.get("donchian_lower"),
            "realized_vol_24h": indicators.get("realized_vol_24h"),
        },
    }
