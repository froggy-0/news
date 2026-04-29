#!/usr/bin/env python3
"""BTC 뉴스 감성 백필 스크립트.

CoinDesk Data API(무인증)와 Alpaca Markets News API(선택)로 과거 뉴스를
수집하거나, 로컬 dataset/data/processed/ 를 사용해 FinBERT로 감성 점수를
계산하여 R2에 업로드한다.

Usage (API 모드 — 기본):
    python scripts/backfill_news_sentiment.py \\
        --start 2024-12-09 \\
        --end   2026-04-13 \\
        [--dry-run] [--force] [--batch-size 32] [--skip-alpaca]

Usage (로컬 모드 — dataset/ 디렉터리 사용, API 불필요):
    python scripts/backfill_news_sentiment.py \\
        --source local \\
        --start 2024-11-06 \\
        --end   2024-12-31 \\
        [--dry-run] [--force] [--batch-size 32]

Required env (일반 모드):
    R2_S3_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_BUCKET
    (legacy alias: R2_ENDPOINT_URL, R2_BUCKET_NAME)

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
from dataclasses import dataclass
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
from backfill.sources.local_dataset import fetch_local_articles  # noqa: E402
from backfill.uploader import create_s3_client, upload_all  # noqa: E402
from morning_brief.r2_env import load_public_r2_env  # noqa: E402
from validate_credentials import BackfillCredentialValidator  # noqa: E402

logger = logging.getLogger(__name__)

_MAX_BACKFILL_DAYS_API = 460
_MAX_BACKFILL_DAYS_LOCAL = 3650


@dataclass
class _StageSnapshot:
    label: str
    detail: str = "대기 중"


@dataclass
class _SourceRange:
    requested_start: str
    requested_end: str
    collected_start: str = ""
    collected_end: str = ""


def _merge_date_range(
    current_start: str,
    current_end: str,
    new_start: str,
    new_end: str,
) -> tuple[str, str]:
    if not new_start or not new_end:
        return current_start, current_end
    if not current_start or new_start < current_start:
        current_start = new_start
    if not current_end or new_end > current_end:
        current_end = new_end
    return current_start, current_end


class _BackfillLiveUI:
    def __init__(self, *, total_steps: int, requested_start: str, requested_end: str) -> None:
        from rich.console import Group
        from rich.live import Live
        from rich.panel import Panel
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
            TimeElapsedColumn,
        )
        from rich.table import Table

        self._Group = Group
        self._Panel = Panel
        self._Table = Table
        self.steps = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=32),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        )
        self.work = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=32),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        )
        self.overall_task = self.steps.add_task("전체 단계", total=total_steps)
        self.coindesk_task = self.work.add_task("CoinDesk 수집", total=None)
        self.alpaca_task = self.work.add_task("Alpaca 수집", total=None)
        self.local_task = self.work.add_task("로컬 데이터셋 로드", total=None)
        self.finbert_task = self.work.add_task("FinBERT 추론", total=100, completed=0)
        self.upload_task = self.work.add_task("R2 업로드", total=100, completed=0)
        self.current_stage = "초기화"
        self.current_detail = "시작 준비 중"
        self.source_ranges = {
            "coindesk": _SourceRange(requested_start=requested_start, requested_end=requested_end),
            "alpaca": _SourceRange(requested_start=requested_start, requested_end=requested_end),
            "local": _SourceRange(requested_start=requested_start, requested_end=requested_end),
        }
        self.snapshots = {
            "coindesk": _StageSnapshot("CoinDesk", f"요청 {requested_start} ~ {requested_end}"),
            "alpaca": _StageSnapshot("Alpaca", f"요청 {requested_start} ~ {requested_end}"),
            "local": _StageSnapshot("로컬", f"요청 {requested_start} ~ {requested_end}"),
            "finbert": _StageSnapshot("FinBERT", "대기 중"),
            "upload": _StageSnapshot("업로드", "대기 중"),
        }
        self.live = Live(self._render(), refresh_per_second=8, transient=False)

    def __enter__(self) -> "_BackfillLiveUI":
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.live.__exit__(exc_type, exc, tb)

    def _render(self):
        table = self._Table.grid(padding=(0, 1))
        table.add_column(style="bold cyan", width=12)
        table.add_column()
        table.add_row("현재 단계", self.current_stage)
        table.add_row("상세", self.current_detail)
        for key in ("coindesk", "alpaca", "local", "finbert", "upload"):
            snapshot = self.snapshots[key]
            table.add_row(snapshot.label, snapshot.detail)
        return self._Panel(
            self._Group(table, self.steps, self.work),
            title="BTC 뉴스 감성 백필 진행 상황",
            border_style="cyan",
        )

    def refresh(self) -> None:
        self.live.update(self._render())

    def set_stage(self, stage: str, detail: str) -> None:
        self.current_stage = stage
        self.current_detail = detail
        self.refresh()

    def advance_step(self, detail: str) -> None:
        self.steps.advance(self.overall_task, 1)
        self.current_detail = detail
        self.refresh()

    def mark_skipped(self, key: str, detail: str) -> None:
        self.snapshots[key].detail = detail
        if key == "alpaca":
            self.work.update(self.alpaca_task, completed=1, total=1)
        self.refresh()

    def update_local(self, event: dict[str, object]) -> None:
        done = int(event.get("done_dates", 0))
        total = max(int(event.get("total_dates", 1)), 1)
        loaded = int(event.get("loaded", 0))
        current_date = str(event.get("date", ""))
        status = str(event.get("status", "running"))
        self.work.update(self.local_task, total=total, completed=done)
        if status == "completed":
            self.snapshots["local"].detail = f"완료: {loaded}건, {total}일 로드"
        else:
            self.snapshots["local"].detail = f"{done}/{total}일, 현재 {current_date}, {loaded}건"
        self.refresh()

    def update_source(self, key: str, event: dict[str, object]) -> None:
        task_id = self.coindesk_task if key == "coindesk" else self.alpaca_task
        pages = int(event.get("pages_fetched", 0))
        collected = int(event.get("collected", 0))
        status = str(event.get("status", "running"))
        oldest = str(event.get("oldest_seen", "")).strip()
        newest = str(event.get("newest_seen", "")).strip()
        source_range = self.source_ranges[key]
        (
            source_range.collected_start,
            source_range.collected_end,
        ) = _merge_date_range(
            source_range.collected_start,
            source_range.collected_end,
            oldest,
            newest,
        )
        requested_window = f"{source_range.requested_start} ~ {source_range.requested_end}"
        collected_window = (
            f"{source_range.collected_start} ~ {source_range.collected_end}"
            if source_range.collected_start and source_range.collected_end
            else "아직 없음"
        )
        page_window = f"{oldest} ~ {newest}" if oldest and newest else "계산 중"
        self.work.update(task_id, total=max(pages, 1), completed=pages)
        self.snapshots[key].detail = (
            f"요청 {requested_window}, 누적 {collected_window}, 현재 페이지 {page_window}, "
            f"{pages}페이지, {collected}건"
        )
        if status == "completed":
            self.work.update(task_id, total=max(pages, 1), completed=max(pages, 1))
            self.snapshots[key].detail = (
                f"완료: 요청 {requested_window}, 수집 {collected_window}, "
                f"{pages}페이지, 총 {collected}건"
            )
        elif status == "failed":
            self.snapshots[key].detail = (
                f"실패 후 종료: 요청 {requested_window}, 수집 {collected_window}, "
                f"{pages}페이지, 총 {collected}건"
            )
        self.refresh()

    def prepare_finbert(self, total_articles: int) -> None:
        total = max(total_articles, 1)
        self.work.update(self.finbert_task, total=total, completed=0)
        self.snapshots["finbert"].detail = f"대기 중: 총 {total_articles}건"
        self.refresh()

    def update_finbert(self, event: dict[str, object]) -> None:
        processed = int(event.get("processed_articles", 0))
        total = max(int(event.get("total_articles", 0)), 1)
        batch_index = int(event.get("batch_index", 0))
        total_batches = max(int(event.get("total_batches", 0)), 1)
        self.work.update(self.finbert_task, total=total, completed=processed)
        if str(event.get("status", "running")) == "completed":
            dates = int(event.get("dates", 0))
            self.snapshots["finbert"].detail = f"완료: {processed}건, {dates}일 집계"
        else:
            self.snapshots[
                "finbert"
            ].detail = f"배치 {batch_index}/{total_batches}, 처리 {processed}/{total}건"
        self.refresh()

    def prepare_upload(self, total_dates: int) -> None:
        total = max(total_dates, 1)
        self.work.update(self.upload_task, total=total, completed=0)
        self.snapshots["upload"].detail = f"대기 중: 총 {total_dates}일"
        self.refresh()

    def update_upload(self, event: dict[str, object]) -> None:
        completed = int(event.get("completed", 0))
        total = max(int(event.get("total", 0)), 1)
        uploaded = int(event.get("uploaded", 0))
        skipped_exists = int(event.get("skipped_exists", 0))
        skipped_protected = int(event.get("skipped_protected", 0))
        failed = int(event.get("failed", 0))
        current_date = str(event.get("date", ""))
        outcome = str(event.get("outcome", ""))
        self.work.update(self.upload_task, total=total, completed=completed)
        self.snapshots["upload"].detail = (
            f"{completed}/{total}일, 최근 {current_date} -> {outcome}, "
            f"성공 {uploaded}, 존재 {skipped_exists}, 보호 {skipped_protected}, 실패 {failed}"
        )
        self.refresh()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BTC 뉴스 감성 백필 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["api", "local"],
        default="api",
        help="데이터 소스: api=CoinDesk/Alpaca API (기본), local=dataset/data/processed/",
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
        help="Alpaca 수집 건너뜀 (CoinDesk만 사용, api 모드 전용)",
    )
    args = parser.parse_args()

    # 날짜 간격 검증
    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end)
    days = (end_dt - start_dt).days
    max_days = _MAX_BACKFILL_DAYS_LOCAL if args.source == "local" else _MAX_BACKFILL_DAYS_API
    if days > max_days:
        raise ValueError(f"백필 최대 기간 {max_days}일 초과 (요청: {days}일, source={args.source})")

    return args


def _validate_env(args: argparse.Namespace) -> None:
    """필수 환경변수 검증 (dry-run 또는 local 소스 시 R2 변수 불필요)."""
    if args.dry_run:
        return

    r2_env = load_public_r2_env()
    missing = []
    if not r2_env.s3_endpoint:
        missing.append("R2_S3_ENDPOINT")
    if not r2_env.access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not r2_env.secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not r2_env.public_bucket:
        missing.append("R2_PUBLIC_BUCKET")
    if missing:
        raise EnvironmentError(
            f"필수 환경변수 누락: {', '.join(missing)}\n"
            "R2_S3_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_BUCKET을 설정하세요."
        )


def _alpaca_creds_present() -> bool:
    return bool(os.getenv("ALPACA_API_KEY_ID")) and bool(os.getenv("ALPACA_API_SECRET_KEY"))


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        import rich  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "rich가 설치되어 있지 않습니다. `pip install -r requirements.txt` 후 다시 실행하세요."
        ) from exc

    args = _parse_args()

    # 인증정보 검증 (dry-run / local 소스 / --skip-validation 시 건너뜀)
    if args.dry_run or args.source == "local":
        reason = "--dry-run 모드" if args.dry_run else "--source local (API 불필요)"
        print(f"⏭️  인증정보 검증 건너뜀 ({reason})\n")
    elif "--skip-validation" not in sys.argv:
        print("\n[1/3] 인증정보 검증 중...\n")
        validator = BackfillCredentialValidator(verbose=False)
        if validator.validate_all() != 0:
            print("❌ 인증정보 검증 실패. 필수 환경변수를 설정한 후 다시 시도하세요.")
            print("   python scripts/validate_credentials.py --backfill --verbose  # 자세한 정보\n")
            return 1
        print("[2/3] 백필 시작...\n")
    else:
        print("⏭️  인증정보 검증 건너뜀 (--skip-validation)\n")

    _validate_env(args)

    start_time = time.time()

    logger.info(f"백필 시작: {args.start} ~ {args.end} (dry_run={args.dry_run})")

    use_local = args.source == "local"
    run_alpaca = not use_local and not args.skip_alpaca and _alpaca_creds_present()
    # 단계 수: 수집(1 or 2) + 병합(1) + FinBERT(1) + 업로드(0 or 1)
    total_steps = (
        (1 if use_local else (2 + (1 if run_alpaca else 0))) + 1 + 1 + (0 if args.dry_run else 1)
    )

    with _BackfillLiveUI(
        total_steps=total_steps,
        requested_start=args.start,
        requested_end=args.end,
    ) as ui:
        ui.set_stage("뉴스 수집 준비", f"기간 {args.start} ~ {args.end}, 소스={args.source}")

        if use_local:
            # ── 1a. 로컬 데이터셋 로드 ────────────────────────
            ui.set_stage("로컬 데이터셋 로드", "dataset/data/processed/ 에서 읽는 중")
            ui.mark_skipped("coindesk", "건너뜀: --source local")
            ui.mark_skipped("alpaca", "건너뜀: --source local")
            local_articles = fetch_local_articles(
                args.start,
                args.end,
                progress_callback=ui.update_local,
            )
            ui.advance_step(f"로컬 로드 완료: {len(local_articles)}건")
            articles_by_date = merge_articles(local_articles, [])
        else:
            # ── 1b. CoinDesk 수집 ─────────────────────────────
            ui.set_stage("CoinDesk 수집", "페이지를 순차적으로 가져오는 중")
            ui.mark_skipped("local", "건너뜀: --source api")
            coindesk_articles = fetch_coindesk_articles(
                args.start,
                args.end,
                progress_callback=lambda event: ui.update_source("coindesk", event),
            )
            ui.advance_step(f"CoinDesk 수집 완료: {len(coindesk_articles)}건")

            # ── 2. Alpaca 수집 (선택) ─────────────────────────
            alpaca_articles = []
            if run_alpaca:
                ui.set_stage("Alpaca 수집", "보완 소스를 페이지 단위로 수집하는 중")
                alpaca_articles = fetch_alpaca_articles(
                    args.start,
                    args.end,
                    os.getenv("ALPACA_API_KEY_ID", ""),
                    os.getenv("ALPACA_API_SECRET_KEY", ""),
                    progress_callback=lambda event: ui.update_source("alpaca", event),
                )
                ui.advance_step(f"Alpaca 수집 완료: {len(alpaca_articles)}건")
            elif args.skip_alpaca:
                ui.mark_skipped("alpaca", "건너뜀: --skip-alpaca")
            else:
                ui.mark_skipped("alpaca", "건너뜀: 자격증명 없음")

            # ── 3. 병합 ───────────────────────────────────────
            ui.set_stage("기사 병합", "중복 제거 후 날짜별로 정리하는 중")
            articles_by_date = merge_articles(coindesk_articles, alpaca_articles)

        deduped_count = sum(len(v) for v in articles_by_date.values())
        ui.advance_step(f"병합 완료: {len(articles_by_date)}일, {deduped_count}건")

        # ── 4. FinBERT 추론 (dry-run 포함 항상 실행) ──────────
        total_articles = sum(len(v) for v in articles_by_date.values())
        ui.set_stage("FinBERT 추론", f"기사 {total_articles}건을 배치 처리하는 중")
        ui.prepare_finbert(total_articles)
        aggregates = score_and_aggregate(
            articles_by_date,
            batch_size=args.batch_size,
            progress_callback=ui.update_finbert,
        )
        ui.advance_step(f"FinBERT 완료: {len(aggregates)}일 집계")

        # ── 5. dry-run: 커버리지 리포트 후 종료 ──────────────
        if args.dry_run:
            ui.set_stage("dry-run 종료", "커버리지 리포트를 출력합니다")
            print_coverage_report(aggregates)
            return 0

        # ── 6. R2 업로드 ──────────────────────────────────────
        bucket = load_public_r2_env().public_bucket
        concurrency = int(os.getenv("BACKFILL_R2_MAX_CONCURRENCY", "5"))
        ui.set_stage("R2 업로드", f"bucket={bucket}, 동시성 {concurrency}")
        ui.prepare_upload(len(aggregates))

        s3 = create_s3_client()
        results = upload_all(
            aggregates,
            s3,
            bucket,
            force=args.force,
            max_concurrency=concurrency,
            progress_callback=ui.update_upload,
        )
        ui.advance_step("업로드 완료")
        ui.set_stage("완료", "최종 요약을 출력합니다")

        # ── 7. 최종 요약 ──────────────────────────────────────
        print_summary(results, aggregates, start_time)
        return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
