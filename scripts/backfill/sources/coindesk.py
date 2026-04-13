"""CoinDesk Data API 뉴스 수집기.

to_ts 커서 방식 역방향 페이지네이션으로 BTC 뉴스를 수집한다.
인증 불필요 (무인증 공개 API).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data-api.coindesk.com/news/v1/article/list"

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


@dataclass
class RawArticle:
    """수집된 원본 기사 (CoinDesk / Alpaca 공통).

    date: UTC 기준 YYYY-MM-DD 문자열 (KST 변환 없음).
    body: FinBERT summary 입력용. BODY/content null/empty이면 빈 문자열.
    published_ts: 원본 Unix timestamp (초 단위). CoinDesk 커서 계산용.
    """

    source: Literal["coindesk", "alpaca"]
    article_id: str
    date: str  # YYYY-MM-DD (UTC 기준)
    title: str
    body: str
    published_ts: int


def _ts_to_utc_date(ts: int) -> str:
    """Unix timestamp(초) → UTC 기준 YYYY-MM-DD."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _date_to_ts(date_str: str) -> int:
    """YYYY-MM-DD → UTC 자정 Unix timestamp(초)."""
    dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _get_with_retry(url: str, params: dict) -> dict:
    """429/5xx 지수 백오프 재시도(최대 3회). 404는 즉시 빈 Data 반환."""
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 404:
                return {"Data": []}
            if resp.status_code in _RETRY_STATUSES:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 16.0)
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                delay = min(delay * 2, 16.0)

    raise last_exc or RuntimeError("request failed")


def fetch_coindesk_articles(
    start_date: str,
    end_date: str,
    *,
    delay_seconds: float = 0.3,
) -> list[RawArticle]:
    """to_ts 커서 방식으로 역방향 페이지네이션.

    배치에 start_ts 이전 기사가 하나라도 등장하면 루프 종료 후 필터링.
    BODY가 null/빈 문자열이면 body="" 설정 (title만으로 FinBERT 입력).
    """
    start_ts = _date_to_ts(start_date)
    # end_date 하루 끝(23:59:59) 포함하기 위해 다음날 자정 - 1초
    end_ts = _date_to_ts(end_date) + 86_400 - 1

    cursor = end_ts
    seen_ids: set[str] = set()
    collected: list[RawArticle] = []

    while True:
        params = {
            "lang": "EN",
            "categories": "BTC",
            "limit": 50,
            "to_ts": cursor,
        }
        try:
            data = _get_with_retry(BASE_URL, params)
        except Exception as exc:
            logger.warning(
                "CoinDesk 페이지 수집 실패, 건너뜁니다",
                extra={
                    "event": "page.skip",
                    "attributes": {
                        "source": "coindesk",
                        "cursor": cursor,
                        "reason": str(exc),
                    },
                },
            )
            break

        articles = data.get("Data", [])
        if not articles:
            break

        has_old = False
        for item in articles:
            pub_ts = int(item.get("PUBLISHED_ON", 0))
            if pub_ts < start_ts:
                has_old = True
                continue  # 필터링: start_ts 이전 기사 제외

            article_id = str(item.get("ID", ""))
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            title = str(item.get("TITLE") or "").strip()
            body_raw = item.get("BODY")
            body = str(body_raw).strip() if body_raw else ""

            collected.append(
                RawArticle(
                    source="coindesk",
                    article_id=article_id,
                    date=_ts_to_utc_date(pub_ts),
                    title=title,
                    body=body,
                    published_ts=pub_ts,
                )
            )

        if has_old:
            break

        min_ts = min(int(item.get("PUBLISHED_ON", cursor)) for item in articles)
        cursor = min_ts - 1  # to_ts inclusive이므로 -1 필수

        time.sleep(delay_seconds)

    return collected
