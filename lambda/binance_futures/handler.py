"""Binance 선물 데이터 수집 Lambda 핸들러.

GitHub Actions(US IP)에서 fapi.binance.com이 HTTP 451로 차단되므로
ap-northeast-2(Seoul) Lambda를 프록시로 사용합니다.

외부 의존성 없음 — urllib 표준 라이브러리만 사용.
Binance fapi 공개 엔드포인트(인증 불필요): fundingRate, openInterestHist, globalLongShortAccountRatio

입력:
    event["lookback_days"]: int  수집할 기간(일), 기본값 30

출력 (성공):
    {
        "funding_rate":        {"YYYY-MM-DD": float, ...},
        "open_interest_usd":   {"YYYY-MM-DD": float, ...},
        "btc_long_short_ratio": {"YYYY-MM-DD": float, ...}
    }

출력 (실패):
    {"error": "메시지"}
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

SYMBOL = "BTCUSDT"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
LSR_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
TIMEOUT = 20


def _get(url: str, params: dict[str, str]) -> Any:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": "morning-market-brief/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _fetch_funding(start_ms: int) -> list[dict]:
    params = {"symbol": SYMBOL, "startTime": str(start_ms), "limit": "1000"}
    try:
        rows = _get(FUNDING_URL, params)
        result = rows if isinstance(rows, list) else []
        logger.info("funding rows=%d", len(result))
        return result
    except urllib.error.HTTPError as exc:
        logger.error("funding HTTP %s %s", exc.code, exc.reason)
        return []
    except Exception as exc:
        logger.error("funding error: %s", exc)
        return []


def _fetch_oi(limit: int) -> list[dict]:
    params = {"symbol": SYMBOL, "period": "1d", "limit": str(min(limit, 500))}
    try:
        rows = _get(OI_URL, params)
        result = rows if isinstance(rows, list) else []
        logger.info("oi rows=%d", len(result))
        return result
    except urllib.error.HTTPError as exc:
        logger.error("oi HTTP %s %s", exc.code, exc.reason)
        return []
    except Exception as exc:
        logger.error("oi error: %s", exc)
        return []


def _fetch_lsr(limit: int) -> list[dict]:
    params = {"symbol": SYMBOL, "period": "1d", "limit": str(min(limit, 500))}
    try:
        rows = _get(LSR_URL, params)
        result = rows if isinstance(rows, list) else []
        logger.info("lsr rows=%d", len(result))
        return result
    except urllib.error.HTTPError as exc:
        logger.error("lsr HTTP %s %s", exc.code, exc.reason)
        return []
    except Exception as exc:
        logger.error("lsr error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _parse_funding(rows: list[dict]) -> dict[str, float]:
    """8시간 펀딩비 3건을 일별 합산."""
    daily: dict[str, list[float]] = {}
    for row in rows:
        ts = row.get("fundingTime")
        rate = row.get("fundingRate")
        if ts is None or rate is None:
            continue
        try:
            daily.setdefault(_day(int(ts)), []).append(float(rate))
        except (TypeError, ValueError):
            continue
    return {d: sum(v) for d, v in daily.items()}


def _parse_oi(rows: list[dict]) -> dict[str, float]:
    daily: dict[str, float] = {}
    for row in rows:
        ts = row.get("timestamp")
        val = row.get("sumOpenInterestValue")
        if ts is None or val is None:
            continue
        try:
            daily[_day(int(ts))] = float(val)
        except (TypeError, ValueError):
            continue
    return daily


def _parse_lsr(rows: list[dict]) -> dict[str, float]:
    daily: dict[str, float] = {}
    for row in rows:
        ts = row.get("timestamp")
        val = row.get("longShortRatio")
        if ts is None or val is None:
            continue
        try:
            daily[_day(int(ts))] = float(val)
        except (TypeError, ValueError):
            continue
    return daily


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: object) -> dict:
    lookback_days: int = int(event.get("lookback_days", 30))
    logger.info("start lookback_days=%d", lookback_days)

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    start_ms = _ms(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    limit = lookback_days + 2

    funding_rows = _fetch_funding(start_ms)
    oi_rows = _fetch_oi(limit)
    lsr_rows = _fetch_lsr(limit)

    if not funding_rows and not oi_rows and not lsr_rows:
        logger.error("all Binance fapi requests failed")
        return {"error": "all Binance fapi requests failed"}

    result = {
        "funding_rate": _parse_funding(funding_rows),
        "open_interest_usd": _parse_oi(oi_rows),
        "btc_long_short_ratio": _parse_lsr(lsr_rows),
    }
    logger.info(
        "done funding_days=%d oi_days=%d lsr_days=%d",
        len(result["funding_rate"]),
        len(result["open_interest_usd"]),
        len(result["btc_long_short_ratio"]),
    )
    return result


# 로컬 직접 실행 (smoke test)
if __name__ == "__main__":
    result = lambda_handler({"lookback_days": 7}, None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
