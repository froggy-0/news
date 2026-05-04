from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd

from morning_brief.data.sources.http_client import get_json_with_retry
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

FRED_OBSERVATION_URL = "https://api.stlouisfed.org/fred/series/observations"

# DTWEXBGS: Trade Weighted U.S. Dollar Index: Broad, Goods and Services (주별)
# DGS10   : 10-Year Treasury Constant Maturity Rate (일별)
# NASDAQCOM: NASDAQ Composite Index (일별)
MACRO_SERIES: dict[str, str] = {
    "usd_broad_index": "DTWEXBGS",
    "us10y": "DGS10",
    "nasdaq": "NASDAQCOM",
}


def _parse_value(raw: object) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _empty_frame(col: str) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.Series(dtype="object"), col: pd.Series(dtype="float64")})


def fetch_macro_history(series_key: str, start_date: str, end_date: str) -> pd.DataFrame:
    """FRED 시계열 하나를 일별(또는 주별) DataFrame으로 반환합니다.

    series_key: MACRO_SERIES의 키 ("usd_broad_index" | "us10y" | "nasdaq")
    반환: date, {series_key} 컬럼. 실패 시 빈 DataFrame.
    DTWEXBGS는 주별 데이터이므로 호출 측에서 ffill 필요.
    """
    if series_key not in MACRO_SERIES:
        raise ValueError(f"알 수 없는 series_key: {series_key}. 허용: {list(MACRO_SERIES)}")

    series_id = MACRO_SERIES[series_key]
    api_key = os.getenv("FRED_API_KEY", "").strip()
    empty = _empty_frame(series_key)

    if not api_key:
        log_structured(
            logger,
            event="source.skipped",
            message=f"FRED_API_KEY 없음 — {series_key} 수집 건너뜀.",
            source=f"macro_{series_key}",
        )
        return empty

    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError as exc:
        log_structured(
            logger,
            event="source.failed",
            message=f"{series_key} 날짜 형식 오류.",
            level=logging.WARNING,
            source=f"macro_{series_key}",
            reason=str(exc),
        )
        return empty

    try:
        payload = get_json_with_retry(
            FRED_OBSERVATION_URL,
            params={
                "series_id": series_id,
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
            message=f"{series_key}({series_id}) 수집 실패.",
            level=logging.WARNING,
            source=f"macro_{series_key}",
            reason=str(exc),
        )
        return empty

    observations = payload.get("observations")
    if not isinstance(observations, list):
        return empty

    records: list[dict[str, object]] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("date", "")).strip()
        if not raw_date:
            continue
        value = _parse_value(item.get("value"))
        if value is None:
            continue
        records.append({"date": raw_date, series_key: value})

    if not records:
        return empty

    frame = pd.DataFrame(records)
    frame = frame.groupby("date", as_index=False)[series_key].last().sort_values("date")
    frame = frame.reset_index(drop=True)

    log_structured(
        logger,
        event="source.complete",
        message=f"{series_key}({series_id}) 수집 완료.",
        source=f"macro_{series_key}",
        rows=len(frame),
        start=frame["date"].iloc[0] if len(frame) else None,
        end=frame["date"].iloc[-1] if len(frame) else None,
    )
    return frame


__all__ = ["MACRO_SERIES", "fetch_macro_history"]
