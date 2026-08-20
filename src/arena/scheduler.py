"""4H APScheduler 사이클 — Binance 4H OHLCV + R2 매크로 → 알고리즘 실행 → 포지션 관리."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import (
    allocator,
    backtest_report,
    config,
    data_lake,
    execution_gate,
    execution_rules,
    frequency,
    futures_baseline,
    indicators,
    liquidation_features,
    market_structure,
    parameters,
    perp_policy,
    positions,
    realtime_risk,
    regime,
    risk,
    short_signals,
    slack_notify,
    sleeves,
    spot_policy,
    state,
    tca_shadow,
)
from .algorithms import (
    ALGORITHMS,
    atr_target_price,
    exit_hold_override,
    explain_signal,
    fng_scaled_tranches,
    fng_target_pct,
    fng_vix_unknown_multiplier,
    meridian_active_leg,
    omnibus_position_multiplier,
    omnibus_target_price,
    primary_flat_skip_reason,
    tsmom_nl_position_multiplier,
    tsmom_nl_position_multiplier_abs,
)
from .algorithms import (
    fng_duration_scale as fng_duration_scale_fn,
)

logger = logging.getLogger(__name__)


class OHLCV(NamedTuple):
    highs: list[float]
    lows: list[float]
    closes: list[float]
    last_close_time: datetime | None
    raw_klines: list[list]
    volumes: list[float] = []  # WI-4: 돌파 확인용 봉 거래량(base asset volume, k[5])


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
        volumes=[float(k[5]) for k in klines],
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
            # P3(2026-07-21): fng<30 연속일수 — fng_contrarian 진입 품질 피처
            "fng_days_below_30": raw.get("fng_days_below_30"),
            # SJM 섀도우 (알고 게이트 미적용 — 30일 관찰 후 승격 여부 판단)
            "sjm_state": raw.get("sjm_state"),
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
    """의사결정 시점 오더북 스냅샷. 실패해도 shadow TCA만 degraded 처리된다.

    limit=1000(parameters.EXEC_GATE_DEPTH_SNAPSHOT_LIMIT) — 이전 limit=20은 BTCUSDT
    10bps 밴드의 5~6%만 커버해 depth_10bp_*_usd가 실제값의 ~1.5~2%로 과소추정되던
    버그(2026-07-30 진단, 실측 $98K vs 실제 $6.26M) 수정.
    """
    try:
        url = (
            f"{config.BINANCE_DEPTH_URL}?symbol={symbol}"
            f"&limit={parameters.EXEC_GATE_DEPTH_SNAPSHOT_LIMIT}"
        )
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
        # spot→perp 전환 Phase A(2026-08-15): 위 필드들은 여전히 "기본 spot" 상태를
        # 기술한다(하위호환) — 실제 알고별 오버라이드는 이 필드로 관측한다.
        "perp_short_enabled_tracks": [
            {"track_symbol": track_symbol, "algo_id": algo_id}
            for track_symbol, algo_id in sorted(parameters.PERP_SHORT_ENABLED_TRACKS)
        ],
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
        portfolio_risk=risk.policy_snapshot(_risk_policy(profile)),
    )


def _position_semantics_for_product_type(product_type: str) -> str:
    """트랙의 product_type(profile.product_type)에서 position_semantics를 도출."""
    return (
        parameters.POSITION_SEMANTICS
        if product_type == "spot"
        else parameters.PERP_POSITION_SEMANTICS
    )


def _short_enabled_for(profile: frequency.FrequencyProfile, algo_id: str) -> bool:
    """Return True only for an explicitly approved perp track and algorithm pair."""
    return parameters.perp_short_enabled(
        track_symbol=profile.symbol,
        product_type=profile.product_type,
        algo_id=algo_id,
    )


def _meridian_concurrent_leg_count(track_symbol: str, leg: str) -> int:
    """`track_symbol`을 제외한 다른 meridian perp 트랙 중, 이미 같은 leg로 열려 있는
    포지션 수를 센다. 신규진입 직전 MERIDIAN_LEG_CONCURRENCY_CAP과 비교하는 용도
    (scheduler.py 상관캡, 2026-08-16). leg는 `signal_reason.diagnostics.factors.active_leg`
    (long: "trend"/"reversion") 또는 "short"에 저장돼 있다(explain_signal 배선)."""
    tracks = parameters.ALGORITHM_TRACK_SCOPE.get("meridian", frozenset())
    count = 0
    for other_symbol in tracks:
        if other_symbol == track_symbol:
            continue
        pos = state.get_position(other_symbol, "meridian")
        if pos is None:
            continue
        diag = (pos.get("signal_reason") or {}).get("diagnostics") or {}
        other_leg = (diag.get("factors") or {}).get("active_leg")
        if pos.get("direction") == "short":
            other_leg = "short"
        if other_leg == leg:
            count += 1
    return count


def _risk_policy(profile: frequency.FrequencyProfile) -> risk.PortfolioRiskPolicy:
    # 숏 캡은 승인된 자산×알고 쌍이 있는 perp 트랙에서만 개방한다.
    # 현물 트랙은 다른 트랙에서 동일 algo_id가 승인됐더라도 숏 캡 0을 유지한다.
    short_active = parameters.perp_short_enabled_for_track(
        track_symbol=profile.symbol,
        product_type=profile.product_type,
    )
    max_short_positions = config.MAX_SHORT_POSITIONS if short_active else 0
    max_net_short_exposure = config.MAX_NET_SHORT_EXPOSURE if short_active else 0.0
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


def _min_depth_10bp_usd_for_symbol(symbol: str) -> float:
    """자산별 depth 하한(2026-08-14) — 단일 전역값이 BTC 기준으로 캘리브레이션돼 SOL
    신호의 62.5%를 "체결 나빠서"가 아니라 "SOL이라서" depth_too_thin으로 거부하던 문제
    수정(실측: scripts/analysis/exec_gate_depth_calibration.py). EXEC_GATE_MIN_DEPTH_
    10BP_USD_BY_SYMBOL에 없는 심볼은 기존 전역 env-override값(BTC 캘리브레이션)으로 폴백.
    ⚠️ _execution_gate_policy()와 _book_execution_features() 양쪽에서 반드시 이 함수를
    통해 조회할 것 — _book_execution_features()가 depth_score/expected_slippage_bps를
    선계산해 explicit 값으로 두면 execution_gate._depth_score()가 policy 값을 무시하고
    그 값을 그대로 쓴다(2026-08-14 배포 직후 SOL 실측으로 발견: depth_score가 신
    threshold가 아니라 구 전역값 $1M 기준으로 나오고 있었음).
    """
    return parameters.EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL.get(
        symbol, config.EXEC_GATE_MIN_DEPTH_10BP_USD
    )


def _execution_gate_policy(
    symbol: str = parameters.BINANCE_SYMBOL,
) -> execution_gate.ExecutionGatePolicy:
    return execution_gate.ExecutionGatePolicy(
        ecr_multiple=config.EXEC_GATE_ECR_MULTIPLE,
        max_spread_bps=config.EXEC_GATE_MAX_SPREAD_BPS,
        max_slippage_bps=config.EXEC_GATE_MAX_SLIPPAGE_BPS,
        min_depth_score=config.EXEC_GATE_MIN_DEPTH_SCORE,
        max_latency_ms=config.EXEC_GATE_MAX_LATENCY_MS,
        vol_spike_max=config.EXEC_GATE_VOL_SPIKE_MAX,
        min_depth_10bp_usd=_min_depth_10bp_usd_for_symbol(symbol),
    )


async def _risk_state(now: datetime, *, symbol: str) -> risk.PortfolioRiskState:
    """symbol 전용 리스크 상태 — 2026-08-06 멀티자산 승격으로 자산 간 일간손실·drawdown이
    섞이지 않도록 심볼별로 독립 평가한다(각 자산×알고 독립자본 원칙과 동일선상)."""
    metrics = await positions.risk_metrics(now, symbol=symbol)
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
    min_depth_10bp_usd: float = parameters.EXEC_GATE_MIN_DEPTH_10BP_USD,
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
                min_depth_10bp_usd / max(min_depth, 1.0) - 1.0,
            )
            features["expected_slippage_bps"] = spread_bps / 2.0 + depth_penalty
            features["depth_score"] = min_depth / min_depth_10bp_usd
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
    reason = execution_rules.build_signal_reason(
        algo_id=algo_id,
        signal=signal,
        indicators=ind,
        macro=macro,
    )
    # direction=signal(2026-08-20 결함수정): 숏 거래의 진단이 롱 조건으로 재계산되던 버그.
    # explain_signal이 direction="short"를 받으면 macd_momentum에 한해 숏 전용 분기로
    # 계산한다(다른 알고는 기존과 동일, 하위호환).
    reason["diagnostics"] = explain_signal(algo_id, macro, ind, direction=signal)
    return reason


def _fng_open_reason() -> dict:
    """fng_contrarian 최초 진입 시 signal_reason에 심을 물타기 진행 상태.

    기준가(fng_ref_price)는 호출측에서 진입가로 채우고, 여기선 1단계 체결을 표기.
    """
    return {"fng_filled_count": 1}


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
            symbol=profile.binance_symbol,
            interval=profile.interval,
            data_timestamp=data_timestamp,
            spot_close=price,
            limit=config.KLINES_LIMIT,
        )
        # 같은 프로세스의 realtime 수집기가 futures_stress 계산에 쓰도록 최신 features 공유
        market_structure.set_latest_market_features(snapshot.features)
        # SJM 섀도우 상태를 feature snapshot에 포함 (로깅 전용, 알고 미연결)
        sjm = macro.get("sjm_state")
        if sjm is not None:
            snapshot.features["sjm_state"] = sjm
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
                macro=macro,
                indicators=ind,
                realtime_features=snapshot.features,
                cost_scenario=cost_scenario,
                risk_decision=None,
                evaluated_at=data_timestamp,
                policy=_execution_gate_policy(profile.binance_symbol),
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


async def _run_cycle(profile_id: str = frequency.LIVE_4H_PROFILE_ID) -> None:
    """4H 라이브 사이클 — 심볼은 profile_id가 결정한다(기본 BTC).

    2026-08-06: ETH/SOL을 signal-only shadow에서 이 함수(포지션 오픈/청산·사이징·
    손절·실행게이트·리스크상태·Slack 전부 포함)로 승격 — BTC와 완전히 동일한 코드
    경로를 심볼만 바꿔 재사용한다(자산별 재튜닝 금지 원칙, frequency.py 멀티자산
    프로파일과 동일 근거). scheduler.run()이 프로파일별로 별도 호출한다.
    """
    run_id = data_lake.new_run_id()
    started_at = datetime.now(timezone.utc)
    capture_results: list[data_lake.CaptureWriteResult] = []
    profile = frequency.get_frequency_profile(profile_id)
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
            market_data_symbol=profile.binance_symbol,
            interval=profile.interval,
            frequency_profile_id=profile.frequency_profile_id,
            indicator_profile_id=indicator_profile_id,
            cost_model_version=cost_scenario.cost_model_version,
            cost_scenario_id=cost_scenario.cost_scenario_id,
            product_type=profile.product_type,
            position_semantics=_position_semantics_for_product_type(profile.product_type),
        )
    )
    # return_exceptions=True 로 각 API 실패를 독립적으로 감지
    # binance_symbol(실제 티커) 사용 — profile.symbol은 트랙 식별자(perp는 "-PERP"
    # 접미사)라 REST 호출엔 못 씀. Phase A2(2026-08-15): 가격 피드는 spot 프록시 유지.
    ohlcv_res, macro_res = await asyncio.gather(
        _fetch_ohlcv(
            symbol=profile.binance_symbol,
            interval=profile.interval,
            limit=config.KLINES_LIMIT,
        ),
        _fetch_macro(),
        return_exceptions=True,
    )

    if isinstance(ohlcv_res, BaseException):
        logger.error("Binance OHLCV 수집 실패 (사이클 중단, %s): %s", profile.symbol, ohlcv_res)
        asyncio.ensure_future(
            slack_notify.notify_error(
                f"Binance OHLCV — {profile.symbol}",
                ohlcv_res,
                url=config.BINANCE_REST_URL,
                run_id=run_id,
                severity="critical",
            )
        )
        await data_lake.record_run_completed(
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            status="data_failed",
            error_message=str(ohlcv_res),
            capture_results=capture_results,
        )
        return

    ohlcv: OHLCV = ohlcv_res

    if isinstance(macro_res, BaseException):
        logger.warning("R2 매크로 수집 실패 (빈 매크로로 계속): %s", macro_res)
        asyncio.ensure_future(
            slack_notify.notify_error(
                "R2 매크로",
                macro_res,
                url=config.LATEST_JSON_URL,
                run_id=run_id,
                severity="error",
            )
        )
        macro_data = MacroData({}, {}, None, config.LATEST_JSON_URL)
    else:
        macro_data: MacroData = macro_res

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
        volumes=ohlcv.volumes,
        interval=profile.interval,
        indicator_profile_id=indicator_profile_id,
    )
    now = datetime.now(timezone.utc)
    data_timestamp = _data_timestamp(ohlcv, now)
    macro = dict(macro_data.signal)
    # 로컬 4h 레짐을 주입해 알고리즘이 일관된 레짐 어휘(bull_trend 등)를 받도록 한다.
    # (매크로 오버레이의 BullQuiet 라벨과 algorithms.py 상수 불일치 버그 수정)
    macro["arena_regime_state"] = regime.classify_regime(ind, {}, macro).regime_state
    # WI-10: 로컬 4h taker 매수/매도 비율 주입 — regime_trend 돌파의 주문흐름 확인을
    # 일간 lag1 z에서 4h 값으로 교체(하루 지연 제거). market_structure 모듈 캐시(직전 4h
    # 사이클 features — futures_stress 배선과 동일 패턴)에서 읽는다. 첫 사이클/미수집 시
    # 없음 → 알고가 일간 z로 graceful 폴백. (_run_shadow_vnext가 매 사이클 캐시 갱신)
    _taker_4h = market_structure.get_latest_market_features().get("taker_buy_sell_ratio")
    if _taker_4h is not None:
        macro["taker_ratio_4h"] = _taker_4h
    # WI-9 v2(2026-08-10): 청산(forceOrder) 소진·비대칭 피처 주입 — 전부 None-graceful, 게이트는
    # parameters.LIQUIDATION_EXHAUSTION_GATE_ENABLED(기본 False)로 별도 차단(설계 근거:
    # docs/arena/research/liquidation-feature-design-20260810.md). 조회 실패해도 사이클 무영향.
    try:
        _liq_bars = await data_lake.fetch_liquidation_bars(
            symbol=profile.binance_symbol, since=now - timedelta(days=32)
        )
        macro.update(liquidation_features.liquidation_snapshot(_liq_bars, now=now))
    except Exception as exc:
        logger.warning("Liquidation feature snapshot skipped (%s): %s", profile.symbol, exc)
    # v43: funding_carry 게이트용 트레일링 평균 펀딩비 — BTC/ETH만(FUNDING_CARRY_ASSETS).
    # profile.binance_symbol(실제 티커)로 조회하므로 spot·perp 두 트랙이 같은 값을 본다
    # (perp_track_symbol 역함수 real_ticker_for_track과 무관하게 애초에 binance_symbol이
    # 실제 티커라 자동으로 일치 — 두 트랙이 매 사이클 같은 결론에 도달하는 근거).
    # get_latest_market_features() 전역 캐시(WI-10, 자산 간 공유되는 알려진 한계)는
    # 여기 안 씀 — funding_carry는 캐리 손익이 직접 걸린 신호라 직접 조회로 정확성 확보.
    if profile.binance_symbol in parameters.FUNDING_CARRY_ASSETS:
        try:
            _funding_rows = await data_lake.fetch_funding_rates(
                symbol=profile.binance_symbol,
                since=now - timedelta(hours=parameters.FUNDING_CARRY_LOOKBACK_HOURS),
                until=now,
            )
            macro["funding_carry_trailing_mean"] = market_structure.trailing_funding_mean(
                _funding_rows, now=now, lookback_hours=parameters.FUNDING_CARRY_LOOKBACK_HOURS
            )
        except Exception as exc:
            logger.warning("Funding carry trailing mean fetch failed (%s): %s", profile.symbol, exc)
    price = ohlcv.closes[-1]
    capture_results.extend(
        await data_lake.record_ohlcv_bars(
            run_id=run_id,
            raw_klines=ohlcv.raw_klines,
            fetched_at=now,
            # binance_symbol(실제 티커) — perp 트랙도 spot 가격 프록시를 쓰므로 봉
            # 데이터가 spot 트랙과 동일하다. 트랙 식별자로 쓰면 캔들 히스토리가
            # 불필요하게 중복 저장되므로 실제 티커 하나로 합쳐 upsert(idempotent).
            symbol=profile.binance_symbol,
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
            # binance_symbol — 지표도 spot 프록시 봉에서 계산되므로 spot 트랙과 동일한
            # 값이다(record_ohlcv_bars와 동일 근거로 실제 티커에 합쳐 저장).
            symbol=profile.binance_symbol,
            interval=profile.interval,
            indicator_profile_id=indicator_profile_id,
            frequency_profile_id=profile.frequency_profile_id,
        )
    )
    capture_results.append(
        await data_lake.record_indicator_feature_bar(
            run_id=run_id,
            symbol=profile.binance_symbol,
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
    # 전부 binance_symbol(실제 티커) — 호가/뎁스/실시간리스크는 실제 시장 데이터라
    # 트랙 식별자로는 조회 안 됨(perp도 spot 프록시 시장데이터를 그대로 씀).
    (bid, ask), (depth_bids, depth_asks) = await asyncio.gather(
        _fetch_book_ticker(profile.binance_symbol),
        _fetch_depth_snapshot(profile.binance_symbol),
    )
    execution_features = _book_execution_features(
        bid=bid,
        ask=ask,
        bids=depth_bids,
        asks=depth_asks,
        price=price,
        data_timestamp=data_timestamp,
        min_depth_10bp_usd=_min_depth_10bp_usd_for_symbol(profile.binance_symbol),
    )
    execution_features.update(
        await _latest_realtime_risk_features(symbol=profile.binance_symbol, now=now)
    )

    had_algo_error = False
    policy = _risk_policy(profile)
    gate_policy = _execution_gate_policy(profile.binance_symbol)
    # symbol(트랙 식별자) 그대로 — 일간손실·drawdown은 트랙(자본풀) 단위로 독립 평가
    # (spot BTC와 perp BTC가 서로 다른 리스크 상태를 가져야 함, ETH/SOL과 동일 원칙).
    portfolio_risk_state = await _risk_state(now, symbol=profile.symbol)
    for algo_id, fn in ALGORITHMS.items():
        current = state.get_position(profile.symbol, algo_id)
        # 알고별 실행 트랙 범위(v36, meridian 등 perp 전용 신규 알고 / v39, perp에서 숏을
        # 안 쓰는 기존 알고 정리) — 스코프 밖이고 열린 포지션도 없으면 이 알고를 아예
        # 건드리지 않는다(신규 진입 차단). 스코프 밖이어도 이미 열린 포지션이 있으면
        # 아래로 계속 진행해 정상 관리한다(시간손절·손절·트레일링·flat청산) — 스코프를
        # 좁혔다고 기존 포지션이 고아화(관리 안 되고 방치)되는 걸 막기 위함.
        in_scope = parameters.algorithm_in_track_scope(algo_id, profile.symbol)
        if not in_scope and current is None:
            continue
        signal: str | None = None
        raw_signal: str | None = None
        action = "flat_skip"
        skipped_reason: str | None = None
        resulting_position_id: int | None = None
        risk_decision: risk.RiskDecision | None = None
        gate_decision: execution_gate.ExecutionGateDecision | None = None
        product_decision: (
            spot_policy.SpotExecutionDecision | perp_policy.PerpExecutionDecision | None
        ) = None
        directional_signal: short_signals.DirectionalSignalDecision | None = None
        product_policy_snapshot: dict | None = None
        current_position_id = current["id"] if current else None
        short_enabled = _short_enabled_for(profile, algo_id)
        try:
            # 시간 손절(가격 손절 제거 알고 보완): 최대 보유시간 초과 시 청산.
            ts_hours = parameters.TIME_STOP_HOURS_BY_ALGO.get(algo_id)
            if (
                algo_id == "omnibus"
                and current is not None
                and parameters.OMNIBUS_LEG_TIME_STOP_HOURS
            ):
                _diag = (current.get("signal_reason") or {}).get("diagnostics") or {}
                _leg = (_diag.get("factors") or {}).get("omni_regime")
                if _leg in parameters.OMNIBUS_LEG_TIME_STOP_HOURS:
                    ts_hours = parameters.OMNIBUS_LEG_TIME_STOP_HOURS[_leg]
            if (
                current is not None
                and ts_hours
                and execution_rules.time_stop_triggered(current["open_time"], now, ts_hours)
            ):
                ret_pct = await positions.close_position(
                    current["id"], now, price, close_reason="time_stop"
                )
                hold_h = execution_rules.hold_hours(current["open_time"], now)
                state.set_position(profile.symbol, algo_id, None)
                portfolio_risk_state = await _risk_state(now, symbol=profile.symbol)
                await slack_notify.notify_close(
                    symbol=profile.symbol,
                    algo_id=algo_id,
                    direction=current["direction"],
                    open_price=current["open_price"],
                    close_price=price,
                    ret_pct=ret_pct,
                    hold_hours=hold_h,
                    position_id=current["id"],
                    is_stop_loss=False,
                    close_reason="time_stop",
                )
                continue

            long_signal = fn(macro, ind)
            directional_signal = short_signals.resolve(
                algo_id=algo_id,
                long_signal=long_signal,
                macro=macro,
                indicators=ind,
                short_enabled=short_enabled,
                current_direction=current.get("direction") if current else None,
                long_enabled=parameters.perp_long_enabled(
                    track_symbol=profile.symbol, algo_id=algo_id
                ),
            )
            raw_signal = directional_signal.resolved_signal
            product_decision = (
                perp_policy.decide(raw_signal, current)
                if short_enabled
                else spot_policy.decide(raw_signal, current)
            )
            product_policy_snapshot = product_decision.policy_snapshot()
            product_policy_snapshot.update(directional_signal.as_dict())
            product_policy_snapshot["short_enabled"] = short_enabled
            product_policy_snapshot["track_symbol"] = profile.symbol
            signal = product_decision.executable_signal
            action = product_decision.action
            skipped_reason = product_decision.skipped_reason
            if action == "flat_skip" and skipped_reason is None:
                skipped_reason = primary_flat_skip_reason(algo_id, macro, ind)

            if product_decision.should_close:
                if current is not None:
                    # 청산 히스테리시스: flat 청산만 보류 대상(risk-off·legacy short·perp
                    # 반전은 즉시 — perp 반전은 바로 아래 min_hold 체크가 별도로 게이팅).
                    if product_decision.close_reason == "flat_signal" and exit_hold_override(
                        algo_id, macro, ind
                    ):
                        action = "hold"
                        skipped_reason = "exit_hold_override"
                        continue
                    # spot은 legacy short 청산·숏 신호를 min_hold 무시하고 즉시 강제청산
                    # (spot은 애초에 숏을 보유할 수 없어 대기 자체가 의미 없음). perp는
                    # 반전을 포함해 min_hold를 균일 적용(backtest.py 비-spot 분기와 동일 —
                    # bypass 없음, 원치 않는 즉시 반전 매매를 억제).
                    bypass_min_hold = (not short_enabled) and (
                        product_decision.legacy_short_close or raw_signal == "short"
                    )
                    if (
                        not execution_rules.min_hold_ok(
                            current,
                            now,
                            algo_id,
                            parameters.MIN_HOLD_HOURS,
                            parameters.MIN_HOLD_FALLBACK_HOURS,
                        )
                        and not bypass_min_hold
                    ):
                        action = "min_hold_skip"
                        skipped_reason = "flat_signal_before_min_hold"
                        continue
                    closing = current
                    ret_pct = await positions.close_position(
                        closing["id"],
                        now,
                        price,
                        close_reason=product_decision.close_reason,
                    )
                    hold_h = execution_rules.hold_hours(closing["open_time"], now)
                    state.set_position(profile.symbol, algo_id, None)
                    current = None
                    portfolio_risk_state = await _risk_state(now, symbol=profile.symbol)
                    await slack_notify.notify_close(
                        symbol=profile.symbol,
                        algo_id=algo_id,
                        direction=closing["direction"],
                        open_price=closing["open_price"],
                        close_price=price,
                        ret_pct=ret_pct,
                        hold_hours=hold_h,
                        position_id=closing["id"],
                        is_stop_loss=False,
                        close_reason=product_decision.close_reason or "flat_signal",
                    )
                # perp 반전(should_open도 True)이면 청산 직후 같은 사이클에서 재진입을
                # 평가한다(아래로 진행) — spot은 should_close/should_open이 상호배타라
                # 항상 continue(기존 동작 무변화).
                if not (short_enabled and product_decision.should_open):
                    continue

            if not product_decision.should_open:
                # 역발산 물타기 4h 백업: 실시간 체결은 stream(1m 틱)이 담당하나, 스트림
                # 재접속 공백 등을 보완해 4h 봉종가에서도 미체결 트랜치를 점검(idempotent).
                if (
                    current is not None
                    and action == "hold"
                    and parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED
                    and algo_id == "fng_contrarian"
                    and current.get("direction") == "long"
                ):
                    updated = await positions.maybe_scale_in_fng_price(current, price)
                    if updated:
                        state.set_position(profile.symbol, algo_id, updated)
                continue

            # meridian 3자산 상관캡 (2026-08-16): 모멘텀 게이트가 자산 간 상관을 못 줄인
            # 것을 확인한 뒤 도입 — 같은 leg로 이미 열린 "다른" perp 트랙 수가 캡 이상이면
            # 신규 진입 차단. leg가 MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG에 없으면 무제한
            # (trend leg는 백테스트상 효과 없어 기본 미등록, parameters.py 참조).
            if algo_id == "meridian":
                leg = meridian_active_leg(macro, ind) if signal == "long" else "short"
                cap = (
                    parameters.MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG.get(leg)
                    if leg is not None
                    else None
                )
                if cap is not None:
                    concurrent = _meridian_concurrent_leg_count(profile.symbol, leg)
                    if concurrent >= cap:
                        action = "risk_blocked"
                        skipped_reason = f"meridian_leg_concurrency_cap:{leg}"
                        continue

            risk_decision = risk.evaluate_open(
                algo_id=algo_id,
                direction=signal,
                open_positions=state.positions_for(profile.symbol),
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
                macro=macro,
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
            # 포지션 사이징 — 변동성타깃 ∧ 거래당 자본위험 중 더 보수적인 비중(현물 0.25~0.7배).
            # signal=="long" 게이팅(2026-08-16, v41 fng_contrarian_short 배선 계기): 물타기·
            # 목표가익절은 v22/P-A로 검증된 롱 전용 메커니즘 — 숏에 적용하면 목표가가 진입가
            # "위"에 잡혀 즉시 손실 확정된다(Phase B §13 실측). 숏은 else 분기의 표준 사이징만.
            is_fng_scale = (
                algo_id == "fng_contrarian"
                and signal == "long"
                and parameters.FNG_CONTRARIAN_SCALE_IN_ENABLED
            )
            fng_duration_scale = 1.0
            if is_fng_scale:
                # 역발산: 1차 트랜치만 진입. 물타기는 가격 하락 시 실시간(stream)으로 추가.
                # P3(2026-07-21, 미검증): fng_days_below_30 기반 균일 스케일.
                fng_duration_scale = fng_duration_scale_fn(macro)
                position_weight = fng_scaled_tranches(fng_duration_scale)[0][1]
            else:
                position_weight = execution_rules.combined_position_weight(
                    ind.get("realized_vol_sizing", ind.get("realized_vol_24h", 0.0)),
                    price,
                    sl_price,
                    target_vol=parameters.VOL_TARGET_PER_BAR,
                    risk_budget_pct=parameters.RISK_PER_TRADE_PCT,
                    weight_min=parameters.VOL_WEIGHT_MIN,
                    weight_max=parameters.VOL_WEIGHT_MAX,
                )
                # omnibus: 레짐별 추가 배수 적용 (UP_TREND=1.0, RANGE=0.4, REBOUND=0.25)
                if algo_id == "omnibus":
                    position_weight *= omnibus_position_multiplier(macro, ind)
                # Nonlinear TSMOM(v35, 2026-08-08 활성화): TSMOM_NL_ENABLED=False면 1.0(무효과).
                # v41: 숏(macd_momentum_short)은 abs 사이징(음수클립 없음) — backtest.py와
                # 동일 근거(롱 클립 함수를 쓰면 숏 신호가 전부 비중 0이 됨).
                if algo_id == "macd_momentum":
                    if signal == "long":
                        position_weight *= tsmom_nl_position_multiplier(macro, ind)
                    else:
                        position_weight *= tsmom_nl_position_multiplier_abs(macro, ind)
                # meridian(v36) — 추세 leg 진입일 때만 TSMOM_NL f(s) 사이징 재적용
                # (역발산 leg는 combined_position_weight 기본값 그대로, 설계 §2-2).
                if algo_id == "meridian" and signal == "long":
                    if meridian_active_leg(macro, ind) == "trend":
                        position_weight *= tsmom_nl_position_multiplier(macro, ind)
            # P4(2026-07-21, 신규·미검증): unknown 레짐 진입 사이징 완화. dict에 없으면
            # 1.0(무효과). fng는 최초 1차 트랜치에만 적용(이후 물타기는 정상 스케줄 유지).
            if algo_id in ("fng_contrarian", "vix_rsi"):
                position_weight *= fng_vix_unknown_multiplier(algo_id, macro)
            # meridian(v36) — 숏 leg 사이징 감쇠(설계 §2-3, 증거 비대칭을 명시적으로 반영).
            if algo_id == "meridian" and signal == "short":
                position_weight *= parameters.MERIDIAN_SHORT_SIZE_DAMPENER
            open_signal_reason = _signal_reason(algo_id, signal, ind, macro)
            if is_fng_scale:
                # 물타기 기준가 = 최초 진입가, 1단계 체결 표기.
                open_signal_reason.update(_fng_open_reason())
                open_signal_reason["fng_ref_price"] = price
                # P3: 진입 시점 스케일 고정 — 이후 stream.py 물타기가 동일 배수로 재사용.
                open_signal_reason["fng_duration_scale"] = fng_duration_scale
                # P-A: 이익 포착 목표 상승률(비율). 물타기로 평단 하락 시 청산가 자동 하향.
                _fng_tp = fng_target_pct(ind, price)
                if _fng_tp is not None:
                    open_signal_reason["fng_target_pct"] = _fng_tp
            # WI-7: omnibus 평균회귀(RANGE/REBOUND) 익절 목표가를 진입 시점에 고정.
            if algo_id == "omnibus":
                _omni_target = omnibus_target_price(macro, ind, price)
                if _omni_target is not None:
                    open_signal_reason["omni_target_price"] = _omni_target
            # Tier2: 범용 목표가 익절(vix_rsi/multi_factor 등). dict에 없으면 무효과.
            if (
                parameters.GENERIC_TARGET_EXIT_ENABLED
                and algo_id in parameters.TARGET_EXIT_ATR_MULT_BY_ALGO
            ):
                _target = atr_target_price(
                    signal,
                    price,
                    ind.get("atr", 0.0) or 0.0,
                    parameters.TARGET_EXIT_ATR_MULT_BY_ALGO[algo_id],
                )
                if _target is not None:
                    open_signal_reason["target_price"] = _target
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
                symbol=profile.symbol,
                product_type=profile.product_type,
                position_semantics=_position_semantics_for_product_type(profile.product_type),
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
                signal_reason=open_signal_reason,
                risk_snapshot=risk_decision.as_dict(),
            )
            state.set_position(profile.symbol, algo_id, new_pos)
            resulting_position_id = new_pos.get("id")
            await slack_notify.notify_open(
                symbol=profile.symbol,
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
            logger.error("알고 %s(%s) 오류: %s", algo_id, profile.symbol, exc, exc_info=True)
            asyncio.ensure_future(
                slack_notify.notify_error(
                    f"알고리즘 — {profile.symbol} {algo_id}",
                    exc,
                    run_id=run_id,
                    severity="error",
                )
            )
        finally:
            if config.ENABLE_ARENA_EXECUTION_GATE_SHADOW:
                gate_decision = gate_decision or execution_gate.evaluate_execution_gate(
                    algo_id=algo_id,
                    signal=signal,
                    macro=macro,
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
                    "signal_reverse",
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
                    product_policy_snapshot=product_policy_snapshot,
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
            market_data_symbol=profile.binance_symbol,
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
        volumes=ohlcv.volumes,
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
    policy = _risk_policy(profile)
    portfolio_risk_state = await _risk_state(now, symbol=profile.symbol)
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


async def _run_asset_shadow_cycle(symbol: str) -> None:
    """멀티자산 확장 1차(BTC 제외 ETH/SOL) 경량 shadow 사이클 (2026-07-31, P1-4).

    설계문서(docs/arena/research/structural-priority-multi-asset-expansion-20260730.md)의
    Track A/B 검증용. `_run_shadow_vnext()`가 재사용하는 sleeves.SHADOW_SLEEVES는
    trend_core(regime_trend) 1개만 등록돼 있어 6개 알고 전부를 검증하려면 적합하지
    않음(구현 중 확인) — 대신 sleeves/allocator/execution_gate vNext 프레임워크는
    건드리지 않고, 6개 production ALGORITHMS를 직접 호출해 record_shadow_decision에
    최소 필드만 기록하는 경량 전용 경로로 구현한다. paper_positions는 접촉하지 않음
    (라이브 BTC 트랙레코드 무영향, 실험원칙4 shadow-only).
    """
    profile_id = frequency.multi_asset_shadow_profile_id(symbol)
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
    logger.info("Multi-asset shadow cycle start: %s", symbol)
    capture_results.append(
        await data_lake.record_run_started(
            run_id=run_id,
            started_at=started_at,
            params_snapshot=base_params_snapshot,
            symbol=profile.symbol,
            market_data_symbol=profile.binance_symbol,
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
        logger.error("Multi-asset shadow data failed (%s): %s", symbol, exc)
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
    ind = indicators.compute(
        ohlcv.highs,
        ohlcv.lows,
        ohlcv.closes,
        volumes=ohlcv.volumes,
        interval=profile.interval,
        indicator_profile_id=indicator_profile_id,
    )

    # arena_regime_state는 이 자산 자신의 ind로 재계산(100% 자산고유, 설계문서 §3.1
    # 코드검증 결과). FNG/VIX/ETF흐름/breadth/stablecoin은 진짜 시장전체 지표라 BTC
    # 공유값 그대로 유지(Phase1 확정 불변).
    regime_decision = regime.classify_regime(
        ind, market_features=None, macro=dict(macro_data.signal)
    )
    asset_macro = dict(macro_data.signal)
    asset_macro["arena_regime_state"] = regime_decision.regime_state

    # Part A(원시 수집) + Part B(롤링 z스코어) — 2026-07-31, eth-sol-futures-baseline
    # 설계문서. funding/LSR은 BTC 시장전체 지표가 아니라 자산고유 데이터라, BTC 공유값
    # 대신 이 자산 자신의 Binance 선물 데이터로 직접 z스코어를 계산해 override한다.
    # 실패해도 그레이스풀(None → 기존 veto 함수가 스킵 처리, 사이클 안 죽음).
    try:
        market_snapshot = await market_structure.fetch_market_structure_snapshot(
            symbol=profile.symbol,
            interval=profile.interval,
            data_timestamp=data_timestamp,
            spot_close=ohlcv.closes[-1],
            limit=config.KLINES_LIMIT,
        )
        capture_results.extend(
            await data_lake.record_market_structure_snapshot(
                run_id=run_id,
                snapshot=market_snapshot,
            )
        )
    except Exception as exc:
        logger.warning("Multi-asset market structure 수집 실패(%s): %s", symbol, exc)

    asset_macro["funding_zscore"] = await futures_baseline.compute_funding_zscore(profile.symbol)
    asset_macro["long_short_ratio_zscore"] = await futures_baseline.compute_lsr_zscore(
        profile.symbol
    )

    for algo_id in ALGORITHMS:
        diag = explain_signal(algo_id, asset_macro, ind)
        direction = diag.get("raw_signal")
        signal = sleeves.SleeveSignal(
            sleeve_id="multi_asset_shadow",
            algo_id=algo_id,
            direction=direction,
            confidence=1.0 if direction else 0.0,
            raw_score=1.0 if direction == "long" else (-1.0 if direction == "short" else 0.0),
            target_weight=0.0,
            reason={"diagnostics": diag},
            feature_snapshot={"indicators": dict(ind), "macro": dict(asset_macro)},
        )
        allocation = sleeves.AllocationDecision(
            allowed=True,
            target_weight=0.0,
            risk_budget=0.0,
            reason={"note": "multi_asset_shadow_record_only_no_execution"},
            regime_snapshot=regime_decision.as_dict(),
            risk_snapshot={},
        )
        capture_results.append(
            await data_lake.record_shadow_decision(
                run_id=run_id,
                signal=signal,
                allocation=allocation,
            )
        )

    await data_lake.record_run_completed(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc),
        status="completed",
        data_timestamp=data_timestamp,
        capture_results=capture_results,
    )


async def _run_multi_asset_shadow_cycle_safe(symbol: str) -> None:
    """_run_asset_shadow_cycle 래퍼 — 예상치 못한 예외로 인한 job 중단 방지."""
    try:
        await _run_asset_shadow_cycle(symbol)
    except Exception:
        logger.exception("Multi-asset shadow cycle 처리되지 않은 예외 (%s)", symbol)


def _frequency_shadow_cron(profile: frequency.FrequencyProfile) -> dict[str, object]:
    if profile.decision_cadence_minutes < 60:
        return {"hour": "*", "minute": f"*/{profile.decision_cadence_minutes}"}
    cadence_hours = max(1, profile.decision_cadence_minutes // 60)
    return {"hour": "*" if cadence_hours == 1 else f"*/{cadence_hours}", "minute": 10}


async def _run_cycle_safe(profile_id: str = frequency.LIVE_4H_PROFILE_ID) -> None:
    """_run_cycle 래퍼 — APScheduler가 삼키는 예상치 못한 최상위 예외를 Slack으로 전달."""
    try:
        await _run_cycle(profile_id)
    except Exception as exc:
        symbol = frequency.get_frequency_profile(profile_id).symbol
        logger.exception("4H 사이클 예상치 못한 오류(%s): %s", symbol, exc)
        try:
            await slack_notify.notify_error(
                f"Arena 4H 사이클 — {symbol}",
                exc,
                severity="critical",
            )
        except Exception:
            pass


async def _run_weekly_backtest_safe() -> None:
    """주간 백테스트 리포트 — 매주 월요일 09:10 KST(00:10 UTC) 실행.

    최근 300봉(~50일) 시뮬레이션 결과를 Slack에 요약 전송.
    live 알고리즘과 동일한 비용·스톱·레짐 로직으로 재현하므로
    파라미터 변경 전후 효과를 주간 단위로 확인 가능.
    """
    logger.info("주간 백테스트 리포트 시작")
    try:
        await backtest_report.run_and_notify()
    except Exception as exc:
        logger.error("주간 백테스트 리포트 오류: %s", exc, exc_info=True)


async def run() -> None:
    """APScheduler 시작 + 즉시 1회 실행. server.py에서 asyncio.gather()로 호출."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_cycle_safe,
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
    if config.ENABLE_ARENA_MULTI_ASSET_SHADOW:
        # 2026-08-06: signal-only shadow(_run_multi_asset_shadow_cycle_safe)에서
        # BTC와 동일한 전체 라이브 사이클(_run_cycle_safe)로 승격 — 알고당 $1000
        # 독립자본·실제 포지션·Slack 알림까지 BTC와 완전히 동일. 메인 BTC 사이클(:05)과
        # 겹치지 않게 심볼마다 2분씩 스태거(REST 호출 부하 분산 목적일 뿐, 4H 주기 자체는
        # 실험원칙5에 따라 라이브와 동일). 자산별 재튜닝 없이 frequency.py의
        # multi_asset_shadow_profile_id 프로파일(비용·min_hold 등 BTC와 완전 동일)을
        # 그대로 재사용한다.
        for offset, symbol in enumerate(config.ARENA_MULTI_ASSET_SHADOW_SYMBOLS, start=1):
            scheduler.add_job(
                _run_cycle_safe,
                "cron",
                args=[frequency.multi_asset_shadow_profile_id(symbol)],
                hour=parameters.SCHEDULER_CRON_HOUR,
                minute=(parameters.SCHEDULER_CRON_MINUTE + offset * 2) % 60,
            )
    if config.ENABLE_ARENA_PERP_LIVE:
        # spot→perp Phase A2(2026-08-15): BTC/ETH/SOL 선물(perp) 트랙 — 위 현물
        # 멀티에셋 루프와 완전히 동일한 패턴(_run_cycle_safe 재사용, 자산별 재튜닝 없이
        # frequency.perp_live_profile_id 프로파일만 다르게). 스태거 오프셋을 현물
        # 오프셋(+2,+4분)과 겹치지 않게 (+3,+5,+7분)으로 분리.
        for offset, symbol in enumerate(parameters.MULTI_ASSET_SYMBOLS, start=1):
            scheduler.add_job(
                _run_cycle_safe,
                "cron",
                args=[frequency.perp_live_profile_id(symbol)],
                hour=parameters.SCHEDULER_CRON_HOUR,
                minute=(parameters.SCHEDULER_CRON_MINUTE + offset * 2 + 1) % 60,
            )
    # 주간 백테스트 리포트: 매주 월요일 00:10 UTC = 09:10 KST
    scheduler.add_job(
        _run_weekly_backtest_safe,
        "cron",
        day_of_week="mon",
        hour=0,
        minute=10,
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
    if config.ENABLE_ARENA_MULTI_ASSET_SHADOW:
        await asyncio.gather(
            *[
                _run_cycle_safe(frequency.multi_asset_shadow_profile_id(symbol))
                for symbol in config.ARENA_MULTI_ASSET_SHADOW_SYMBOLS
            ]
        )
    if config.ENABLE_ARENA_PERP_LIVE:
        await asyncio.gather(
            *[
                _run_cycle_safe(frequency.perp_live_profile_id(symbol))
                for symbol in parameters.MULTI_ASSET_SYMBOLS
            ]
        )

    try:
        while True:
            await asyncio.sleep(parameters.SERVER_IDLE_SLEEP_SECONDS)
    finally:
        scheduler.shutdown()
