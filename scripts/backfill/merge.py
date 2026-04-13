"""CoinDesk + Alpaca 기사 병합기.

CoinDesk 기사를 먼저 삽입(우선 보존)하고, Alpaca 기사를 이어 추가한다.
중복 기준: title.lower().strip() 정확 일치 (날짜 내).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from backfill.sources.coindesk import RawArticle

logger = logging.getLogger(__name__)


def merge_articles(
    coindesk: list[RawArticle],
    alpaca: list[RawArticle],
) -> dict[str, list[RawArticle]]:
    """날짜(YYYY-MM-DD) → 기사 리스트 딕셔너리 반환.

    CoinDesk 기사를 먼저 삽입한 뒤 Alpaca 기사 추가.
    동일 날짜 내 title.lower().strip() 일치 → CoinDesk 우선 보존.
    """
    result: dict[str, list[RawArticle]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)  # date → normalized titles

    for article in coindesk + alpaca:
        key = article.title.lower().strip()
        if key not in seen[article.date]:
            seen[article.date].add(key)
            result[article.date].append(article)

    # 날짜별 로그
    all_dates = set(a.date for a in coindesk + alpaca)
    for date in sorted(all_dates):
        cd_count = sum(1 for a in coindesk if a.date == date)
        al_count = sum(1 for a in alpaca if a.date == date)
        total = len(result[date])
        logger.info(
            "병합 완료",
            extra={
                "event": "merge.complete",
                "attributes": {
                    "date": date,
                    "coindesk_count": cd_count,
                    "alpaca_count": al_count,
                    "total_after_dedup": total,
                },
            },
        )

    return dict(result)
