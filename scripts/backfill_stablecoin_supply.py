#!/usr/bin/env python3
"""USDT·USDC 일별 공급량을 DefiLlama에서 수집해 Supabase stablecoin_supply_daily 테이블에 백필합니다.

── Supabase 테이블 DDL (Supabase 대시보드 SQL 에디터에서 먼저 실행) ──────────
CREATE TABLE stablecoin_supply_daily (
    date        DATE             NOT NULL,
    symbol      TEXT             NOT NULL,
    supply_usd  DOUBLE PRECISION NOT NULL,
    source      TEXT             NOT NULL DEFAULT 'defillama',
    created_at  TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (date, symbol)
);
─────────────────────────────────────────────────────────────────────────────

필요 환경변수:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

실행:
    # 기본: 2024-01-01 ~ 오늘
    .venv/bin/python3 scripts/backfill_stablecoin_supply.py

    # 날짜 지정
    .venv/bin/python3 scripts/backfill_stablecoin_supply.py \\
        --start-date 2023-01-01 --end-date 2026-05-04

    # 저장 없이 수집 결과만 확인
    .venv/bin/python3 scripts/backfill_stablecoin_supply.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from morning_brief.analysis.sentiment_join.sources.defillama_stablecoins import (
    _fetch_chart,
    _lookup_id,
    _write_to_supabase,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backfill_stablecoin")


def _check_env() -> bool:
    missing = [
        k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.getenv(k, "").strip()
    ]
    if missing:
        logger.error("필수 환경변수 미설정: %s", ", ".join(missing))
        return False
    return True


def run(start_date: str, end_date: str, dry_run: bool) -> None:
    logger.info("백필 시작: %s ~ %s (dry_run=%s)", start_date, end_date, dry_run)

    # ID 조회
    usdt_id = _lookup_id("USDT")
    usdc_id = _lookup_id("USDC")
    if not usdt_id or not usdc_id:
        logger.error("USDT 또는 USDC ID 조회 실패. 종료합니다.")
        sys.exit(1)
    logger.info("DefiLlama ID — USDT: %s, USDC: %s", usdt_id, usdc_id)

    # 전체 이력 수집 (start_date 이후만)
    logger.info("USDT chart 수집 중...")
    usdt_chart = _fetch_chart(usdt_id, start_date)
    logger.info("USDC chart 수집 중...")
    usdc_chart = _fetch_chart(usdc_id, start_date)

    logger.info("수집 결과 — USDT: %d일, USDC: %d일", len(usdt_chart), len(usdc_chart))

    if not usdt_chart and not usdc_chart:
        logger.error("수집 데이터 없음. 종료합니다.")
        sys.exit(1)

    # end_date 범위 필터링
    usdt_chart = {d: v for d, v in usdt_chart.items() if d <= end_date}
    usdc_chart = {d: v for d, v in usdc_chart.items() if d <= end_date}

    # 레코드 구성
    all_dates = sorted(set(usdt_chart) | set(usdc_chart))
    records: list[dict] = []
    for d in all_dates:
        if usdt_val := usdt_chart.get(d):
            records.append(
                {"date": d, "symbol": "USDT", "supply_usd": usdt_val, "source": "defillama"}
            )
        if usdc_val := usdc_chart.get(d):
            records.append(
                {"date": d, "symbol": "USDC", "supply_usd": usdc_val, "source": "defillama"}
            )

    logger.info("upsert 대상 레코드: %d건 (%d일)", len(records), len(all_dates))

    # 샘플 출력
    sample = records[:3] + records[-3:] if len(records) >= 6 else records
    for r in sample:
        logger.info("  sample: %s", r)

    if dry_run:
        logger.info("dry-run 모드 — Supabase 저장 건너뜀.")
        return

    if not _check_env():
        sys.exit(1)

    _write_to_supabase(records)
    logger.info("백필 완료.")


def main() -> None:
    today = date.today().isoformat()
    parser = argparse.ArgumentParser(description="Stablecoin supply Supabase 백필")
    parser.add_argument("--start-date", default="2024-01-01", help="수집 시작일 (기본: 2024-01-01)")
    parser.add_argument("--end-date", default=today, help=f"수집 종료일 (기본: {today})")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 수집 결과만 출력")
    args = parser.parse_args()

    run(args.start_date, args.end_date, args.dry_run)


if __name__ == "__main__":
    main()
