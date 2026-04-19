#!/usr/bin/env python3
"""BTC 선물 이력 데이터를 Supabase btc_futures_daily 테이블에 백필합니다.

펀딩비  : 전체 이력 (페이지네이션, 제한 없음)
미결제약정: Binance 최근 30일 또는 Coinalyze daily history
롱숏비율 : Binance 최근 30일 또는 Coinalyze daily history

── Supabase 테이블 DDL (Supabase 대시보드 SQL 에디터에서 먼저 실행) ──────────
CREATE TABLE IF NOT EXISTS btc_futures_daily (
    date   DATE    NOT NULL,
    symbol TEXT    NOT NULL DEFAULT 'BTCUSDT',
    funding_rate         DOUBLE PRECISION,
    open_interest_usd    DOUBLE PRECISION,
    btc_long_short_ratio DOUBLE PRECISION,
    source               TEXT    NOT NULL DEFAULT 'binance',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, symbol)
);
─────────────────────────────────────────────────────────────────────────────

필요 환경변수:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

선택 환경변수:
    COINALYZE_API_KEY (provider=coinalyze일 때 필요)
    FUTURES_BACKFILL_PROVIDER (binance | coinalyze, 기본값: binance)
    FUTURES_BACKFILL_LOOKBACK_DAYS (기본값: binance 30, coinalyze 360)

실행:
    python scripts/backfill_btc_futures.py
    python scripts/backfill_btc_futures.py --dry-run
    python scripts/backfill_btc_futures.py --provider coinalyze --lookback-days 360
    python scripts/backfill_btc_futures.py --provider coinalyze --start 2025-04-24 --end 2026-04-18
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from morning_brief.analysis.sentiment_join.sources.futures import (
    _aggregate_daily_funding,
    _extract_daily_long_short_ratio,
    _extract_daily_oi,
    _fetch_funding_rate_history,
    _fetch_long_short_ratio,
    _fetch_oi_history,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TABLE = "btc_futures_daily"
SYMBOL = "BTCUSDT"
COINALYZE_SYMBOL = "BTCUSDT_PERP.A"
COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
REQUEST_TIMEOUT_SECONDS = 20


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _unix_seconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _date_from_unix_seconds(timestamp: int, *, shift_days: int = 0) -> str:
    day = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
    if shift_days:
        day = day + timedelta(days=shift_days)
    return day.isoformat()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _coinalyze_get_history(
    endpoint: str,
    *,
    api_key: str,
    start: date,
    end: date,
    extra_params: dict[str, str] | None = None,
) -> list[dict]:
    params = {
        "api_key": api_key,
        "symbols": COINALYZE_SYMBOL,
        "interval": "daily",
        "from": str(_unix_seconds(start)),
        "to": str(_unix_seconds(end)),
    }
    if extra_params:
        params.update(extra_params)
    response = requests.get(
        f"{COINALYZE_BASE_URL}/{endpoint}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"Coinalyze API error: {payload['error']}")
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Coinalyze API returned empty payload")
    history = payload[0].get("history") if isinstance(payload[0], dict) else None
    if not isinstance(history, list):
        raise RuntimeError("Coinalyze API payload missing history")
    return history


def _extract_coinalyze_oi(
    rows: list[dict],
    *,
    start: date,
    end: date,
) -> dict[str, float]:
    """Coinalyze daily OI close(c)를 Supabase 계약 날짜로 변환합니다.

    Binance daily OI timestamp는 해당 interval 종료일 쪽으로 기록됩니다. 실측 비교상
    Coinalyze OI daily t는 같은 값을 하루 전 날짜에 싣기 때문에 date + 1일로 정렬합니다.
    """
    lower = start.isoformat()
    upper = end.isoformat()
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("t") is None or row.get("c") is None:
            continue
        try:
            day = _date_from_unix_seconds(int(row["t"]), shift_days=1)
            if lower <= day <= upper:
                daily[day] = float(row["c"])
        except (TypeError, ValueError):
            continue
    return daily


def _extract_coinalyze_lsr(
    rows: list[dict],
    *,
    start: date,
    end: date,
) -> dict[str, float]:
    """Coinalyze long/short ratio(r)는 Binance LSR과 같은 UTC 날짜로 정렬합니다."""
    lower = start.isoformat()
    upper = end.isoformat()
    daily: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("t") is None or row.get("r") is None:
            continue
        try:
            day = _date_from_unix_seconds(int(row["t"]))
            if lower <= day <= upper:
                daily[day] = float(row["r"])
        except (TypeError, ValueError):
            continue
    return daily


def _fetch_all(lookback_days: int) -> dict[str, dict[str, float | None]]:
    """Binance에서 전체 이력을 수집해 {date: {funding_rate, open_interest_usd, btc_long_short_ratio}} 반환."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    start_ms = _ms(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    end_ms = (
        _ms(datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1))
        - 1
    )

    logger.info("펀딩비 수집 중 (전체 이력, 페이지네이션)...")
    funding_rows = _fetch_funding_rate_history(start_ms, end_ms)
    daily_funding = _aggregate_daily_funding(funding_rows)
    logger.info("  펀딩비 %d일치", len(daily_funding))

    logger.info("미결제약정 수집 중 (최대 %d일)...", min(lookback_days + 2, 500))
    oi_rows = _fetch_oi_history(min(lookback_days + 2, 500))
    daily_oi = _extract_daily_oi(oi_rows)
    logger.info("  OI %d일치", len(daily_oi))

    logger.info("롱숏비율 수집 중 (최대 500일)...")
    lsr_rows = _fetch_long_short_ratio(min(lookback_days + 2, 500))
    daily_lsr = _extract_daily_long_short_ratio(lsr_rows)
    logger.info("  LSR %d일치", len(daily_lsr))

    all_dates = sorted(set(daily_funding) | set(daily_oi) | set(daily_lsr))
    return {
        d: {
            "funding_rate": daily_funding.get(d),
            "open_interest_usd": daily_oi.get(d),
            "btc_long_short_ratio": daily_lsr.get(d),
        }
        for d in all_dates
    }


def _fetch_coinalyze_all(start: date, end: date) -> dict[str, dict[str, float | None]]:
    api_key = os.getenv("COINALYZE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("COINALYZE_API_KEY 환경변수 미설정")

    oi_start = start - timedelta(days=1)
    logger.info("Coinalyze 미결제약정 수집 중 (%s ~ %s, OI date +1d 정렬)...", start, end)
    oi_rows = _coinalyze_get_history(
        "open-interest-history",
        api_key=api_key,
        start=oi_start,
        end=end,
        extra_params={"convert_to_usd": "true"},
    )
    daily_oi = _extract_coinalyze_oi(oi_rows, start=start, end=end)
    logger.info("  OI %d일치", len(daily_oi))

    logger.info("Coinalyze 롱숏비율 수집 중 (%s ~ %s)...", start, end)
    lsr_rows = _coinalyze_get_history(
        "long-short-ratio-history",
        api_key=api_key,
        start=start,
        end=end,
    )
    daily_lsr = _extract_coinalyze_lsr(lsr_rows, start=start, end=end)
    logger.info("  LSR %d일치", len(daily_lsr))

    all_dates = sorted(set(daily_oi) | set(daily_lsr))
    return {
        d: {
            "funding_rate": None,
            "open_interest_usd": daily_oi.get(d),
            "btc_long_short_ratio": daily_lsr.get(d),
        }
        for d in all_dates
    }


def _row_for_upsert(date_key: str, values: dict[str, float | None], *, source: str) -> dict:
    row: dict[str, object] = {
        "date": date_key,
        "symbol": SYMBOL,
        "source": source,
    }
    for key in ("funding_rate", "open_interest_usd", "btc_long_short_ratio"):
        value = values.get(key)
        if value is not None:
            row[key] = float(value)
    return row


def _upsert(
    by_date: dict[str, dict[str, float | None]],
    *,
    dry_run: bool,
    source: str,
) -> int:
    rows = [
        _row_for_upsert(d, v, source=source)
        for d, v in by_date.items()
        if any(val is not None for val in v.values())
    ]

    if not rows:
        logger.warning("저장할 데이터 없음")
        return 0

    if dry_run:
        logger.info("[dry-run] upsert 대상 %d행", len(rows))
        for r in rows[:3]:
            logger.info(
                "  %s funding=%.6f oi=%.0f lsr=%.4f",
                r["date"],
                r.get("funding_rate") or 0,
                r.get("open_interest_usd") or 0,
                r.get("btc_long_short_ratio") or 0,
            )
        return len(rows)

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        logger.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수 미설정")
        return 0

    from supabase import create_client

    client = create_client(supabase_url, service_role_key)
    BATCH = 200
    upserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        client.table(TABLE).upsert(batch, on_conflict="date,symbol").execute()
        upserted += len(batch)
        logger.info("  upsert %d/%d", upserted, len(rows))
    return upserted


def main() -> int:
    parser = argparse.ArgumentParser(description="BTC 선물 이력 백필")
    parser.add_argument("--dry-run", action="store_true", help="Supabase에 실제로 쓰지 않음")
    parser.add_argument(
        "--provider",
        choices=("binance", "coinalyze"),
        default=os.getenv("FUTURES_BACKFILL_PROVIDER", "binance").strip() or "binance",
        help="백필 공급자 (기본값: FUTURES_BACKFILL_PROVIDER 또는 binance)",
    )
    parser.add_argument("--lookback-days", type=int, help="오늘 기준 백필 일수")
    parser.add_argument("--start", help="백필 시작일 YYYY-MM-DD (coinalyze provider)")
    parser.add_argument("--end", help="백필 종료일 YYYY-MM-DD (기본값: 오늘 UTC)")
    args = parser.parse_args()

    if args.lookback_days is None:
        default_lookback = "360" if args.provider == "coinalyze" else "30"
        lookback_days = int(os.getenv("FUTURES_BACKFILL_LOOKBACK_DAYS", default_lookback))
    else:
        lookback_days = args.lookback_days

    logger.info("=== 선물 백필 시작 — provider=%s lookback=%d일 ===", args.provider, lookback_days)

    if args.provider == "coinalyze":
        end = _parse_date(args.end) if args.end else datetime.now(timezone.utc).date()
        start = _parse_date(args.start) if args.start else end - timedelta(days=lookback_days - 1)
        if start > end:
            logger.error("start는 end보다 늦을 수 없습니다.")
            return 1
        data = _fetch_coinalyze_all(start, end)
    else:
        data = _fetch_all(lookback_days)
    logger.info("수집 완료 — 총 %d일치", len(data))

    n = _upsert(data, dry_run=args.dry_run, source=args.provider)
    logger.info("=== 완료 — %d행 upsert ===", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
