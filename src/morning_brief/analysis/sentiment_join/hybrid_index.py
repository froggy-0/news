from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.quality import quality_status_for_ratio
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

ScalerKind = Literal["standard", "robust"]


def make_scaler(kind: ScalerKind) -> Any:
    """PCA 전처리 스케일러 팩토리.

    - "standard": 기존 파이프라인. 평균 0, 분산 1로 정규화 (0-mean, unit-variance).
    - "robust": median · IQR 기반. 극단값에 둔감해 winsorize/mask 의존도를 낮춤.
    """
    from sklearn.preprocessing import RobustScaler, StandardScaler

    if kind == "standard":
        return StandardScaler()
    if kind == "robust":
        return RobustScaler()
    raise ValueError(f"Unknown scaler kind: {kind!r}")


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
    # VIX rolling median 대비 상대적 위치 (연속값 [-3,3]). vol_regime baseline의
    # adaptive threshold 정보를 PCA가 흡수할 수 있도록 추가. vix_lag1과 공선성이 있으나
    # VIF gate(threshold=10.0)가 자동 처리한다.
    "vix_regime_score_lag1",
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
FULL_EXPANSION_FEATURES = frozenset(
    {
        "btc_long_short_ratio_lag1",
        "etf_net_inflow_usd_lag1",
        "vix_lag1",
    }
)


@dataclass(frozen=True)
class IndexSpec:
    """하이브리드 지수 설정. full/core를 동일 코드 경로로 처리하기 위한 파라미터.

    scaler_kind 는 PCA 입력 스케일러를 선택한다. 기본 "standard" 는 기존 동작과 동등.
    실험 플랫폼에서 "robust" 로 교체해 outlier 영향도를 비교할 수 있다.
    """

    name: str  # "full" | "core"
    candidates: list[str]
    vif_threshold: float | None  # None이면 VIF gate skip
    scaler_kind: ScalerKind = "standard"


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
        "excluded_features": extra.get("excluded_features", []),
        "quality_status": extra.get("quality_status", "degraded"),
        "quality_reasons": extra.get("quality_reasons", []),
    }


def _candidate_exclusions(
    df: pd.DataFrame,
    candidates: list[str],
    feature_exclusion_reasons: dict[str, str] | None,
) -> list[dict[str, str]]:
    exclusions: list[dict[str, str]] = []
    for feature in candidates:
        if feature_exclusion_reasons and feature in feature_exclusion_reasons:
            exclusions.append({"feature": feature, "reason": feature_exclusion_reasons[feature]})
            continue
        if feature not in df.columns:
            exclusions.append({"feature": feature, "reason": "missing_column"})
            continue
        if not pd.to_numeric(df[feature], errors="coerce").notna().any():
            exclusions.append({"feature": feature, "reason": "all_nan_or_missing"})
    return exclusions


def _quality_summary(
    *,
    spec: IndexSpec,
    pca_status: str,
    coverage_ratio: float,
    selected_features: list[str],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if pca_status not in {"ok", "ok_pre_fitted"}:
        reasons.append(f"pca_status:{pca_status}")
    if quality_status_for_ratio(coverage_ratio) != "ok":
        reasons.append("coverage_below_threshold")
    if spec.name == "full" and not any(
        feature in selected_features for feature in FULL_EXPANSION_FEATURES
    ):
        reasons.append("missing_full_expansion_features")
    return ("ok" if not reasons else "degraded"), reasons


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
    *,
    feature_exclusion_reasons: dict[str, str] | None = None,
    pre_fitted_scaler: Any | None = None,
    pre_fitted_pca: Any | None = None,
    pre_fitted_pc1_min: float | None = None,
    pre_fitted_pc1_max: float | None = None,
    pre_fitted_features: list[str] | None = None,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    """단일 하이브리드 지수와 0~100 score를 계산합니다.

    pre-fitted 파라미터가 모두 제공되면 VIF 선택/scaler fit/PCA fit을 건너뛰고
    transform만 수행합니다 (Walk-Forward test 구간용).

    반환: (raw_pc1_series, score_series, diagnostics) — 두 Series 모두 df.index 기준.
    """
    from sklearn.decomposition import PCA

    raw_series = pd.Series(np.nan, index=df.index, dtype=float)
    score_series = pd.Series(np.nan, index=df.index, dtype=float)

    # pre-fitted 모드 판정
    _pre_fitted = (
        pre_fitted_scaler is not None
        and pre_fitted_pca is not None
        and pre_fitted_pc1_min is not None
        and pre_fitted_pc1_max is not None
        and pre_fitted_features is not None
    )

    if _pre_fitted:
        # ── pre-fitted 모드: train에서 선택된 feature 목록 사용, fit 건너뜀 ──
        selected = [f for f in pre_fitted_features if f in df.columns]  # type: ignore[union-attr]
        excluded_features = _candidate_exclusions(df, spec.candidates, feature_exclusion_reasons)
        if len(selected) < MIN_PCA_FEATURES:
            quality_status, quality_reasons = _quality_summary(
                spec=spec,
                pca_status="insufficient_features",
                coverage_ratio=0.0,
                selected_features=selected,
            )
            return (
                raw_series,
                score_series,
                _empty_diagnostics(
                    "insufficient_features",
                    available_features=selected,
                    coverage={"rows_total": total_rows, "rows_used": 0, "ratio": 0.0},
                    excluded_features=excluded_features,
                    quality_status=quality_status,
                    quality_reasons=quality_reasons,
                ),
            )

        work = df[selected].copy()
        for col in selected:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        clean_idx = work.dropna().index
        df_clean = work.loc[clean_idx]

        if len(df_clean) == 0:
            quality_status, quality_reasons = _quality_summary(
                spec=spec,
                pca_status="insufficient_rows",
                coverage_ratio=0.0,
                selected_features=selected,
            )
            return (
                raw_series,
                score_series,
                _empty_diagnostics(
                    "insufficient_rows",
                    rows=0,
                    coverage={"rows_total": total_rows, "rows_used": 0, "ratio": 0.0},
                    excluded_features=excluded_features,
                    quality_status=quality_status,
                    quality_reasons=quality_reasons,
                ),
            )

        # transform only
        assert pre_fitted_scaler is not None
        assert pre_fitted_pca is not None
        assert pre_fitted_pc1_min is not None
        assert pre_fitted_pc1_max is not None
        scaled = pre_fitted_scaler.transform(df_clean[selected].values)
        components = pre_fitted_pca.transform(scaled)

        # 부호 고정: train에서 이미 부호 보정된 PCA를 사용하므로 추가 보정 불필요
        raw_pc1 = components[:, 0]

        # train의 min/max로 0~100 스케일링 + clip
        spread = pre_fitted_pc1_max - pre_fitted_pc1_min
        if spread > 0:
            score_arr = (raw_pc1 - pre_fitted_pc1_min) / spread * 100.0
        else:
            score_arr = np.full_like(raw_pc1, 50.0, dtype=float)
        score_arr = np.clip(score_arr, 0, 100)

        raw_series.loc[clean_idx] = raw_pc1
        score_series.loc[clean_idx] = score_arr

        coverage_ratio = round(len(df_clean) / total_rows, 4) if total_rows else 0.0
        quality_status, quality_reasons = _quality_summary(
            spec=spec,
            pca_status="ok_pre_fitted",
            coverage_ratio=coverage_ratio,
            selected_features=selected,
        )
        diagnostics: dict[str, Any] = {
            "vif_diagnostics": [],
            "pca_summary": {
                "status": "ok_pre_fitted",
                "selected_features": selected,
                "pc1_min": pre_fitted_pc1_min,
                "pc1_max": pre_fitted_pc1_max,
                "score_scale_method": "minmax_0_100_pre_fitted",
            },
            "coverage": {
                "rows_total": total_rows,
                "rows_used": len(df_clean),
                "ratio": coverage_ratio,
            },
            "excluded_features": excluded_features,
            "quality_status": quality_status,
            "quality_reasons": quality_reasons,
        }
        return raw_series, score_series, diagnostics

    # ── 통상 모드 (기존 로직) ──

    # 전 행 NaN인 후보는 dropna에서 전체 행을 날리므로 사전에 제외합니다.
    # §4 3-4: VIX가 수집되지 않은 run에서도 full 지수가 계산되도록 하기 위한 방어.
    available = [
        col
        for col in spec.candidates
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any()
    ]
    excluded_features = _candidate_exclusions(df, spec.candidates, feature_exclusion_reasons)
    if len(available) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="PCA 입력 변수가 2개 미만입니다.",
            level=logging.WARNING,
            index=spec.name,
            available_features=available,
        )
        quality_status, quality_reasons = _quality_summary(
            spec=spec,
            pca_status="insufficient_features",
            coverage_ratio=0.0,
            selected_features=available,
        )
        return (
            raw_series,
            score_series,
            _empty_diagnostics(
                "insufficient_features",
                available_features=available,
                coverage={"rows_total": total_rows, "rows_used": 0, "ratio": 0.0},
                excluded_features=excluded_features,
                quality_status=quality_status,
                quality_reasons=quality_reasons,
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
        coverage_ratio = round(len(df_clean) / total_rows, 4) if total_rows else 0.0
        quality_status, quality_reasons = _quality_summary(
            spec=spec,
            pca_status="insufficient_rows",
            coverage_ratio=coverage_ratio,
            selected_features=available,
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
                    "ratio": coverage_ratio,
                },
                excluded_features=excluded_features,
                quality_status=quality_status,
                quality_reasons=quality_reasons,
            ),
        )

    selected, vif_diagnostics = _select_low_vif_features(
        df_clean, available, spec.vif_threshold, spec.name
    )
    removed_by_vif = [
        {"feature": feature, "reason": "vif_threshold"}
        for feature in available
        if feature not in selected
    ]
    excluded_features = excluded_features + removed_by_vif
    if len(selected) < MIN_PCA_FEATURES:
        log_structured(
            logger,
            event="stats.pca_insufficient_features",
            message="VIF 제거 후 PCA 입력 변수가 부족합니다.",
            level=logging.WARNING,
            index=spec.name,
            remaining_features=selected,
        )
        quality_status, quality_reasons = _quality_summary(
            spec=spec,
            pca_status="insufficient_features_after_vif",
            coverage_ratio=0.0,
            selected_features=selected,
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
                "excluded_features": excluded_features,
                "quality_status": quality_status,
                "quality_reasons": quality_reasons,
            },
        )

    scaler = make_scaler(spec.scaler_kind)
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
    coverage_ratio = round(len(df_clean) / total_rows, 4) if total_rows else 0.0
    quality_status, quality_reasons = _quality_summary(
        spec=spec,
        pca_status="ok",
        coverage_ratio=coverage_ratio,
        selected_features=selected,
    )

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
            "ratio": coverage_ratio,
        },
        "excluded_features": excluded_features,
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        # Walk-Forward에서 재사용할 fitted 객체 (JSON 직렬화 대상 아님)
        "_fitted_scaler": scaler,
        "_fitted_pca": pca_final,
    }
    return raw_series, score_series, diagnostics


def compute_hybrid_indices(
    df: pd.DataFrame,
    *,
    feature_exclusion_reasons: dict[str, str] | None = None,
    specs: tuple[IndexSpec, ...] | None = None,
) -> pd.DataFrame:
    """full / core 두 세트의 하이브리드 지수와 0~100 score를 계산합니다.

    생성 컬럼:
        - full_hybrid_index, full_hybrid_index_score
        - core_hybrid_index, core_hybrid_index_score

    attrs["hybrid_index_diagnostics"]: {
        "full": {vif_diagnostics, pca_summary, coverage},
        "core": {...},
    }

    Args:
        specs: 커스텀 IndexSpec 튜플(예: scaler_kind="robust" 주입용). None 이면 기본 INDEX_SPECS.
    """
    active_specs = specs if specs is not None else INDEX_SPECS

    result = df.copy()
    result.attrs = dict(df.attrs)
    total_rows = len(df)
    diagnostics: dict[str, dict[str, Any]] = {}

    for spec in active_specs:
        raw_series, score_series, index_diag = _compute_single_index(
            df,
            spec,
            total_rows,
            feature_exclusion_reasons=feature_exclusion_reasons,
        )
        result[f"{spec.name}_hybrid_index"] = raw_series
        result[f"{spec.name}_hybrid_index_score"] = score_series
        diagnostics[spec.name] = index_diag

    # attrs에는 JSON 직렬화 가능한 키만 저장 (_fitted_* 객체 제외)
    serializable_diagnostics: dict[str, dict[str, Any]] = {}
    for name, diag in diagnostics.items():
        serializable_diagnostics[name] = {
            k: v for k, v in diag.items() if not k.startswith("_fitted_")
        }
    result.attrs["hybrid_index_diagnostics"] = serializable_diagnostics
    return result


def compute_today_score_oos(
    df: pd.DataFrame,
    spec: IndexSpec,
    *,
    feature_exclusion_reasons: dict[str, Any] | None = None,
) -> float | None:
    """오늘(마지막 행)의 OOS 점수를 expanding window로 반환한다.

    train = df[:-1] (전체 과거), test = df[-1:] (오늘).
    1. train으로 scaler/PCA/pc1_min-max fit (normal mode)
    2. train에서 추출한 fitted 객체로 test를 pre-fitted mode transform
    3. 점수 반환 — 룩어헤드 없는 오늘의 시황 점수.

    데이터 부족 또는 PCA 실패 시 None 반환 (파이프라인 중단 없음).
    """
    if len(df) < MIN_PCA_ROWS + 1:
        return None

    train = df.iloc[:-1].copy()
    test = df.iloc[-1:].copy()

    _, _, train_diag = _compute_single_index(
        train,
        spec,
        len(train),
        feature_exclusion_reasons=feature_exclusion_reasons,
    )
    pca_summary = train_diag.get("pca_summary") or {}
    if pca_summary.get("status") not in {"ok", "ok_pre_fitted"}:
        return None

    scaler = train_diag.get("_fitted_scaler")
    pca = train_diag.get("_fitted_pca")
    pc1_min = pca_summary.get("pc1_min")
    pc1_max = pca_summary.get("pc1_max")
    features: list[str] | None = pca_summary.get("selected_features")

    if None in (scaler, pca, pc1_min, pc1_max, features):
        return None

    _, score_series, _ = _compute_single_index(
        test,
        spec,
        len(test),
        feature_exclusion_reasons=feature_exclusion_reasons,
        pre_fitted_scaler=scaler,
        pre_fitted_pca=pca,
        pre_fitted_pc1_min=float(pc1_min),
        pre_fitted_pc1_max=float(pc1_max),
        pre_fitted_features=features,
    )
    valid = score_series.dropna()
    return round(float(valid.iloc[-1]), 1) if len(valid) > 0 else None


__all__ = [
    "HYBRID_FEATURE_CANDIDATES_CORE",
    "HYBRID_FEATURE_CANDIDATES_FULL",
    "HYBRID_FEATURE_SCHEMA_VERSION",
    "HYBRID_SIGN_ANCHOR",
    "INDEX_SPECS",
    "IndexSpec",
    "ScalerKind",
    "_compute_single_index",
    "compute_hybrid_indices",
    "compute_today_score_oos",
    "make_scaler",
]
