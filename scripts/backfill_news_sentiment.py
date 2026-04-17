#!/usr/bin/env python3
"""BTC 뉴스 감성 백필 스크립트.

CoinDesk Data API(무인증)와 Alpaca Markets News API(선택)로 과거 460일치
BTC 뉴스를 수집하고 FinBERT로 감성 점수를 계산하여 R2에 업로드한다.

Usage:
    python scripts/backfill_news_sentiment.py \\
        --start 2024-12-09 \\
        --end   2026-04-13 \\
        [--dry-run] [--force] [--batch-size 32] [--skip-alpaca]

Required env (일반 모드):
    R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

Optional env:
    ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY  (없으면 Alpaca 단계 skip)
    BACKFILL_FINBERT_BATCH_SIZE               (기본 32, --batch-size로 override)
    BACKFILL_R2_MAX_CONCURRENCY               (기본 5)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# src/ 경로 추가 (morning_brief 임포트를 위해)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
SCRIPTS_PATH = PROJECT_ROOT / "scripts"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from backfill.merge import merge_articles  # noqa: E402
from backfill.reporter import print_coverage_report, print_summary  # noqa: E402
from backfill.scorer import score_and_aggregate  # noqa: E402
from backfill.sources.alpaca import fetch_alpaca_articles  # noqa: E402
from backfill.sources.coindesk import fetch_coindesk_articles  # noqa: E402
from backfill.uploader import create_s3_client, upload_all  # noqa: E402
from validate_credentials import BackfillCredentialValidator  # noqa: E402

logger = logging.getLogger(__name__)

_R2_REQUIRED = ["R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"]
_MAX_BACKFILL_DAYS = 460


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BTC 뉴스 감성 백필 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="YYYY-MM-DD",
        help="백필 시작 날짜 (UTC 기준, 필수)",
    )
    parser.add_argument(
        "--end",
        default=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        metavar="YYYY-MM-DD",
        help="백필 종료 날짜 (기본값: 오늘 UTC)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="업로드 없이 수집+FinBERT 추론 후 커버리지 리포트만 출력",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 백필 파일 덮어쓰기 허용 (파이프라인 원본은 항상 보호)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("BACKFILL_FINBERT_BATCH_SIZE", "16")),
        dest="batch_size",
        help="FinBERT 배치 크기 (기본값: 16, 운영 파이프라인과 통일)",
    )
    parser.add_argument(
        "--skip-alpaca",
        action="store_true",
        dest="skip_alpaca",
        help="Alpaca 수집 건너뜀 (CoinDesk만 사용)",
    )
    args = parser.parse_args()

    # 날짜 간격 검증
    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end)
    days = (end_dt - start_dt).days
    if days > _MAX_BACKFILL_DAYS:
        raise ValueError(f"백필 최대 기간 {_MAX_BACKFILL_DAYS}일 초과 (요청: {days}일)")

    return args


def _validate_env(args: argparse.Namespace) -> None:
    """필수 환경변수 검증 (dry-run 시 R2 변수 불필요)."""
    if args.dry_run:
        return

    missing = [v for v in _R2_REQUIRED if not os.getenv(v)]
    if missing:
        raise EnvironmentError(
            f"필수 환경변수 누락: {', '.join(missing)}\n"
            "R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME을 설정하세요."
        )


def _alpaca_creds_present() -> bool:
    return bool(os.getenv("ALPACA_API_KEY_ID")) and bool(os.getenv("ALPACA_API_SECRET_KEY"))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()

    # 인증정보 검증 (--skip-validation으로 건너뜀 가능)
    if "--skip-validation" not in sys.argv and not args.dry_run:
        print("\n[1/3] 인증정보 검증 중...\n")
        validator = BackfillCredentialValidator(verbose=False)
        if validator.validate_all() != 0:
            print("❌ 인증정보 검증 실패. 필수 환경변수를 설정한 후 다시 시도하세요.")
            print("   python scripts/validate_credentials.py --backfill --verbose  # 자세한 정보\n")
            return 1
        print("[2/3] 백필 시작...\n")
    elif args.dry_run:
        print("⏭️  인증정보 검증 건너뜀 (--dry-run 모드)\n")
    else:
        print("⏭️  인증정보 검증 건너뜀 (--skip-validation)\n")

    _validate_env(args)

    start_time = time.time()

    logger.info(f"백필 시작: {args.start} ~ {args.end} (dry_run={args.dry_run})")

    # ── 1. CoinDesk 수집 ──────────────────────────────────
    logger.info("CoinDesk 수집 시작...")
    coindesk_articles = fetch_coindesk_articles(args.start, args.end)
    logger.info(f"CoinDesk 수집 완료: {len(coindesk_articles)}건")

    # ── 2. Alpaca 수집 (선택) ─────────────────────────────
    alpaca_articles = []
    if not args.skip_alpaca and _alpaca_creds_present():
        logger.info("Alpaca 수집 시작...")
        alpaca_articles = fetch_alpaca_articles(
            args.start,
            args.end,
            os.getenv("ALPACA_API_KEY_ID", ""),
            os.getenv("ALPACA_API_SECRET_KEY", ""),
        )
        logger.info(f"Alpaca 수집 완료: {len(alpaca_articles)}건")
    elif args.skip_alpaca:
        logger.info("Alpaca 수집 건너뜀 (--skip-alpaca)")
    else:
        logger.info("Alpaca 수집 건너뜀 (자격증명 없음)")

    # ── 3. 병합 ──────────────────────────────────────────
    articles_by_date = merge_articles(coindesk_articles, alpaca_articles)
    logger.info(
        f"병합 완료: {len(articles_by_date)}개 날짜, "
        f"{sum(len(v) for v in articles_by_date.values())}건 (dedup 후)"
    )

    # ── 4. FinBERT 추론 (dry-run 포함 항상 실행) ──────────
    logger.info("FinBERT 추론 시작...")
    aggregates = score_and_aggregate(articles_by_date, batch_size=args.batch_size)
    logger.info(f"FinBERT 추론 완료: {len(aggregates)}개 날짜")

    # ── 5. dry-run: 커버리지 리포트 후 종료 ──────────────
    if args.dry_run:
        print_coverage_report(aggregates)
        return 0

    # ── 6. R2 업로드 ──────────────────────────────────────
    bucket = os.environ["R2_BUCKET_NAME"]
    concurrency = int(os.getenv("BACKFILL_R2_MAX_CONCURRENCY", "5"))
    logger.info(f"R2 업로드 시작: bucket={bucket}, concurrency={concurrency}")

    s3 = create_s3_client()
    results = upload_all(aggregates, s3, bucket, force=args.force, max_concurrency=concurrency)

    # ── 7. 최종 요약 ──────────────────────────────────────
    print_summary(results, aggregates, start_time)
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
