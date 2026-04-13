"""백필 진행 로그 및 완료 요약 출력."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backfill.scorer import DailyAggregate
    from backfill.uploader import UploadResults

logger = logging.getLogger(__name__)


def log_date_processed(
    date: str,
    coindesk_count: int,
    alpaca_count: int,
    total: int,
    status: str,
    duration_ms: int,
) -> None:
    """날짜 처리 완료 INFO 로그."""
    logger.info(
        f"날짜 처리 완료: {date}",
        extra={
            "event": "date.processed",
            "attributes": {
                "date": date,
                "coindesk_count": coindesk_count,
                "alpaca_count": alpaca_count,
                "total": total,
                "status": status,
                "duration_ms": duration_ms,
            },
        },
    )


def print_coverage_report(aggregates: list[DailyAggregate]) -> None:
    """dry-run 커버리지 리포트 출력 (실제 FinBERT 추론 결과 기반)."""
    if not aggregates:
        print("수집된 기사 없음.")
        return

    ok_count = sum(1 for a in aggregates if a.status == "ok")
    degraded_count = sum(1 for a in aggregates if a.status == "degraded")
    skipped_count = sum(1 for a in aggregates if a.status == "skipped")
    valid_count = ok_count + degraded_count
    total_articles = sum(a.count for a in aggregates)
    total_coindesk = sum(a.coindesk_count for a in aggregates)
    total_alpaca = sum(a.alpaca_count for a in aggregates)

    sorted_by_count = sorted(aggregates, key=lambda a: a.count, reverse=True)
    top5 = sorted_by_count[:5]
    bottom5 = sorted_by_count[-5:]

    print("\n" + "=" * 60)
    print("  백필 커버리지 리포트 (dry-run)")
    print("=" * 60)

    print("\n[기사 수 상위 5개 날짜]")
    print(f"  {'날짜':<12} {'count':>6} {'status':<10}")
    print(f"  {'-' * 12} {'-' * 6} {'-' * 10}")
    for a in top5:
        print(f"  {a.date:<12} {a.count:>6} {a.status:<10}")

    print("\n[기사 수 하위 5개 날짜]")
    print(f"  {'날짜':<12} {'count':>6} {'status':<10}")
    print(f"  {'-' * 12} {'-' * 6} {'-' * 10}")
    for a in bottom5:
        print(f"  {a.date:<12} {a.count:>6} {a.status:<10}")

    print("\n[status 요약]")
    print(f"  ok:       {ok_count:>4}일")
    print(f"  degraded: {degraded_count:>4}일")
    print(f"  skipped:  {skipped_count:>4}일")
    print(f"  유효 행:  {valid_count:>4}일 (ok+degraded)")

    granger_ok = "✅ 충족" if valid_count >= 180 else "⚠️ 미달"
    print(f"\n[Granger 검정 충족 여부] {granger_ok} (권장: 180일, 현재: {valid_count}일)")

    print("\n[총 기사 수]")
    print(f"  전체:     {total_articles:>6}건")
    print(f"  CoinDesk: {total_coindesk:>6}건")
    print(f"  Alpaca:   {total_alpaca:>6}건")
    print("=" * 60)


def print_summary(
    results: UploadResults,
    aggregates: list[DailyAggregate],
    start_time: float,
) -> None:
    """최종 완료 요약 출력."""
    elapsed_sec = time.time() - start_time
    valid_count = results.aggregates_ok + results.aggregates_degraded
    total_days = len(aggregates)

    total_articles = sum(a.coindesk_count + a.alpaca_count for a in aggregates)
    cd_total = sum(a.coindesk_count for a in aggregates)
    al_total = sum(a.alpaca_count for a in aggregates)
    avg_per_day = total_articles / total_days if total_days > 0 else 0
    cd_avg = cd_total / total_days if total_days > 0 else 0
    al_avg = al_total / total_days if total_days > 0 else 0

    print("\n" + "=" * 60)
    print("  백필 완료 요약")
    print("=" * 60)
    print(f"  전체 대상 날짜:      {total_days:>4}일")
    print(f"  업로드 성공:         {results.uploaded:>4}일")
    print(f"  건너뜀 (기존 존재):  {results.skipped_exists:>4}일")
    print(f"  건너뜀 (원본 보호):  {results.skipped_protected:>4}일")
    print(f"  실패:                {results.failed:>4}일")
    print(f"  유효 행 (ok+degraded): {valid_count:>3}일")
    print(
        f"  평균 기사 수/일:     {avg_per_day:.1f}건 (CoinDesk {cd_avg:.1f} / Alpaca {al_avg:.1f})"
    )
    print(f"  총 소요 시간:        {elapsed_sec:.0f}초")

    if valid_count < 180:
        print(
            f"\n  ⚠️  WARNING: 유효 행 {valid_count}개 — Granger 검정 권장치(180) 미달."
            " CryptoPanic 등 추가 소스를 검토하세요."
        )

    print("\n" + "=" * 60)
    print("\n백필 완료. 이제 아래 명령어로 parquet을 생성하세요:")
    print("  SENTIMENT_JOIN_LOOKBACK_DAYS=460 make sentiment-join")
