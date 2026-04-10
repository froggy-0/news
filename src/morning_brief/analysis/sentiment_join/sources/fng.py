from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from morning_brief.data.sources.http_client import get_json_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"


def _date_strings_for_lookback(lookback_days: int) -> list[str]:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=lookback_days)
    return [
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range((end_date - start_date).days + 1)
    ]


def _empty_fng_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "fng_value": pd.array([pd.NA] * len(dates), dtype="Int64"),
        }
    )


def _parse_fng_date(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%m-%d-%Y").date().isoformat()
    except ValueError:
        return None


def _parse_fng_value(value: object) -> int | pd._libs.missing.NAType:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return pd.NA


def fetch_fng(lookback_days: int) -> pd.DataFrame:
    dates = _date_strings_for_lookback(lookback_days)
    grid = _empty_fng_frame(dates)

    try:
        payload = get_json_with_retry(
            FNG_URL,
            params={"limit": str(lookback_days + 7), "date_format": "us"},
            provider="alternative_me",
            timeout=20,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="Fear & Greed Index 수집에 실패해 NaN으로 채웁니다.",
            level=logging.WARNING,
            source="fng",
            reason=str(exc),
        )
        grid.attrs["fallback_used"] = False
        return grid

    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        log_structured(
            logger,
            event="source.failed",
            message="Fear & Greed Index 응답이 비어 있어 NaN으로 채웁니다.",
            level=logging.WARNING,
            source="fng",
            reason="empty_response",
        )
        grid.attrs["fallback_used"] = False
        return grid

    values_by_date: dict[str, int | pd._libs.missing.NAType] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed_date = _parse_fng_date(row.get("timestamp"))
        if parsed_date is None:
            continue
        values_by_date[parsed_date] = _parse_fng_value(row.get("value"))

    grid["fng_value"] = pd.array(
        [values_by_date.get(date, pd.NA) for date in grid["date"]],
        dtype="Int64",
    )
    grid.attrs["fallback_used"] = False
    return grid


__all__ = ["fetch_fng"]
