from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from supabase import create_client

from morning_brief.analysis.sentiment_join.quality import (
    STRUCTURED_SOURCE_MIN_COVERAGE_RATIO,
    calculate_coverage_ratio,
    quality_status_for_ratio,
)
from morning_brief.data.etf_storage import DEFAULT_ETF_GOLD_TABLE
from morning_brief.data.sources.btc_etf_official import fetch_official_btc_etf_snapshots
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

ETF_ANALYSIS_TICKERS = ("IBIT", "BITB", "GBTC")
ETF_HISTORY_LOOKBACK_BUFFER_DAYS = 30


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


def _set_history_attrs(
    frame: pd.DataFrame,
    *,
    source_mode: str,
    history_non_null_days: int,
    requested_days: int,
) -> pd.DataFrame:
    history_coverage_ratio = calculate_coverage_ratio(history_non_null_days, requested_days)
    history_quality_reasons: list[str] = []
    if source_mode != "gold_history":
        history_quality_reasons.append(f"source_mode:{source_mode}")
    if history_coverage_ratio < STRUCTURED_SOURCE_MIN_COVERAGE_RATIO:
        history_quality_reasons.append("history_coverage_below_threshold")

    frame.attrs["source_mode"] = source_mode
    frame.attrs["history_non_null_days"] = history_non_null_days
    frame.attrs["requested_days"] = requested_days
    frame.attrs["history_coverage_ratio"] = history_coverage_ratio
    frame.attrs["history_quality_status"] = (
        "ok"
        if source_mode == "gold_history"
        and quality_status_for_ratio(history_coverage_ratio) == "ok"
        else "degraded"
    )
    frame.attrs["history_quality_reasons"] = history_quality_reasons
    return frame


def _coerce_float(value: object) -> float | None:
    if not isinstance(value, (int, float, str, bytes)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _history_query_window(start_date: str, end_date: str) -> tuple[str, str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    query_start = (start - timedelta(days=ETF_HISTORY_LOOKBACK_BUFFER_DAYS)).isoformat()
    return query_start, end.isoformat()


def _query_gold_history(start_date: str, end_date: str) -> list[dict[str, Any]]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return []

    query_start_date, query_end_date = _history_query_window(start_date, end_date)
    client = create_client(supabase_url, service_role_key)
    response = (
        client.table(
            os.getenv("BTC_ETF_GOLD_TABLE", DEFAULT_ETF_GOLD_TABLE).strip()
            or DEFAULT_ETF_GOLD_TABLE
        )
        .select("ticker,as_of_date,aum_usd,total_btc,source_type,quality_status")
        .gte("as_of_date", query_start_date)
        .lte("as_of_date", query_end_date)
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


def _rows_to_totals(
    rows: list[dict[str, Any]],
    *,
    dates: list[str],
) -> dict[str, dict[str, float]]:
    normalized_rows: list[dict[str, object]] = []
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
        normalized_rows.append(
            {
                "ticker": ticker,
                "date": as_of_date,
                "total_btc": total_btc,
                "aum_usd": aum_usd,
            }
        )

    if not normalized_rows:
        return {}

    df = pd.DataFrame(normalized_rows)
    date_index = pd.Index(dates, name="date")
    totals_by_metric: dict[str, pd.Series] = {}

    for metric, output_name in (
        ("total_btc", "etf_total_btc"),
        ("aum_usd", "etf_total_aum_usd"),
    ):
        pivot = df.pivot_table(index="date", columns="ticker", values=metric, aggfunc="last")
        pivot = pivot.reindex(date_index).sort_index().ffill()
        totals_by_metric[output_name] = pivot.sum(axis=1, min_count=1)

    return {
        date: {
            "etf_total_btc": float(totals_by_metric["etf_total_btc"].loc[date]),
            "etf_total_aum_usd": float(totals_by_metric["etf_total_aum_usd"].loc[date]),
        }
        for date in dates
        if pd.notna(totals_by_metric["etf_total_btc"].loc[date])
        or pd.notna(totals_by_metric["etf_total_aum_usd"].loc[date])
    }


def fetch_etf_flow_features(
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    del cache_dir  # historical source is Supabase gold table; cache_dir reserved for future use

    dates = _date_strings(start_date, end_date)
    frame = _set_history_attrs(
        _empty_etf_frame(start_date, end_date),
        source_mode="empty",
        history_non_null_days=0,
        requested_days=len(dates),
    )
    source_mode = "empty"

    try:
        rows = _query_gold_history(start_date, end_date)
        if rows:
            source_mode = "gold_history"
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
            source_mode = "latest_snapshot_fallback" if rows else "empty"
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

    totals_by_date = _rows_to_totals(rows, dates=dates)
    if not totals_by_date:
        _set_history_attrs(
            frame,
            source_mode=source_mode,
            history_non_null_days=0,
            requested_days=len(dates),
        )
        return frame

    frame["etf_total_btc"] = [totals_by_date.get(d, {}).get("etf_total_btc") for d in dates]
    frame["etf_total_aum_usd"] = [totals_by_date.get(d, {}).get("etf_total_aum_usd") for d in dates]
    frame["etf_total_btc"] = pd.to_numeric(frame["etf_total_btc"], errors="coerce").ffill()
    frame["etf_total_aum_usd"] = pd.to_numeric(frame["etf_total_aum_usd"], errors="coerce").ffill()
    history_non_null_days = int(frame["etf_total_btc"].notna().sum())
    _set_history_attrs(
        frame,
        source_mode=source_mode,
        history_non_null_days=history_non_null_days,
        requested_days=len(dates),
    )

    log_structured(
        logger,
        event="source.complete",
        message="ETF 공식 보유량 분석용 피처를 준비했습니다.",
        source="btc_etf_gold",
        rows=len(frame),
        source_mode=source_mode,
        non_null_days=history_non_null_days,
        history_coverage_ratio=frame.attrs.get("history_coverage_ratio"),
        history_quality_status=frame.attrs.get("history_quality_status"),
    )
    return frame


__all__ = [
    "ETF_ANALYSIS_TICKERS",
    "ETF_HISTORY_LOOKBACK_BUFFER_DAYS",
    "fetch_etf_flow_features",
]
