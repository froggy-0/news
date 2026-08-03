"""arena_asset_news publisher — ETH/SOL 뉴스 헤드라인을 아레나 대시보드용으로 기록.

morning-brief가 이미 수집한 newsdata.io 기사(coin 필드 기반 topic 태깅,
newsdata_provider.py 참조)를 그대로 재사용한다 — 별도 API 호출·키 불필요.
아레나는 morning_brief를 import하지 않는 별도 코드베이스라, 반대 방향(morning_brief가
아레나 대시보드 테이블에 쓰는 것)은 기존 신호 기록(signal_logger.py)과 같은 방향의
단방향 의존이라 문제 없음.

순수 표시용: 이 데이터는 아레나의 어떤 알고리즘 신호에도 연결되지 않는다
(docs/arena/research/arena-eth-sol-dashboard-news-20260803.md 참조).
"""

from __future__ import annotations

import logging
from typing import Any

from morning_brief.models import NewsItem

logger = logging.getLogger(__name__)

# newsdata.io coin 필드가 소문자로 topic에 매핑됨(newsdata_provider._topic_for_article).
# BTC는 스코프 밖 — 아레나 BTC 탭은 이미 실거래 트랙레코드가 있어 뉴스 위젯이 불필요.
COIN_SYMBOL_MAP = {"eth": "ETHUSDT", "sol": "SOLUSDT"}


def _get_supabase_client(supabase_url: str, service_role_key: str):  # type: ignore[return]
    try:
        from supabase import create_client

        return create_client(supabase_url, service_role_key)
    except Exception as exc:
        logger.warning("Supabase 클라이언트 초기화 실패(asset_news): %s", exc)
        return None


def _item_to_rows(item: NewsItem) -> list[dict[str, Any]]:
    if not item.title or not item.url:
        return []
    topics = {t.strip() for t in (item.topic or "").split(",") if t.strip()}
    symbols = sorted({COIN_SYMBOL_MAP[t] for t in topics if t in COIN_SYMBOL_MAP})
    if not symbols:
        return []
    return [
        {
            "symbol": symbol,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary,
        }
        for symbol in symbols
    ]


def publish_asset_news(
    items: list[NewsItem],
    *,
    supabase_url: str,
    service_role_key: str,
) -> int:
    """ETH/SOL 태깅된 기사를 arena_asset_news에 upsert하고 기록된 행 수를 반환.

    Supabase 미설정이거나 실패해도 예외를 올리지 않고 0을 반환 — 모닝브리프 본 파이프라인
    (이메일/공개사이트 생성)에는 어떤 영향도 주지 않는다(signal_logger.py와 동일 관례).
    """
    if not supabase_url or not service_role_key:
        return 0

    rows: list[dict[str, Any]] = []
    for item in items:
        rows.extend(_item_to_rows(item))
    if not rows:
        return 0

    client = _get_supabase_client(supabase_url, service_role_key)
    if client is None:
        return 0

    try:
        client.table("arena_asset_news").upsert(rows, on_conflict="symbol,url").execute()
        logger.info("arena_asset_news 기록 완료: %d건", len(rows))
        return len(rows)
    except Exception as exc:
        logger.warning("arena_asset_news 기록 실패: %s", exc)
        return 0
