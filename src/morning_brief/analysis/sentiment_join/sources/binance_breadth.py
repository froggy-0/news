from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

SPOT_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
SPOT_KLINES_URL_FALLBACK = "https://api.binance.com/api/v3/klines"

# Lambda와 동일한 목록으로 유지
BREADTH_SYMBOLS: list[str] = [
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "POLUSDT",
]


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _empty_breadth_frame() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.Series(dtype="object")})


# ---------------------------------------------------------------------------
# 로컬 직접 수집 경로
# ---------------------------------------------------------------------------


def _call_klines(params: dict[str, Any]) -> list[list]:
    from morning_brief.data.sources.http_client import get_list_with_retry

    for url in (SPOT_KLINES_URL, SPOT_KLINES_URL_FALLBACK):
        try:
            return get_list_with_retry(url, params=params, provider="binance_spot", timeout=20)
        except Exception:
            if url == SPOT_KLINES_URL_FALLBACK:
                raise
    raise RuntimeError("unreachable")


def _fetch_closes_direct(symbol: str, start_ms: int, end_ms: int) -> dict[str, float]:
    try:
        rows = _call_klines(
            {
                "symbol": symbol,
                "interval": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        return {
            datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d"): float(
                r[4]
            )
            for r in rows
            if isinstance(r, (list, tuple)) and len(r) >= 5
        }
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message=f"Binance spot klines 직접 수집 실패: {symbol}",
            level=logging.WARNING,
            source=f"binance_spot_{symbol}",
            reason=str(exc),
        )
        return {}


def _fetch_breadth_direct(lookback_days: int) -> dict[str, dict[str, float]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    start_ms = _ms(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    end_ms = (
        _ms(datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1))
        - 1
    )

    result: dict[str, dict[str, float]] = {}
    for symbol in BREADTH_SYMBOLS:
        result[symbol] = _fetch_closes_direct(symbol, start_ms, end_ms)
    return result


# ---------------------------------------------------------------------------
# Lambda 프록시 경로
# ---------------------------------------------------------------------------


def _invoke_lambda(arn: str, lookback_days: int) -> dict | None:
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
            event="breadth.lambda_failed",
            message="Lambda 호출 실패 — spot breadth NaN으로 처리합니다.",
            level=logging.WARNING,
            reason=str(exc),
        )
        return None

    if resp.get("FunctionError"):
        log_structured(
            logger,
            event="breadth.lambda_failed",
            message="Lambda FunctionError — spot breadth NaN으로 처리합니다.",
            level=logging.WARNING,
            reason=resp.get("FunctionError"),
        )
        return None

    try:
        payload = json.loads(resp["Payload"].read())
    except Exception as exc:
        log_structured(
            logger,
            event="breadth.lambda_failed",
            message="Lambda 응답 파싱 실패 — spot breadth NaN으로 처리합니다.",
            level=logging.WARNING,
            reason=str(exc),
        )
        return None

    if "error" in payload:
        log_structured(
            logger,
            event="breadth.lambda_failed",
            message="Lambda error 응답 — spot breadth NaN으로 처리합니다.",
            level=logging.WARNING,
            reason=payload["error"],
        )
        return None

    return payload


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def fetch_breadth_data(lookback_days: int, lambda_arn: str = "") -> pd.DataFrame:
    """Binance top10 alt 일봉 종가를 수집해 wide DataFrame으로 반환합니다.

    columns: date, ETHUSDT_close, BNBUSDT_close, ...(10개)

    로컬(!GITHUB_ACTIONS): data-api.binance.vision 직접 호출
    GitHub Actions + lambda_arn: 기존 Lambda payload의 spot_breadth 키 추출
    실패 시: 빈 DataFrame (파이프라인은 NaN 컬럼으로 처리)
    """
    is_github_actions = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    arn = lambda_arn.strip() or os.getenv("FUTURES_LAMBDA_ARN", "").strip()

    if is_github_actions and arn:
        payload = _invoke_lambda(arn, lookback_days)
        breadth_raw: dict[str, dict[str, float]] = (
            payload.get("spot_breadth") or {} if payload else {}
        )
        source = "lambda"
    else:
        breadth_raw = _fetch_breadth_direct(lookback_days)
        source = "binance_spot_direct"

    if not breadth_raw:
        log_structured(
            logger,
            event="source.skipped",
            message="spot breadth 데이터 없음 — 빈 DataFrame 반환.",
            source="binance_breadth",
        )
        return _empty_breadth_frame()

    # wide DataFrame 구성: date 유니온, 심볼별 종가 컬럼
    all_dates: set[str] = set()
    for closes in breadth_raw.values():
        all_dates.update(closes.keys())

    if not all_dates:
        return _empty_breadth_frame()

    dates_sorted = sorted(all_dates)
    df = pd.DataFrame({"date": dates_sorted})
    for symbol in BREADTH_SYMBOLS:
        closes = breadth_raw.get(symbol, {})
        df[f"{symbol}_close"] = [closes.get(d, float("nan")) for d in dates_sorted]

    valid_symbols = sum(1 for s in BREADTH_SYMBOLS if breadth_raw.get(s))
    log_structured(
        logger,
        event="source.complete",
        message=f"spot breadth 수집 완료 ({valid_symbols}/{len(BREADTH_SYMBOLS)} 심볼).",
        source=source,
        rows=len(df),
        start=dates_sorted[0] if dates_sorted else None,
        end=dates_sorted[-1] if dates_sorted else None,
        valid_symbols=valid_symbols,
    )
    return df


__all__ = ["BREADTH_SYMBOLS", "fetch_breadth_data"]
