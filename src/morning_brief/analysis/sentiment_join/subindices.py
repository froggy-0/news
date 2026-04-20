from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import (
    MIN_PCA_FEATURES,
    MIN_PCA_ROWS,
    ScalerKind,
    make_scaler,
)

FUNDING_LSR_INTERACTION = "funding_lsr_interaction"
SENTIMENT_VIX_INTERACTION = "sentiment_vix_interaction"
SUBINDEX_SCORE_SUFFIX = "_subindex_score"
SUBINDEX_RAW_SUFFIX = "_subindex"


@dataclass(frozen=True)
class SubIndexSpec:
    name: str
    features: tuple[str, ...]
    scaler_kind: ScalerKind = "standard"
    pca_components: int | None = None


@dataclass(frozen=True)
class SubIndexBundle:
    frame: pd.DataFrame
    diagnostics: dict[str, dict[str, Any]]


DEFAULT_SUBINDEX_SPECS: tuple[SubIndexSpec, ...] = (
    SubIndexSpec(
        name="sentiment",
        features=("news_sentiment_mean_lag1", "fng_value_lag1", SENTIMENT_VIX_INTERACTION),
    ),
    SubIndexSpec(
        name="positioning",
        features=("funding_rate_lag1", "btc_long_short_ratio_lag1", FUNDING_LSR_INTERACTION),
    ),
    SubIndexSpec(
        name="flow",
        features=("etf_net_inflow_usd_lag1", "oi_change_pct_lag1", "volume_change_pct_lag1"),
    ),
    SubIndexSpec(
        name="vol",
        features=("vix_lag1", "volume_change_pct_lag1"),
    ),
)


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if "funding_rate_lag1" in result.columns and "btc_long_short_ratio_lag1" in result.columns:
        result[FUNDING_LSR_INTERACTION] = pd.to_numeric(
            result["funding_rate_lag1"], errors="coerce"
        ) * pd.to_numeric(result["btc_long_short_ratio_lag1"], errors="coerce")
    else:
        result[FUNDING_LSR_INTERACTION] = float("nan")

    if "news_sentiment_mean_lag1" in result.columns and "vix_lag1" in result.columns:
        result[SENTIMENT_VIX_INTERACTION] = pd.to_numeric(
            result["news_sentiment_mean_lag1"], errors="coerce"
        ) * pd.to_numeric(result["vix_lag1"], errors="coerce")
    else:
        result[SENTIMENT_VIX_INTERACTION] = float("nan")
    return result


def _empty_diagnostics(status: str, *, rows_total: int, features: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "available_features": features,
        "selected_features": [],
        "rows_total": rows_total,
        "rows_used": 0,
        "coverage": 0.0,
        "quality_status": "degraded",
        "quality_reasons": [status],
    }


def _minmax(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    if len(values) == 0:
        return values, float("nan"), float("nan")
    low = float(np.min(values))
    high = float(np.max(values))
    spread = high - low
    if spread <= 0:
        return np.full_like(values, 50.0, dtype=float), low, high
    return (values - low) / spread * 100.0, low, high


def _compute_one(
    df: pd.DataFrame, spec: SubIndexSpec
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    from sklearn.decomposition import PCA

    raw = pd.Series(np.nan, index=df.index, dtype=float)
    score = pd.Series(np.nan, index=df.index, dtype=float)
    available = [
        col
        for col in spec.features
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any()
    ]
    if len(available) < MIN_PCA_FEATURES:
        return (
            raw,
            score,
            _empty_diagnostics("insufficient_features", rows_total=len(df), features=available),
        )

    work = df[available].apply(pd.to_numeric, errors="coerce")
    clean = work.dropna()
    if len(clean) < MIN_PCA_ROWS:
        return (
            raw,
            score,
            _empty_diagnostics("insufficient_rows", rows_total=len(df), features=available),
        )

    scaler = make_scaler(spec.scaler_kind)
    scaled = scaler.fit_transform(clean.values)
    max_components = min(len(available), len(clean))
    n_components = spec.pca_components or 1
    n_components = max(1, min(n_components, max_components))
    pca = PCA(n_components=n_components)
    components = pca.fit_transform(scaled)
    pc1 = components[:, 0]
    score_values, pc1_min, pc1_max = _minmax(pc1)
    raw.loc[clean.index] = pc1
    score.loc[clean.index] = np.clip(score_values, 0, 100)
    coverage = round(len(clean) / len(df), 4) if len(df) else 0.0

    diagnostics = {
        "status": "ok",
        "available_features": available,
        "selected_features": available,
        "rows_total": len(df),
        "rows_used": len(clean),
        "coverage": coverage,
        "scaler_kind": spec.scaler_kind,
        "n_components": n_components,
        "explained_variance": float(np.sum(pca.explained_variance_ratio_)),
        "loadings": {available[i]: float(pca.components_[0, i]) for i in range(len(available))},
        "pc1_min": pc1_min,
        "pc1_max": pc1_max,
        "quality_status": "ok",
        "quality_reasons": [],
    }
    return raw, score, diagnostics


def compute_subindices(
    df: pd.DataFrame,
    specs: tuple[SubIndexSpec, ...] | None = None,
) -> pd.DataFrame:
    active_specs = specs if specs is not None else DEFAULT_SUBINDEX_SPECS
    result = add_interaction_features(df)
    diagnostics: dict[str, dict[str, Any]] = {}

    for spec in active_specs:
        raw, score, diag = _compute_one(result, spec)
        result[f"{spec.name}{SUBINDEX_RAW_SUFFIX}"] = raw
        result[f"{spec.name}{SUBINDEX_SCORE_SUFFIX}"] = score
        diagnostics[spec.name] = diag

    result.attrs = dict(df.attrs)
    result.attrs["subindex_diagnostics"] = diagnostics
    return result


__all__ = [
    "DEFAULT_SUBINDEX_SPECS",
    "FUNDING_LSR_INTERACTION",
    "SENTIMENT_VIX_INTERACTION",
    "SUBINDEX_RAW_SUFFIX",
    "SUBINDEX_SCORE_SUFFIX",
    "SubIndexBundle",
    "SubIndexSpec",
    "add_interaction_features",
    "compute_subindices",
]
