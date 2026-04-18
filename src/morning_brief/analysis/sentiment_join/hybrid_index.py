from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# §4: PCA 하이브리드 지수는 full / core 두 세트로 운영합니다.
# - full: 기존 확장 feature set + VIF gate로 공선성 자동 제거
# - core: 결측 내성이 높은 핵심 4개 feature, VIF gate skip (큐레이션된 세트)
HYBRID_FEATURE_CANDIDATES_FULL = [
    "news_sentiment_mean_lag1",
    "fng_value_lag1",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",
    "etf_net_inflow_usd_lag1",
    "volume_change_pct_lag1",
    # §4 3-4: VIX는 optional. 수집 실패 시 전 행 NaN이므로 compute_hybrid_indices의
    # dropna 단계에서 자동 제외됩니다 (VIF gate 없이도 안전).
    "vix_lag1",
]
HYBRID_FEATURE_CANDIDATES_CORE = [
    "news_sentiment_mean_lag1",
    "fng_value_lag1",
    "funding_rate_lag1",
    "volume_change_pct_lag1",
]
HYBRID_FEATURE_SCHEMA_VERSION = "v4"
# v1~v3: 단일 hybrid_index
# v4: full/core 이중 지수 + 0~100 score 분리 저장. hybrid_index 컬럼 삭제.
HYBRID_SIGN_ANCHOR = "fng_value_lag1"
VIF_THRESHOLD_FULL = 10.0
MIN_PCA_FEATURES = 2
MIN_PCA_ROWS = 10
TARGET_EXPLAINED_VARIANCE = 0.80


@dataclass(frozen=True)
class IndexSpec:
    """하이브리드 지수 설정. full/core를 동일 코드 경로로 처리하기 위한 파라미터."""

    name: str  # "full" | "core"
    candidates: list[str]
    vif_threshold: float | None  # None이면 VIF gate skip


INDEX_SPECS: tuple[IndexSpec, ...] = (
    IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, VIF_THRESHOLD_FULL),
    IndexSpec("core", HYBRID_FEATURE_CANDIDATES_CORE, None),
)


def _compute_vif(matrix: np.ndarray, feature_names: list[str]) -> list[dict[str, Any]]:
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    records = []
    for idx, name in enumerate(feature_names):
        try:
            vif_value = variance_inflation_factor(matrix, idx)
        except Exception:
            vif_value = float("nan")
        records.append({"feature": name, "vif": float(vif_value)})
    return records


def _select_low_vif_features(
    df_clean: pd.DataFrame,
    feature_names: list[str],
    threshold: float | None,
    index_name: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """VIF를 계산하고 threshold가 주어지면 반복 제거합니다. threshold=None이면 진단만 남깁니다."""
    from sklearn.preprocessing import StandardScaler

    remaining = list(feature_names)
    latest_vif_records: list[dict[str, Any]] = []
    while len(remaining) >= MIN_PCA_FEATURES:
        matrix = StandardScaler().fit_transform(df_clean[remaining].values)
        vif_records = _compute_vif(matrix, remaining)
        latest_vif_records = vif_records
        log_structured(
            logger,
            event="stats.vif_diagnostics",
            message="VIF 진단 결과입니다.",
            index=index_name,
            features=vif_records,
        )
        if threshold is None:
            break
        high_vif = [(r["feature"], r["vif"]) for r in vif_records if r["vif"] >= threshold]
        if not high_vif:
            break
        worst = max(high_vif, key=lambda x: x[1])
        log_structured(
            logger,
            event="stats.vif_feature_removed",
            message="VIF 임계값을 초과한 변수를 PCA 입력에서 제거합니다.",
            level=logging.WARNING,
            index=index_name,
            feature=worst[0],
            vif=worst[1],
            threshold=threshold,
        )
        remaining.remove(worst[0])
    return remaining, latest_vif_records


def _empty_diagnostics(status: str, **extra: Any) -> dict[str, Any]:
    return {
        "vif_diagnostics": [],
        "pca_summary": {"status": status, **extra},
        "coverage": extra.get("coverage", {}),
    }


def _minmax_score(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    """raw PC1 값을 0~100으로 min-max 스케일링합니다. 상수 벡터는 50으로 고정."""
    pc1_min = float(values.min())
    pc1_max = float(values.max())
    spread = pc1_max - pc1_min
    if spread > 0:
        score = (values - pc1_min) / spread * 100.0
    else:
        score = np.full_like(values, 50.0, dtype=float)
    return score, pc1_min, pc1_max


def _compute_single_index(
    df: pd.DataFrame,
    spec: IndexSpec,
    total_rows: int,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    """단일 하이브리드 지수와 0~100 score를 계산합니다.

    반환: (raw_pc1_series, score_series, diagnostics) — 두 Series 모두 df.index 기준.
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    raw_series = pd.Series(np.nan, index=df.index, dtype=float)
    score_series = pd.Series(np.nan, index=df.index, dtype=float)

    # 전 행 NaN인 후보는 dropna에서 전체 행을 날리므로 사전에 제외합니다.
    # §4 3-4: VIX가 수집되지 않은 run에서도 full 지수가 계산되도록 하기 위한 방어.
    available = [
        col
        for col in spec.candidates
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any()
    ]
    if len(available) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="PCA 입력 변수가 2개 미만입니다.",
            level=logging.WARNING,
            index=spec.name,
            available_features=available,
        )
        return (
            raw_series,
            score_series,
            _empty_diagnostics(
                "insufficient_features",
                available_features=available,
                coverage={"rows_total": total_rows, "rows_used": 0, "ratio": 0.0},
            ),
        )

    work = df[available].copy()
    for col in available:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    clean_idx = work.dropna().index
    df_clean = work.loc[clean_idx]

    if len(df_clean) < MIN_PCA_ROWS:
        log_structured(
            logger,
            event="stats.pca_insufficient_rows",
            message="PCA 실행에 필요한 최소 행 수를 충족하지 못합니다.",
            level=logging.WARNING,
            index=spec.name,
            rows=len(df_clean),
            min_required=MIN_PCA_ROWS,
        )
        return (
            raw_series,
            score_series,
            _empty_diagnostics(
                "insufficient_rows",
                rows=len(df_clean),
                coverage={
                    "rows_total": total_rows,
                    "rows_used": len(df_clean),
                    "ratio": round(len(df_clean) / total_rows, 4) if total_rows else 0.0,
                },
            ),
        )

    selected, vif_diagnostics = _select_low_vif_features(
        df_clean, available, spec.vif_threshold, spec.name
    )
    if len(selected) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="VIF 제거 후 PCA 입력 변수가 부족합니다.",
            level=logging.WARNING,
            index=spec.name,
            remaining_features=selected,
        )
        return (
            raw_series,
            score_series,
            {
                "vif_diagnostics": vif_diagnostics,
                "pca_summary": {
                    "status": "insufficient_features_after_vif",
                    "remaining_features": selected,
                },
                "coverage": {
                    "rows_total": total_rows,
                    "rows_used": 0,
                    "ratio": 0.0,
                },
            },
        )

    scaler = StandardScaler()
    scaled = scaler.fit_transform(df_clean[selected].values)

    pca_full = PCA()
    pca_full.fit(scaled)
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, TARGET_EXPLAINED_VARIANCE) + 1)
    n_components = min(n_components, len(selected))

    pca_final = PCA(n_components=n_components)
    components = pca_final.fit_transform(scaled)

    loadings = {selected[i]: float(pca_final.components_[0, i]) for i in range(len(selected))}

    # §5.2: HYBRID_SIGN_ANCHOR가 선택된 feature에 포함되어 있으면 loading이 양수가 되도록 부호 고정.
    # full / core 모두 같은 anchor(fng_value_lag1)를 사용해 두 지수의 방향성을 통일합니다.
    if HYBRID_SIGN_ANCHOR in selected:
        anchor_idx = selected.index(HYBRID_SIGN_ANCHOR)
        if pca_final.components_[0, anchor_idx] < 0:
            components[:, 0] = -components[:, 0]
            pca_final.components_[0] = -pca_final.components_[0]
            loadings = {k: -v for k, v in loadings.items()}

    raw_pc1 = components[:, 0]
    score, pc1_min, pc1_max = _minmax_score(raw_pc1)

    raw_series.loc[clean_idx] = raw_pc1
    score_series.loc[clean_idx] = score

    explained_variance = float(cumvar[n_components - 1])

    log_structured(
        logger,
        event="stats.pca_complete",
        message="PCA를 완료하고 하이브리드 지수를 생성했습니다.",
        index=spec.name,
        n_components=n_components,
        explained_variance=explained_variance,
        features=selected,
        loadings=loadings,
        feature_schema_version=HYBRID_FEATURE_SCHEMA_VERSION,
        rows_used=len(df_clean),
    )

    diagnostics = {
        "vif_diagnostics": vif_diagnostics,
        "pca_summary": {
            "status": "ok",
            "selected_features": selected,
            "n_components": n_components,
            "explained_variance": explained_variance,
            "loadings": loadings,
            "feature_schema_version": HYBRID_FEATURE_SCHEMA_VERSION,
            "pc1_min": pc1_min,
            "pc1_max": pc1_max,
            "score_scale_method": "minmax_0_100",
        },
        "coverage": {
            "rows_total": total_rows,
            "rows_used": len(df_clean),
            "ratio": round(len(df_clean) / total_rows, 4) if total_rows else 0.0,
        },
    }
    return raw_series, score_series, diagnostics


def compute_hybrid_indices(df: pd.DataFrame) -> pd.DataFrame:
    """full / core 두 세트의 하이브리드 지수와 0~100 score를 계산합니다.

    생성 컬럼:
        - full_hybrid_index, full_hybrid_index_score
        - core_hybrid_index, core_hybrid_index_score

    attrs["hybrid_index_diagnostics"]: {
        "full": {vif_diagnostics, pca_summary, coverage},
        "core": {...},
    }
    """
    result = df.copy()
    result.attrs = dict(df.attrs)
    total_rows = len(df)
    diagnostics: dict[str, dict[str, Any]] = {}

    for spec in INDEX_SPECS:
        raw_series, score_series, index_diag = _compute_single_index(df, spec, total_rows)
        result[f"{spec.name}_hybrid_index"] = raw_series
        result[f"{spec.name}_hybrid_index_score"] = score_series
        diagnostics[spec.name] = index_diag

    result.attrs["hybrid_index_diagnostics"] = diagnostics
    return result


__all__ = [
    "HYBRID_FEATURE_CANDIDATES_CORE",
    "HYBRID_FEATURE_CANDIDATES_FULL",
    "HYBRID_FEATURE_SCHEMA_VERSION",
    "HYBRID_SIGN_ANCHOR",
    "INDEX_SPECS",
    "IndexSpec",
    "compute_hybrid_indices",
]
