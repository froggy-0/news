from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

MASTER_FILE_RE = re.compile(r"^master_(\d{8})\.parquet$")
MAX_SENTIMENT_INTELLIGENCE_AGE_DAYS = 7


def _latest_parquet_path(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.glob("master_*.parquet"))
    return candidates[-1] if candidates else None


def _metadata_for(path: Path) -> dict[str, Any]:
    metadata = dict(pq.read_metadata(path).metadata or {})
    raw_stats = metadata.get(b"sentiment_join_stats", b"{}").decode("utf-8")
    stats = json.loads(raw_stats)
    return {
        "btc_source": metadata.get(b"btc_source", b"unknown").decode("utf-8"),
        "stats": stats if isinstance(stats, dict) else {},
    }


def _is_recent_enough(path: Path) -> bool:
    match = MASTER_FILE_RE.match(path.name)
    if match is None:
        return False
    as_of = datetime.strptime(match.group(1), "%Y%m%d").date()
    return (datetime.now(timezone.utc).date() - as_of).days <= MAX_SENTIMENT_INTELLIGENCE_AGE_DAYS


def _last_non_null(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.iloc[-1])


def _previous_non_null(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 2:
        return None
    return float(clean.iloc[-2])


def _hybrid_signal_label(series: pd.Series) -> tuple[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return "neutral", None
    window = clean.tail(30)
    if len(window) < 2:
        return "neutral", None
    mean = float(window.mean())
    std = float(window.std(ddof=0))
    if std == 0:
        return "neutral", 0.0
    zscore = float((window.iloc[-1] - mean) / std)
    if zscore >= 0.5:
        return "risk_on", zscore
    if zscore <= -0.5:
        return "risk_off", zscore
    return "neutral", zscore


def _adf_summary(stats: dict[str, Any]) -> dict[str, Any]:
    adf = stats.get("adf", {})
    if not isinstance(adf, dict):
        return {"tested_columns": [], "stationary": [], "non_stationary": []}
    stationary = [
        key for key, value in adf.items() if isinstance(value, dict) and value.get("stationary")
    ]
    non_stationary = [
        key for key, value in adf.items() if isinstance(value, dict) and not value.get("stationary")
    ]
    return {
        "tested_columns": sorted(adf.keys()),
        "stationary": stationary,
        "non_stationary": non_stationary,
    }


def _granger_summary(stats: dict[str, Any]) -> dict[str, Any]:
    entries = stats.get("granger_results", [])
    if not isinstance(entries, list):
        return {"significant": []}
    significant = [
        entry for entry in entries if isinstance(entry, dict) and bool(entry.get("significant"))
    ]
    significant.sort(key=lambda entry: float(entry.get("pvalue", 1.0)))
    return {"significant": significant[:5]}


def load_sentiment_intelligence(output_dir: Path) -> dict[str, Any] | None:
    path = _latest_parquet_path(output_dir)
    if path is None:
        return None
    if not _is_recent_enough(path):
        raise ValueError(f"sentiment intelligence가 너무 오래되었습니다: {path.name}")

    df = pd.read_parquet(path).sort_values("date").reset_index(drop=True)
    if df.empty or "date" not in df.columns:
        raise ValueError(f"sentiment intelligence parquet 형식이 올바르지 않습니다: {path.name}")

    meta = _metadata_for(path)
    latest = df.iloc[-1]
    hybrid_index = _last_non_null(df["hybrid_index"]) if "hybrid_index" in df.columns else None
    hybrid_prev = _previous_non_null(df["hybrid_index"]) if "hybrid_index" in df.columns else None
    hybrid_delta = (
        float(hybrid_index - hybrid_prev)
        if hybrid_index is not None and hybrid_prev is not None
        else None
    )
    hybrid_signal_label, hybrid_zscore = (
        _hybrid_signal_label(df["hybrid_index"])
        if "hybrid_index" in df.columns
        else ("neutral", None)
    )

    etf_flow = pd.to_numeric(df.get("etf_net_inflow_usd"), errors="coerce")
    latest_flow = _last_non_null(etf_flow) if isinstance(etf_flow, pd.Series) else None
    if latest_flow is None:
        etf_flow_direction = "unknown"
    elif latest_flow > 0:
        etf_flow_direction = "inflow"
    elif latest_flow < 0:
        etf_flow_direction = "outflow"
    else:
        etf_flow_direction = "flat"

    return {
        "as_of_date": str(latest["date"]),
        "hybrid_index": hybrid_index,
        "hybrid_index_prev": hybrid_prev,
        "hybrid_index_delta": hybrid_delta,
        "hybrid_signal_label": hybrid_signal_label,
        "hybrid_zscore": hybrid_zscore,
        "adf_summary": _adf_summary(meta["stats"]),
        "granger_summary": _granger_summary(meta["stats"]),
        "futures_summary": {
            "funding_rate": None
            if pd.isna(latest.get("funding_rate"))
            else float(latest["funding_rate"]),
            "open_interest_usd": None
            if pd.isna(latest.get("open_interest_usd"))
            else float(latest["open_interest_usd"]),
            "btc_long_short_ratio": None
            if pd.isna(latest.get("btc_long_short_ratio"))
            else float(latest["btc_long_short_ratio"]),
        },
        "etf_flow_summary": {
            "etf_total_btc": None
            if pd.isna(latest.get("etf_total_btc"))
            else float(latest["etf_total_btc"]),
            "etf_total_aum_usd": None
            if pd.isna(latest.get("etf_total_aum_usd"))
            else float(latest["etf_total_aum_usd"]),
            "etf_net_inflow_usd": latest_flow,
            "direction": etf_flow_direction,
        },
        "stats_source": {
            "path": str(path),
            "run_id": meta["stats"].get("run_id"),
            "btc_source": meta["btc_source"],
        },
    }


__all__ = ["load_sentiment_intelligence"]
