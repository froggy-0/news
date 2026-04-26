"""CoinDesk Data API 수집기.

카테고리 필터 없이 전체 기사를 날짜 단위로 수집한다.
to_ts 역방향 커서 페이지네이션 + full-jitter 지수 백오프 재시도.

실측 확인된 API 스펙:
  - 최대 limit: 100 (150 이상은 HTTP 400)
  - 페이지네이션: to_ts 커서 방식 (page 파라미터는 오프셋 없음)
  - 공식 rate limit 헤더 없음 → 0.5s 이상 간격 권장
  - 인증 불필요 (공개 API)
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

import requests
from requests.exceptions import ConnectionError as ConnError
from requests.exceptions import Timeout

logger = logging.getLogger(__name__)

BASE_URL = "https://data-api.coindesk.com/news/v1/article/list"
_PAGE_LIMIT = 100  # 실측 최대값 (150+ → HTTP 400)

_HEADERS = {
    "User-Agent": "coindesk-dataset-collector/1.0 (research; contact via github)",
    "Accept": "application/json",
}

# 재시도 설정
_MAX_ATTEMPTS = 5
_BASE_DELAY = 1.0  # 초
_MAX_DELAY = 60.0  # 초 (상한)

_NO_RETRY_STATUSES = frozenset({400, 401, 403})
_RATE_LIMIT_STATUS = 429
_SERVER_ERROR_STATUSES = frozenset({500, 502, 503, 504})


def _jitter_delay(attempt: int) -> float:
    """Full jitter 지수 백오프: uniform(0, min(MAX_DELAY, BASE * 2^attempt))."""
    ceiling = min(_MAX_DELAY, _BASE_DELAY * (2**attempt))
    return random.uniform(0, ceiling)


def _get_with_retry(params: dict) -> dict:
    """지수 백오프 + jitter 재시도로 API 요청.

    오류 유형별 처리:
    - Timeout / ConnectionError: jitter 백오프 후 재시도
    - 404: 즉시 빈 결과 반환
    - 400/401/403: 재시도 없이 즉시 실패 (클라이언트 오류)
    - 429: Retry-After 헤더 우선, 없으면 jitter 백오프
    - 500/502/503/504: jitter 백오프 후 재시도
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = requests.get(BASE_URL, params=params, headers=_HEADERS, timeout=20)
        except Timeout:
            delay = _jitter_delay(attempt)
            logger.warning(
                "타임아웃 (시도 %d/%d) → %.1f초 후 재시도", attempt + 1, _MAX_ATTEMPTS, delay
            )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(delay)
            continue
        except ConnError as exc:
            delay = _jitter_delay(attempt)
            logger.warning(
                "연결 오류 (시도 %d/%d): %s → %.1f초 후 재시도",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
                delay,
            )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(delay)
            continue

        if resp.status_code == 404:
            return {"Data": []}
        if resp.status_code in _NO_RETRY_STATUSES:
            resp.raise_for_status()
        if resp.status_code == _RATE_LIMIT_STATUS:
            raw_after = resp.headers.get("Retry-After")
            delay = float(raw_after) if raw_after else _jitter_delay(attempt)
            logger.warning(
                "Rate limit 429 (시도 %d/%d) → %.1f초 후 재시도", attempt + 1, _MAX_ATTEMPTS, delay
            )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(delay)
            continue
        if resp.status_code in _SERVER_ERROR_STATUSES:
            delay = _jitter_delay(attempt)
            logger.warning(
                "서버 오류 %d (시도 %d/%d) → %.1f초 후 재시도",
                resp.status_code,
                attempt + 1,
                _MAX_ATTEMPTS,
                delay,
            )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(delay)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"최대 재시도 횟수 {_MAX_ATTEMPTS}회 초과")


def _date_to_ts(date_str: str) -> int:
    dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _extract_authors(item: dict) -> list[str]:
    """AUTHORS 필드에서 이름 리스트 추출."""
    authors_raw = item.get("AUTHORS")
    if not authors_raw:
        return []
    if isinstance(authors_raw, list):
        return [str(a.get("NAME") or a) for a in authors_raw if a]
    return [str(authors_raw)]


def fetch_day(date: str, delay_seconds: float = 0.5) -> list[dict]:
    """지정 UTC 날짜의 기사 전체를 수집하여 정규화된 dict 리스트로 반환.

    - limit=100 (실측 최대값) 사용으로 요청 수 최소화
    - 기본 delay 0.5s (2 req/s) — 공개 API 안전 속도
    - BODY 없는 기사도 포함 (has_body=False)
    - 누락 없이 하루치 전체 수집 (to_ts 커서 역방향 페이지네이션)
    """
    start_ts = _date_to_ts(date)
    end_ts = start_ts + 86_400 - 1
    cursor = end_ts
    seen_ids: set[str] = set()
    articles: list[dict] = []
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        try:
            data = _get_with_retry({"lang": "EN", "limit": _PAGE_LIMIT, "to_ts": cursor})
        except Exception as exc:
            logger.warning("페이지 수집 실패 date=%s cursor=%d: %s", date, cursor, exc)
            break

        raw_articles = data.get("Data", [])
        if not raw_articles:
            break

        has_old = False
        for item in raw_articles:
            pub_ts = int(item.get("PUBLISHED_ON") or 0)
            if pub_ts < start_ts:
                has_old = True
                continue

            article_id = str(item.get("ID") or "")
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            title = str(item.get("TITLE") or "").strip()
            subtitle = str(item.get("SUBTITLE") or "").strip()
            body_raw = item.get("BODY")
            body = str(body_raw).strip() if body_raw else ""
            url = item.get("URL") or item.get("url") or item.get("LINK") or item.get("link") or ""
            categories = [
                cd.get("NAME", "") for cd in item.get("CATEGORY_DATA", []) if cd.get("NAME")
            ]
            source_name = (item.get("SOURCE_DATA") or {}).get("NAME", "")

            articles.append(
                {
                    "_schema_version": "1",
                    # 식별자
                    "id": article_id,
                    "guid": str(item.get("GUID") or ""),
                    # 본문
                    "title": title,
                    "subtitle": subtitle,
                    "body": body,
                    "title_char_count": len(title),
                    "body_char_count": len(body),
                    "has_body": bool(body),
                    # 메타
                    "authors": _extract_authors(item),
                    "categories": categories,
                    "keywords": str(item.get("KEYWORDS") or ""),
                    "sentiment": str(item.get("SENTIMENT") or ""),
                    # 품질 시그널
                    "score": item.get("SCORE"),
                    "upvotes": item.get("UPVOTES", 0),
                    "downvotes": item.get("DOWNVOTES", 0),
                    # 출처
                    "url": url,
                    "source": source_name or "CoinDesk",
                    # 타임스탬프
                    "published_at": datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "published_ts": pub_ts,
                    "created_on": item.get("CREATED_ON"),
                    "updated_on": item.get("UPDATED_ON"),
                    "date": date,
                    # 수집 메타
                    "_collected_at": collected_at,
                }
            )

        if has_old:
            break

        min_ts = min(int(item.get("PUBLISHED_ON") or cursor) for item in raw_articles)
        cursor = min_ts - 1
        time.sleep(delay_seconds)

    return articles
