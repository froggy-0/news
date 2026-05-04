"""Binance 선물 + Spot breadth 데이터 수집 Lambda 핸들러.

GitHub Actions(US IP)에서 fapi.binance.com이 HTTP 451로 차단되므로
ap-northeast-2(Seoul) Lambda를 프록시로 사용합니다.

외부 의존성 없음 — urllib 표준 라이브러리만 사용.
Binance fapi 공개 엔드포인트(인증 불필요): fundingRate, openInterestHist, globalLongShortAccountRatio
Binance spot 공개 엔드포인트(인증 불필요): data-api.binance.vision klines

입력:
    event["lookback_days"]: int  수집할 기간(일), 기본값 30

출력 (성공):
    {
        "funding_rate":        {"YYYY-MM-DD": float, ...},
        "open_interest_usd":   {"YYYY-MM-DD": float, ...},
        "btc_long_short_ratio": {"YYYY-MM-DD": float, ...},
        "spot_breadth": {
            "ETHUSDT":  {"YYYY-MM-DD": float, ...},
            "BNBUSDT":  {"YYYY-MM-DD": float, ...},
            ...
        }
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

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
LSR_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
SPOT_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
SPOT_KLINES_URL_FALLBACK = "https://api.binance.com/api/v3/klines"
TIMEOUT = 20

# Binance USDT spot 거래량 기준 상위 10개 (BTC 제외, 정적 고정)
# MATICUSDT는 2024-09-10 상장폐지 → POLUSDT(Polygon 리브랜딩)로 교체
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


def _fetch_funding(start_ms: int, end_ms: int) -> list[dict]:
    """펀딩비 이력을 페이지네이션으로 완전 수집합니다.

    단일 호출 limit=1000(≈333일) 절단 문제를 방지하기 위해
    last fundingTime+1 커서 방식으로 end_ms까지 모든 레코드를 수집합니다.
    """
    all_rows: list[dict] = []
    cursor_ms = start_ms

    for _ in range(10):
        params = {
            "symbol": SYMBOL,
            "startTime": str(cursor_ms),
            "endTime": str(end_ms),
            "limit": "1000",
        }
        try:
            page = _get(FUNDING_URL, params)
        except urllib.error.HTTPError as exc:
            logger.error("funding HTTP %s: %s", exc.code, exc.reason)
            break
        except Exception as exc:
            logger.error("funding error: %s", exc)
            break

        if not isinstance(page, list) or not page:
            break

        all_rows.extend(page)

        if len(page) < 1000:
            break

        last_ts = page[-1].get("fundingTime")
        if last_ts is None:
            break
        next_cursor = int(last_ts) + 1
        if next_cursor >= end_ms:
            break
        cursor_ms = next_cursor

    return all_rows


def _fetch_oi(limit: int) -> list[dict]:
    params = {"symbol": SYMBOL, "period": "1d", "limit": str(min(limit, 500))}
    try:
        rows = _get(OI_URL, params)
        return rows if isinstance(rows, list) else []
    except urllib.error.HTTPError as exc:
        logger.error("oi HTTP %s: %s", exc.code, exc.reason)
        return []
    except Exception as exc:
        logger.error("oi error: %s", exc)
        return []


def _fetch_lsr(limit: int) -> list[dict]:
    params = {"symbol": SYMBOL, "period": "1d", "limit": str(min(limit, 500))}
    try:
        rows = _get(LSR_URL, params)
        return rows if isinstance(rows, list) else []
    except urllib.error.HTTPError as exc:
        logger.error("lsr HTTP %s: %s", exc.code, exc.reason)
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
# Spot klines (breadth)
# ---------------------------------------------------------------------------


def _fetch_spot_klines(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    """단일 심볼 일봉 klines를 data-api.binance.vision에서 수집합니다.

    547일(limit=1000 내) 단발 호출로 충분. 실패 시 빈 리스트 반환.
    """
    params = {
        "symbol": symbol,
        "interval": "1d",
        "startTime": str(start_ms),
        "endTime": str(end_ms),
        "limit": "1000",
    }
    for url in (SPOT_KLINES_URL, SPOT_KLINES_URL_FALLBACK):
        try:
            data = _get(url, params)
            if isinstance(data, list):
                return data
        except urllib.error.HTTPError as exc:
            logger.warning("spot klines %s HTTP %s (url=%s)", symbol, exc.code, url)
            if url == SPOT_KLINES_URL_FALLBACK:
                return []
        except Exception as exc:
            logger.warning("spot klines %s error: %s (url=%s)", symbol, exc, url)
            if url == SPOT_KLINES_URL_FALLBACK:
                return []
    return []


def _parse_spot_closes(rows: list[list]) -> dict[str, float]:
    """klines 응답 → {YYYY-MM-DD: close} 딕셔너리."""
    closes: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            day = _day(int(row[0]))
            closes[day] = float(row[4])
        except (TypeError, ValueError, IndexError):
            continue
    return closes


def _fetch_spot_breadth(start_ms: int, end_ms: int) -> dict[str, dict[str, float]]:
    """BREADTH_SYMBOLS 전체 일봉 종가를 수집합니다.

    실패 심볼은 빈 dict로 포함 (부분 실패 허용).
    반환: {"ETHUSDT": {"YYYY-MM-DD": float, ...}, ...}
    """
    result: dict[str, dict[str, float]] = {}
    for symbol in BREADTH_SYMBOLS:
        rows = _fetch_spot_klines(symbol, start_ms, end_ms)
        result[symbol] = _parse_spot_closes(rows)
        logger.info("spot breadth %s: %d days collected", symbol, len(result[symbol]))
    return result


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: object) -> dict:
    lookback_days: int = int(event.get("lookback_days", 30))

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    start_ms = _ms(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    end_ms = (
        _ms(datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1))
        - 1
    )
    limit = lookback_days + 2

    funding_rows = _fetch_funding(start_ms, end_ms)
    oi_rows = _fetch_oi(limit)
    lsr_rows = _fetch_lsr(limit)

    if not funding_rows and not oi_rows and not lsr_rows:
        logger.error("source=fapi.binance.com all_endpoints_failed")
        return {"error": "all Binance fapi requests failed"}

    result = {
        "funding_rate": _parse_funding(funding_rows),
        "open_interest_usd": _parse_oi(oi_rows),
        "btc_long_short_ratio": _parse_lsr(lsr_rows),
    }

    fr = result["funding_rate"]
    oi = result["open_interest_usd"]
    lsr = result["btc_long_short_ratio"]
    date_from = min(fr or oi or lsr)
    date_to = max(fr or oi or lsr)
    logger.info(
        "source=fapi.binance.com symbol=%s range=%s~%s "
        "funding_days=%d(latest=%.6f) oi_days=%d(latest=%.0f) lsr_days=%d(latest=%.4f)",
        SYMBOL,
        date_from,
        date_to,
        len(fr),
        list(fr.values())[-1] if fr else float("nan"),
        len(oi),
        list(oi.values())[-1] if oi else float("nan"),
        len(lsr),
        list(lsr.values())[-1] if lsr else float("nan"),
    )

    # Spot breadth: 실패해도 futures 결과는 반환 (부분 실패 허용)
    spot_breadth = _fetch_spot_breadth(start_ms, end_ms)
    breadth_days = {sym: len(closes) for sym, closes in spot_breadth.items()}
    logger.info("spot_breadth collected: %s", breadth_days)
    result["spot_breadth"] = spot_breadth

    return result


# 로컬 직접 실행 (smoke test)
if __name__ == "__main__":
    result = lambda_handler({"lookback_days": 7}, None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
