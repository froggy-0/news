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


def target_exit_triggered(
    *,
    direction: str,
    current_price: float,
    target_price: float | None,
) -> bool:
    """평균회귀 목표가(익절) 도달 여부 — WI-7 omnibus RANGE/REBOUND.

    long: current >= target, short: current <= target. target 미설정(None/≤0) 시 False.
    익절 트리거이므로 손절과 비대칭(호출측이 min_hold보다 우선 적용). backtest는 봉 high/low
    로 평가, live는 1m 틱으로 평가 — 동일 순수함수로 패리티.
    """
    if target_price is None or target_price <= 0:
        return False
    if direction == "long":
        return current_price >= target_price
    if direction == "short":
        return current_price <= target_price
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


def risk_targeted_weight(
    open_price: float,
    stop_loss_price: float,
    *,
    risk_budget_pct: float,
    weight_min: float,
    weight_max: float,
) -> float:
    """손절거리 기준 거래당 자본위험 고정 사이징 = clamp(risk_budget / stop_dist, min, max).

    손절 도달 시 손실 ≈ weight × stop_distance_pct ≈ risk_budget_pct 로 고정된다.
    좁은 손절 → 큰 비중 허용, 넓은 손절 → 비중 축소. open/stop 미상정 시 보수적으로
    weight_min. 근거: 고정분율 위험(fixed-fractional risk) — 거래당 손실 균질화로
    단일 올인 진입의 꼬리손실을 제거. backtest·live 공용 순수 함수.
    """
    if open_price <= 0 or stop_loss_price <= 0:
        return weight_min
    stop_distance_pct = abs(open_price - stop_loss_price) / open_price
    if stop_distance_pct <= 0:
        return weight_max
    raw = risk_budget_pct / stop_distance_pct
    return max(weight_min, min(weight_max, raw))


def combined_position_weight(
    realized_vol: float,
    open_price: float,
    stop_loss_price: float,
    *,
    target_vol: float,
    risk_budget_pct: float,
    weight_min: float,
    weight_max: float,
) -> float:
    """변동성타깃과 리스크타깃 중 더 보수적인(작은) 비중을 채택.

    - 저변동 국면: 변동성타깃이 상한에 붙어 올인을 요구하지만 리스크타깃이 손절거리
      기준으로 비중을 제한 → 단일 진입 자본위험 통제.
    - 고변동 국면: 변동성타깃이 먼저 축소되어 기존 보호를 유지.
    가장 보수적인 레버가 항상 바인딩된다. backtest·live 공용 순수 함수.
    """
    vt = vol_target_weight(
        realized_vol,
        target_vol=target_vol,
        weight_min=weight_min,
        weight_max=weight_max,
    )
    rb = risk_targeted_weight(
        open_price,
        stop_loss_price,
        risk_budget_pct=risk_budget_pct,
        weight_min=weight_min,
        weight_max=weight_max,
    )
    return min(vt, rb)


def time_stop_triggered(
    open_time: datetime | str,
    now: datetime,
    max_hold_hours: float,
) -> bool:
    """보유시간이 max_hold_hours 이상이면 True. 평균회귀 시간 손절(가격 손절 대체).

    평균회귀는 수익이 초기 봉에 집중되므로, 일정 시간 내 회귀(익절)가 없으면 청산해
    자본 점유를 풀고 다음 기회로 회전한다. backtest·live 공용 순수 함수.
    """
    if max_hold_hours <= 0:
        return False
    return hold_hours(open_time, now) >= max_hold_hours


def pending_price_tranches(
    current_price: float,
    ref_price: float,
    filled_count: int,
    tranches: tuple[tuple[float, float], ...],
) -> list[tuple[int, float]]:
    """현재가가 진입 기준가 대비 충분히 하락해 새로 체결 가능한 물타기 트랜치 목록.

    각 트랜치 (진입가 하락률 drop≤0, 추가 비중). 이미 filled_count개 체결됐다고 보고
    그 다음 인덱스부터 순차적으로 `current_price <= ref_price*(1+drop)`를 만족하는
    동안 반환(가격이 갭다운하면 여러 단계 동시 체결). 반환 (트랜치 인덱스, 추가 비중).
    backtest(봉 저가)·live(1m 틱) 공용 순수 함수.
    """
    if ref_price <= 0:
        return []
    out: list[tuple[int, float]] = []
    for i in range(max(filled_count, 0), len(tranches)):
        drop, add_weight = tranches[i]
        if current_price <= ref_price * (1.0 + drop):
            out.append((i, add_weight))
        else:
            break  # 순차적 — 더 깊은 단계는 아직 미도달
    return out


def averaged_entry_price(
    old_price: float,
    old_weight: float,
    add_price: float,
    add_weight: float,
) -> float:
    """비중 가중 평균 진입가 = (old·w_old + add·w_add) / (w_old + w_add). 물타기 회계."""
    total = old_weight + add_weight
    if total <= 0:
        return old_price
    return (old_price * old_weight + add_price * add_weight) / total


def fill_price_tranches(
    old_avg: float,
    old_weight: float,
    ref_price: float,
    pending: list[tuple[int, float]],
    tranches: tuple[tuple[float, float], ...],
    weight_cap: float,
) -> tuple[float, float, int]:
    """물타기 트랜치들을 각자의 한계가(ref×(1+drop))에 체결한 결과 회계.

    페이퍼 한계주문 모델: 트랜치 i는 진입가 대비 drop_i 지점에 걸어둔 매수로 보고
    ref_price*(1+drop_i)에 체결. 누적 비중은 weight_cap 상한. live(1m 틱)·
    backtest(봉 저가) 모두 동일 한계가에 체결해 패리티 유지. 반환 (새 평균진입가,
    새 누적비중, 실제 체결 트랜치 수).
    """
    avg = old_avg
    weight = old_weight
    applied = 0
    for idx, add_weight in pending:
        room = weight_cap - weight
        if room <= 1e-9:
            break
        aw = min(add_weight, room)
        if aw <= 0:
            break
        fill_price = ref_price * (1.0 + tranches[idx][0])
        avg = averaged_entry_price(avg, weight, fill_price, aw)
        weight += aw
        applied += 1
    return avg, weight, applied


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
            "btc_above_ma200": macro.get("btc_above_ma200"),
            "long_short_ratio_zscore": macro.get("long_short_ratio_zscore"),
            "taker_imbalance_zscore": macro.get("taker_imbalance_zscore"),
            "breadth_up_ratio": macro.get("breadth_up_ratio"),
            "stablecoin_supply_zscore": macro.get("stablecoin_supply_zscore"),
            "btc_drawdown_90d": macro.get("btc_drawdown_90d"),
            "close": indicators.get("close"),
            "rsi": indicators.get("rsi"),
            "macd_hist": indicators.get("macd_hist"),
            "macd_hist_prev": indicators.get("macd_hist_prev"),
            "bb_pos": indicators.get("bb_pos"),
            "bb_width": indicators.get("bb_width"),
            "bb_mid": indicators.get("bb_mid"),
            "rsi_prev": indicators.get("rsi_prev"),
            "rel_volume": indicators.get("rel_volume"),
            "taker_ratio_4h": macro.get("taker_ratio_4h"),
            "atr": indicators.get("atr"),
            "adx": indicators.get("adx"),
            "ema_fast": indicators.get("ema_fast"),
            "ema_slow": indicators.get("ema_slow"),
            "ema_fast_slope": indicators.get("ema_fast_slope"),
            "donchian_upper": indicators.get("donchian_upper"),
            "donchian_lower": indicators.get("donchian_lower"),
            "realized_vol_24h": indicators.get("realized_vol_24h"),
        },
    }
