"""ETH/SOL(비-BTC) 4H OHLCV 히스토리를 arena_ohlcv_bars에 백필한다.

멀티자산 확장 P1-5의 선결작업 — load_frames_from_supabase()가 arena_ohlcv_bars를
직접 조회하므로(Binance를 그때그때 새로 안 부름), 백테스트를 돌리려면 먼저 이 테이블에
심볼별 4H 봉 히스토리가 있어야 한다. BTC 라이브 경로는 매 4H 사이클마다 자연스럽게
쌓이지만, ETH/SOL은 shadow 사이클(4H)로도 시간이 걸리므로 20개월치를 한 번에 채운다.

Binance klines REST(limit=1000/호출)를 startTime 기준으로 페이지네이션해 수집하고,
arena_ohlcv_bars에 upsert(exchange,symbol,interval,open_time 충돌 시 갱신)한다.
run_id는 이 백필 실행 전체에 대해 1개 생성해 arena_runs에 기록(FK 제약 충족).

재현:
  .venv/bin/python3 scripts/analysis/backfill_ohlcv_symbol.py --symbol ETHUSDT \
      --start 2024-11-01 --end 2026-07-31
  .venv/bin/python3 scripts/analysis/backfill_ohlcv_symbol.py --symbol SOLUSDT \
      --start 2024-11-01 --end 2026-07-31
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import httpx  # noqa: E402

from arena import config, data_lake, parameters, positions  # noqa: E402

BATCH_LIMIT = 1000


async def _fetch_klines_page(
    client: httpx.AsyncClient, *, symbol: str, interval: str, start_ms: int, end_ms: int
) -> list[list]:
    url = (
        f"{config.BINANCE_REST_URL}?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit={BATCH_LIMIT}"
    )
    res = await client.get(url)
    res.raise_for_status()
    return res.json()


async def backfill(symbol: str, interval: str, start: datetime, end: datetime) -> int:
    await positions.init()
    run_id = data_lake.new_run_id()
    started_at = datetime.now(timezone.utc)
    await data_lake.record_run_started(
        run_id=run_id,
        started_at=started_at,
        params_snapshot={"backfill": True, "symbol": symbol, "interval": interval},
        symbol=symbol,
        interval=interval,
        frequency_profile_id=f"backfill_{symbol.lower()}",
        product_type=config.TARGET_PRODUCT,
        position_semantics=config.POSITION_SEMANTICS,
    )

    total_rows = 0
    cursor_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    fetched_at = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=parameters.HTTP_TIMEOUT_SECONDS) as client:
        while cursor_ms < end_ms:
            klines = await _fetch_klines_page(
                client, symbol=symbol, interval=interval, start_ms=cursor_ms, end_ms=end_ms
            )
            if not klines:
                break
            await data_lake.record_ohlcv_bars(
                run_id=run_id,
                raw_klines=klines,
                fetched_at=fetched_at,
                symbol=symbol,
                interval=interval,
            )
            total_rows += len(klines)
            last_open_ms = int(klines[-1][0])
            print(
                f"  {symbol} {interval}: +{len(klines)}행 "
                f"(누적 {total_rows}, 마지막 open_time={datetime.fromtimestamp(last_open_ms / 1000, tz=timezone.utc)})"
            )
            if len(klines) < BATCH_LIMIT:
                break
            cursor_ms = last_open_ms + 1  # 다음 페이지는 마지막 봉 다음부터

    await data_lake.record_run_completed(
        run_id=run_id,
        completed_at=datetime.now(timezone.utc),
        status="completed",
        data_timestamp=end,
    )
    return total_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="예: ETHUSDT, SOLUSDT")
    ap.add_argument("--interval", default=parameters.BINANCE_KLINE_INTERVAL)
    ap.add_argument("--start", default="2024-11-01")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

    print(f"백필 시작: {args.symbol} {args.interval} {start.date()} ~ {end.date()}")
    total = asyncio.run(backfill(args.symbol, args.interval, start, end))
    print(f"완료: 총 {total}행 upsert (arena_ohlcv_bars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
