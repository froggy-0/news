"""ETH/SOL 등 비-BTC 자산의 funding/LSR 롤링 z스코어 계산 (2026-07-31).

설계: docs/arena/research/eth-sol-futures-baseline-design-20260731.md

BTC의 funding_zscore/long_short_ratio_zscore는 morning-brief의 일간 R2 파이프라인
(risk_overlay._last_rolling_zscore)에서 산출돼 3자산이 공유해왔다(Track A/B 설계
§3.1 확정). 이 모듈은 그 로직을 이식해, arena 자신이 이미 심볼별로 수집·저장 중인
arena_funding_rates/arena_market_feature_snapshots에서 직접 자산고유 z스코어를
계산한다 — pandas 의존 없이 순수 파이썬으로 구현(라이브 서비스 의존성 최소화).

API 실측 확인(2026-07-31): Binance funding/OI/LSR 히스토리 엔드포인트는 첫 호출부터
30일 과거 데이터를 즉시 반환(펀딩 90건, OI/LSR 180건) — 배선 즉시 min_periods 충족,
별도 대기 불필요.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from . import positions

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 30
DEFAULT_MIN_PERIODS = 15
_HISTORY_ROW_LIMIT = 500


def rolling_zscore_last(
    values: list[float],
    *,
    window: int = DEFAULT_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> float | None:
    """마지막 값의 롤링 z스코어.

    risk_overlay._last_rolling_zscore()와 동일 의미(직전 window 관측치 기준 평균·
    표준편차, 표본표준편차 ddof=1로 pandas .std() 기본값과 일치). 관측치 부족·
    표준편차 0이면 None(그레이스풀).
    """
    if len(values) < min_periods:
        return None
    tail = values[-window:] if len(values) > window else list(values)
    if len(tail) < min_periods or len(tail) < 2:
        return None
    mean = statistics.fmean(tail)
    stdev = statistics.stdev(tail)
    if stdev == 0:
        return None
    return (tail[-1] - mean) / stdev


async def compute_funding_zscore(
    symbol: str,
    *,
    window: int = DEFAULT_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> float | None:
    """arena_funding_rates(symbol별 이미 축적 중)에서 펀딩비 롤링 z스코어."""
    try:
        res = (
            await positions.db()
            .table("arena_funding_rates")
            .select("funding_time,funding_rate")
            .eq("symbol", symbol)
            .eq("exchange", "binance")
            .order("funding_time")
            .limit(_HISTORY_ROW_LIMIT)
            .execute()
        )
    except Exception as exc:
        logger.warning("funding zscore 조회 실패(%s): %s", symbol, exc)
        return None
    values = _extract_floats(res.data or [], "funding_rate")
    return rolling_zscore_last(values, window=window, min_periods=min_periods)


async def compute_lsr_zscore(
    symbol: str,
    *,
    window: int = DEFAULT_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> float | None:
    """arena_market_feature_snapshots.features->>'top_position_ls_ratio'에서 LSR 롤링 z스코어."""
    try:
        res = (
            await positions.db()
            .table("arena_market_feature_snapshots")
            .select("data_timestamp,features")
            .eq("symbol", symbol)
            .order("data_timestamp")
            .limit(_HISTORY_ROW_LIMIT)
            .execute()
        )
    except Exception as exc:
        logger.warning("LSR zscore 조회 실패(%s): %s", symbol, exc)
        return None
    values: list[float] = []
    for row in res.data or []:
        features = row.get("features") or {}
        raw = features.get("top_position_ls_ratio")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return rolling_zscore_last(values, window=window, min_periods=min_periods)


def _extract_floats(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(key)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values
