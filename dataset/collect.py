#!/usr/bin/env python3
"""CoinDesk 역사 뉴스 데이터셋 수집 CLI.

서브커맨드:
  collect  날짜 범위의 뉴스를 raw/ 에 수집 (중단 재시작 지원)
  process  raw/ → processed/ 정제 (RSS 꼬리말 제거 등)
  split    raw/ → by_category/ 분기
  status   수집 현황 요약 출력

사용 예:
  python dataset/collect.py collect
  python dataset/collect.py collect --start 2021-01-01 --end 2023-12-31
  python dataset/collect.py collect --force
  python dataset/collect.py process
  python dataset/collect.py split
  python dataset/collect.py status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pipeline.checkpoint import Checkpoint  # noqa: E402
from pipeline.fetcher import fetch_day  # noqa: E402
from pipeline.processor import process_day  # noqa: E402
from pipeline.splitter import split_raw_to_categories  # noqa: E402
from pipeline.writer import write_day_raw  # noqa: E402

DATA_ROOT = ROOT / "data"
META_DIR = DATA_ROOT / "_meta"
CHECKPOINT_PATH = META_DIR / "checkpoint.db"
DATASET_JSON = META_DIR / "dataset.json"
DEFAULT_START = "2013-01-01"

console = Console()


# ── 공통 유틸 ─────────────────────────────────────────────────────────────────


def _iter_dates(start: str, end: str):
    """end → start 방향 (최신 → 과거) 으로 날짜를 yield."""
    current = date.fromisoformat(end)
    start_date = date.fromisoformat(start)
    while current >= start_date:
        yield current.isoformat()
        current -= timedelta(days=1)


def _size_str(size_bytes: int) -> str:
    kb = size_bytes / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def _write_dataset_json(checkpoint: Checkpoint) -> None:
    """수집/처리 현황을 _meta/dataset.json 에 기록."""
    summary = checkpoint.summary()
    raw_files = list((DATA_ROOT / "raw").rglob("*.jsonl")) if (DATA_ROOT / "raw").exists() else []
    proc_files = (
        list((DATA_ROOT / "processed").rglob("*.jsonl"))
        if (DATA_ROOT / "processed").exists()
        else []
    )

    payload = {
        "schema_version": "1",
        "source": "CoinDesk Data API",
        "api_endpoint": "https://data-api.coindesk.com/news/v1/article/list",
        "language": "EN",
        "category_filter": None,
        "date_range": {
            "start": summary["earliest_date"],
            "end": summary["latest_date"],
        },
        "stats": {
            "completed_dates": summary["completed_dates"],
            "total_articles": summary["total_articles"],
            "raw_size_bytes": summary["total_raw_bytes"],
            "raw_size_human": _size_str(summary["total_raw_bytes"]),
            "raw_files": len(raw_files),
            "processed_dates": summary["processed_dates"],
            "processed_articles": summary["processed_articles"],
            "processed_files": len(proc_files),
        },
        "notes": (
            "raw/ 는 API 응답 원본 (불변). "
            "processed/ 는 RSS 꼬리말 제거 등 정제 사본. "
            "by_category/ 는 raw 기반 카테고리 파생 뷰."
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    META_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(bar_width=45),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        auto_refresh=False,
        console=console,
    )


def _make_stats_panel(
    label: str,
    current_item: str,
    total_articles: int,
    total_bytes: int,
    error_count: int,
    elapsed: float,
    done: int,
) -> Panel:
    speed_str = ""
    if elapsed > 0 and done > 0:
        speed_str = f"  •  [dim]속도[/] {done / (elapsed / 60):.1f}일/분"

    err_style = "bold red" if error_count > 0 else "dim"
    body = (
        f"[yellow]{current_item}[/]"
        f"  •  [cyan]처리[/] {total_articles:,}건"
        f"  •  [green]크기[/] {_size_str(total_bytes)}"
        f"{speed_str}"
        f"  •  [{err_style}]오류 {error_count}건[/]"
    )
    return Panel(body, title=f"[bold blue]{label}[/]", border_style="blue dim")


# ── collect ───────────────────────────────────────────────────────────────────


def cmd_collect(args: argparse.Namespace) -> None:
    start = args.start or DEFAULT_START
    end = args.end or date.today().isoformat()

    checkpoint = Checkpoint(CHECKPOINT_PATH)
    all_dates = list(_iter_dates(start, end))
    pending = [d for d in all_dates if not checkpoint.is_done(d) or args.force]

    console.print(
        f"[bold]수집 범위[/] {start} ~ {end}  "
        f"[dim]|[/]  전체 {len(all_dates):,}일  "
        f"[dim]|[/]  완료(skip) {len(all_dates) - len(pending):,}일  "
        f"[dim]|[/]  수집 예정 [bold cyan]{len(pending):,}일[/]"
    )

    if not pending:
        console.print("[yellow]수집할 날짜가 없습니다.[/] (--force 로 재수집 가능)")
        _write_dataset_json(checkpoint)
        checkpoint.close()
        return

    progress = _make_progress()
    task_id = progress.add_task("수집", total=len(pending))

    total_articles = 0
    total_bytes = 0
    error_count = 0
    t_start = time.monotonic()
    current_date = pending[0]

    def render():
        elapsed = time.monotonic() - t_start
        done = int(progress.tasks[task_id].completed)
        return Group(
            _make_stats_panel(
                "CoinDesk 수집 현황",
                current_date,
                total_articles,
                total_bytes,
                error_count,
                elapsed,
                done,
            ),
            progress,
        )

    with Live(render(), refresh_per_second=4, console=console) as live:
        for date_str in pending:
            current_date = date_str
            live.update(render())

            try:
                articles = fetch_day(date_str, delay_seconds=args.delay)
            except Exception as exc:
                error_count += 1
                logging.getLogger(__name__).error("수집 실패 %s: %s", date_str, exc)
                progress.advance(task_id)
                live.update(render())
                continue

            out_path = write_day_raw(DATA_ROOT, date_str, articles)
            file_size = out_path.stat().st_size
            checkpoint.mark_done(date_str, len(articles), file_size)

            total_articles += len(articles)
            total_bytes += file_size
            progress.advance(task_id)
            live.update(render())

    _write_dataset_json(checkpoint)
    checkpoint.close()
    console.print(
        f"\n[bold green]수집 완료[/]  {total_articles:,}건  •  "
        f"{_size_str(total_bytes)}  •  오류 {error_count}건"
    )


# ── process ───────────────────────────────────────────────────────────────────


def cmd_process(args: argparse.Namespace) -> None:
    checkpoint = Checkpoint(CHECKPOINT_PATH)

    raw_root = DATA_ROOT / "raw"
    if not raw_root.exists():
        console.print("[yellow]raw/ 디렉토리가 없습니다. 먼저 collect 를 실행하세요.[/]")
        checkpoint.close()
        return

    all_raw = sorted((f.stem for f in raw_root.rglob("*.jsonl")), reverse=True)
    pending = [d for d in all_raw if not checkpoint.is_processed(d) or args.force]

    console.print(
        f"[bold]처리 대상[/]  전체 {len(all_raw):,}일  "
        f"[dim]|[/]  완료(skip) {len(all_raw) - len(pending):,}일  "
        f"[dim]|[/]  처리 예정 [bold cyan]{len(pending):,}일[/]"
    )

    if not pending:
        console.print("[yellow]처리할 날짜가 없습니다.[/] (--force 로 재처리 가능)")
        checkpoint.close()
        return

    progress = _make_progress()
    task_id = progress.add_task("정제", total=len(pending))

    total_articles = 0
    total_bytes = 0
    t_start = time.monotonic()
    current_date = pending[0]

    def render():
        elapsed = time.monotonic() - t_start
        done = int(progress.tasks[task_id].completed)
        return Group(
            _make_stats_panel(
                "processed/ 정제 현황", current_date, total_articles, total_bytes, 0, elapsed, done
            ),
            progress,
        )

    with Live(render(), refresh_per_second=4, console=console) as live:
        for date_str in pending:
            current_date = date_str
            live.update(render())

            count, size = process_day(DATA_ROOT, date_str, force=args.force)
            checkpoint.mark_processed(date_str, count, size)

            total_articles += count
            total_bytes += size
            progress.advance(task_id)
            live.update(render())

    _write_dataset_json(checkpoint)
    checkpoint.close()
    console.print(f"\n[bold green]정제 완료[/]  {total_articles:,}건  •  {_size_str(total_bytes)}")


# ── split ─────────────────────────────────────────────────────────────────────


def cmd_split(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    split_raw_to_categories(DATA_ROOT, force=args.force)

    checkpoint = Checkpoint(CHECKPOINT_PATH)
    _write_dataset_json(checkpoint)
    checkpoint.close()


# ── status ────────────────────────────────────────────────────────────────────


def cmd_status(_args: argparse.Namespace) -> None:
    checkpoint = Checkpoint(CHECKPOINT_PATH)
    summary = checkpoint.summary()
    checkpoint.close()

    raw_files = list((DATA_ROOT / "raw").rglob("*.jsonl")) if (DATA_ROOT / "raw").exists() else []
    proc_files = (
        list((DATA_ROOT / "processed").rglob("*.jsonl"))
        if (DATA_ROOT / "processed").exists()
        else []
    )

    table = Table(title="데이터셋 현황", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column(style="bold")

    table.add_row("수집 날짜", f"{summary['completed_dates']:,}일")
    table.add_row("수집 기사", f"{summary['total_articles']:,}건")
    table.add_row("수집 범위", f"{summary['earliest_date']} ~ {summary['latest_date']}")
    table.add_row("raw 파일 수", f"{len(raw_files):,}개")
    table.add_row("raw 크기", _size_str(summary["total_raw_bytes"]))
    table.add_row("processed 날짜", f"{summary['processed_dates']:,}일")
    table.add_row("processed 파일 수", f"{len(proc_files):,}개")

    cat_root = DATA_ROOT / "by_category"
    if cat_root.exists():
        cats = sorted(p.name for p in cat_root.iterdir() if p.is_dir())
        table.add_row("카테고리", ", ".join(cats))

    console.print(table)

    if DATASET_JSON.exists():
        console.print(f"[dim]dataset.json: {DATASET_JSON}[/]")


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CoinDesk 역사 뉴스 데이터셋 수집",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_collect = sub.add_parser("collect", help="뉴스 수집 → raw/")
    p_collect.add_argument(
        "--start", default=None, metavar="YYYY-MM-DD", help=f"수집 시작일 (기본: {DEFAULT_START})"
    )
    p_collect.add_argument(
        "--end", default=None, metavar="YYYY-MM-DD", help="수집 종료일 (기본: 오늘)"
    )
    p_collect.add_argument("--force", action="store_true", help="완료된 날짜도 재수집")
    p_collect.add_argument(
        "--delay",
        type=float,
        default=0.5,
        metavar="SEC",
        help="요청 간 딜레이 초 (기본: 0.5 / 권장 최소 0.5)",
    )
    p_collect.set_defaults(func=cmd_collect)

    p_process = sub.add_parser("process", help="raw/ → processed/ 정제")
    p_process.add_argument("--force", action="store_true", help="이미 처리된 날짜도 재처리")
    p_process.set_defaults(func=cmd_process)

    p_split = sub.add_parser("split", help="raw/ → by_category/ 분기")
    p_split.add_argument(
        "--force", action="store_true", help="이미 존재하는 카테고리 파일도 덮어쓰기"
    )
    p_split.set_defaults(func=cmd_split)

    p_status = sub.add_parser("status", help="수집 현황 확인")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
