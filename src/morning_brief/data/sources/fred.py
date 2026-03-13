from __future__ import annotations

import logging
from datetime import datetime, timezone

from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.models import MarketPoint

logger = logging.getLogger(__name__)

FRED_OBSERVATION_URL = "https://api.stlouisfed.org/fred/series/observations"

# https://fred.stlouisfed.org/docs/api/fred/series_observations.html
SERIES_MAP = [
    ("미국 10년물 국채금리", "DGS10"),
    ("미국 2년물 국채금리", "DGS2"),
    ("달러 인덱스(광의)", "DTWEXBGS"),
    ("VIX", "VIXCLS"),
]


def _parse_observation_value(raw: str) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _latest_two_values(series_id: str, api_key: str) -> tuple[float, float]:
    payload = get_json_with_retry(
        FRED_OBSERVATION_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 15,
        },
        provider="fred",
    )

    observations = payload.get("observations", [])
    if not isinstance(observations, list):
        raise ValueError(f"FRED 응답 구조가 예상과 달라요: {series_id}")

    values: list[float] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        value = _parse_observation_value(str(item.get("value", "")))
        if value is None:
            continue
        values.append(value)
        if len(values) >= 2:
            break

    if len(values) < 2:
        raise ValueError(f"FRED 시계열 값이 충분하지 않아요: {series_id}")

    return values[0], values[1]


def fetch_macro_points_from_fred(api_key: str) -> list[MarketPoint]:
    if not api_key:
        raise ValueError("FRED API 키가 필요해요.")

    points: list[MarketPoint] = []
    for label, series_id in SERIES_MAP:
        latest, previous = _latest_two_values(series_id=series_id, api_key=api_key)
        if previous == 0:
            change_pct = 0.0
        else:
            change_pct = ((latest - previous) / previous) * 100

        points.append(
            MarketPoint(
                label=label,
                ticker=series_id,
                price=round(latest, 4),
                change_pct=round(change_pct, 2),
            )
        )

    return points


def build_fred_packet(points: list[MarketPoint]) -> dict:
    return {
        "provider": "FRED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "points": [point.__dict__ for point in points],
    }


__all__ = [
    "HttpFetchError",
    "SERIES_MAP",
    "fetch_macro_points_from_fred",
    "build_fred_packet",
]
