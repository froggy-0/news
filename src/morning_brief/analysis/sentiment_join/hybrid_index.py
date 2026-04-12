from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

# Req 13: PCA 입력 후보 변수들 (DataFrame에 있는 것만 사용)
HYBRID_FEATURE_CANDIDATES = [
    "news_sentiment_mean",
    "fng_value",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",
    "etf_net_inflow_usd_lag1",
]
VIF_THRESHOLD = 10.0
MIN_PCA_FEATURES = 2
MIN_PCA_ROWS = 10
TARGET_EXPLAINED_VARIANCE = 0.80


def _compute_vif(matrix: np.ndarray, feature_names: list[str]) -> list[dict[str, Any]]:
    """Req 13.1: 각 변수의 VIF를 계산합니다."""
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
) -> tuple[list[str], list[dict[str, Any]]]:
    """Req 13.2: VIF >= VIF_THRESHOLD인 변수를 반복 제거합니다."""
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
            features=vif_records,
        )
        high_vif = [(r["feature"], r["vif"]) for r in vif_records if r["vif"] >= VIF_THRESHOLD]
        if not high_vif:
            break
        # 가장 높은 VIF 변수 제거
        worst = max(high_vif, key=lambda x: x[1])
        log_structured(
            logger,
            event="stats.vif_feature_removed",
            message="VIF 임계값을 초과한 변수를 PCA 입력에서 제거합니다.",
            level=logging.WARNING,
            feature=worst[0],
            vif=worst[1],
            threshold=VIF_THRESHOLD,
        )
        remaining.remove(worst[0])
    return remaining, latest_vif_records


def compute_hybrid_index(df: pd.DataFrame) -> pd.DataFrame:
    """Req 13: VIF 진단 후 PCA를 적용해 hybrid_index 컬럼을 생성합니다.

    - VIF >= 10인 변수를 제거한 뒤 StandardScaler + PCA를 실행합니다.
    - 누적 설명 분산 >= 80%를 달성하는 최소 주성분 수를 자동 선택합니다.
    - 첫 번째 주성분을 hybrid_index로 저장합니다.
    - PCA 입력 변수가 2개 미만이거나 데이터가 부족하면 NaN으로 채웁니다.
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    result = df.copy()
    result.attrs = dict(df.attrs)
    result["hybrid_index"] = np.nan

    # 사용 가능한 후보 변수 선별
    available = [col for col in HYBRID_FEATURE_CANDIDATES if col in df.columns]
    if len(available) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="PCA 입력 변수가 2개 미만이어서 hybrid_index를 생성할 수 없습니다.",
            level=logging.WARNING,
            available_features=available,
        )
        result.attrs["hybrid_index_diagnostics"] = {
            "vif_diagnostics": [],
            "pca_summary": {"status": "insufficient_features", "available_features": available},
        }
        return result

    # 수치형 변환 및 결측 제거
    work = df[available].copy()
    for col in available:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    clean_idx = work.dropna().index
    df_clean = work.loc[clean_idx]

    if len(df_clean) < MIN_PCA_ROWS:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="PCA 실행에 필요한 최소 행 수를 충족하지 못합니다.",
            level=logging.WARNING,
            rows=len(df_clean),
            min_required=MIN_PCA_ROWS,
        )
        result.attrs["hybrid_index_diagnostics"] = {
            "vif_diagnostics": [],
            "pca_summary": {"status": "insufficient_rows", "rows": len(df_clean)},
        }
        return result

    # VIF 기반 변수 선택
    selected, vif_diagnostics = _select_low_vif_features(df_clean, available)
    if len(selected) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="VIF 제거 후 PCA 입력 변수가 2개 미만이 되었습니다.",
            level=logging.WARNING,
            remaining_features=selected,
        )
        result.attrs["hybrid_index_diagnostics"] = {
            "vif_diagnostics": vif_diagnostics,
            "pca_summary": {
                "status": "insufficient_features_after_vif",
                "remaining_features": selected,
            },
        }
        return result

    df_selected = df_clean[selected]
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df_selected.values)

    # 전체 PCA로 누적 분산 >= 80% 달성하는 주성분 수 결정
    pca_full = PCA()
    pca_full.fit(scaled)
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, TARGET_EXPLAINED_VARIANCE) + 1)
    n_components = min(n_components, len(selected))

    pca_final = PCA(n_components=n_components)
    components = pca_final.fit_transform(scaled)

    # 변수 기여 가중치 기록
    loadings = {selected[i]: float(pca_final.components_[0, i]) for i in range(len(selected))}
    log_structured(
        logger,
        event="stats.pca_complete",
        message="PCA를 완료하고 hybrid_index를 생성했습니다.",
        n_components=n_components,
        explained_variance=float(cumvar[n_components - 1]),
        features=selected,
        loadings=loadings,
    )

    result.loc[clean_idx, "hybrid_index"] = components[:, 0]
    result.attrs["hybrid_index_diagnostics"] = {
        "vif_diagnostics": vif_diagnostics,
        "pca_summary": {
            "status": "ok",
            "selected_features": selected,
            "n_components": n_components,
            "explained_variance": float(cumvar[n_components - 1]),
            "loadings": loadings,
        },
    }
    return result


__all__ = ["compute_hybrid_index"]
