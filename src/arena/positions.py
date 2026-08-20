"""Supabase async CRUD — paper_positions 테이블. 신호 변경 기반 오픈/클로즈."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

from supabase import AsyncClient, acreate_client

from . import config, execution_rules, market_structure, parameters, state
from .algorithms import ALGORITHMS, fng_scaled_tranches

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


async def refresh_open_positions(*, symbol: str = parameters.BINANCE_SYMBOL) -> None:
    """DB에서 symbol의 오픈 포지션 로드 → state.open_positions[symbol] 갱신.

    2026-08-06: ETH/SOL 실거래 승격으로 심볼별 네임스페이스 필수화(이전엔 symbol=None
    이 전체 조회 후 단일 flat dict에 합쳐 심볼 간 포지션이 뒤섞일 여지가 있었음).
    server.py가 라이브 심볼마다 한 번씩 호출한다.
    """
    res = (
        await _db()
        .table("paper_positions")
        .select("*")
        .eq("status", "open")
        .eq("symbol", symbol)
        .execute()
    )
    by_algo: dict[str, dict | None] = {k: None for k in ALGORITHMS}
    for row in res.data:
        by_algo[row["algo_id"]] = row
    state.open_positions[symbol] = by_algo
    logger.info(
        "Open positions refreshed(%s): %s",
        symbol,
        {k: v is not None for k, v in by_algo.items()},
    )


async def risk_metrics(now: datetime, *, symbol: str | None = None) -> dict[str, Any]:
    """Return realized daily PnL and per-algo max drawdown from closed paper trades.

    symbol=None(기본)이면 기존과 동일하게 전체 자산 합산 — BTC 라이브 경로 무회귀.
    """
    now_utc = execution_rules.parse_utc_datetime(now)
    day_start = datetime.combine(now_utc.date(), time.min, tzinfo=timezone.utc)
    query = (
        _db()
        .table("paper_positions")
        .select("algo_id,ret_pct,close_time,position_weight")
        .eq("status", "closed")
    )
    if symbol is not None:
        query = query.eq("symbol", symbol)
    res = await query.order("close_time").limit(10000).execute()

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
        # 변동성 타깃 가중 적용 — 대시보드/백테스트 equity 회계와 일관(실제 자본 기준).
        weight = float(row.get("position_weight") or 1.0)
        weighted_ret = weight * float(ret_pct)
        close_time = row.get("close_time")
        if close_time and execution_rules.parse_utc_datetime(close_time) >= day_start:
            daily_realized += weighted_ret

        equity = equity_by_algo.get(algo_id, 1.0) * (1.0 + weighted_ret)
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
    symbol: str = parameters.BINANCE_SYMBOL,
    product_type: str,
    position_semantics: str,
    params_snapshot: dict[str, Any],
    indicator_snapshot: dict[str, Any],
    macro_snapshot: dict[str, Any],
    market_snapshot: dict[str, Any],
    signal_reason: dict[str, Any],
    risk_snapshot: dict[str, Any] | None = None,
) -> dict:
    """포지션 오픈. stop_loss_price는 ATR 기반으로 계산된 절대 가격.

    product_type/position_semantics은 트랙 프로파일이 반드시 명시해야 한다.
    algo_id로 상품을 추론하면 spot 트랙에 perp 포지션을 기록할 수 있어
    폴백을 허용하지 않는다.
    """
    if product_type == parameters.TARGET_PRODUCT:
        if position_semantics != parameters.POSITION_SEMANTICS:
            raise ValueError("spot product requires spot_long_flat position semantics")
        if symbol.endswith(parameters.PERP_TRACK_SUFFIX):
            raise ValueError("spot product cannot use a perp track symbol")
    elif product_type == parameters.PERP_TARGET_PRODUCT:
        if position_semantics != parameters.PERP_POSITION_SEMANTICS:
            raise ValueError("perp product requires usdm_perp_long_short position semantics")
        if not symbol.endswith(parameters.PERP_TRACK_SUFFIX):
            raise ValueError("perp product requires a -PERP track symbol")
    else:
        raise ValueError(f"unsupported live product_type: {product_type}")

    if direction == "short" and not parameters.perp_short_enabled(
        track_symbol=symbol,
        product_type=product_type,
        algo_id=algo_id,
    ):
        raise ValueError(
            f"short position requires an approved (perp track, algo_id) pair: {symbol}, {algo_id}"
        )
    # 래칫 트레일링 거리 = |진입가 − 초기 손절가| (ATR×multiple 클램핑 거리 재사용) × mult.
    trail_distance = execution_rules.trail_distance_from_stop(
        open_price,
        stop_loss_price,
        mult=parameters.TRAIL_DISTANCE_MULT_BY_ALGO.get(algo_id, 1.0),
    )
    payload = {
        "algo_id": algo_id,
        "symbol": symbol,
        "direction": direction,
        "status": "open",
        "open_time": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_timestamp": data_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open_price": open_price,
        "stop_loss_price": stop_loss_price,
        "trail_distance": trail_distance,
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
        "product_type": product_type,
        "position_semantics": position_semantics,
    }
    # 아직 마이그레이션 전인 DB(컬럼 부재)에서도 안전하게 동작하도록 선택 컬럼 fallback.
    # symbol: 2026-07-31 멀티자산 마이그레이션(20260731_arena_multi_asset_v1.sql) 미적용
    # 상태에서도 라이브 BTC 경로가 깨지지 않도록 포함 — 적용 전엔 자동 생략, 적용 후엔
    # 자동으로 포함(코드 변경 불필요).
    _optional_columns = (
        "risk_snapshot",
        "slippage_bps",
        "spread_bps_round_trip",
        "product_type",
        "position_semantics",
        "position_weight",
        "trail_distance",
        "symbol",
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


async def scale_in_position(
    position_id: int,
    *,
    new_open_price: float,
    new_position_weight: float,
    reason_updates: dict[str, Any],
) -> dict:
    """물타기(분할매수) in-place 갱신 — 비중 가중 평균 진입가 + 누적 비중.

    역발산 알고가 가격 하락 시 추가 트랜치를 체결할 때 호출. 단일 행 모델 유지:
    open_price는 가중평균, position_weight는 누적, signal_reason에 진행 상태 병합
    (체결 단계 수·기준가 — 재체결 방지). status='open' 조건부 update로 race 가드.
    """
    update_payload = {
        "open_price": new_open_price,
        "position_weight": new_position_weight,
    }
    res = (
        await _db()
        .table("paper_positions")
        .update(update_payload)
        .eq("id", position_id)
        .eq("status", "open")
        .execute()
    )
    if not res.data:
        logger.info("scale_in_position no-op(이미 closed): id=%s", position_id)
        return {}
    row = res.data[0]
    # 진행 상태를 signal_reason에 병합 — jsonb 부분 갱신은 read-merge-write.
    reason = dict(row.get("signal_reason") or {})
    reason.update(reason_updates)
    try:
        await (
            _db()
            .table("paper_positions")
            .update({"signal_reason": reason})
            .eq("id", position_id)
            .execute()
        )
        row["signal_reason"] = reason
    except Exception as exc:  # signal_reason 갱신 실패는 치명적이지 않음(비중·가격은 반영됨)
        logger.warning("scale_in signal_reason update failed: %s", exc)
    logger.info(
        "Scaled-in: %s  avg_open=%.2f  weight=%.3f  filled=%s",
        row.get("algo_id"),
        new_open_price,
        new_position_weight,
        reason.get("fng_filled_count"),
    )
    return row


async def maybe_scale_in_fng_price(current: dict, price: float) -> dict | None:
    """역발산 가격 기준 물타기 — 현재가가 다음 트랜치 한계가 이하면 추가 체결.

    live(stream 1m 틱·scheduler 4h)·backtest 공용 진입점. signal_reason의
    fng_ref_price(최초 진입가)·fng_filled_count(체결 단계 수)를 읽어 미체결 트랜치를
    평가, 한계가에 체결하고 가중평균가·누적비중·단계수를 갱신. 추가분 없으면 None.
    """
    reason = current.get("signal_reason") or {}
    ref_price = float(reason.get("fng_ref_price") or current.get("open_price") or 0.0)
    filled = int(reason.get("fng_filled_count") or 1)
    # P3(2026-07-21, 미검증): 진입 시점 고정된 scale(signal_reason.fng_duration_scale)로
    # 스케줄 전체를 균일 스케일 — backtest._maybe_scale_in_fng_sim과 동일 로직.
    scale = float(reason.get("fng_duration_scale") or 1.0)
    tranches = fng_scaled_tranches(scale)
    pending = execution_rules.pending_price_tranches(price, ref_price, filled, tranches)
    if not pending:
        return None
    old_weight = float(current.get("position_weight") or 0.0)
    new_open, new_weight, applied = execution_rules.fill_price_tranches(
        float(current["open_price"]),
        old_weight,
        ref_price,
        pending,
        tranches,
        parameters.VOL_WEIGHT_MAX * scale,
    )
    if applied <= 0:
        return None
    return await scale_in_position(
        current["id"],
        new_open_price=new_open,
        new_position_weight=new_weight,
        reason_updates={"fng_filled_count": filled + applied, "fng_ref_price": ref_price},
    )


async def update_stop_loss(position_id: int, new_stop_loss_price: float) -> None:
    """래칫된 트레일링 손절가를 DB에 persist. 매 틱이 아닌 임계 이동 시에만 호출."""
    await (
        _db()
        .table("paper_positions")
        .update({"stop_loss_price": new_stop_loss_price})
        .eq("id", position_id)
        .execute()
    )


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
    # 중복 청산 가드: stream(1m)과 scheduler(4h)가 같은 포지션을 await 사이 인터리브로
    # 이중 close 호출할 수 있음. 이미 closed면 기존 ret_pct를 반환하고 재기록하지 않음.
    if row.get("status") == "closed":
        logger.info("close_position skip(이미 closed): id=%s", position_id)
        return float(row.get("ret_pct") or 0.0)
    # 풀 비용 적용: fee + slippage + spread(왕복). 레거시 행은 컬럼 부재 → 0.0 fallback.
    price_pnl_pct = execution_rules.fee_adjusted_return_pct(
        direction=row["direction"],
        open_price=row["open_price"],
        close_price=close_price,
        fee_bps=row["fee_bps"],
        slippage_bps=float(row.get("slippage_bps") or 0.0),
        spread_bps_round_trip=float(row.get("spread_bps_round_trip") or 0.0),
    )
    ret_pct = price_pnl_pct
    # 2026-08-20: funding_carry처럼 가격손익과 펀딩비가 섞이면 안 되는 알고를 위해 둘을
    # 분리 보존 — ret_pct(DB 컬럼, 기존 집계·대시보드 전부 이 값 사용)는 계속 합산값을
    # 쓰되, price_pnl_pct/funding_pnl_pct 전용 컬럼에 따로 기록해 사후분해 가능하게 한다.
    funding_pnl_pct = 0.0
    # perp 전환 Phase A(2026-08-15): spot은 펀딩 없음(product_type='spot'/None). perp
    # 포지션은 보유기간 동안의 실제 arena_funding_rates(4h마다 수집)를 합산해 정산 —
    # backtest.py._close_position이 이미 하는 것과 동일 방식(부호: 롱은 양의 펀딩비
    # 지불·숏은 수취, market_structure.funding_return_pct). 조회 실패는 그레이스풀(펀딩 0).
    if row.get("product_type") not in (None, "spot"):
        from . import data_lake  # 순환 임포트 회피(data_lake가 positions를 임포트함)

        try:
            # Phase A2(2026-08-15): row["symbol"]은 이제 트랙 식별자(예: "BTCUSDT-PERP")일
            # 수 있음 — arena_funding_rates는 실제 바이낸스 티커로만 저장되므로 반드시
            # real_ticker_for_track()로 역변환해서 조회해야 한다(안 하면 조회 0건 →
            # 펀딩 항상 0 취급되는 조용한 버그).
            funding_rows = await data_lake.fetch_funding_rates(
                symbol=parameters.real_ticker_for_track(
                    row.get("symbol", parameters.BINANCE_SYMBOL)
                ),
                since=execution_rules.parse_utc_datetime(row["open_time"]),
                until=execution_rules.parse_utc_datetime(close_time),
            )
            funding_pnl_pct = market_structure.funding_return_pct(
                direction=row["direction"],
                funding_rates=funding_rows,
                open_time=row["open_time"],
                close_time=close_time,
            )
            ret_pct += funding_pnl_pct
        except Exception as exc:
            logger.warning("Funding accrual skipped (id=%s): %s", position_id, exc)
    hold_hours = execution_rules.hold_hours(row["open_time"], close_time)

    update_payload = {
        "status": "closed",
        "close_time": close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_price": close_price,
        "ret_pct": ret_pct,
        # 2026-08-20: 가격손익/펀딩비 분리 컬럼 — funding_carry처럼 ret_pct 하나로는
        # "펀딩비로 실제 얼마 벌었나"를 검증할 수 없던 문제 해결(전용 컬럼, ret_pct =
        # price_pnl_pct + funding_pnl_pct 항상 성립).
        "price_pnl_pct": price_pnl_pct,
        "funding_pnl_pct": funding_pnl_pct,
        "hit": ret_pct > 0,
        "is_stop_loss": is_stop_loss,
        "hold_hours": round(hold_hours, 2),
    }
    if close_reason:
        update_payload["close_reason"] = close_reason

    # status='open' 조건부 update — 동시 호출 시 두 번째는 0행 영향(원자적 가드).
    try:
        res = (
            await _db()
            .table("paper_positions")
            .update(update_payload)
            .eq("id", position_id)
            .eq("status", "open")
            .execute()
        )
    except Exception as exc:
        if "close_reason" not in str(exc):
            raise
        update_payload.pop("close_reason", None)
        res = (
            await _db()
            .table("paper_positions")
            .update(update_payload)
            .eq("id", position_id)
            .eq("status", "open")
            .execute()
        )
    if not res.data:
        logger.info("close_position no-op(이미 closed, race): id=%s", position_id)
        return float(row.get("ret_pct") or ret_pct)
    logger.info(
        "Closed: %s %s ret=%.2f%% hold=%.1fh stop_loss=%s",
        row["algo_id"],
        row["direction"],
        ret_pct * 100,
        hold_hours,
        is_stop_loss,
    )
    return ret_pct
