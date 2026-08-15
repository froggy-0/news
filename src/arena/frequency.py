"""Frequency, indicator, and cost profiles for Arena research."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import parameters

LIVE_4H_PROFILE_ID = "live_4h"
MULTI_ASSET_SHADOW_PROFILE_PREFIX = "shadow_4h_"
DEFAULT_INDICATOR_PROFILE_ID = "time_normalized_v1"
INTRADAY_INDICATOR_PROFILE_ID = "intraday_native_v1"
COST_MODEL_VERSION = "arena-cost-v3"
DEFAULT_COST_SCENARIO_ID = "base"


@dataclass(frozen=True)
class IndicatorSettings:
    indicator_profile_id: str
    interval: str
    rsi_period: int
    rsi_recent_multiple: int
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    bollinger_period: int
    bollinger_stddev: float
    atr_period: int
    atr_fallback_pct: float
    trend_ema_fast_period: int
    trend_ema_slow_period: int
    return_24h_bars: int
    return_72h_bars: int
    realized_vol_24h_bars: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "indicator_profile_id": self.indicator_profile_id,
            "interval": self.interval,
            "rsi_period": self.rsi_period,
            "rsi_recent_multiple": self.rsi_recent_multiple,
            "macd_fast_period": self.macd_fast_period,
            "macd_slow_period": self.macd_slow_period,
            "macd_signal_period": self.macd_signal_period,
            "bollinger_period": self.bollinger_period,
            "bollinger_stddev": self.bollinger_stddev,
            "atr_period": self.atr_period,
            "atr_fallback_pct": self.atr_fallback_pct,
            "trend_ema_fast_period": self.trend_ema_fast_period,
            "trend_ema_slow_period": self.trend_ema_slow_period,
            "return_24h_bars": self.return_24h_bars,
            "return_72h_bars": self.return_72h_bars,
            "realized_vol_24h_bars": self.realized_vol_24h_bars,
        }


@dataclass(frozen=True)
class FrequencyProfile:
    frequency_profile_id: str
    # DB/state/대시보드 파티션 키(트랙 식별자) — 실제 바이낸스 티커와 다를 수 있다.
    # spot→perp 트랙 분리(Phase A2, 2026-08-15): perp 트랙은 "{binance_symbol}-PERP"
    # 컨벤션(parameters.real_ticker_for_track()가 역변환)을 쓴다. 기존 spot/shadow/
    # research 프로파일은 symbol == binance_symbol(무변화).
    symbol: str
    # REST/WS 호출에 실제로 쓰는 바이낸스 티커. symbol과 분리한 이유는 위 주석 참조.
    binance_symbol: str
    interval: str
    decision_cadence_minutes: int
    # 설명용 메타데이터일 뿐 런타임 게이트가 아니다 — 실제 실거래 여부는
    # config.ENABLE_ARENA_MULTI_ASSET_SHADOW 등 config.py 플래그가 결정한다
    # (2026-08-07 감사: 이 필드를 읽는 코드가 저장소 전체에 0건, `as_dict()` 직렬화 전용).
    live_enabled: bool
    shadow_candidate: bool
    train_days: int
    test_days: int
    embargo_hours: int
    ecr_threshold: float
    max_trades_per_day_per_algo: float
    min_hold_hours: dict[str, float]
    min_hold_fallback_hours: float
    default_indicator_profile_id: str = DEFAULT_INDICATOR_PROFILE_ID
    default_cost_scenario_id: str = DEFAULT_COST_SCENARIO_ID
    # 이 프로파일로 연 포지션에 기록할 product_type/position_semantics — 트랙 단위로
    # 결정(Phase A2). "spot" | "usdm_perp".
    product_type: str = "spot"

    def as_dict(self) -> dict[str, Any]:
        return {
            "frequency_profile_id": self.frequency_profile_id,
            "symbol": self.symbol,
            "binance_symbol": self.binance_symbol,
            "interval": self.interval,
            "decision_cadence_minutes": self.decision_cadence_minutes,
            "live_enabled": self.live_enabled,
            "shadow_candidate": self.shadow_candidate,
            "train_days": self.train_days,
            "test_days": self.test_days,
            "embargo_hours": self.embargo_hours,
            "ecr_threshold": self.ecr_threshold,
            "max_trades_per_day_per_algo": self.max_trades_per_day_per_algo,
            "min_hold_hours": dict(self.min_hold_hours),
            "min_hold_fallback_hours": self.min_hold_fallback_hours,
            "default_indicator_profile_id": self.default_indicator_profile_id,
            "default_cost_scenario_id": self.default_cost_scenario_id,
            "product_type": self.product_type,
        }


@dataclass(frozen=True)
class CostScenario:
    cost_scenario_id: str
    frequency_profile_id: str
    cost_model_version: str
    fee_bps: float
    slippage_bps: float
    spread_bps_round_trip: float
    funding_buffer_bps_per_8h: float

    @property
    def trading_cost_bps_round_trip(self) -> float:
        return 2.0 * (self.fee_bps + self.slippage_bps) + self.spread_bps_round_trip

    @property
    def all_in_round_trip_bps(self) -> float:
        return self.trading_cost_bps_round_trip + self.funding_buffer_bps_per_8h

    @property
    def all_in_round_trip_cost_pct(self) -> float:
        return self.all_in_round_trip_bps / 10_000.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cost_scenario_id": self.cost_scenario_id,
            "frequency_profile_id": self.frequency_profile_id,
            "cost_model_version": self.cost_model_version,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "spread_bps_round_trip": self.spread_bps_round_trip,
            "funding_buffer_bps_per_8h": self.funding_buffer_bps_per_8h,
            "trading_cost_bps_round_trip": self.trading_cost_bps_round_trip,
            "all_in_round_trip_bps": self.all_in_round_trip_bps,
            "all_in_round_trip_cost_pct": self.all_in_round_trip_cost_pct,
        }


def interval_to_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    if interval.endswith("d"):
        return int(interval[:-1]) * 24 * 60
    raise ValueError(f"unsupported interval: {interval!r}")


def interval_to_hours(interval: str) -> float:
    return interval_to_minutes(interval) / 60.0


def bars_for_hours(hours: float, interval: str) -> int:
    if hours <= 0:
        return 0
    return max(1, int(math.ceil(hours * 60.0 / interval_to_minutes(interval))))


def bars_for_days(days: float, interval: str) -> int:
    return bars_for_hours(days * 24.0, interval)


def _scaled_period(period: int, interval: str) -> int:
    base_minutes = interval_to_minutes(parameters.BINANCE_KLINE_INTERVAL)
    current_minutes = interval_to_minutes(interval)
    return max(1, int(round(period * base_minutes / current_minutes)))


FREQUENCY_PROFILES: dict[str, FrequencyProfile] = {
    LIVE_4H_PROFILE_ID: FrequencyProfile(
        frequency_profile_id=LIVE_4H_PROFILE_ID,
        symbol=parameters.BINANCE_SYMBOL,
        binance_symbol=parameters.BINANCE_SYMBOL,
        interval="4h",
        decision_cadence_minutes=240,
        live_enabled=True,
        shadow_candidate=True,
        train_days=84,
        test_days=20,
        embargo_hours=24,
        ecr_threshold=1.3,
        max_trades_per_day_per_algo=3.0,
        min_hold_hours=dict(parameters.MIN_HOLD_HOURS),
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
    "research_1h": FrequencyProfile(
        frequency_profile_id="research_1h",
        symbol=parameters.BINANCE_SYMBOL,
        binance_symbol=parameters.BINANCE_SYMBOL,
        interval="1h",
        decision_cadence_minutes=60,
        live_enabled=False,
        shadow_candidate=True,
        train_days=90,
        test_days=21,
        embargo_hours=24,
        ecr_threshold=1.5,
        max_trades_per_day_per_algo=6.0,
        min_hold_hours=parameters.MIN_HOLD_HOURS,
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
    "research_15m": FrequencyProfile(
        frequency_profile_id="research_15m",
        symbol=parameters.BINANCE_SYMBOL,
        binance_symbol=parameters.BINANCE_SYMBOL,
        interval="15m",
        decision_cadence_minutes=15,
        live_enabled=False,
        shadow_candidate=False,
        train_days=60,
        test_days=14,
        embargo_hours=12,
        ecr_threshold=1.7,
        max_trades_per_day_per_algo=12.0,
        min_hold_hours=parameters.MIN_HOLD_HOURS,
        min_hold_fallback_hours=parameters.MIN_HOLD_FALLBACK_HOURS,
    ),
}


_COST_SCENARIOS: dict[tuple[str, str], CostScenario] = {}


def _add_costs(profile_id: str, rows: list[tuple[str, float, float, float, float]]) -> None:
    for scenario_id, fee_bps, slippage_bps, spread_bps, funding_bps in rows:
        _COST_SCENARIOS[(profile_id, scenario_id)] = CostScenario(
            cost_scenario_id=scenario_id,
            frequency_profile_id=profile_id,
            cost_model_version=COST_MODEL_VERSION,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            spread_bps_round_trip=spread_bps,
            funding_buffer_bps_per_8h=funding_bps,
        )


_add_costs(
    LIVE_4H_PROFILE_ID,
    [
        # 현물 BTCUSDT 비용 현실화 (arena-cost-v2):
        # base = fee 10bps/leg(arena-cost-v3, Binance VIP0 taker 무할인) + slippage 1bps/leg
        # + spread 1bps 왕복 = 왕복 ~23bps. 현물이므로 funding=0. low/high는 비용 민감도 하한/상한.
        ("low", parameters.FEE_BPS, 0.0, 0.0, 0.0),
        ("base", parameters.FEE_BPS, 1.0, 1.0, 0.0),
        ("high", parameters.FEE_BPS, 2.0, 3.0, 0.0),
    ],
)
_add_costs(
    "research_1h",
    [
        ("low", parameters.FEE_BPS, 1.0, 2.0, 0.25),
        ("base", parameters.FEE_BPS, 2.0, 3.0, 0.5),
        ("high", parameters.FEE_BPS, 4.0, 6.0, 1.0),
    ],
)
_add_costs(
    "research_15m",
    [
        ("low", parameters.FEE_BPS, 2.0, 3.0, 0.5),
        ("base", parameters.FEE_BPS, 4.0, 5.0, 1.0),
        ("high", parameters.FEE_BPS, 8.0, 10.0, 2.0),
    ],
)


def multi_asset_shadow_profile_id(symbol: str) -> str:
    """ETH/SOL frequency_profile_id (예: ETHUSDT -> shadow_4h_ethusdt).

    LIVE_4H_PROFILE_ID는 BTC 라이브 경로 전용이라 값·의미를 바꾸지 않는다. 신규 자산은
    전부 이 접두사의 별도 프로파일로 등록된다. "shadow_4h_" 접두사는 2026-07-31
    signal-only shadow로 도입됐던 이름 잔재 — 2026-08-06부로 BTC와 동일한 전체 라이브
    사이클(알고당 독립자본·실제 포지션)로 승격됐지만, DB에 이미 이 문자열로 기록된
    과거 행(paper_positions.frequency_profile_id 등)과의 연속성 때문에 이름은 유지한다.
    """
    return f"{MULTI_ASSET_SHADOW_PROFILE_PREFIX}{symbol.lower()}"


def _register_multi_asset_shadow_profiles() -> None:
    """ETH/SOL 프로파일 등록 (2026-07-31 최초 등록, 2026-08-06 실거래 승격).

    설계문서(docs/arena/research/structural-priority-multi-asset-expansion-20260730.md
    §4 원칙2)에 따라 LIVE_4H_PROFILE_ID와 완전히 동일한 파라미터(train/test/embargo/
    ecr_threshold/max_trades/min_hold/비용산식)를 심볼만 바꿔 재사용한다. 자산별
    재튜닝 금지. live_enabled=True(2026-08-07 정정: 2026-08-06 실거래 승격 후에도
    False로 남아있던 stale 값 — 이 필드는 런타임 게이트가 아니라 설명용 메타데이터라
    기능 영향은 없었음. 실제 게이팅은 config.ENABLE_ARENA_MULTI_ASSET_SHADOW).
    """
    base = FREQUENCY_PROFILES[LIVE_4H_PROFILE_ID]
    for symbol in parameters.MULTI_ASSET_SYMBOLS:
        if symbol == parameters.BINANCE_SYMBOL:
            continue
        profile_id = multi_asset_shadow_profile_id(symbol)
        FREQUENCY_PROFILES[profile_id] = FrequencyProfile(
            frequency_profile_id=profile_id,
            symbol=symbol,
            binance_symbol=symbol,
            interval=base.interval,
            decision_cadence_minutes=base.decision_cadence_minutes,
            live_enabled=True,
            shadow_candidate=True,
            train_days=base.train_days,
            test_days=base.test_days,
            embargo_hours=base.embargo_hours,
            ecr_threshold=base.ecr_threshold,
            max_trades_per_day_per_algo=base.max_trades_per_day_per_algo,
            min_hold_hours=dict(base.min_hold_hours),
            min_hold_fallback_hours=base.min_hold_fallback_hours,
            default_indicator_profile_id=base.default_indicator_profile_id,
            default_cost_scenario_id=base.default_cost_scenario_id,
        )
        # 동일 비용 산식 재사용 (실험 원칙5: 동일 거래비용 산식) — LIVE_4H_PROFILE_ID의
        # low/base/high 행을 그대로 복제.
        _add_costs(
            profile_id,
            [
                ("low", parameters.FEE_BPS, 0.0, 0.0, 0.0),
                ("base", parameters.FEE_BPS, 1.0, 1.0, 0.0),
                ("high", parameters.FEE_BPS, 2.0, 3.0, 0.0),
            ],
        )


_register_multi_asset_shadow_profiles()

PERP_LIVE_PROFILE_PREFIX = "perp_live_"


def perp_live_profile_id(symbol: str) -> str:
    """자산의 선물(perp) 트랙 frequency_profile_id (예: BTCUSDT -> perp_live_btcusdt).

    `symbol` 인자는 실제 바이낸스 티커(BTCUSDT 등) — 반환값은 그 티커의 perp 트랙
    profile_id일 뿐, 이 profile의 `.symbol`(DB/state 파티션 키)은 별도로
    `f"{symbol}-PERP"`가 된다(`_register_perp_live_profiles` 참조).
    """
    return f"{PERP_LIVE_PROFILE_PREFIX}{symbol.lower()}"


def _register_perp_live_profiles() -> None:
    """spot→perp Phase A2(2026-08-15) — 자산×시장 루트 트랙 분리.

    "BTC 현물"과 "BTC 선물"을 오늘의 "BTC"/"ETH"처럼 완전히 독립된 자본 풀로 만든다.
    기존 현물 프로파일(LIVE_4H_PROFILE_ID/shadow_4h_*)과 동일 파라미터를 심볼만 바꿔
    재사용(자산별 재튜닝 금지 원칙, _register_multi_asset_shadow_profiles와 동일 근거).
    핵심 차이 2가지: (1) `.symbol`(DB/state 파티션 키)은 `f"{binance_symbol}-PERP"`
    — 기존 spot 트랙과 다른 문자열이라 `(symbol, algo_id)` 유니크 인덱스·
    `state.open_positions[symbol]` 등 기존 파티셔닝이 마이그레이션 없이 그대로 통함.
    (2) `.binance_symbol`은 실제 티커 그대로 — REST/WS 호출은 spot API를 계속 쓴다
    (가격 피드는 spot 프록시 유지, 전용 futures 피드는 별도 스프린트 — 근거는
    docs/arena/research/spot-to-perp-phase-a-infrastructure-20260815.md).
    BTC도 포함(현물과 달리 perp는 BTC도 신규 트랙이라 심볼 스킵 없음).
    """
    base = FREQUENCY_PROFILES[LIVE_4H_PROFILE_ID]
    for symbol in parameters.MULTI_ASSET_SYMBOLS:
        profile_id = perp_live_profile_id(symbol)
        FREQUENCY_PROFILES[profile_id] = FrequencyProfile(
            frequency_profile_id=profile_id,
            symbol=parameters.perp_track_symbol(symbol),
            binance_symbol=symbol,
            interval=base.interval,
            decision_cadence_minutes=base.decision_cadence_minutes,
            live_enabled=True,
            shadow_candidate=False,
            train_days=base.train_days,
            test_days=base.test_days,
            embargo_hours=base.embargo_hours,
            ecr_threshold=base.ecr_threshold,
            max_trades_per_day_per_algo=base.max_trades_per_day_per_algo,
            min_hold_hours=dict(base.min_hold_hours),
            min_hold_fallback_hours=base.min_hold_fallback_hours,
            default_indicator_profile_id=base.default_indicator_profile_id,
            default_cost_scenario_id=base.default_cost_scenario_id,
            product_type="usdm_perp",
        )
        # 왕복비용 산식은 spot과 동일(fee/slippage/spread) — 펀딩비는 여기서 정액
        # 반영하지 않고 positions.close_position()이 실제 arena_funding_rates로
        # 청산 시점에 정산한다(backtest.py와 동일 패턴).
        _add_costs(
            profile_id,
            [
                ("low", parameters.FEE_BPS, 0.0, 0.0, 0.0),
                ("base", parameters.FEE_BPS, 1.0, 1.0, 0.0),
                ("high", parameters.FEE_BPS, 2.0, 3.0, 0.0),
            ],
        )


_register_perp_live_profiles()

DAILY_RESEARCH_PROFILE_PREFIX = "research_1d_"


def daily_research_profile_id(symbol: str) -> str:
    """1d 고정사양 감사 전용 frequency_profile_id (예: BTCUSDT -> research_1d_btcusdt).

    P2 문서(docs/arena/research/p2-edge-cost-audit-20260804.md §4)가 정한 다음 단계 —
    "고정된 1d 주기 비교". research 전용(live_enabled=False)이라 BTC도 포함한다
    (LIVE_4H_PROFILE_ID와 별개 경로, 라이브 무영향).
    """
    return f"{DAILY_RESEARCH_PROFILE_PREFIX}{symbol.lower()}"


def _register_daily_research_profiles() -> None:
    """2026-08-06 — 1d 고정사양 edge/cost 감사용 research 프로파일.

    거래비용(fee/slippage/spread)은 봉 주기와 무관한 거래당 산식이라 LIVE_4H와 동일 행을
    재사용한다(자산별 재튜닝 금지 원칙, _register_multi_asset_shadow_profiles와 동일
    근거). min_hold_hours도 시간 단위 그대로 재사용(research_1h/research_15m 선례) —
    1d 봉 1개(24h)가 대부분의 알고 MIN_HOLD(8~60h)보다 짧거나 비슷해, 사실상 "1봉 지나면
    보유조건 충족"으로 완화되지만 이것도 고정사양 그대로이므로 새 튜닝이 아니다.
    """
    base = FREQUENCY_PROFILES[LIVE_4H_PROFILE_ID]
    for symbol in parameters.MULTI_ASSET_SYMBOLS:
        profile_id = daily_research_profile_id(symbol)
        FREQUENCY_PROFILES[profile_id] = FrequencyProfile(
            frequency_profile_id=profile_id,
            symbol=symbol,
            binance_symbol=symbol,
            interval="1d",
            decision_cadence_minutes=1440,
            live_enabled=False,
            shadow_candidate=False,
            train_days=base.train_days,
            test_days=base.test_days,
            embargo_hours=base.embargo_hours,
            ecr_threshold=base.ecr_threshold,
            max_trades_per_day_per_algo=base.max_trades_per_day_per_algo,
            min_hold_hours=dict(base.min_hold_hours),
            min_hold_fallback_hours=base.min_hold_fallback_hours,
            default_indicator_profile_id=base.default_indicator_profile_id,
            default_cost_scenario_id=base.default_cost_scenario_id,
        )
        _add_costs(
            profile_id,
            [
                ("low", parameters.FEE_BPS, 0.0, 0.0, 0.0),
                ("base", parameters.FEE_BPS, 1.0, 1.0, 0.0),
                ("high", parameters.FEE_BPS, 2.0, 3.0, 0.0),
            ],
        )


_register_daily_research_profiles()


def get_frequency_profile(profile_id: str = LIVE_4H_PROFILE_ID) -> FrequencyProfile:
    try:
        return FREQUENCY_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown frequency profile: {profile_id!r}") from exc


def get_cost_scenario(
    profile_id: str = LIVE_4H_PROFILE_ID,
    cost_scenario_id: str = DEFAULT_COST_SCENARIO_ID,
) -> CostScenario:
    try:
        return _COST_SCENARIOS[(profile_id, cost_scenario_id)]
    except KeyError as exc:
        raise ValueError(
            f"unknown cost scenario {cost_scenario_id!r} for profile {profile_id!r}"
        ) from exc


def all_cost_scenarios() -> list[CostScenario]:
    return list(_COST_SCENARIOS.values())


def indicator_settings(
    *,
    interval: str,
    indicator_profile_id: str = DEFAULT_INDICATOR_PROFILE_ID,
) -> IndicatorSettings:
    if indicator_profile_id == DEFAULT_INDICATOR_PROFILE_ID:

        def scale(period: int) -> int:
            return _scaled_period(period, interval)
    elif indicator_profile_id == INTRADAY_INDICATOR_PROFILE_ID:

        def scale(period: int) -> int:
            return period
    else:
        raise ValueError(f"unknown indicator profile: {indicator_profile_id!r}")

    return IndicatorSettings(
        indicator_profile_id=indicator_profile_id,
        interval=interval,
        rsi_period=scale(parameters.RSI_PERIOD),
        rsi_recent_multiple=parameters.RSI_RECENT_MULTIPLE,
        macd_fast_period=scale(parameters.MACD_FAST_PERIOD),
        macd_slow_period=scale(parameters.MACD_SLOW_PERIOD),
        macd_signal_period=scale(parameters.MACD_SIGNAL_PERIOD),
        bollinger_period=scale(parameters.BOLLINGER_PERIOD),
        bollinger_stddev=parameters.BOLLINGER_STDDEV,
        atr_period=scale(parameters.ATR_PERIOD),
        atr_fallback_pct=parameters.ATR_FALLBACK_PCT,
        trend_ema_fast_period=scale(parameters.TREND_EMA_FAST_PERIOD),
        trend_ema_slow_period=scale(parameters.TREND_EMA_SLOW_PERIOD),
        return_24h_bars=bars_for_hours(24.0, interval),
        return_72h_bars=bars_for_hours(72.0, interval),
        realized_vol_24h_bars=bars_for_hours(24.0, interval),
    )


def walk_forward_bar_counts(profile: FrequencyProfile) -> dict[str, int]:
    return {
        "train_bars": bars_for_days(profile.train_days, profile.interval),
        "test_bars": bars_for_days(profile.test_days, profile.interval),
        "step_bars": bars_for_days(profile.test_days, profile.interval),
        "embargo_bars": bars_for_hours(profile.embargo_hours, profile.interval),
    }


def profile_snapshot(
    profile: FrequencyProfile,
    *,
    indicator_profile_id: str | None = None,
    cost_scenario_id: str | None = None,
) -> dict[str, Any]:
    indicator_id = indicator_profile_id or profile.default_indicator_profile_id
    cost_id = cost_scenario_id or profile.default_cost_scenario_id
    cost = get_cost_scenario(profile.frequency_profile_id, cost_id)
    return {
        "frequency_profile": profile.as_dict(),
        "indicator_profile": indicator_settings(
            interval=profile.interval,
            indicator_profile_id=indicator_id,
        ).as_dict(),
        "cost_scenario": cost.as_dict(),
    }
