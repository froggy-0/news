"""4H APScheduler 사이클 — Binance 4H OHLCV + R2 매크로 → 알고리즘 실행 → 포지션 관리."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import NamedTuple

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import (
    allocator,
    config,
    data_lake,
    execution_gate,
    execution_rules,
    frequency,
    indicators,
    market_structure,
    parameters,
    positions,
    realtime_risk,
    regime,
    risk,
    slack_notify,
    sleeves,
    spot_policy,
    state,
    tca_shadow,
)
from .algorithms import ALGORITHMS

logger = logging.getLogger(__name__)


class OHLCV(NamedTuple):
    highs: list[float]
    lows: list[float]
    closes: list[float]
    last_close_time: datetime | None
    raw_klines: list[list]


class MacroData(NamedTuple):
    signal: dict
    payload: dict
    fetched_at: datetime | None
    source_url: str


async def _fetch_ohlcv(
    *,
    symbol: str,
    interval: str,
    limit: int,
) -> OHLCV:
    """Binance OHLCV 수집. 미확정 오픈 캔들 제거."""
    url = f"{config.BINANCE_REST_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        res = await client.get(url)
        res.raise_for_status()
    klines = res.json()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if klines and int(klines[-1][6]) > now_ms:
        klines = klines[:-1]
    return OHLCV(
        highs=[float(k[2]) for k in klines],
        lows=[float(k[3]) for k in klines],
        closes=[float(k[4]) for k in klines],
        last_close_time=(
            datetime.fromtimestamp(int(klines[-1][6]) / 1000, tz=timezone.utc) if klines else None
        ),
        raw_klines=klines,
    )


async def _fetch_macro() -> MacroData:
    """R2 latest.json 수집. stale 데이터는 거시 신호로 사용하지 않음."""
    if not config.LATEST_JSON_URL:
        logger.warning("LATEST_JSON_URL 미설정 — 빈 매크로 사용")
        return MacroData({}, {}, None, "")
    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        res = await client.get(config.LATEST_JSON_URL)
        res.raise_for_status()
    data = res.json()
    fetched_at = datetime.now(timezone.utc)

    # 신선도 검증: referenceDate 기준 경과 시간 확인
    ref_date = data.get("referenceDate", "")
    stale_h: float | None = None
    if ref_date:
        try:
            ref_dt = datetime.fromisoformat(ref_date.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            else:
                ref_dt = ref_dt.astimezone(timezone.utc)
            stale_h = (datetime.now(timezone.utc) - ref_dt).total_seconds() / 3600
            if stale_h > config.MACRO_STALE_HOURS:
                logger.warning(
                    "Macro data stale: %.0fh (ref=%s, threshold=%.0fh) — macro signals disabled",
                    stale_h,
                    ref_date,
                    config.MACRO_STALE_HOURS,
                )
                return MacroData({}, data, fetched_at, config.LATEST_JSON_URL)
        except ValueError:
            logger.warning(
                "Macro referenceDate parse failed: %s — macro signals disabled", ref_date
            )
            return MacroData({}, data, fetched_at, config.LATEST_JSON_URL)

    overlay = data.get("riskOverlay", {})
    raw = overlay.get("regimeRaw", {})
    sovereign = data.get("sovereignIndex", {}) or {}
    return MacroData(
        {
            "regime_state": overlay.get("regimeState", ""),
            "fng": raw.get("fng"),
            "vix_now": raw.get("vix_now"),
            "vix_q40": raw.get("vix_q40"),
            # 선물 데이터 — 현물 진입 과열 회피 필터용 (research_features_only)
            "funding_zscore": raw.get("funding_zscore"),
            "oi_divergence_flag": raw.get("oi_divergence_flag"),
            # 기관 ETF 순유입 z-score — 펀더멘털 레짐 스위치 (대량 유출 시 롱 보류)
            "etf_flow_zscore": raw.get("etf_flow_zscore"),
            # 구조적 강세 게이트 + 군중 과밀 + 주문흐름 확인 + 낙폭 컨텍스트
            # (regimeRaw 미수집 시 None → 알고리즘이 graceful 처리, veto 없음)
            "btc_above_ma200": raw.get("btc_above_ma200"),
            "long_short_ratio_zscore": raw.get("long_short_ratio_zscore"),
            "taker_imbalance_zscore": raw.get("taker_imbalance_zscore"),
            "btc_drawdown_90d": raw.get("btc_drawdown_90d"),
            # 시장 폭 + 온체인 유동성 (복합 투표 알고 건전성 필터)
            "breadth_up_ratio": raw.get("breadth_up_ratio"),
            "stablecoin_supply_zscore": raw.get("stablecoin_supply_zscore"),
            # 변동성 환경 라벨 (사이징/신뢰도 컨텍스트)
            "vol_level": overlay.get("volLevel"),
            "vol_trend": overlay.get("volTrend"),
            # OOS 검증 종합 센티먼트 지수 (risk_on/risk_off/neutral)
            "sovereign_score": sovereign.get("score"),
            "sovereign_label": sovereign.get("signalLabel"),
            "reference_date": ref_date or None,
            "stale_hours": round(stale_h, 2) if stale_h is not None else None,
        },
        data,
        fetched_at,
        config.LATEST_JSON_URL,
    )


async def _fetch_book_ticker(symbol: str) -> tuple[float | None, float | None]:
    """의사결정 시점 최우선 호가(bid/ask) 수집. 실패해도 사이클에 영향 없음."""
    try:
        url = f"{config.BINANCE_BOOK_TICKER_URL}?symbol={symbol}"
        async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
            res = await client.get(url)
            res.raise_for_status()
        data = res.json()
        return float(data["bidPrice"]), float(data["askPrice"])
    except Exception as exc:
        logger.warning("bookTicker 수집 실패: %s", exc)
        return None, None


async def _fetch_depth_snapshot(
    symbol: str,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """의사결정 시점 depth20 스냅샷. 실패해도 shadow TCA만 degraded 처리된다."""
    try:
        url = f"{config.BINANCE_DEPTH_URL}?symbol={symbol}&limit=20"
        async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
            res = await client.get(url)
            res.raise_for_status()
        data = res.json()
        return (
            tca_shadow.normalize_depth_levels(data.get("bids")),
            tca_shadow.normalize_depth_levels(data.get("asks")),
        )
    except Exception as exc:
        logger.warning("depth snapshot 수집 실패: %s", exc)
        return [], []


def _base_params_snapshot(
    *,
    profile: frequency.FrequencyProfile,
    indicator_profile_id: str,
    cost_scenario: frequency.CostScenario,
) -> dict:
    snapshot = parameters.base_params_snapshot()
    snapshot["market_data"].update(
        {
            "symbol": profile.symbol,
            "kline_interval": profile.interval,
            "frequency_profile_id": profile.frequency_profile_id,
            "indicator_profile_id": indicator_profile_id,
            "cost_model_version": cost_scenario.cost_model_version,
            "cost_scenario_id": cost_scenario.cost_scenario_id,
        }
    )
    snapshot["frequency_research"] = frequency.profile_snapshot(
        profile,
        indicator_profile_id=indicator_profile_id,
        cost_scenario_id=cost_scenario.cost_scenario_id,
    )
    snapshot["execution_product"] = {
        "target_product": config.TARGET_PRODUCT,
        "position_semantics": config.POSITION_SEMANTICS,
        "short_signal_action": config.SHORT_SIGNAL_ACTION,
        "allow_live_short": config.ALLOW_LIVE_SHORT,
        "research_perp_shadow_enabled": config.RESEARCH_PERP_SHADOW_ENABLED,
        "spot_execution_only": True,
        "derivatives_data_usage": "research_features_only",
    }
    return snapshot


def _params_snapshot(
    algo_id: str,
    *,
    profile: frequency.FrequencyProfile,
    indicator_profile_id: str,
    cost_scenario: frequency.CostScenario,
) -> dict:
    return execution_rules.build_params_snapshot(
        base_snapshot=_base_params_snapshot(
            profile=profile,
            indicator_profile_id=indicator_profile_id,
            cost_scenario=cost_scenario,
        ),
        algo_id=algo_id,
        stop_loss_fallback_pct=config.STOP_LOSS_PCT,
        fee_bps=cost_scenario.fee_bps,
        atr_multiple=config.ATR_MULTIPLE,
        stop_loss_min_pct=config.STOP_LOSS_MIN_PCT,
        stop_loss_max_pct=config.STOP_LOSS_MAX_PCT,
        macro_stale_hours=config.MACRO_STALE_HOURS,
        slippage_bps=cost_scenario.slippage_bps,
        portfolio_risk=risk.policy_snapshot(_risk_policy()),
    )


def _risk_policy() -> risk.PortfolioRiskPolicy:
    max_short_positions = 0 if config.TARGET_PRODUCT == "spot" else config.MAX_SHORT_POSITIONS
    max_net_short_exposure = (
        0.0 if config.TARGET_PRODUCT == "spot" else config.MAX_NET_SHORT_EXPOSURE
    )
    return risk.PortfolioRiskPolicy(
        position_unit=config.POSITION_UNIT,
        max_open_positions_total=config.MAX_OPEN_POSITIONS_TOTAL,
        max_long_positions=config.MAX_LONG_POSITIONS,
        max_short_positions=max_short_positions,
        max_net_long_exposure=config.MAX_NET_LONG_EXPOSURE,
        max_net_short_exposure=max_net_short_exposure,
        daily_loss_limit_pct=config.DAILY_LOSS_LIMIT_PCT,
        algo_max_drawdown_kill_pct=config.ALGO_MAX_DRAWDOWN_KILL_PCT,
        cooldown_after_kill_hours=config.COOLDOWN_AFTER_KILL_HOURS,
    )


def _execution_gate_policy() -> execution_gate.ExecutionGatePolicy:
    return execution_gate.ExecutionGatePolicy(
        ecr_multiple=config.EXEC_GATE_ECR_MULTIPLE,
        max_spread_bps=config.EXEC_GATE_MAX_SPREAD_BPS,
        max_slippage_bps=config.EXEC_GATE_MAX_SLIPPAGE_BPS,
        min_depth_score=config.EXEC_GATE_MIN_DEPTH_SCORE,
        max_latency_ms=config.EXEC_GATE_MAX_LATENCY_MS,
        vol_spike_max=config.EXEC_GATE_VOL_SPIKE_MAX,
        min_depth_10bp_usd=config.EXEC_GATE_MIN_DEPTH_10BP_USD,
    )


async def _risk_state(now: datetime) -> risk.PortfolioRiskState:
    metrics = await positions.risk_metrics(now)
    return risk.PortfolioRiskState(
        daily_realized_ret_pct=metrics["daily_realized_ret_pct"],
        algo_drawdown_pct=metrics["algo_drawdown_pct"],
    )


def _data_timestamp(ohlcv: OHLCV, now: datetime) -> datetime:
    return ohlcv.last_close_time or now


def _market_snapshot(
    price: float,
    ohlcv: OHLCV,
    data_timestamp: datetime,
    *,
    symbol: str,
    interval: str,
    bid: float | None = None,
    ask: float | None = None,
) -> dict:
    return execution_rules.build_market_snapshot(
        symbol=symbol,
        interval=interval,
        klines_limit=config.KLINES_LIMIT,
        price=price,
        high=ohlcv.highs[-1] if ohlcv.highs else None,
        low=ohlcv.lows[-1] if ohlcv.lows else None,
        closes_count=len(ohlcv.closes),
        data_timestamp=data_timestamp,
        bid=bid,
        ask=ask,
    )


def _book_execution_features(
    *,
    bid: float | None,
    ask: float | None,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
    price: float,
    data_timestamp: datetime,
) -> dict:
    features = {
        "source": "book_ticker_snapshot",
        "data_timestamp": execution_rules.format_utc_timestamp(data_timestamp),
        "last_price": price,
    }
    if bid and ask and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000.0
        features.update(
            {
                "last_bid": bid,
                "last_ask": ask,
                "spread_bps_avg": spread_bps,
                "spread_bps_p95": spread_bps,
                "expected_slippage_bps": spread_bps / 2.0,
            }
        )
        bids = bids or []
        asks = asks or []
        bid_depth = tca_shadow.depth_within_bps(bids, mid=mid, side="bid")
        ask_depth = tca_shadow.depth_within_bps(asks, mid=mid, side="ask")
        min_depth = (
            min(value for value in (bid_depth, ask_depth) if value is not None)
            if (bid_depth is not None or ask_depth is not None)
            else None
        )
        if min_depth is not None:
            depth_penalty = max(
                0.0,
                config.EXEC_GATE_MIN_DEPTH_10BP_USD / max(min_depth, 1.0) - 1.0,
            )
            features["expected_slippage_bps"] = spread_bps / 2.0 + depth_penalty
            features["depth_score"] = min_depth / config.EXEC_GATE_MIN_DEPTH_10BP_USD
        features.update(
            {
                "depth_10bp_bid_usd": bid_depth,
                "depth_10bp_ask_usd": ask_depth,
                "depth_bids": bids,
                "depth_asks": asks,
            }
        )
    return features


async def _latest_realtime_risk_features(
    *,
    symbol: str,
    now: datetime,
) -> dict:
    row = await data_lake.fetch_latest_realtime_risk_state(
        symbol=symbol,
        now=now,
        max_age_seconds=config.REALTIME_RISK_FRESHNESS_SECONDS,
    )
    if not row:
        return {
            "realtime_risk_state": None,
            "realtime_risk_live_enabled": config.ENABLE_ARENA_REALTIME_RISK_LIVE,
        }
    return {
        "realtime_risk_state": row.get("risk_state"),
        "realtime_risk_score": row.get("risk_score"),
        "realtime_risk_recommended_action": row.get("recommended_action"),
        "realtime_risk_trigger_reasons": row.get("trigger_reasons") or [],
        "realtime_risk_quality_status": row.get("quality_status"),
        "realtime_risk_fresh": row.get("fresh", False),
        "realtime_risk_age_seconds": row.get("age_seconds"),
        "realtime_risk_live_enabled": config.ENABLE_ARENA_REALTIME_RISK_LIVE,
        "realtime_risk_snapshot": row.get("risk_snapshot") or row,
    }


def _realtime_risk_blocks_entry(features: dict) -> bool:
    if not config.ENABLE_ARENA_REALTIME_RISK_LIVE:
        return False
    if not features.get("realtime_risk_fresh"):
        return False
    return features.get("realtime_risk_state") in {
        realtime_risk.STATE_BLOCK_ENTRY,
        realtime_risk.STATE_EXIT_CANDIDATE,
        realtime_risk.STATE_FORCE_EXIT_CANDIDATE,
    }


def _decision_from_snapshot(features: dict, now: datetime) -> realtime_risk.RealtimeRiskDecision:
    snapshot = dict(features.get("realtime_risk_snapshot") or {})
    window_start = execution_rules.parse_utc_datetime(snapshot.get("window_start") or now)
    window_end = execution_rules.parse_utc_datetime(snapshot.get("window_end") or now)
    return realtime_risk.RealtimeRiskDecision(
        symbol=str(snapshot.get("symbol") or parameters.BINANCE_SYMBOL),
        window_start=window_start,
        window_end=window_end,
        risk_state=str(features.get("realtime_risk_state") or realtime_risk.STATE_UNKNOWN),
        risk_score=features.get("realtime_risk_score"),
        component_scores=dict(snapshot.get("component_scores") or {}),
        trigger_reasons=list(features.get("realtime_risk_trigger_reasons") or []),
        recommended_action=str(
            features.get("realtime_risk_recommended_action") or "shadow_block_new_spot_buy"
        ),
        quality_status=str(features.get("realtime_risk_quality_status") or "degraded"),
        feature_snapshot=dict(snapshot.get("feature_snapshot") or {}),
        baseline_snapshot=dict(snapshot.get("baseline_snapshot") or {}),
        policy=realtime_risk.RealtimeRiskPolicy(),
        evaluated_at=now,
    )


def _signal_reason(algo_id: str, signal: str | None, ind: dict, macro: dict) -> dict:
    return execution_rules.build_signal_reason(
        algo_id=algo_id,
        signal=signal,
        indicators=ind,
        macro=macro,
    )


async def _run_shadow_vnext(
    *,
    run_id: str,
    data_timestamp: datetime,
    price: float,
    ind: dict,
    macro: dict,
    policy: risk.PortfolioRiskPolicy,
    portfolio_risk_state: risk.PortfolioRiskState,
    profile: frequency.FrequencyProfile,
    cost_scenario: frequency.CostScenario,
) -> list[data_lake.CaptureWriteResult]:
    if not config.ENABLE_ARENA_SHADOW_VNEXT:
        return []
    results: list[data_lake.CaptureWriteResult] = []
    try:
        snapshot = await market_structure.fetch_market_structure_snapshot(
            symbol=profile.symbol,
            interval=profile.interval,
            data_timestamp=data_timestamp,
            spot_close=price,
            limit=config.KLINES_LIMIT,
        )
        # 같은 프로세스의 realtime 수집기가 futures_stress 계산에 쓰도록 최신 features 공유
        market_structure.set_latest_market_features(snapshot.features)
        results.extend(
            await data_lake.record_market_structure_snapshot(
                run_id=run_id,
                snapshot=snapshot,
            )
        )
        risk_snapshot = {
            "policy": risk.policy_snapshot(policy),
            "state": {
                "daily_realized_ret_pct": portfolio_risk_state.daily_realized_ret_pct,
                "algo_drawdown_pct": dict(portfolio_risk_state.algo_drawdown_pct),
                "killed_algos": dict(portfolio_risk_state.killed_algos),
            },
        }
        for sleeve_signal, regime_decision in sleeves.evaluate_shadow_sleeves(
            ind,
            snapshot.features,
            macro,
            profile=profile,
            cost_scenario=cost_scenario,
        ):
            allocation = allocator.allocate_shadow(
                sleeve_signal,
                regime_snapshot=regime_decision.as_dict(),
                risk_snapshot=risk_snapshot,
            )
            gate_decision = execution_gate.evaluate_execution_gate(
                algo_id=sleeve_signal.algo_id,
                signal=sleeve_signal.direction,
                indicators=ind,
                realtime_features=snapshot.features,
                cost_scenario=cost_scenario,
                risk_decision=None,
                evaluated_at=data_timestamp,
                policy=_execution_gate_policy(),
            )
            sleeve_reason = dict(sleeve_signal.reason)
            sleeve_reason["execution_gate"] = gate_decision.as_dict()
            sleeve_signal = sleeves.SleeveSignal(
                sleeve_id=sleeve_signal.sleeve_id,
                algo_id=sleeve_signal.algo_id,
                direction=sleeve_signal.direction,
                confidence=sleeve_signal.confidence,
                raw_score=sleeve_signal.raw_score,
                target_weight=sleeve_signal.target_weight,
                reason=sleeve_reason,
                feature_snapshot={
                    **sleeve_signal.feature_snapshot,
                    "execution_gate": gate_decision.as_dict(),
                },
            )
            results.append(
                await data_lake.record_shadow_decision(
                    run_id=run_id,
                    signal=sleeve_signal,
                    allocation=allocation,
                )
            )
    except Exception as exc:
        logger.warning("Arena shadow vNext failed: %s", exc)
        results.append(
            data_lake.CaptureWriteResult(
                label="arena_shadow_vnext",
                ok=False,
                error=str(exc),
            )
        )
    return results


async def _run_cycle() -> None:
    run_id = data_lake.new_run_id()
    started_at = datetime.now(timezone.utc)
    capture_results: list[data_lake.CaptureWriteResult] = []
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    indicator_profile_id = profile.default_indicator_profile_id
    cost_scenario = frequency.get_cost_scenario(
        profile.frequency_profile_id,
        profile.default_cost_scenario_id,
    )
    base_params_snapshot = _base_params_snapshot(
        profile=profile,
        indicator_profile_id=indicator_profile_id,
        cost_scenario=cost_scenario,
    )
    logger.info("4H cycle start")
    capture_results.extend(
        await data_lake.record_strategy_metadata(params_snapshot=base_params_snapshot)
    )
    capture_results.append(
        await data_lake.record_run_started(
            run_id=run_id,
            started_at=started_at,
            params_snapshot=base_params_snapshot,
            symbol=profile.symbol,
            interval=profile.interval,
            frequency_profile_id=profile.frequency_profile_id,
            indicator_profile_id=indicator_profile_id,
            cost_model_version=cost_scenario.cost_model_version,
            cost_scenario_id=cost_scenario.cost_scenario_id,
            product_type=config.TARGET_PRODUCT,
            position_semantics=config.POSITION_SEMANTICS,
        )
    )
    try:
        ohlcv, macro_data = await asyncio.gather(
            _fetch_ohlcv(
                symbol=profile.symbol,
                interval=profile.interval,
                limit=config.KLINES_LIMIT,
            ),
            _fetch_macro(),
        )
    except Exception as exc:
        logger.error("데이터 수집 실패: %s", exc)
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message=str(exc),
            capture_results=capture_results,
        )
        return

    if not ohlcv.closes:
        logger.error("closes 비어있음 — 사이클 스킵")
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message="empty_closes",
            capture_results=capture_results,
        )
        return

    ind = indicators.compute(
        ohlcv.highs,
        ohlcv.lows,
        ohlcv.closes,
        interval=profile.interval,
        indicator_profile_id=indicator_profile_id,
    )
    now = datetime.now(timezone.utc)
    data_timestamp = _data_timestamp(ohlcv, now)
    macro = dict(macro_data.signal)
    # 로컬 4h 레짐을 주입해 알고리즘이 일관된 레짐 어휘(bull_trend 등)를 받도록 한다.
    # (매크로 오버레이의 BullQuiet 라벨과 algorithms.py 상수 불일치 버그 수정)
    macro["arena_regime_state"] = regime.classify_regime(ind, {}, macro).regime_state
    price = ohlcv.closes[-1]
    capture_results.extend(
        await data_lake.record_ohlcv_bars(
            run_id=run_id,
            raw_klines=ohlcv.raw_klines,
            fetched_at=now,
            symbol=profile.symbol,
            interval=profile.interval,
        )
    )
    capture_results.append(
        await data_lake.record_macro_snapshot(
            run_id=run_id,
            fetched_at=macro_data.fetched_at or now,
            source_url=macro_data.source_url,
            payload=macro_data.payload,
            signal=macro,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_snapshot(
            run_id=run_id,
            data_timestamp=data_timestamp,
            indicators=ind,
            symbol=profile.symbol,
            interval=profile.interval,
            indicator_profile_id=indicator_profile_id,
            frequency_profile_id=profile.frequency_profile_id,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_feature_bar(
            run_id=run_id,
            symbol=profile.symbol,
            interval=profile.interval,
            data_timestamp=data_timestamp,
            indicators=ind,
            indicator_profile_id=indicator_profile_id,
            frequency_profile_id=profile.frequency_profile_id,
        )
    )
    logger.info(
        "price=%.2f  rsi=%.1f  macd_hist=%.4f  atr=%.2f  macro=%s",
        price,
        ind["rsi"],
        ind["macd_hist"],
        ind["atr"],
        macro,
    )

    # 의사결정 시점 호가 스냅샷 (Tier 1 TCA 선행 데이터). 사이클당 1회 공유.
    (bid, ask), (depth_bids, depth_asks) = await asyncio.gather(
        _fetch_book_ticker(profile.symbol),
        _fetch_depth_snapshot(profile.symbol),
    )
    execution_features = _book_execution_features(
        bid=bid,
        ask=ask,
        bids=depth_bids,
        asks=depth_asks,
        price=price,
        data_timestamp=data_timestamp,
    )
    execution_features.update(await _latest_realtime_risk_features(symbol=profile.symbol, now=now))

    had_algo_error = False
    policy = _risk_policy()
    gate_policy = _execution_gate_policy()
    portfolio_risk_state = await _risk_state(now)
    for algo_id, fn in ALGORITHMS.items():
        signal: str | None = None
        raw_signal: str | None = None
        action = "flat_skip"
        skipped_reason: str | None = None
        resulting_position_id: int | None = None
        risk_decision: risk.RiskDecision | None = None
        gate_decision: execution_gate.ExecutionGateDecision | None = None
        product_decision: spot_policy.SpotExecutionDecision | None = None
        current = state.open_positions.get(algo_id)
        current_position_id = current["id"] if current else None
        try:
            raw_signal = fn(macro, ind)
            product_decision = spot_policy.decide(raw_signal, current)
            signal = product_decision.executable_signal
            action = product_decision.action
            skipped_reason = product_decision.skipped_reason

            if product_decision.should_close:
                if current is not None:
                    if (
                        not execution_rules.min_hold_ok(
                            current,
                            now,
                            algo_id,
                            parameters.MIN_HOLD_HOURS,
                            parameters.MIN_HOLD_FALLBACK_HOURS,
                        )
                        and not product_decision.legacy_short_close
                        and raw_signal != "short"
                    ):
                        action = "min_hold_skip"
                        skipped_reason = "flat_signal_before_min_hold"
                        continue
                    ret_pct = await positions.close_position(
                        current["id"],
                        now,
                        price,
                        close_reason=product_decision.close_reason,
                    )
                    hold_h = execution_rules.hold_hours(current["open_time"], now)
                    state.open_positions[algo_id] = None
                    portfolio_risk_state = await _risk_state(now)
                    await slack_notify.notify_close(
                        algo_id=algo_id,
                        direction=current["direction"],
                        open_price=current["open_price"],
                        close_price=price,
                        ret_pct=ret_pct,
                        hold_hours=hold_h,
                        position_id=current["id"],
                        is_stop_loss=False,
                        close_reason=product_decision.close_reason or "flat_signal",
                    )
                continue

            if not product_decision.should_open:
                continue

            risk_decision = risk.evaluate_open(
                algo_id=algo_id,
                direction=signal,
                open_positions=state.open_positions,
                state=portfolio_risk_state,
                evaluated_at=now,
                policy=policy,
            )
            if not risk_decision.allowed:
                action = "risk_blocked"
                skipped_reason = risk_decision.reason
                capture_results.append(
                    await data_lake.record_risk_event(
                        run_id=run_id,
                        algo_id=algo_id,
                        event_type=risk_decision.reason,
                        risk_decision=risk_decision.as_dict(),
                        risk_snapshot=risk_decision.as_dict(),
                        position_id=current_position_id,
                    )
                )
                continue

            gate_decision = execution_gate.evaluate_execution_gate(
                algo_id=algo_id,
                signal=signal,
                indicators=ind,
                realtime_features=execution_features,
                cost_scenario=cost_scenario,
                risk_decision=risk_decision,
                evaluated_at=now,
                policy=gate_policy,
            )
            if config.ENABLE_ARENA_EXECUTION_GATE_LIVE and not gate_decision.allowed:
                action = "execution_gate_blocked"
                skipped_reason = gate_decision.reject_reason
                continue
            if _realtime_risk_blocks_entry(execution_features):
                action = "realtime_risk_blocked"
                skipped_reason = str(execution_features.get("realtime_risk_state"))
                capture_results.append(
                    await data_lake.record_realtime_risk_event(
                        decision=_decision_from_snapshot(execution_features, now),
                        previous_state=None,
                        event_type="live_entry_block",
                        run_id=run_id,
                        position_id=current_position_id,
                    )
                )
                continue

            sl_price = execution_rules.calc_stop_loss_price(
                signal,
                price,
                ind["atr"],
                atr_multiple=config.ATR_MULTIPLE,
                stop_loss_min_pct=config.STOP_LOSS_MIN_PCT,
                stop_loss_max_pct=config.STOP_LOSS_MAX_PCT,
            )
            # 변동성 타깃 포지션 사이징 — 고변동 축소 / 저변동 확대 (현물 0.25~1.0배).
            position_weight = execution_rules.vol_target_weight(
                ind.get("realized_vol_24h", 0.0),
                target_vol=parameters.VOL_TARGET_PER_BAR,
                weight_min=parameters.VOL_WEIGHT_MIN,
                weight_max=parameters.VOL_WEIGHT_MAX,
            )
            new_pos = await positions.open_position(
                algo_id,
                signal,
                now,
                price,
                sl_price,
                data_timestamp=data_timestamp,
                strategy_version=parameters.STRATEGY_VERSION,
                params_version=parameters.PARAMS_VERSION,
                position_weight=position_weight,
                slippage_bps=cost_scenario.slippage_bps,
                spread_bps_round_trip=cost_scenario.spread_bps_round_trip,
                params_snapshot=_params_snapshot(
                    algo_id,
                    profile=profile,
                    indicator_profile_id=indicator_profile_id,
                    cost_scenario=cost_scenario,
                ),
                indicator_snapshot=ind,
                macro_snapshot=macro,
                market_snapshot=_market_snapshot(
                    price,
                    ohlcv,
                    data_timestamp,
                    symbol=profile.symbol,
                    interval=profile.interval,
                    bid=bid,
                    ask=ask,
                ),
                signal_reason=_signal_reason(algo_id, signal, ind, macro),
                risk_snapshot=risk_decision.as_dict(),
            )
            state.open_positions[algo_id] = new_pos
            resulting_position_id = new_pos.get("id")
            await slack_notify.notify_open(
                algo_id=algo_id,
                direction=signal,
                price=price,
                stop_loss_price=sl_price,
                ind=ind,
                macro=macro,
                position_id=resulting_position_id,
                strategy_version=parameters.STRATEGY_VERSION,
            )

        except Exception as exc:
            had_algo_error = True
            action = "error"
            skipped_reason = str(exc)
            logger.error("알고 %s 오류: %s", algo_id, exc)
        finally:
            if config.ENABLE_ARENA_EXECUTION_GATE_SHADOW:
                gate_decision = gate_decision or execution_gate.evaluate_execution_gate(
                    algo_id=algo_id,
                    signal=signal,
                    indicators=ind,
                    realtime_features=execution_features,
                    cost_scenario=cost_scenario,
                    risk_decision=risk_decision,
                    evaluated_at=now,
                    policy=gate_policy,
                )
                capture_results.append(
                    await data_lake.record_execution_gate(
                        run_id=run_id,
                        algo_id=algo_id,
                        signal=signal,
                        timeframe=profile.interval,
                        decision=gate_decision,
                    )
                )
                if signal is not None and action in {
                    "open",
                    "reverse",
                    "risk_blocked",
                    "execution_gate_blocked",
                    "realtime_risk_blocked",
                }:
                    rows = tca_shadow.build_shadow_tca_rows(
                        run_id=run_id,
                        algo_id=algo_id,
                        signal=signal,
                        timeframe=profile.interval,
                        evaluated_at=now,
                        gate_decision=gate_decision,
                        cost_scenario=cost_scenario,
                        target_notional_usd=config.SHADOW_ORDER_NOTIONAL_USD,
                        timeout_sec=config.SHADOW_ORDER_TIMEOUT_SEC,
                        arrival_benchmark_sec=config.SHADOW_ARRIVAL_BENCHMARK_SEC,
                    )
                    capture_results.extend(
                        await data_lake.record_shadow_tca_order(
                            parent_order=rows.parent_order,
                            execution_quality=rows.execution_quality,
                        )
                    )
            capture_results.append(
                await data_lake.record_decision(
                    run_id=run_id,
                    algo_id=algo_id,
                    signal=signal,
                    action=action,
                    reason=_signal_reason(algo_id, signal, ind, macro),
                    current_position_id=current_position_id,
                    resulting_position_id=resulting_position_id,
                    skipped_reason=skipped_reason,
                    risk_decision=risk_decision.as_dict() if risk_decision else None,
                    risk_snapshot=risk_decision.as_dict() if risk_decision else None,
                    raw_signal=product_decision.raw_signal if product_decision else raw_signal,
                    executable_signal=signal,
                    product_policy_snapshot=(
                        product_decision.policy_snapshot() if product_decision else None
                    ),
                )
            )

    capture_results.extend(
        await _run_shadow_vnext(
            run_id=run_id,
            data_timestamp=data_timestamp,
            price=price,
            ind=ind,
            macro=macro,
            policy=policy,
            portfolio_risk_state=portfolio_risk_state,
            profile=profile,
            cost_scenario=cost_scenario,
        )
    )

    await data_lake.record_run_completed(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc),
        status="partial_failed" if had_algo_error else "completed",
        data_timestamp=data_timestamp,
        capture_results=capture_results,
    )


async def _run_frequency_shadow_cycle(profile_id: str) -> None:
    profile = frequency.get_frequency_profile(profile_id)
    indicator_profile_id = profile.default_indicator_profile_id
    cost_scenario = frequency.get_cost_scenario(
        profile.frequency_profile_id,
        profile.default_cost_scenario_id,
    )
    run_id = data_lake.new_run_id()
    started_at = datetime.now(timezone.utc)
    capture_results: list[data_lake.CaptureWriteResult] = []
    base_params_snapshot = _base_params_snapshot(
        profile=profile,
        indicator_profile_id=indicator_profile_id,
        cost_scenario=cost_scenario,
    )
    logger.info("Frequency shadow cycle start: %s", profile.frequency_profile_id)
    capture_results.extend(
        await data_lake.record_strategy_metadata(params_snapshot=base_params_snapshot)
    )
    capture_results.append(
        await data_lake.record_run_started(
            run_id=run_id,
            started_at=started_at,
            params_snapshot=base_params_snapshot,
            symbol=profile.symbol,
            interval=profile.interval,
            frequency_profile_id=profile.frequency_profile_id,
            indicator_profile_id=indicator_profile_id,
            cost_model_version=cost_scenario.cost_model_version,
            cost_scenario_id=cost_scenario.cost_scenario_id,
            product_type=config.TARGET_PRODUCT,
            position_semantics=config.POSITION_SEMANTICS,
        )
    )
    try:
        ohlcv, macro_data = await asyncio.gather(
            _fetch_ohlcv(
                symbol=profile.symbol,
                interval=profile.interval,
                limit=config.KLINES_LIMIT,
            ),
            _fetch_macro(),
        )
    except Exception as exc:
        logger.error("Frequency shadow data failed (%s): %s", profile.frequency_profile_id, exc)
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message=str(exc),
            capture_results=capture_results,
        )
        return

    if not ohlcv.closes:
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message="empty_closes",
            capture_results=capture_results,
        )
        return

    now = datetime.now(timezone.utc)
    data_timestamp = _data_timestamp(ohlcv, now)
    macro = dict(macro_data.signal)
    price = ohlcv.closes[-1]
    ind = indicators.compute(
        ohlcv.highs,
        ohlcv.lows,
        ohlcv.closes,
        interval=profile.interval,
        indicator_profile_id=indicator_profile_id,
    )
    macro["arena_regime_state"] = regime.classify_regime(ind, {}, macro).regime_state
    capture_results.extend(
        await data_lake.record_ohlcv_bars(
            run_id=run_id,
            raw_klines=ohlcv.raw_klines,
            fetched_at=now,
            symbol=profile.symbol,
            interval=profile.interval,
        )
    )
    capture_results.append(
        await data_lake.record_macro_snapshot(
            run_id=run_id,
            fetched_at=macro_data.fetched_at or now,
            source_url=macro_data.source_url,
            payload=macro_data.payload,
            signal=macro,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_snapshot(
            run_id=run_id,
            data_timestamp=data_timestamp,
            indicators=ind,
            symbol=profile.symbol,
            interval=profile.interval,
            indicator_profile_id=indicator_profile_id,
            frequency_profile_id=profile.frequency_profile_id,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_feature_bar(
            run_id=run_id,
            symbol=profile.symbol,
            interval=profile.interval,
            data_timestamp=data_timestamp,
            indicators=ind,
            indicator_profile_id=indicator_profile_id,
            frequency_profile_id=profile.frequency_profile_id,
        )
    )
    policy = _risk_policy()
    portfolio_risk_state = await _risk_state(now)
    capture_results.extend(
        await _run_shadow_vnext(
            run_id=run_id,
            data_timestamp=data_timestamp,
            price=price,
            ind=ind,
            macro=macro,
            policy=policy,
            portfolio_risk_state=portfolio_risk_state,
            profile=profile,
            cost_scenario=cost_scenario,
        )
    )
    await data_lake.record_run_completed(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc),
        status="completed",
        data_timestamp=data_timestamp,
        capture_results=capture_results,
    )


def _frequency_shadow_cron(profile: frequency.FrequencyProfile) -> dict[str, object]:
    if profile.decision_cadence_minutes < 60:
        return {"hour": "*", "minute": f"*/{profile.decision_cadence_minutes}"}
    cadence_hours = max(1, profile.decision_cadence_minutes // 60)
    return {"hour": "*" if cadence_hours == 1 else f"*/{cadence_hours}", "minute": 10}


async def run() -> None:
    """APScheduler 시작 + 즉시 1회 실행. server.py에서 asyncio.gather()로 호출."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_cycle,
        "cron",
        hour=parameters.SCHEDULER_CRON_HOUR,
        minute=parameters.SCHEDULER_CRON_MINUTE,
    )
    if config.ENABLE_ARENA_FREQUENCY_SHADOW:
        for profile_id in config.ARENA_FREQUENCY_SHADOW_PROFILES:
            profile = frequency.get_frequency_profile(profile_id)
            cron = _frequency_shadow_cron(profile)
            scheduler.add_job(
                _run_frequency_shadow_cycle,
                "cron",
                args=[profile_id],
                **cron,
            )
    scheduler.start()
    logger.info("Scheduler started (cron every 4H at :%02d)", parameters.SCHEDULER_CRON_MINUTE)

    await _run_cycle()
    if config.ENABLE_ARENA_FREQUENCY_SHADOW:
        await asyncio.gather(
            *[
                _run_frequency_shadow_cycle(profile_id)
                for profile_id in config.ARENA_FREQUENCY_SHADOW_PROFILES
            ]
        )

    try:
        while True:
            await asyncio.sleep(parameters.SERVER_IDLE_SLEEP_SECONDS)
    finally:
        scheduler.shutdown()
