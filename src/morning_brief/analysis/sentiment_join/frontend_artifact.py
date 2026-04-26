"""프론트엔드 소비용 분석 아티팩트 추출 모듈.

Master Parquet 메타데이터의 sentiment_join_stats JSON을
대시보드가 읽기 쉬운 camelCase 블록으로 변환한다.
통계 계산은 수행하지 않으며, 원본 metadata는 rawStats에 보존해 정보 손실을 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from morning_brief.analysis.sentiment_join.statistical_tests import GRANGER_PAIRS_REVERSE

ARTIFACT_SCHEMA_VERSION = "sentiment-insight-v2"

# 역방향 페어를 set으로 변환해 O(1) 조회
_REVERSE_PAIR_SET: frozenset[tuple[str, str]] = frozenset(GRANGER_PAIRS_REVERSE)

# 아티팩트에 허용된 granger result 키 (화이트리스트)
_GRANGER_RESULT_ALLOWED_KEYS = {
    "predictor",
    "target",
    "direction",
    "lag",
    "pvalue",
    "pvalueAdjusted",
    "significant",
    "optimalLag",
}

# PCA index 허용 키 (화이트리스트)
_PCA_INDEX_ALLOWED_KEYS = {
    "status",
    "selectedFeatures",
    "nComponents",
    "explainedVariance",
    "loadings",
    "excludedFeatures",
    "coverageRatio",
    "qualityStatus",
    "qualityReasons",
}


def _to_direction(predictor: str, target: str) -> str:
    return "reverse" if (predictor, target) in _REVERSE_PAIR_SET else "forward"


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result
    return None


def _json_safe(value: Any) -> Any:
    """JSON으로 안전하게 직렬화 가능한 값만 재귀적으로 보존한다."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _build_granger_results(raw_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """granger_results 원본 배열에서 필요한 필드만 추출하고 유도 필드를 계산한다.

    optimalLag: 같은 (predictor, target, direction) 그룹에서
    pvalue_adjusted 최솟값인 lag에만 True. 동률 시 작은 lag 우선.
    """
    # 1단계: 필드 추출 + direction 계산
    extracted: list[dict[str, Any]] = []
    for row in raw_results:
        predictor = str(row.get("predictor", ""))
        target = str(row.get("target", ""))
        lag_raw = row.get("lag")
        pvalue_raw = row.get("pvalue")
        pvalue_adjusted_raw = row.get("pvalue_adjusted")
        significant_raw = row.get("significant")

        if not predictor or not target or lag_raw is None:
            continue

        extracted.append(
            {
                "predictor": predictor,
                "target": target,
                "direction": _to_direction(predictor, target),
                "lag": int(lag_raw),
                "pvalue": float(pvalue_raw) if pvalue_raw is not None else None,
                "pvalueAdjusted": float(pvalue_adjusted_raw)
                if pvalue_adjusted_raw is not None
                else None,
                "significant": bool(significant_raw) if significant_raw is not None else False,
                "optimalLag": False,  # 2단계에서 설정
            }
        )

    # 2단계: optimalLag 설정 — 그룹별 pvalueAdjusted 최솟값 lag에 True
    # 그룹 키: (predictor, target, direction)
    GroupKey = tuple[str, str, str]
    group_best: dict[GroupKey, tuple[float, int]] = {}  # key → (best_pvalue_adj, best_lag)

    for item in extracted:
        pv = item["pvalueAdjusted"]
        if pv is None:
            continue
        key: GroupKey = (item["predictor"], item["target"], item["direction"])
        current_best = group_best.get(key)
        if (
            current_best is None
            or pv < current_best[0]
            or (pv == current_best[0] and item["lag"] < current_best[1])
        ):
            group_best[key] = (pv, item["lag"])

    for item in extracted:
        key = (item["predictor"], item["target"], item["direction"])
        best = group_best.get(key)
        if best is not None and item["lag"] == best[1] and item["pvalueAdjusted"] == best[0]:
            item["optimalLag"] = True

    return extracted


def _build_granger_skips(raw_skips: list[Any]) -> list[dict[str, Any]]:
    skips: list[dict[str, Any]] = []
    for row in raw_skips:
        if not isinstance(row, dict):
            continue
        predictor = str(row.get("predictor", ""))
        target = str(row.get("target", ""))
        skips.append(
            {
                "predictor": predictor,
                "target": target,
                "direction": str(row.get("direction") or _to_direction(predictor, target)),
                "reason": str(row.get("reason", "unknown")),
                "rowsBeforeStationarity": _as_int(row.get("rows_before_stationarity")),
                "rowsAfterStationarity": _as_int(row.get("rows_after_stationarity")),
                "message": str(row.get("message", "")),
            }
        )
    return skips


def _build_pca_index(raw_index: dict[str, Any]) -> dict[str, Any]:
    """hybrid_indices.{full|core} 원본에서 pca_summary + coverage + quality만 추출."""
    pca_summary = raw_index.get("pca_summary") or {}
    coverage = raw_index.get("coverage") or {}

    status = str(pca_summary.get("status", "unknown"))
    selected_features: list[str] = list(pca_summary.get("selected_features") or [])
    n_components = int(pca_summary.get("n_components", 0))
    explained_variance = float(pca_summary.get("explained_variance", 0.0))
    loadings_raw = pca_summary.get("loadings") or {}
    loadings: dict[str, float] = {k: float(v) for k, v in loadings_raw.items()}

    # excluded_features: list[dict] or list[str] 두 형태 모두 처리
    excluded_raw = raw_index.get("excluded_features") or []
    excluded: list[dict[str, str]] = []
    for item in excluded_raw:
        if isinstance(item, dict):
            excluded.append(
                {
                    "feature": str(item.get("feature", "")),
                    "reason": str(item.get("reason", "")),
                }
            )
        elif isinstance(item, str):
            excluded.append({"feature": item, "reason": ""})

    coverage_ratio = float(coverage.get("ratio", 0.0))
    quality_status = str(raw_index.get("quality_status", "degraded"))
    quality_reasons: list[str] = list(raw_index.get("quality_reasons") or [])

    return {
        "status": status,
        "selectedFeatures": selected_features,
        "nComponents": n_components,
        "explainedVariance": explained_variance,
        "loadings": loadings,
        "excludedFeatures": excluded,
        "coverageRatio": coverage_ratio,
        "qualityStatus": quality_status,
        "qualityReasons": quality_reasons,
    }


def _build_summary(
    payload: dict[str, Any],
    *,
    granger_results: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_metrics = _as_record(payload.get("baseline_metrics"))
    horizon_metrics = _as_record(payload.get("horizon_metrics"))
    target_diagnostics = _as_record(payload.get("target_diagnostics"))
    structured_sources = _as_record(payload.get("structured_sources"))

    return {
        "rowsBeforeOutlierFilter": _as_int(payload.get("rows_before_outlier_filter")),
        "rowsAfterOutlierFilter": _as_int(payload.get("rows_after_outlier_filter")),
        "outlierFilteredCount": _as_int(payload.get("outlier_filtered_count")),
        "outlierFilteredRatio": _as_float(payload.get("outlier_filtered_ratio")),
        "grangerEligibleRows": _as_int(payload.get("granger_eligible_rows")),
        "grangerExecuted": bool(payload.get("granger_executed", False)),
        "significantGrangerCount": sum(1 for row in granger_results if row.get("significant")),
        "grangerTestCount": len(granger_results),
        "alphaCandidateCount": len(_as_list(payload.get("hit_rates"))),
        "baselineHorizonCount": len(baseline_metrics),
        "horizonMetricCount": len(horizon_metrics),
        "targetCount": len(target_diagnostics),
        "sourceCount": len(structured_sources),
    }


def _build_data_quality(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "rows": {
            "beforeOutlierFilter": _as_int(payload.get("rows_before_outlier_filter")),
            "afterOutlierFilter": _as_int(payload.get("rows_after_outlier_filter")),
            "outlierFilteredCount": _as_int(payload.get("outlier_filtered_count")),
            "outlierFilteredRatio": _as_float(payload.get("outlier_filtered_ratio")),
        },
        "ffillBreakdown": _json_safe(_as_record(payload.get("ffill_breakdown"))),
        "structuredSources": _json_safe(_as_record(payload.get("structured_sources"))),
        "exclusionCounts": _json_safe(_as_record(payload.get("exclusion_counts"))),
    }


def _build_alpha(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "hitRates": _json_safe(_as_list(payload.get("hit_rates"))),
        "correlations": _json_safe(_as_list(payload.get("correlations"))),
        "backtest": _json_safe(_as_list(payload.get("backtest"))),
        "walkForward": _json_safe(_as_record(payload.get("walk_forward"))),
        "baselineMetrics": _json_safe(_as_record(payload.get("baseline_metrics"))),
        "horizonMetrics": _json_safe(_as_record(payload.get("horizon_metrics"))),
        "walkForwardHorizons": _json_safe(_as_record(payload.get("walk_forward_horizons"))),
    }


def _build_targets(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "diagnostics": _json_safe(_as_record(payload.get("target_diagnostics"))),
    }


def _build_stationarity(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "adf": _json_safe(_as_record(payload.get("adf"))),
    }


def build_frontend_artifact(
    *,
    stats_metadata_bytes: bytes,
    reference_date: str,
) -> dict[str, Any]:
    """sentiment_join_stats bytes에서 프론트 소비용 아티팩트 dict를 생성한다.

    Args:
        stats_metadata_bytes: build_stats_metadata_payload()가 반환한 bytes
        reference_date: 분석 기준일 (YYYY-MM-DD)

    Returns:
        프론트 전용 아티팩트 dict. 허용되지 않은 키는 포함하지 않는다.
    """
    payload: dict[str, Any] = json.loads(stats_metadata_bytes.decode("utf-8"))

    run_id = str(payload.get("run_id", ""))
    generated_at_utc = str(payload.get("generated_at_utc", ""))
    granger_executed = bool(payload.get("granger_executed", False))

    # Granger
    raw_results: list[dict[str, Any]] = []
    if isinstance(payload.get("granger_results"), list):
        raw_results = [row for row in payload["granger_results"] if isinstance(row, dict)]
    granger_results = _build_granger_results(raw_results) if granger_executed else []
    granger_skips = _build_granger_skips(_as_list(payload.get("granger_skips")))
    granger_skip_summary = _json_safe(_as_record(payload.get("granger_skip_summary")))

    correction_raw = _as_record(payload.get("granger_correction"))
    granger_correction = {
        "method": str(correction_raw.get("correction_method", "fdr_bh")),
        "nTests": int(correction_raw.get("n_tests", 0)),
    }

    # PCA
    hybrid_indices = _as_record(payload.get("hybrid_indices"))
    full_raw = _as_record(hybrid_indices.get("full"))
    core_raw = _as_record(hybrid_indices.get("core"))

    return {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "generatedAtUtc": generated_at_utc,
        "referenceDate": reference_date,
        "runId": run_id,
        "summary": _build_summary(payload, granger_results=granger_results),
        "dataQuality": _build_data_quality(payload),
        "granger": {
            "executed": granger_executed,
            "correction": granger_correction,
            "eligibleRows": _as_int(payload.get("granger_eligible_rows")),
            "results": granger_results,
            "skips": granger_skips,
            "skipSummary": granger_skip_summary,
        },
        "pca": {
            "full": _build_pca_index(full_raw),
            "core": _build_pca_index(core_raw),
        },
        "alpha": _build_alpha(payload),
        "targets": _build_targets(payload),
        "stationarity": _build_stationarity(payload),
        "rawStats": _json_safe(payload),
    }


def should_skip_artifact(artifact: dict[str, Any]) -> bool:
    """full과 core 양쪽 qualityStatus가 모두 'critical'일 때만 True."""
    pca = artifact.get("pca") or {}
    full_status = (pca.get("full") or {}).get("qualityStatus", "")
    core_status = (pca.get("core") or {}).get("qualityStatus", "")
    return full_status == "critical" and core_status == "critical"


def write_frontend_artifact(
    output_dir: Path,
    artifact: dict[str, Any],
    run_date: str,
) -> tuple[Path, Path]:
    """아티팩트를 latest.json과 {run_date}.json 두 파일로 저장한다.

    Args:
        output_dir: 출력 디렉토리 (data/sentiment_join/)
        artifact: build_frontend_artifact()의 반환값
        run_date: YYYYMMDD 형식 날짜 문자열

    Returns:
        (latest_path, dated_path) 튜플
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(artifact, ensure_ascii=False, indent=2, default=str)

    latest_path = output_dir / "latest.json"
    dated_path = output_dir / f"{run_date}.json"

    latest_path.write_text(content, encoding="utf-8")
    dated_path.write_text(content, encoding="utf-8")

    return latest_path, dated_path


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "build_frontend_artifact",
    "should_skip_artifact",
    "write_frontend_artifact",
]
