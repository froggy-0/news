from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from morning_brief.analysis.sentiment_join.outlier_policy import (
    NON_MASK_COLS,
    OutlierPolicyFactory,
    PolicyName,
)
from morning_brief.analysis.sentiment_join.subindices import compute_subindices

FEATURE_STORE_RULES_VERSION = "feature_store_v1"


@dataclass(frozen=True)
class FeatureStoreBundle:
    raw: pd.DataFrame
    clean: pd.DataFrame
    model: pd.DataFrame
    manifest: dict[str, Any]
    output_dir: Path | None = None


def _default_cache_key(df: pd.DataFrame, *, rules_version: str) -> str:
    cols = ",".join(df.columns)
    seed = f"{rules_version}:{len(df)}:{cols}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


def _model_columns(df: pd.DataFrame) -> list[str]:
    prefixes = (
        "btc_fwd_",
        "btc_large_move",
        "full_hybrid",
        "core_hybrid",
    )
    suffixes = ("_lag1", "_subindex", "_subindex_score", "_interaction")
    keep = ["date", "btc_log_return", "btc_direction_label"]
    for col in df.columns:
        if col in keep:
            continue
        if col.startswith(prefixes) or col.endswith(suffixes):
            keep.append(col)
    return [col for col in keep if col in df.columns]


def _lineage_from(df: pd.DataFrame) -> dict[str, Any]:
    lineage_cols = [col for col in df.columns if col.endswith("_source")]
    return {
        col: sorted(str(v) for v in df[col].dropna().unique())
        for col in lineage_cols
        if col in df.columns
    }


def _write_snapshot(bundle: FeatureStoreBundle, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.raw.to_parquet(output_dir / "features_raw.parquet", index=False)
    bundle.clean.to_parquet(output_dir / "features_clean.parquet", index=False)
    bundle.model.to_parquet(output_dir / "features_model.parquet", index=False)
    (output_dir / "manifest.json").write_text(
        json.dumps(bundle.manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def build_feature_store(
    df: pd.DataFrame,
    *,
    cache_key: str | None = None,
    output_dir: Path | None = None,
    outlier_policy: PolicyName = "none",
) -> FeatureStoreBundle:
    raw = df.copy()
    key = cache_key or _default_cache_key(raw, rules_version=FEATURE_STORE_RULES_VERSION)
    mask_cols = [col for col in raw.columns if col not in NON_MASK_COLS]
    outlier_result = OutlierPolicyFactory.create(outlier_policy).apply(raw, mask_cols)
    clean = outlier_result.df
    model_base = compute_subindices(clean)
    model = model_base[_model_columns(model_base)].copy()
    manifest = {
        "rules_version": FEATURE_STORE_RULES_VERSION,
        "cache_key": key,
        "outlier_policy": outlier_policy,
        "rows": {"raw": len(raw), "clean": len(clean), "model": len(model)},
        "lineage": _lineage_from(raw),
        "snapshots": {
            "raw": "features_raw.parquet",
            "clean": "features_clean.parquet",
            "model": "features_model.parquet",
        },
    }
    bundle = FeatureStoreBundle(raw=raw, clean=clean, model=model, manifest=manifest)
    if output_dir is not None:
        _write_snapshot(bundle, output_dir)
        bundle = FeatureStoreBundle(
            raw=raw, clean=clean, model=model, manifest=manifest, output_dir=output_dir
        )
    return bundle


__all__ = [
    "FEATURE_STORE_RULES_VERSION",
    "FeatureStoreBundle",
    "build_feature_store",
]
