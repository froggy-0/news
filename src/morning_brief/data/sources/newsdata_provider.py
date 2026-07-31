"""newsdata.io /1/crypto 전용 엔드포인트 연동 (2026-07-31).

설계: docs/research/crypto-news-source-expansion-plan-20260731.md

무료 플랜 제약(실측·문서 확인, 2026-07-31):
- 200 API 크레딧/일, 요청당 1크레딧 — 파이프라인이 실행당 요청 1회만 쓰도록 설계돼
  있어 하루 몇 번을 돌려도 한도에 여유가 크다(페이지네이션 없음, 단발 호출).
- 크레딧당 최대 10건(무료), 12시간 지연(실시간 아님) — 기존 파이프라인이 이미
  36시간 lookback을 쓰므로 문제없음.
- `coin` 파라미터로 정확히 티커 필터링 가능(`coin=BTC,ETH,SOL`).
- `domainurl` 파라미터로 공식 도메인 화이트리스트 필터링 가능.
- ⚠️ `from_date`/`to_date`는 무료 플랜에서 사용 불가(실측, 2026-07-31): 프로덕션에서
  `422 UnsupportedParameter — "Access Denied! To use the date parameter, please
  upgrade your plan or contact support."` 확인됨. 문서(OpenAPI 스펙)에는 이 플랜
  제약이 드러나지 않아 사전에 알 수 없었음 — 날짜 파라미터를 아예 보내지 않고
  최신순 응답을 받은 뒤 `lookback_hours`는 클라이언트 사이드에서만 필터링한다
  (CoinDesk 연동의 `_dedup_latest`/사후 필터 패턴과 동일).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from morning_brief.data import providers
from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.logging_utils import log_structured
from morning_brief.models import NewsItem
from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

NEWSDATA_PROVIDER = "newsdata_io"
BASE_URL = "https://newsdata.io/api/1/crypto"
FREE_PLAN_MAX_PAGE_SIZE = 10


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _published_at(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    return None


def _topic_for_article(coins: object) -> str:
    """coin 필드(예: ["BTC"], ["ETH","SOL"])를 그대로 topic에 반영 — CoinDesk의
    _article_topic()이 항상 "bitcoin"만 반환하던 것과 같은 버그를 반복하지 않는다."""
    if isinstance(coins, list) and coins:
        return ",".join(str(c).lower() for c in coins if c)
    return "crypto"


def _why_it_matters(title: str, description: str) -> str:
    source = description or title
    if not source:
        return "newsdata.io 크립토 뉴스 — BTC/ETH/SOL 시장 흐름을 확인하는 데 도움이 돼요."
    return f"newsdata.io 크립토 뉴스: {source[:180]}"


def _article_to_news_item(raw: dict[str, Any]) -> NewsItem | None:
    title = str(raw.get("title", "")).strip()
    url = str(raw.get("link", "")).strip()
    if not title or not url:
        return None

    description = str(raw.get("description", "")).strip()
    return NewsItem(
        title=title,
        url=url,
        source=str(raw.get("source_name") or raw.get("source_id") or "newsdata.io").strip(),
        published_at=_published_at(raw.get("pubDate")),
        topic=_topic_for_article(raw.get("coin")),
        provider=providers.NEWSDATA_IO,
        summary=description,
        why_it_matters=_why_it_matters(title, description),
        citations=[url],
    )


def fetch_newsdata_crypto_news(
    *,
    api_key: str,
    max_items: int,
    lookback_hours: int,
    coins: str = "BTC,ETH,SOL",
    domainurl: str = "",
    observer: PipelineObserver | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    """newsdata.io /1/crypto 단발 호출(페이지네이션 없음 — 무료 크레딧 보존).

    실패 시 예외를 올리지 않고 빈 리스트 반환(호출부가 다른 소스로 이어가도록).
    """
    if not api_key or max_items <= 0 or lookback_hours <= 0:
        return []

    run_now = now or _now_utc()
    if run_now.tzinfo is None:
        run_now = run_now.replace(tzinfo=timezone.utc)
    run_now = run_now.astimezone(timezone.utc)
    start_at = run_now - timedelta(hours=lookback_hours)

    # from_date/to_date는 무료 플랜에서 422(UnsupportedParameter)로 거부됨(실측) —
    # 날짜 파라미터 없이 최신순으로 받은 뒤 lookback_hours는 아래에서 클라이언트
    # 사이드로 필터링한다.
    params: dict[str, Any] = {
        "apikey": api_key,
        "coin": coins,
        "language": "en",
        "size": min(max_items, FREE_PLAN_MAX_PAGE_SIZE),
        "removeduplicate": 1,
    }
    if domainurl:
        params["domainurl"] = domainurl

    try:
        payload = get_json_with_retry(
            BASE_URL,
            params=params,
            provider=NEWSDATA_PROVIDER,
            timeout=20,
        )
    except HttpFetchError as exc:
        log_structured(
            logger,
            event="error.raised",
            message="newsdata.io에서 뉴스를 가져오지 못해 다른 소스로 이어갈게요.",
            level=logging.WARNING,
            provider=NEWSDATA_PROVIDER,
            reason=str(exc),
        )
        if observer is not None:
            observer.log_event(
                "newsdata_news_degraded",
                level=logging.WARNING,
                reason=str(exc),
            )
        return []

    if payload.get("status") != "success":
        log_structured(
            logger,
            event="error.raised",
            message="newsdata.io 응답이 실패로 표시됐어요.",
            level=logging.WARNING,
            provider=NEWSDATA_PROVIDER,
            reason=str(payload.get("results")),
        )
        if observer is not None:
            observer.log_event(
                "newsdata_news_degraded",
                level=logging.WARNING,
                reason=str(payload.get("results")),
            )
        return []

    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        raw_results = []

    items = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        item = _article_to_news_item(raw)
        if item is None:
            continue
        if item.published_at is not None and item.published_at < start_at:
            continue
        items.append(item)
    items = items[:max_items]

    log_structured(
        logger,
        event="selection.complete",
        message="newsdata.io에서 크립토 뉴스를 수집했어요.",
        provider=NEWSDATA_PROVIDER,
        candidate_count=len(raw_results),
        kept_count=len(items),
        coins=coins,
    )
    if observer is not None:
        observer.log_event(
            "newsdata_news_collected",
            provider=NEWSDATA_PROVIDER,
            candidate_count=len(raw_results),
            kept_count=len(items),
            coins=coins,
        )
    return items
