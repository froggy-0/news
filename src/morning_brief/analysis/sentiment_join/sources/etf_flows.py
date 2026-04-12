from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from supabase import create_client

from morning_brief.data.etf_storage import DEFAULT_ETF_GOLD_TABLE
from morning_brief.data.sources.btc_etf_official import fetch_official_btc_etf_snapshots
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

ETF_ANALYSIS_TICKERS = ("IBIT", "BITB")


def _date_strings(start_date: str, end_date: str) -> list[str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    return [
        (start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)
    ]


def _empty_etf_frame(start_date: str, end_date: str) -> pd.DataFrame:
    dates = _date_strings(start_date, end_date)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_total_btc": [float("nan")] * len(dates),
            "etf_total_aum_usd": [float("nan")] * len(dates),
        }
    )


def _coerce_float(value: object) -> float | None:
    if not isinstance(value, (int, float, str, bytes)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query_gold_history(start_date: str, end_date: str) -> list[dict[str, Any]]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return []

    client = create_client(supabase_url, service_role_key)
    response = (
        client.table(
            os.getenv("BTC_ETF_GOLD_TABLE", DEFAULT_ETF_GOLD_TABLE).strip()
            or DEFAULT_ETF_GOLD_TABLE
        )
        .select("ticker,as_of_date,aum_usd,total_btc,source_type,quality_status")
        .gte("as_of_date", start_date)
        .lte("as_of_date", end_date)
        .in_("ticker", list(ETF_ANALYSIS_TICKERS))
        .order("as_of_date")
        .execute()
    )
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def _fallback_latest_snapshot(end_date: str) -> list[dict[str, Any]]:
    snapshots = fetch_official_btc_etf_snapshots(api_key="")
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.ticker not in ETF_ANALYSIS_TICKERS:
            continue
        rows.append(
            {
                "ticker": snapshot.ticker,
                "as_of_date": snapshot.as_of_date.isoformat() if snapshot.as_of_date else end_date,
                "aum_usd": snapshot.aum_usd,
                "total_btc": snapshot.total_btc,
                "source_type": snapshot.source_type,
                "quality_status": snapshot.quality_status,
            }
        )
    return rows


def _rows_to_totals(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_date: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        as_of_date = str(row.get("as_of_date", "")).strip()
        source_type = str(row.get("source_type", "")).strip().lower()
        quality_status = str(row.get("quality_status", "")).strip().lower()
        if ticker not in ETF_ANALYSIS_TICKERS or not as_of_date:
            continue
        if source_type == "aggregator" or quality_status == "critical":
            continue
        total_btc = _coerce_float(row.get("total_btc"))
        aum_usd = _coerce_float(row.get("aum_usd"))
        if total_btc is None or aum_usd is None:
            continue
        slot = by_date.setdefault(as_of_date, {"etf_total_btc": 0.0, "etf_total_aum_usd": 0.0})
        slot["etf_total_btc"] += total_btc
        slot["etf_total_aum_usd"] += aum_usd
    return by_date


def fetch_etf_flow_features(
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    del cache_dir  # historical source is Supabase gold table; cache_dir reserved for future use

    dates = _date_strings(start_date, end_date)
    frame = _empty_etf_frame(start_date, end_date)

    try:
        rows = _query_gold_history(start_date, end_date)
    except Exception as exc:
        log_structured(
            logger,
            event="source.failed",
            message="ETF 공식 보유량 이력을 가져오지 못했습니다.",
            level=logging.WARNING,
            source="btc_etf_gold",
            reason=str(exc),
        )
        rows = []

    if not rows:
        try:
            rows = _fallback_latest_snapshot(end_date)
        except Exception as exc:
            log_structured(
                logger,
                event="source.failed",
                message="ETF 최신 공식 스냅샷 fallback도 가져오지 못했습니다.",
                level=logging.WARNING,
                source="btc_etf_official",
                reason=str(exc),
            )
            rows = []

    totals_by_date = _rows_to_totals(rows)
    if not totals_by_date:
        return frame

    frame["etf_total_btc"] = [totals_by_date.get(d, {}).get("etf_total_btc") for d in dates]
    frame["etf_total_aum_usd"] = [totals_by_date.get(d, {}).get("etf_total_aum_usd") for d in dates]
    frame["etf_total_btc"] = pd.to_numeric(frame["etf_total_btc"], errors="coerce").ffill()
    frame["etf_total_aum_usd"] = pd.to_numeric(frame["etf_total_aum_usd"], errors="coerce").ffill()

    log_structured(
        logger,
        event="source.complete",
        message="ETF 공식 보유량 분석용 피처를 준비했습니다.",
        source="btc_etf_gold",
        rows=len(frame),
        non_null_days=int(frame["etf_total_btc"].notna().sum()),
    )
    return frame


__all__ = ["ETF_ANALYSIS_TICKERS", "fetch_etf_flow_features"]
