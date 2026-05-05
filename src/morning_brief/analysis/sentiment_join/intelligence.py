from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from morning_brief.analysis.sentiment_join.hybrid_index import INDEX_SPECS
from morning_brief.analysis.sentiment_join.signals import hybrid_signal_label

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


def _build_hybrid_block(df: pd.DataFrame, stats: dict[str, Any], index_name: str) -> dict[str, Any]:
    raw_col = f"{index_name}_hybrid_index"
    score_col = f"{index_name}_hybrid_index_score"
    if raw_col not in df.columns:
        return {
            "raw": None,
            "raw_prev": None,
            "raw_delta": None,
            "score": None,
            "signal_label": "neutral",
            "zscore": None,
            "coverage": {},
        }
    raw_last = _last_non_null(df[raw_col])
    raw_prev = _previous_non_null(df[raw_col])
    raw_delta = (
        float(raw_last - raw_prev) if raw_last is not None and raw_prev is not None else None
    )
    score_last = _last_non_null(df[score_col]) if score_col in df.columns else None
    label, zscore = hybrid_signal_label(df[raw_col])
    hybrid_indices_meta = stats.get("hybrid_indices", {})
    coverage: dict[str, Any] = {}
    if isinstance(hybrid_indices_meta, dict):
        entry = hybrid_indices_meta.get(index_name, {})
        if isinstance(entry, dict):
            coverage = entry.get("coverage", {}) or {}
    return {
        "raw": raw_last,
        "raw_prev": raw_prev,
        "raw_delta": raw_delta,
        "score": score_last,
        "signal_label": label,
        "zscore": zscore,
        "coverage": coverage,
    }


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

    # §4 v4: full / core 두 지수를 모두 노출합니다. 운영 신호(delta/score)는 core가 더
    # 연속성이 높으므로 primary로 사용하고, full은 보조 지표로 함께 반환합니다.
    hybrid_blocks = {
        spec.name: _build_hybrid_block(df, meta["stats"], spec.name) for spec in INDEX_SPECS
    }
    primary = hybrid_blocks.get("core", hybrid_blocks["full"])

    latest = df.iloc[-1]
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

    # Risk Overlay — latest.json의 overlay decision과 함께 산출
    risk_overlay_dict: dict[str, Any] | None = None
    try:
        from .risk_overlay import compute_risk_overlay

        latest_json = Path(output_dir) / "latest.json"
        overlay_decision = "research_only"
        if latest_json.exists():
            import json as _json

            with latest_json.open() as _fp:
                _artifact = _json.load(_fp)
            overlay_decision = (
                _artifact.get("alpha", {})
                .get("promotionGate", {})
                .get("volRegimeV2Overlay", {})
                .get("decision", "research_only")
            )
        risk_overlay_dict = compute_risk_overlay(df, overlay_decision).to_dict()
    except Exception:
        pass

    return {
        "as_of_date": str(latest["date"]),
        "risk_overlay": risk_overlay_dict,
        "hybrid_indices": hybrid_blocks,
        "hybrid_primary": "core",
        "hybrid_index": primary["raw"],
        "hybrid_index_prev": primary["raw_prev"],
        "hybrid_index_delta": primary["raw_delta"],
        "hybrid_index_score": primary["score"],
        "hybrid_signal_label": primary["signal_label"],
        "hybrid_zscore": primary["zscore"],
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
