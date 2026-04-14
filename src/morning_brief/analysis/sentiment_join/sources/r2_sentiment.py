from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import numpy as np
import pandas as pd

from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.data.storage.analytics_contract import validate_analytics_sentiment_payload
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


def _empty_sentiment_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "news_sentiment_mean": [np.nan] * len(dates),
            "news_sentiment_std": [np.nan] * len(dates),
            "n_articles": pd.array([pd.NA] * len(dates), dtype="Int64"),
            "sentiment_status": [""] * len(dates),
            "is_backfill_valid": [False] * len(dates),
            "ingest_validation_reason": [None] * len(dates),
        }
    )


def _nan_sentiment_row(date: str, *, reason: str | None = None) -> dict[str, object]:
    return {
        "date": date,
        "news_sentiment_mean": np.nan,
        "news_sentiment_std": np.nan,
        "n_articles": pd.NA,
        "sentiment_status": "",
        "is_backfill_valid": False,
        "ingest_validation_reason": reason,
    }


def _coerce_int(value: object) -> int | pd._libs.missing.NAType:
    if value is None or value is pd.NA:
        return pd.NA
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return pd.NA


def _parse_sentiment_payload(date: str, payload: dict[str, Any]) -> dict[str, object]:
    """analytics/btc/{date}.json 계약 기준으로 파싱한다."""
    validation = validate_analytics_sentiment_payload(payload)
    if not validation["valid"]:
        return _nan_sentiment_row(date, reason=validation["reason"])

    sentiment_status = str(payload.get("sentimentStatus", "")).strip().lower()
    aggregate = payload.get("newsSentiment")
    if not isinstance(aggregate, dict):
        return _nan_sentiment_row(date, reason="invalid_contract")

    mean = aggregate.get("mean")
    if sentiment_status == "skipped" or mean is None:
        return {
            "date": date,
            "news_sentiment_mean": np.nan,
            "news_sentiment_std": np.nan,
            "n_articles": pd.NA,
            "sentiment_status": sentiment_status,
            "is_backfill_valid": True,
            "ingest_validation_reason": None,
        }

    std = aggregate.get("std")
    return {
        "date": date,
        "news_sentiment_mean": float(mean),
        "news_sentiment_std": float(std) if isinstance(std, (int, float)) else np.nan,
        "n_articles": _coerce_int(aggregate.get("count")),
        "sentiment_status": sentiment_status,
        "is_backfill_valid": True,
        "ingest_validation_reason": None,
    }


def _fetch_single_date(date: str, *, r2_public_bucket: str) -> tuple[dict[str, object], bool]:
    # analytics 계약 경로만 읽는다 (Req 5.1)
    url = f"{r2_public_bucket.rstrip('/')}/analytics/btc/{date}.json"
    try:
        payload = get_json_with_retry(url, provider="r2", timeout=20)
    except HttpFetchError as exc:
        if exc.status_code == 404:
            return _nan_sentiment_row(date), False
        return _nan_sentiment_row(date), True
    except Exception:
        return _nan_sentiment_row(date), True

    try:
        return _parse_sentiment_payload(date, payload), False
    except Exception:
        return _nan_sentiment_row(date), True


def fetch_r2_sentiment(
    dates: list[str],
    r2_public_bucket: str,
    max_concurrency: int = 10,
) -> pd.DataFrame:
    if not dates:
        return _empty_sentiment_frame([])

    if not r2_public_bucket.strip():
        log_structured(
            logger,
            event="source.failed",
            message="R2 공개 버킷 설정이 없어 감성 점수를 비워 둡니다.",
            level=logging.WARNING,
            source="r2",
            reason="missing_r2_public_bucket",
        )
        frame = _empty_sentiment_frame(dates)
        frame.attrs["fallback_used"] = False
        return frame

    rows: list[dict[str, object]] = []
    error_count = 0
    fetch = partial(_fetch_single_date, r2_public_bucket=r2_public_bucket)
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        for row, had_error in executor.map(fetch, dates):
            rows.append(row)
            if had_error:
                error_count += 1

    if error_count == len(dates):
        log_structured(
            logger,
            event="source.failed",
            message="R2 감성 점수 수집에 전체 실패해 NaN으로 채웁니다.",
            level=logging.WARNING,
            source="r2",
            reason="all_requests_failed",
        )

    frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    frame["n_articles"] = pd.array(frame["n_articles"], dtype="Int64")
    frame.attrs["fallback_used"] = False
    return frame


__all__ = ["fetch_r2_sentiment"]
