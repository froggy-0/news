from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from morning_brief.analysis.sentiment_join.quality import (
    STRUCTURED_SOURCE_MIN_COVERAGE_RATIO,
    calculate_coverage_ratio,
    quality_status_for_ratio,
)
from morning_brief.data.sources.http_client import get_json_with_retry, get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

SUPABASE_FUTURES_TABLE = "btc_futures_daily"

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
BINANCE_LSR_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_OI_PERIOD = "1d"
BINANCE_MAX_LIMIT = 1000

# Binance fapi가 지역 제한(HTTP 451)으로 차단되면 Bybit 공개 API로 폴백합니다.
# Bybit 공개 API는 인증 불필요 · geo-restriction 없음 · 동일 지표 제공.
BYBIT_BASE_URL = "https://api.bybit.com"


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Binance fapi 수집 함수
# ---------------------------------------------------------------------------


def _fetch_funding_rate_history(start_ms: int, end_ms: int) -> list[dict]:
    """Binance 펀딩비 이력을 페이지네이션으로 완전 수집합니다.

    단일 호출 limit=1000(≈333일)으로 잘리는 문제를 방지하기 위해
    last fundingTime+1 커서 방식으로 end_ms까지 모든 레코드를 수집합니다.
    730일 × 3건/일 = 2190건 → 최대 3페이지.
    """
    all_rows: list[dict] = []
    cursor_ms = start_ms

    for _ in range(10):
        try:
            page = get_list_with_retry(
                BINANCE_FUNDING_URL,
                params={
                    "symbol": BINANCE_SYMBOL,
                    "startTime": str(cursor_ms),
                    "endTime": str(end_ms),
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
            break

        if not isinstance(page, list) or not page:
            break

        all_rows.extend(page)

        if len(page) < BINANCE_MAX_LIMIT:
            break

        last_ts = page[-1].get("fundingTime")
        if last_ts is None:
            break
        next_cursor = int(last_ts) + 1
        if next_cursor >= end_ms:
            break
        cursor_ms = next_cursor

    return all_rows


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


# ---------------------------------------------------------------------------
# Binance 파싱 함수
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Bybit 폴백 수집 함수
# ---------------------------------------------------------------------------


def _fetch_bybit_funding_rows(start_ms: int, end_ms: int) -> list[dict]:
    """Bybit 펀딩비 이력을 수집합니다.

    docs: startTime만 전달하면 에러 → startTime+endTime 쌍으로 요청.
    """
    try:
        payload = get_json_with_retry(
            f"{BYBIT_BASE_URL}/v5/market/funding/history",
            params={
                "category": "linear",
                "symbol": BINANCE_SYMBOL,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 200,
            },
            provider="bybit",
            timeout=20,
        )
        rows = payload.get("result", {}).get("list", [])
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Bybit 펀딩비 수집에 실패했습니다.",
            level=logging.WARNING,
            source="bybit_funding",
            reason=str(exc),
        )
        return []


def _fetch_bybit_oi_rows(start_ms: int, end_ms: int, limit: int) -> list[dict]:
    try:
        payload = get_json_with_retry(
            f"{BYBIT_BASE_URL}/v5/market/open-interest",
            params={
                "category": "linear",
                "symbol": BINANCE_SYMBOL,
                "intervalTime": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": min(limit, 200),
            },
            provider="bybit",
            timeout=20,
        )
        rows = payload.get("result", {}).get("list", [])
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Bybit 미결제약정 수집에 실패했습니다.",
            level=logging.WARNING,
            source="bybit_oi",
            reason=str(exc),
        )
        return []


def _fetch_bybit_btc_closes(start_ms: int, end_ms: int, limit: int) -> dict[str, float]:
    """Bybit BTCUSDT 일봉 종가(date → USD)를 반환합니다.

    Bybit linear OI는 BTC 단위이므로 USD 환산에 종가가 필요합니다.
    응답 배열 인덱스: [0]=startTime(ms), [1]=open, [2]=high, [3]=low, [4]=close
    """
    try:
        payload = get_json_with_retry(
            f"{BYBIT_BASE_URL}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": BINANCE_SYMBOL,
                "interval": "D",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": min(limit, 200),
            },
            provider="bybit",
            timeout=20,
        )
        rows = payload.get("result", {}).get("list", [])
        if not isinstance(rows, list):
            return {}
        closes: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 5:
                continue
            try:
                day = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
                closes[day] = float(row[4])
            except (TypeError, ValueError, IndexError):
                continue
        return closes
    except Exception:
        return {}


def _fetch_bybit_lsr_rows(start_ms: int, end_ms: int, limit: int) -> list[dict]:
    try:
        payload = get_json_with_retry(
            f"{BYBIT_BASE_URL}/v5/market/account-ratio",
            params={
                "category": "linear",
                "symbol": BINANCE_SYMBOL,
                "period": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": min(limit, 500),
            },
            provider="bybit",
            timeout=20,
        )
        rows = payload.get("result", {}).get("list", [])
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Bybit Long/Short Ratio 수집에 실패했습니다.",
            level=logging.WARNING,
            source="bybit_lsr",
            reason=str(exc),
        )
        return []


# ---------------------------------------------------------------------------
# Bybit 파싱 함수
# ---------------------------------------------------------------------------


def _aggregate_bybit_daily_funding(rows: list[dict]) -> dict[str, float]:
    """Bybit 8시간 펀딩비를 일별로 합산합니다.

    응답 필드: fundingRate(str), fundingRateTimestamp(str, ms)
    """
    daily: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("fundingRateTimestamp")
        rate = row.get("fundingRate")
        if ts_ms is None or rate is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            daily.setdefault(day, []).append(float(rate))
        except (TypeError, ValueError):
            continue
    return {day: sum(rates) for day, rates in daily.items()}


def _extract_bybit_daily_oi(rows: list[dict], btc_closes: dict[str, float]) -> dict[str, float]:
    """Bybit OI(BTC 단위) × 일봉 종가(USD) = open_interest_usd 추정값.

    응답 필드: openInterest(str, BTC), timestamp(str, ms)
    종가 데이터가 없는 날짜는 누락됩니다(NaN으로 처리).
    """
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("timestamp")
        oi_btc = row.get("openInterest")
        if ts_ms is None or oi_btc is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            btc_price = btc_closes.get(day)
            if btc_price is None or btc_price <= 0:
                continue
            daily[day] = float(oi_btc) * btc_price
        except (TypeError, ValueError):
            continue
    return daily


def _extract_bybit_daily_lsr(rows: list[dict]) -> dict[str, float]:
    """Bybit buyRatio / sellRatio → longShortRatio.

    응답 필드: buyRatio(str, 0~1), sellRatio(str, 0~1), timestamp(str, ms)
    Binance longShortRatio와 동일한 해석: 1.0 초과 = 롱 우세.
    """
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("timestamp")
        buy = row.get("buyRatio")
        sell = row.get("sellRatio")
        if ts_ms is None or buy is None or sell is None:
            continue
        try:
            sell_f = float(sell)
            if sell_f == 0:
                continue
            day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            daily[day] = float(buy) / sell_f
        except (TypeError, ValueError):
            continue
    return daily


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------


def _empty_futures_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "funding_rate": [float("nan")] * len(dates),
            "open_interest_usd": [float("nan")] * len(dates),
            "btc_long_short_ratio": [float("nan")] * len(dates),
        }
    )


OI_LSR_SIGNAL_WINDOW = 30


def _metric_quality(days: int, requested_days: int) -> tuple[str, list[str]]:
    ratio = calculate_coverage_ratio(days, requested_days)
    reasons: list[str] = []
    if days == 0:
        reasons.append("no_history")
    if quality_status_for_ratio(ratio) != "ok":
        reasons.append("coverage_below_threshold")
    return quality_status_for_ratio(ratio), reasons


def _recent_window_quality(
    grid: pd.DataFrame,
    column: str,
    dates: list[str],
    signal_window: int,
) -> tuple[str, list[str], float]:
    """최근 signal_window일 윈도우 기준 quality 판정.

    Binance OI/LSR API는 최근 30일만 보존하므로, 전체 lookback 대비 coverage ratio 대신
    '마지막 30일이 완전한가'를 기준으로 게이트를 판단합니다.
    전체 커버리지는 oi_quality_status/lsr_quality_status에 진단용으로 별도 보관합니다.
    """
    if not dates:
        return "degraded", ["no_history"], 0.0
    recent_dates = set(dates[-signal_window:])
    effective_window = len(recent_dates)
    if column in grid.columns and "date" in grid.columns:
        non_null_in_window = int(
            grid[grid["date"].isin(recent_dates) & grid[column].notna()].shape[0]
        )
    else:
        non_null_in_window = 0
    ratio = calculate_coverage_ratio(non_null_in_window, effective_window)
    reasons: list[str] = []
    if non_null_in_window == 0:
        reasons.append("no_history")
    if quality_status_for_ratio(ratio) != "ok":
        reasons.append("coverage_below_threshold")
    return quality_status_for_ratio(ratio), reasons, ratio


def _date_bounds(grid: pd.DataFrame, column: str) -> tuple[str | None, str | None]:
    if column not in grid.columns or "date" not in grid.columns:
        return None, None
    non_null_dates = grid.loc[grid[column].notna(), "date"].astype(str)
    if non_null_dates.empty:
        return None, None
    return non_null_dates.min(), non_null_dates.max()


def _attach_futures_attrs(
    grid: pd.DataFrame,
    *,
    dates: list[str],
    source: str,
    fallback_used: bool,
) -> pd.DataFrame:
    requested_days = len(dates)
    funding_days = int(grid["funding_rate"].notna().sum())
    oi_days = int(grid["open_interest_usd"].notna().sum())
    lsr_days = int(grid["btc_long_short_ratio"].notna().sum())
    funding_quality_status, funding_quality_reasons = _metric_quality(funding_days, requested_days)
    # 전체 lookback 커버리지 (진단용)
    oi_quality_status, oi_quality_reasons = _metric_quality(oi_days, requested_days)
    lsr_quality_status, lsr_quality_reasons = _metric_quality(lsr_days, requested_days)
    # 최근 30일 윈도우 커버리지 (게이트 판단용 — Binance API 30일 보존 제약 반영)
    api_capped = requested_days > OI_LSR_SIGNAL_WINDOW
    oi_recent_status, oi_recent_reasons, oi_recent_ratio = _recent_window_quality(
        grid, "open_interest_usd", dates, OI_LSR_SIGNAL_WINDOW
    )
    lsr_recent_status, lsr_recent_reasons, lsr_recent_ratio = _recent_window_quality(
        grid, "btc_long_short_ratio", dates, OI_LSR_SIGNAL_WINDOW
    )

    overall_quality_reasons = []
    if oi_recent_status != "ok":
        overall_quality_reasons.append("open_interest_history_incomplete")
    if lsr_recent_status != "ok":
        overall_quality_reasons.append("long_short_ratio_history_incomplete")
    if funding_quality_status != "ok":
        overall_quality_reasons.append("funding_history_incomplete")

    funding_min, funding_max = _date_bounds(grid, "funding_rate")
    oi_min, oi_max = _date_bounds(grid, "open_interest_usd")
    lsr_min, lsr_max = _date_bounds(grid, "btc_long_short_ratio")

    grid.attrs["fallback_used"] = fallback_used
    grid.attrs["futures_source"] = source
    grid.attrs["requested_days"] = requested_days
    grid.attrs["requested_start_date"] = dates[0] if dates else None
    grid.attrs["requested_end_date"] = dates[-1] if dates else None
    grid.attrs["funding_days"] = funding_days
    grid.attrs["oi_days"] = oi_days
    grid.attrs["lsr_days"] = lsr_days
    grid.attrs["funding_coverage_ratio"] = calculate_coverage_ratio(funding_days, requested_days)
    grid.attrs["oi_coverage_ratio"] = calculate_coverage_ratio(oi_days, requested_days)
    grid.attrs["lsr_coverage_ratio"] = calculate_coverage_ratio(lsr_days, requested_days)
    grid.attrs["funding_quality_status"] = funding_quality_status
    grid.attrs["funding_quality_reasons"] = funding_quality_reasons
    # 전체 lookback 커버리지 — 진단 및 리포트용 (게이트에는 미사용)
    grid.attrs["oi_quality_status"] = oi_quality_status
    grid.attrs["oi_quality_reasons"] = oi_quality_reasons
    grid.attrs["lsr_quality_status"] = lsr_quality_status
    grid.attrs["lsr_quality_reasons"] = lsr_quality_reasons
    # 최근 30일 윈도우 커버리지 — pipeline 게이트 판단에 사용
    grid.attrs["oi_api_capped"] = api_capped
    grid.attrs["lsr_api_capped"] = api_capped
    grid.attrs["oi_recent_coverage_ratio"] = oi_recent_ratio
    grid.attrs["lsr_recent_coverage_ratio"] = lsr_recent_ratio
    grid.attrs["oi_recent_quality_status"] = oi_recent_status
    grid.attrs["oi_recent_quality_reasons"] = oi_recent_reasons
    grid.attrs["lsr_recent_quality_status"] = lsr_recent_status
    grid.attrs["lsr_recent_quality_reasons"] = lsr_recent_reasons
    grid.attrs["quality_status"] = (
        "ok"
        if funding_quality_status == "ok" and oi_recent_status == "ok" and lsr_recent_status == "ok"
        else "degraded"
    )
    grid.attrs["quality_reasons"] = overall_quality_reasons
    grid.attrs["returned_min_date"] = {
        "funding_rate": funding_min,
        "open_interest_usd": oi_min,
        "btc_long_short_ratio": lsr_min,
    }
    grid.attrs["returned_max_date"] = {
        "funding_rate": funding_max,
        "open_interest_usd": oi_max,
        "btc_long_short_ratio": lsr_max,
    }
    return grid


def _build_grid(
    dates: list[str],
    daily_funding: dict[str, float],
    daily_oi: dict[str, float],
    daily_lsr: dict[str, float],
) -> pd.DataFrame:
    grid = _empty_futures_frame(dates)
    grid["funding_rate"] = [daily_funding.get(d, float("nan")) for d in dates]
    grid["open_interest_usd"] = [daily_oi.get(d, float("nan")) for d in dates]
    grid["btc_long_short_ratio"] = [daily_lsr.get(d, float("nan")) for d in dates]
    return grid


def _is_cache_complete(
    cached: dict[str, dict[str, float | None]],
    dates: list[str],
) -> bool:
    """캐시가 파이프라인 가동에 충분한지 판정합니다.

    - OI/LSR: 최근 OI_LSR_SIGNAL_WINDOW(30)일 중 non-NULL 날짜 >= WINDOW * MIN_COVERAGE(0.60)
    - Funding: 전체 날짜 중 non-NULL 날짜 >= len(dates) * MIN_COVERAGE
    기존 "날짜 행 존재 여부"만 보는 조건을 교체합니다.
    """
    if not dates:
        return False
    # 가장 최근 날짜가 캐시에 없으면 항상 미스 — 최신 데이터를 API로 갱신
    if dates[-1] not in cached:
        return False

    effective_window = min(len(dates), OI_LSR_SIGNAL_WINDOW)
    min_recent = int(effective_window * STRUCTURED_SOURCE_MIN_COVERAGE_RATIO)
    recent_dates = set(dates[-effective_window:])

    oi_count = sum(
        1 for d in recent_dates if d in cached and cached[d].get("open_interest_usd") is not None
    )
    lsr_count = sum(
        1 for d in recent_dates if d in cached and cached[d].get("btc_long_short_ratio") is not None
    )
    funding_required = int(len(dates) * STRUCTURED_SOURCE_MIN_COVERAGE_RATIO)
    funding_count = sum(
        1 for d in dates if d in cached and cached[d].get("funding_rate") is not None
    )
    return oi_count >= min_recent and lsr_count >= min_recent and funding_count >= funding_required


def _merge_with_cache(
    api_funding: dict[str, float],
    api_oi: dict[str, float],
    api_lsr: dict[str, float],
    cached_funding: dict[str, float],
    cached_oi: dict[str, float],
    cached_lsr: dict[str, float],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """API 결과(우선) + Supabase 캐시(보완)를 병합합니다.

    API 결과가 캐시보다 우선합니다 (최신 데이터 우위).
    캐시는 API가 반환하지 않은 과거 날짜를 보완하는 역할입니다.
    """
    return (
        {**cached_funding, **api_funding},
        {**cached_oi, **api_oi},
        {**cached_lsr, **api_lsr},
    )


# ---------------------------------------------------------------------------
# Supabase 캐시 레이어
# ---------------------------------------------------------------------------


def _read_futures_from_supabase(
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, float | None]]:
    """btc_futures_daily 테이블에서 캐시 데이터를 읽습니다.

    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 미설정 시 빈 dict 반환.
    테이블이 없거나 오류 시에도 빈 dict 반환 (파이프라인 계속 진행).
    """
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return {}
    try:
        from supabase import create_client

        client = create_client(supabase_url, service_role_key)
        resp = (
            client.table(SUPABASE_FUTURES_TABLE)
            .select("date,funding_rate,open_interest_usd,btc_long_short_ratio")
            .eq("symbol", BINANCE_SYMBOL)
            .gte("date", start_date)
            .lte("date", end_date)
            .order("date")
            .limit(2000)
            .execute()
        )
        data = getattr(resp, "data", None)
        if not isinstance(data, list):
            return {}
        return {
            row["date"]: {
                "funding_rate": row.get("funding_rate"),
                "open_interest_usd": row.get("open_interest_usd"),
                "btc_long_short_ratio": row.get("btc_long_short_ratio"),
            }
            for row in data
            if isinstance(row, dict) and row.get("date")
        }
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Supabase 선물 캐시 읽기 실패.",
            level=logging.WARNING,
            source="supabase_futures",
            reason=str(exc),
        )
        return {}


def _write_futures_to_supabase(grid: pd.DataFrame) -> None:
    """선물 데이터를 btc_futures_daily 테이블에 upsert합니다.

    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 미설정 시 무시.
    오류 시 로그만 남기고 파이프라인 계속 진행.
    """
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return
    try:
        import math

        from supabase import create_client

        client = create_client(supabase_url, service_role_key)
        rows = []
        for _, row in grid.iterrows():
            fr = row["funding_rate"]
            oi = row["open_interest_usd"]
            lsr = row["btc_long_short_ratio"]
            # 모든 지표가 null인 날은 저장하지 않음
            if all(v is None or (isinstance(v, float) and math.isnan(v)) for v in (fr, oi, lsr)):
                continue
            rows.append(
                {
                    "date": str(row["date"]),
                    "symbol": BINANCE_SYMBOL,
                    "funding_rate": None
                    if (fr is None or (isinstance(fr, float) and math.isnan(fr)))
                    else float(fr),
                    "open_interest_usd": None
                    if (oi is None or (isinstance(oi, float) and math.isnan(oi)))
                    else float(oi),
                    "btc_long_short_ratio": None
                    if (lsr is None or (isinstance(lsr, float) and math.isnan(lsr)))
                    else float(lsr),
                    "source": grid.attrs.get("futures_source", "binance"),
                }
            )
        if not rows:
            return
        BATCH = 200
        for i in range(0, len(rows), BATCH):
            client.table(SUPABASE_FUTURES_TABLE).upsert(
                rows[i : i + BATCH], on_conflict="date,symbol"
            ).execute()
        log_structured(
            logger,
            event="source.complete",
            message="Supabase 선물 캐시 저장 완료.",
            source="supabase_futures",
            rows=len(rows),
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Supabase 선물 캐시 저장 실패.",
            level=logging.WARNING,
            source="supabase_futures",
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Lambda 프록시 호출
# ---------------------------------------------------------------------------


def _lambda_payload_to_grid(payload: dict, dates: list[str]) -> pd.DataFrame:
    """Lambda 응답 JSON → futures grid DataFrame."""
    funding = payload.get("funding_rate") or {}
    oi = payload.get("open_interest_usd") or {}
    lsr = payload.get("btc_long_short_ratio") or {}
    grid = _empty_futures_frame(dates)
    grid["funding_rate"] = [float(funding[d]) if d in funding else float("nan") for d in dates]
    grid["open_interest_usd"] = [float(oi[d]) if d in oi else float("nan") for d in dates]
    grid["btc_long_short_ratio"] = [float(lsr[d]) if d in lsr else float("nan") for d in dates]
    return grid


def _invoke_futures_lambda(
    arn: str,
    lookback_days: int,
) -> dict | None:
    """ap-northeast-2 Lambda를 호출해 Binance 선물 데이터를 가져옵니다.

    성공 시 raw payload dict 반환.
    실패(네트워크·FunctionError·payload error) 시 None 반환 → Bybit으로 계속.
    """
    try:
        import boto3

        client = boto3.client("lambda", region_name="ap-northeast-2")
        resp = client.invoke(
            FunctionName=arn,
            InvocationType="RequestResponse",
            Payload=json.dumps({"lookback_days": lookback_days}),
        )
    except Exception as exc:
        log_structured(
            logger,
            event="futures.lambda_failed",
            message="Lambda 호출에 실패했습니다. Bybit으로 계속합니다.",
            level=logging.WARNING,
            reason=str(exc),
        )
        return None

    if resp.get("FunctionError"):
        log_structured(
            logger,
            event="futures.lambda_failed",
            message="Lambda FunctionError 응답. Bybit으로 계속합니다.",
            level=logging.WARNING,
            reason=resp.get("FunctionError"),
        )
        return None

    try:
        payload = json.loads(resp["Payload"].read())
    except Exception as exc:
        log_structured(
            logger,
            event="futures.lambda_failed",
            message="Lambda 응답 파싱 실패. Bybit으로 계속합니다.",
            level=logging.WARNING,
            reason=str(exc),
        )
        return None

    if "error" in payload:
        log_structured(
            logger,
            event="futures.lambda_failed",
            message="Lambda가 error를 반환했습니다. Bybit으로 계속합니다.",
            level=logging.WARNING,
            reason=payload["error"],
        )
        return None

    return payload


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def fetch_futures_data(lookback_days: int, futures_lambda_arn: str = "") -> pd.DataFrame:
    """Req 11: Binance fapi에서 펀딩비·미결제약정·Long/Short Ratio 이력을 수집합니다.

    환경별 전략:
    - 로컬 개발: Binance fapi 직접 호출 (451 차단 없음, 정확한 과거 데이터)
    - GitHub Actions (CI/CD): Lambda 프록시 사용 (US IP 451 차단 우회)
    - Fallback: Bybit 공개 API

    Returns DataFrame with columns: date, funding_rate, open_interest_usd, btc_long_short_ratio.
    attrs["futures_source"]: "binance" | "lambda" | "bybit" | "none"
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]

    start_ms = _ms_timestamp(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    end_ms = (
        _ms_timestamp(
            datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)
        )
        - 1
    )

    lambda_arn = futures_lambda_arn.strip() or os.getenv("FUTURES_LAMBDA_ARN", "").strip()

    # 환경 감지: GitHub Actions(CI/CD)인지 로컬인지
    is_github_actions = os.getenv("GITHUB_ACTIONS", "").lower() == "true"

    # 로컬: 항상 Binance fapi 직접 호출 (451 차단 없음, 정확한 과거 데이터)
    # CI/CD: Lambda 프록시 사용 (US IP에서 451 차단 우회)
    use_binance_direct = not is_github_actions

    log_structured(
        logger,
        event="futures.strategy_selected",
        message=f"선물 데이터 수집 전략 선택: {'로컬 Binance fapi 직접 호출' if use_binance_direct else 'Lambda 프록시'}",
        environment="local" if use_binance_direct else "github_actions",
        lookback_days=lookback_days,
    )

    # --- 0차: Supabase 캐시 확인 ---
    cached = _read_futures_from_supabase(dates[0], dates[-1])

    if _is_cache_complete(cached, dates):
        # 완전 캐시 히트: API 호출 생략
        daily_funding = {
            d: float(val) for d, v in cached.items() if (val := v.get("funding_rate")) is not None
        }
        daily_oi = {
            d: float(val)
            for d, v in cached.items()
            if (val := v.get("open_interest_usd")) is not None
        }
        daily_lsr = {
            d: float(val)
            for d, v in cached.items()
            if (val := v.get("btc_long_short_ratio")) is not None
        }
        grid = _attach_futures_attrs(
            _build_grid(dates, daily_funding, daily_oi, daily_lsr),
            dates=dates,
            source="supabase",
            fallback_used=False,
        )
        log_structured(
            logger,
            event="source.complete",
            message="Supabase 캐시에서 선물 데이터를 로드했습니다.",
            source="supabase_futures",
            cached_days=len(cached),
            funding_days=int(grid["funding_rate"].notna().sum()),
            oi_days=int(grid["open_interest_usd"].notna().sum()),
            lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
        )
        return grid

    # 부분 히트: Supabase 캐시에서 가져올 수 있는 것만 준비 (API 결과와 병합용)
    _cached_funding: dict[str, float] = {
        d: float(val) for d, v in cached.items() if (val := v.get("funding_rate")) is not None
    }
    _cached_oi: dict[str, float] = {
        d: float(val) for d, v in cached.items() if (val := v.get("open_interest_usd")) is not None
    }
    _cached_lsr: dict[str, float] = {
        d: float(val)
        for d, v in cached.items()
        if (val := v.get("btc_long_short_ratio")) is not None
    }

    # --- 1차: 로컬이거나 Lambda ARN 없으면 Binance fapi 직접 시도 ---
    funding_rows: list[dict] = []
    oi_rows: list[dict] = []
    lsr_rows: list[dict] = []

    if use_binance_direct:
        funding_rows = _fetch_funding_rate_history(start_ms, end_ms)
        oi_rows = _fetch_oi_history(lookback_days + 2)
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

    if not funding_rows and not oi_rows:
        if not (use_binance_direct and not lambda_arn):
            log_structured(
                logger,
                event="source.failed",
                message="Binance 선물 데이터를 가져오지 못했습니다.",
                level=logging.WARNING,
                source="binance_futures",
                reason="binance_fapi_failed",
            )

        # --- 2차: Lambda 프록시 (GitHub Actions에서 451 차단 우회용) ---
        if is_github_actions and lambda_arn:
            log_structured(
                logger,
                event="futures.lambda_fallback",
                message="Lambda 프록시로 Binance 선물 데이터를 수집합니다.",
                level=logging.WARNING,
            )
            lambda_payload = _invoke_futures_lambda(lambda_arn, lookback_days)
            if lambda_payload is not None:
                # Lambda payload → daily dict로 변환 후 Supabase 부분 캐시와 병합
                lam_raw = _lambda_payload_to_grid(lambda_payload, dates)
                lam_funding = {
                    str(d): float(v)
                    for d, v in zip(lam_raw["date"], lam_raw["funding_rate"])
                    if pd.notna(v)
                }
                lam_oi = {
                    str(d): float(v)
                    for d, v in zip(lam_raw["date"], lam_raw["open_interest_usd"])
                    if pd.notna(v)
                }
                lam_lsr = {
                    str(d): float(v)
                    for d, v in zip(lam_raw["date"], lam_raw["btc_long_short_ratio"])
                    if pd.notna(v)
                }
                merged_f, merged_oi, merged_lsr = _merge_with_cache(
                    lam_funding,
                    lam_oi,
                    lam_lsr,
                    _cached_funding,
                    _cached_oi,
                    _cached_lsr,
                )
                grid = _attach_futures_attrs(
                    _build_grid(dates, merged_f, merged_oi, merged_lsr),
                    dates=dates,
                    source="lambda",
                    fallback_used=True,
                )
                log_structured(
                    logger,
                    event="source.complete",
                    message="Lambda 프록시를 통해 Binance 선물 데이터를 수집했습니다.",
                    source="lambda_binance_futures",
                    funding_days=int(grid["funding_rate"].notna().sum()),
                    oi_days=int(grid["open_interest_usd"].notna().sum()),
                    lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
                )
                _write_futures_to_supabase(grid)
                return grid

        # --- 3차: Bybit 폴백 ---
        log_structured(
            logger,
            event="futures.bybit_fallback",
            message="Bybit 선물 API로 폴백합니다.",
            level=logging.WARNING,
        )
        limit = lookback_days + 2
        bybit_funding = _fetch_bybit_funding_rows(start_ms, end_ms)
        bybit_oi = _fetch_bybit_oi_rows(start_ms, end_ms, limit)
        bybit_closes = _fetch_bybit_btc_closes(start_ms, end_ms, limit) if bybit_oi else {}
        bybit_lsr = _fetch_bybit_lsr_rows(start_ms, end_ms, limit)

        if not bybit_funding and not bybit_oi and not bybit_lsr:
            log_structured(
                logger,
                event="source.failed",
                message="Bybit 선물 데이터도 수집에 실패했습니다. NaN으로 채웁니다.",
                level=logging.WARNING,
                source="bybit_futures",
                reason="all_requests_failed",
            )
            grid = _empty_futures_frame(dates)
            return _attach_futures_attrs(grid, dates=dates, source="none", fallback_used=False)

        _bybit_funding, _bybit_oi, _bybit_lsr = _merge_with_cache(
            _aggregate_bybit_daily_funding(bybit_funding),
            _extract_bybit_daily_oi(bybit_oi, bybit_closes),
            _extract_bybit_daily_lsr(bybit_lsr),
            _cached_funding,
            _cached_oi,
            _cached_lsr,
        )
        grid = _attach_futures_attrs(
            _build_grid(dates, _bybit_funding, _bybit_oi, _bybit_lsr),
            dates=dates,
            source="bybit",
            fallback_used=True,
        )
        log_structured(
            logger,
            event="source.complete",
            message="Bybit에서 선물 데이터를 수집했습니다.",
            source="bybit_futures",
            funding_days=int(grid["funding_rate"].notna().sum()),
            oi_days=int(grid["open_interest_usd"].notna().sum()),
            lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
            oi_quality_status=grid.attrs.get("oi_quality_status"),
            lsr_quality_status=grid.attrs.get("lsr_quality_status"),
        )
        _write_futures_to_supabase(grid)
        return grid

    # --- Binance 성공 경로 ---
    _api_funding = _aggregate_daily_funding(funding_rows)
    _api_oi = _extract_daily_oi(oi_rows)
    _api_lsr = _extract_daily_long_short_ratio(lsr_rows)
    merged_funding, merged_oi, merged_lsr = _merge_with_cache(
        _api_funding,
        _api_oi,
        _api_lsr,
        _cached_funding,
        _cached_oi,
        _cached_lsr,
    )
    grid = _attach_futures_attrs(
        _build_grid(dates, merged_funding, merged_oi, merged_lsr),
        dates=dates,
        source="binance",
        fallback_used=False,
    )

    log_structured(
        logger,
        event="source.complete",
        message="Binance 선물 데이터 수집을 완료했습니다.",
        source="binance_futures",
        funding_days=int(grid["funding_rate"].notna().sum()),
        oi_days=int(grid["open_interest_usd"].notna().sum()),
        lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
        oi_quality_status=grid.attrs.get("oi_quality_status"),
        lsr_quality_status=grid.attrs.get("lsr_quality_status"),
    )
    _write_futures_to_supabase(grid)
    return grid


__all__ = [
    "fetch_futures_data",
    "_is_cache_complete",
    "_merge_with_cache",
]
