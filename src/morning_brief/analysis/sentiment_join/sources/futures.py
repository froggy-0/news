from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from morning_brief.data.sources.http_client import get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
BINANCE_LSR_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_OI_PERIOD = "1d"
BINANCE_MAX_LIMIT = 1000


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _fetch_funding_rate_history(start_ms: int) -> list[dict]:
    try:
        return get_list_with_retry(
            BINANCE_FUNDING_URL,
            params={
                "symbol": BINANCE_SYMBOL,
                "startTime": str(start_ms),
                "limit": str(BINANCE_MAX_LIMIT),
            },
            provider="binance_futures",
            timeout=20,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Binance 펀딩비 이력 수집에 실패했습니다.",
            level=logging.WARNING,
            source="binance_funding",
            reason=str(exc),
        )
        return []


def _fetch_oi_history(limit_days: int) -> list[dict]:
    try:
        return get_list_with_retry(
            BINANCE_OI_URL,
            params={
                "symbol": BINANCE_SYMBOL,
                "period": BINANCE_OI_PERIOD,
                "limit": str(min(max(limit_days, 1), BINANCE_MAX_LIMIT)),
            },
            provider="binance_futures",
            timeout=20,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Binance 미결제약정 이력 수집에 실패했습니다.",
            level=logging.WARNING,
            source="binance_oi",
            reason=str(exc),
        )
        return []


def _fetch_long_short_ratio(limit_days: int) -> list[dict]:
    try:
        return get_list_with_retry(
            BINANCE_LSR_URL,
            params={
                "symbol": BINANCE_SYMBOL,
                "period": "1d",
                "limit": str(min(max(limit_days, 1), 500)),
            },
            provider="binance_futures",
            timeout=20,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Binance Long/Short Ratio 수집에 실패했습니다.",
            level=logging.WARNING,
            source="binance_lsr",
            reason=str(exc),
        )
        return []


def _aggregate_daily_funding(rows: list[dict]) -> dict[str, float]:
    """8시간 펀딩비 3건을 일별로 합산하여 daily funding rate를 산출합니다."""
    daily: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("fundingTime")
        rate_raw = row.get("fundingRate")
        if ts_ms is None or rate_raw is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            daily.setdefault(day, []).append(float(rate_raw))
        except (TypeError, ValueError):
            continue
    return {day: sum(rates) for day, rates in daily.items()}


def _extract_daily_oi(rows: list[dict]) -> dict[str, float]:
    """일별 종가 기준 미결제약정 USD 값을 추출합니다."""
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("timestamp")
        oi_value = row.get("sumOpenInterestValue")
        if ts_ms is None or oi_value is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            daily[day] = float(oi_value)
        except (TypeError, ValueError):
            continue
    return daily


def _extract_daily_long_short_ratio(rows: list[dict]) -> dict[str, float]:
    """일별 글로벌 Long/Short 계좌 비율을 추출합니다.

    longShortRatio 필드는 str 타입으로 반환되므로 float 변환이 필수입니다.
    값이 1.0을 초과할 수 있습니다(롱 비중이 숏보다 크면 > 1).
    """
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("timestamp")
        lsr_raw = row.get("longShortRatio")
        if ts_ms is None or lsr_raw is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            daily[day] = float(lsr_raw)
        except (TypeError, ValueError):
            continue
    return daily


def _empty_futures_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "funding_rate": [float("nan")] * len(dates),
            "open_interest_usd": [float("nan")] * len(dates),
            "btc_long_short_ratio": [float("nan")] * len(dates),
        }
    )


def fetch_futures_data(lookback_days: int) -> pd.DataFrame:
    """Req 11: Binance 공식 API에서 펀딩비·미결제약정·Long/Short Ratio 이력을 수집합니다.

    Returns DataFrame with columns: date, funding_rate, open_interest_usd, btc_long_short_ratio.
    On failure, returns a frame of NaN values so the pipeline can continue.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]
    grid = _empty_futures_frame(dates)

    start_ms = _ms_timestamp(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    funding_rows = _fetch_funding_rate_history(start_ms)
    oi_rows = _fetch_oi_history(lookback_days + 2)

    # LSR 수집은 funding/OI와 독립적으로 실패해도 진행
    try:
        lsr_rows = _fetch_long_short_ratio(lookback_days + 2)
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Binance LSR 수집에 실패했습니다.",
            level=logging.WARNING,
            source="binance_lsr",
            reason=str(exc),
        )
        lsr_rows = []

    if not funding_rows and not oi_rows:
        log_structured(
            logger,
            event="source.failed",
            message="Binance 선물 데이터를 가져오지 못해 NaN으로 채웁니다.",
            level=logging.WARNING,
            source="binance_futures",
            reason="all_requests_failed",
        )
        grid.attrs["fallback_used"] = False
        return grid

    daily_funding = _aggregate_daily_funding(funding_rows)
    daily_oi = _extract_daily_oi(oi_rows)
    daily_lsr = _extract_daily_long_short_ratio(lsr_rows)

    grid["funding_rate"] = [daily_funding.get(d, float("nan")) for d in dates]
    grid["open_interest_usd"] = [daily_oi.get(d, float("nan")) for d in dates]
    grid["btc_long_short_ratio"] = [daily_lsr.get(d, float("nan")) for d in dates]
    grid.attrs["fallback_used"] = False

    log_structured(
        logger,
        event="source.complete",
        message="Binance 선물 데이터 수집을 완료했습니다.",
        source="binance_futures",
        funding_days=sum(1 for v in grid["funding_rate"] if pd.notna(v)),
        oi_days=sum(1 for v in grid["open_interest_usd"] if pd.notna(v)),
        lsr_days=sum(1 for v in grid["btc_long_short_ratio"] if pd.notna(v)),
    )
    return grid


__all__ = ["fetch_futures_data"]
