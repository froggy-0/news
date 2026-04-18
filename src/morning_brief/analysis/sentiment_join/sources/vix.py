from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd

from morning_brief.data.sources.http_client import get_json_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# §4 3-4: VIX는 optional feature. FRED API key 미설정 또는 조회 실패 시 빈 DataFrame을 반환합니다.
# 파이프라인은 이 결과를 left-join으로 붙이므로 없어도 깨지지 않습니다.
FRED_OBSERVATION_URL = "https://api.stlouisfed.org/fred/series/observations"
VIX_SERIES_ID = "VIXCLS"


def _parse_observation_value(raw: object) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _empty_vix_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="object"),
            "vix": pd.Series(dtype="float64"),
        }
    )


def fetch_vix_history(start_date: str, end_date: str) -> pd.DataFrame:
    """FRED VIXCLS 일별 시계열을 가져옵니다. 실패 시 빈 프레임."""
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        log_structured(
            logger,
            event="source.skipped",
            message="FRED_API_KEY가 없어 VIX 수집을 건너뜁니다.",
            source="vix",
        )
        frame = _empty_vix_frame()
        frame.attrs["fallback_used"] = False
        return frame

    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError as exc:
        log_structured(
            logger,
            event="source.failed",
            message="VIX 날짜 형식이 올바르지 않습니다.",
            level=logging.WARNING,
            source="vix",
            reason=str(exc),
        )
        frame = _empty_vix_frame()
        frame.attrs["fallback_used"] = False
        return frame

    try:
        payload = get_json_with_retry(
            FRED_OBSERVATION_URL,
            params={
                "series_id": VIX_SERIES_ID,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start_date,
                "observation_end": end_date,
                "sort_order": "asc",
            },
            provider="fred",
        )
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="VIX 수집에 실패했습니다.",
            level=logging.WARNING,
            source="vix",
            reason=str(exc),
        )
        frame = _empty_vix_frame()
        frame.attrs["fallback_used"] = False
        return frame

    observations = payload.get("observations")
    if not isinstance(observations, list):
        frame = _empty_vix_frame()
        frame.attrs["fallback_used"] = False
        return frame

    records: list[dict[str, object]] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("date", "")).strip()
        if not raw_date:
            continue
        value = _parse_observation_value(item.get("value"))
        if value is None:
            continue
        records.append({"date": raw_date, "vix": value})

    if not records:
        frame = _empty_vix_frame()
        frame.attrs["fallback_used"] = False
        return frame

    frame = pd.DataFrame(records)
    frame = frame.groupby("date", as_index=False)["vix"].last().sort_values("date")
    frame = frame.reset_index(drop=True)
    frame.attrs["fallback_used"] = False
    return frame


__all__ = ["fetch_vix_history"]
