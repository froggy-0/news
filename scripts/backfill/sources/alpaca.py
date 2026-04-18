"""Alpaca Markets News API 수집기 (보완 소스).

Benzinga 기반 BTC/USD 금융 뉴스를 next_page_token 페이지네이션으로 수집한다.
ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY 없으면 빈 리스트 반환.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone

import requests

from backfill.sources.coindesk import RawArticle

logger = logging.getLogger(__name__)

ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _iso_to_utc_date(created_at: str) -> str:
    """ISO 8601 UTC 문자열 → UTC 기준 YYYY-MM-DD."""
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _get_with_retry(url: str, headers: dict, params: dict) -> dict:
    """429/5xx 지수 백오프 재시도(최대 3회)."""
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 401:
                raise EnvironmentError(
                    "Alpaca API 인증 실패 (401) — ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY 확인"
                )
            if resp.status_code == 400:
                raise ValueError(f"Alpaca API 파라미터 오류 (400): {resp.text[:200]}")
            if resp.status_code in _RETRY_STATUSES:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 16.0)
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (EnvironmentError, ValueError):
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                delay = min(delay * 2, 16.0)

    raise last_exc or RuntimeError("request failed")


def fetch_alpaca_articles(
    start_date: str,
    end_date: str,
    api_key_id: str,
    api_secret_key: str,
    *,
    delay_seconds: float = 0.2,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> list[RawArticle]:
    """next_page_token 방식 순방향 페이지네이션.

    body 우선순위: content(HTML 제거) → summary → ""
    날짜 변환: created_at(ISO 8601 UTC) → UTC 기준 YYYY-MM-DD
    """
    if not api_key_id or not api_secret_key:
        logger.info(
            "Alpaca 자격증명 없음, 수집 건너뜀",
            extra={
                "event": "source.skip",
                "attributes": {"source": "alpaca", "reason": "missing_credentials"},
            },
        )
        return []

    headers = {
        "APCA-API-KEY-ID": api_key_id,
        "APCA-API-SECRET-KEY": api_secret_key,
    }
    params: dict = {
        "symbols": "BTC/USD",
        "start": f"{start_date}T00:00:00Z",
        "end": f"{end_date}T23:59:59Z",
        "sort": "desc",
        "limit": 50,
        "include_content": "true",
        "exclude_contentless": "true",
    }

    collected: list[RawArticle] = []
    pages_fetched = 0

    while True:
        data = _get_with_retry(ALPACA_NEWS_URL, headers, params)
        news_items = data.get("news", [])
        if news_items:
            pages_fetched += 1

        for item in news_items:
            article_id = str(item.get("id", ""))
            headline = str(item.get("headline") or "").strip()
            created_at = item.get("created_at", "")
            date = _iso_to_utc_date(created_at) if created_at else ""

            content_raw = item.get("content") or ""
            summary_raw = item.get("summary") or ""
            if content_raw.strip():
                body = _strip_html(content_raw)
            elif summary_raw.strip():
                body = summary_raw.strip()
            else:
                body = ""

            # created_at → Unix timestamp (커서 계산 불필요하지만 RawArticle 필드 유지)
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                pub_ts = int(dt.timestamp())
            except (ValueError, AttributeError):
                pub_ts = 0

            collected.append(
                RawArticle(
                    source="alpaca",
                    article_id=article_id,
                    date=date,
                    title=headline,
                    body=body,
                    published_ts=pub_ts,
                )
            )

        if progress_callback and news_items:
            created_ats = [
                str(item.get("created_at") or "") for item in news_items if item.get("created_at")
            ]
            progress_callback(
                {
                    "source": "alpaca",
                    "status": "running",
                    "pages_fetched": pages_fetched,
                    "page_articles": len(news_items),
                    "collected": len(collected),
                    "oldest_seen": _iso_to_utc_date(min(created_ats)) if created_ats else "",
                    "newest_seen": _iso_to_utc_date(max(created_ats)) if created_ats else "",
                }
            )

        next_token = data.get("next_page_token")
        if not next_token:
            break

        params = dict(params)
        params["page_token"] = next_token
        time.sleep(delay_seconds)

    if progress_callback:
        progress_callback(
            {
                "source": "alpaca",
                "status": "completed",
                "pages_fetched": pages_fetched,
                "collected": len(collected),
            }
        )

    return collected
