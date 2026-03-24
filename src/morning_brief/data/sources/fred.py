from __future__ import annotations

import logging

from morning_brief.data.market_policy import (
    canonical_key_for,
    canonical_label_for,
    is_rate_canonical_key,
    normalize_change_bps,
)
from morning_brief.data.sources.http_client import HttpFetchError, get_json_with_retry
from morning_brief.models import MarketPoint

logger = logging.getLogger(__name__)

FRED_OBSERVATION_URL = "https://api.stlouisfed.org/fred/series/observations"

# https://fred.stlouisfed.org/docs/api/fred/series_observations.html
SERIES_MAP = [
    ("us10y", "DGS10"),
    ("us2y", "DGS2"),
    ("vix", "VIXCLS"),
    # dxy: FRED DTWEXAFEGS — 일별 연준 무역가중 달러 지수 (Advanced Foreign Economies)
    # 기존 yfinance DX=F(ICE Dollar Futures)에서 연준 공식 시리즈로 교체
    ("dxy", "DTWEXAFEGS"),
    # hy_spread: FRED BAMLH0A0HYM2 — ICE BofA 미국 하이일드 옵션조정 스프레드
    # 단위: %. 정상: 2~4%, 경계: 4~6%, 위험: 6~8%, 위기: 8%+ (2008: 20%, 2020 COVID: 10%)
    ("hy_spread", "BAMLH0A0HYM2"),
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
    for canonical_key, series_id in SERIES_MAP:
        latest, previous = _latest_two_values(series_id=series_id, api_key=api_key)
        normalized_key = canonical_key_for(series_id, canonical_key)
        change_pct: float | None = None
        change_bps: float | None = None
        if is_rate_canonical_key(normalized_key):
            change_bps = normalize_change_bps((latest - previous) * 100)
        elif previous == 0:
            change_pct = 0.0
        else:
            change_pct = ((latest - previous) / previous) * 100

        points.append(
            MarketPoint(
                label=canonical_label_for(canonical_key),
                ticker=series_id,
                price=round(latest, 4),
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_bps=change_bps,
                canonical_key=normalized_key,
                raw_value=round(latest, 4),
                resolved_value=round(latest, 4),
            )
        )

    return points


__all__ = [
    "HttpFetchError",
    "SERIES_MAP",
    "fetch_macro_points_from_fred",
]
