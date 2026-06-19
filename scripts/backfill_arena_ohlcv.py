"""backfill_arena_ohlcv.py — Binance 공개 API로 BTCUSDT 4H 과거 데이터를 arena_ohlcv_bars에 채운다.

인증 불필요. arena_ohlcv_bars의 upsert constraint(exchange,symbol,interval,open_time)로
중복 없이 안전하게 적재.

사용법:
    .venv/bin/python scripts/backfill_arena_ohlcv.py
    .venv/bin/python scripts/backfill_arena_ohlcv.py --days 365
    .venv/bin/python scripts/backfill_arena_ohlcv.py --days 730 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "4h"
EXCHANGE = "binance"
BARS_PER_REQUEST = 1000  # Binance 최대


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_kline(kline: list) -> dict:
    return {
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "open_time": _ts(int(kline[0])),
        "open": float(kline[1]),
        "high": float(kline[2]),
        "low": float(kline[3]),
        "close": float(kline[4]),
        "volume": float(kline[5]),
        "close_time": _ts(int(kline[6])),
        "quote_volume": float(kline[7]) if len(kline) > 7 else None,
        "trade_count": int(kline[8]) if len(kline) > 8 else None,
        "taker_buy_base_volume": float(kline[9]) if len(kline) > 9 else None,
        "taker_buy_quote_volume": float(kline[10]) if len(kline) > 10 else None,
        "raw_payload": kline,
        # run_id 없음 — backfill 행은 NULL 허용 또는 sentinel
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def fetch_klines(
    client: httpx.AsyncClient,
    start_ms: int,
    end_ms: int,
) -> list[dict]:
    """start_ms ~ end_ms 범위 kline을 페이지네이션으로 모두 수집."""
    rows: list[dict] = []
    current_ms = start_ms

    while current_ms < end_ms:
        params = {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "startTime": current_ms,
            "endTime": end_ms,
            "limit": BARS_PER_REQUEST,
        }
        resp = await client.get(BINANCE_KLINES_URL, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for kline in batch:
            rows.append(_parse_kline(kline))

        # 다음 페이지 시작 = 마지막 bar의 close_time + 1ms
        current_ms = int(batch[-1][6]) + 1

        print(
            f"  fetched {len(batch):4d} bars  "
            f"[{_ts(int(batch[0][0]))} ~ {_ts(int(batch[-1][6]))}]  "
            f"total={len(rows)}",
            flush=True,
        )

        if len(batch) < BARS_PER_REQUEST:
            break
        await asyncio.sleep(0.2)  # rate limit 여유

    return rows


async def save_to_supabase(rows: list[dict], dry_run: bool) -> int:
    from supabase._async.client import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    db = await create_client(url, key)

    if dry_run:
        print(f"  [dry-run] {len(rows)}행 upsert 생략")
        return len(rows)

    # run_id 컬럼이 NOT NULL이면 upsert 실패 — 먼저 테이블 확인 후 제거
    # arena_ohlcv_bars에는 run_id가 있지만 backfill 행은 run_id 없음
    # → run_id 컬럼을 제거하고 upsert
    clean_rows = [{k: v for k, v in row.items() if k != "run_id"} for row in rows]

    chunk = 500
    saved = 0
    for start in range(0, len(clean_rows), chunk):
        batch = clean_rows[start : start + chunk]
        await (
            db.table("arena_ohlcv_bars")
            .upsert(batch, on_conflict="exchange,symbol,interval,open_time")
            .execute()
        )
        saved += len(batch)
        print(f"  upserted {saved}/{len(clean_rows)}", flush=True)

    return saved


async def main(args: argparse.Namespace) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - int(args.days * 24 * 3600 * 1000)

    print(f"Backfill: {SYMBOL} {INTERVAL}  {args.days}일  [{_ts(start_ms)} ~ {_ts(now_ms)}]")
    print(f"예상 bars: ~{args.days * 6}개 ({args.days}일 × 6bar/day)\n")

    async with httpx.AsyncClient() as client:
        rows = await fetch_klines(client, start_ms, now_ms)

    print(f"\n총 {len(rows)}개 bar 수집 완료")

    if not rows:
        print("수집된 데이터 없음 — 종료")
        return

    print(f"\nSupabase upsert 시작 ({'dry-run' if args.dry_run else '실제 저장'})...")
    saved = await save_to_supabase(rows, args.dry_run)
    print(f"\n완료: {saved}행 처리")
    print(f"usable bars (warmup 35 제외): ~{max(0, saved - 35)}")
    print(
        f"walk-forward 가능 여부: {'✓' if saved - 35 >= 626 else f'✗ ({626 - (saved - 35)}개 부족)'}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--days", type=int, default=180, help="과거 몇 일치 수집 (기본 180일 = ~1080 bars)"
    )
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 수집만")
    asyncio.run(main(parser.parse_args()))
