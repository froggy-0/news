from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from morning_brief.data.sources.http_client import get_json_with_retry, get_list_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

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
    dates: list[str],
) -> pd.DataFrame | None:
    """ap-northeast-2 Lambda를 호출해 Binance 선물 데이터를 가져옵니다.

    성공 시 grid DataFrame 반환.
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

    grid = _lambda_payload_to_grid(payload, dates)
    grid.attrs["fallback_used"] = True
    grid.attrs["futures_source"] = "lambda"
    log_structured(
        logger,
        event="source.complete",
        message="Lambda 프록시를 통해 Binance 선물 데이터를 수집했습니다.",
        source="lambda_binance_futures",
        funding_days=int(grid["funding_rate"].notna().sum()),
        oi_days=int(grid["open_interest_usd"].notna().sum()),
        lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
    )
    return grid


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def fetch_futures_data(lookback_days: int, futures_lambda_arn: str = "") -> pd.DataFrame:
    """Req 11: Binance fapi에서 펀딩비·미결제약정·Long/Short Ratio 이력을 수집합니다.

    Binance fapi가 지역 제한(HTTP 451)으로 실패하면 Bybit 공개 API로 자동 폴백합니다.
    두 소스 모두 실패하면 NaN 프레임을 반환해 파이프라인이 계속 진행됩니다.

    Returns DataFrame with columns: date, funding_rate, open_interest_usd, btc_long_short_ratio.
    attrs["futures_source"]: "binance" | "bybit" | "none"
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

    # --- 1차: Binance fapi ---
    funding_rows = _fetch_funding_rate_history(start_ms)
    oi_rows = _fetch_oi_history(lookback_days + 2)

    lsr_rows: list[dict] = []
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
        log_structured(
            logger,
            event="source.failed",
            message="Binance 선물 데이터를 가져오지 못해 NaN으로 채웁니다.",
            level=logging.WARNING,
            source="binance_futures",
            reason="all_requests_failed",
        )

        # --- 2차: Lambda 프록시 (ap-northeast-2 → Seoul IP → fapi.binance.com) ---
        lambda_arn = futures_lambda_arn.strip() or os.getenv("FUTURES_LAMBDA_ARN", "").strip()
        if lambda_arn:
            log_structured(
                logger,
                event="futures.lambda_fallback",
                message="Lambda 프록시로 Binance 선물 데이터를 재시도합니다.",
                level=logging.WARNING,
            )
            lambda_result = _invoke_futures_lambda(lambda_arn, lookback_days, dates)
            if lambda_result is not None:
                return lambda_result

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
            grid.attrs["fallback_used"] = False
            grid.attrs["futures_source"] = "none"
            return grid

        grid = _build_grid(
            dates,
            _aggregate_bybit_daily_funding(bybit_funding),
            _extract_bybit_daily_oi(bybit_oi, bybit_closes),
            _extract_bybit_daily_lsr(bybit_lsr),
        )
        grid.attrs["fallback_used"] = True
        grid.attrs["futures_source"] = "bybit"
        log_structured(
            logger,
            event="source.complete",
            message="Bybit에서 선물 데이터를 수집했습니다.",
            source="bybit_futures",
            funding_days=int(grid["funding_rate"].notna().sum()),
            oi_days=int(grid["open_interest_usd"].notna().sum()),
            lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
        )
        return grid

    # --- Binance 성공 경로 ---
    grid = _build_grid(
        dates,
        _aggregate_daily_funding(funding_rows),
        _extract_daily_oi(oi_rows),
        _extract_daily_long_short_ratio(lsr_rows),
    )
    grid.attrs["fallback_used"] = False
    grid.attrs["futures_source"] = "binance"

    log_structured(
        logger,
        event="source.complete",
        message="Binance 선물 데이터 수집을 완료했습니다.",
        source="binance_futures",
        funding_days=int(grid["funding_rate"].notna().sum()),
        oi_days=int(grid["open_interest_usd"].notna().sum()),
        lsr_days=int(grid["btc_long_short_ratio"].notna().sum()),
    )
    return grid


__all__ = ["fetch_futures_data"]
