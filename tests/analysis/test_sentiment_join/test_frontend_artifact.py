"""frontend_artifact 모듈 단위 테스트."""
from __future__ import annotations

import json
from pathlib import Path

from morning_brief.analysis.sentiment_join.frontend_artifact import (
    build_frontend_artifact,
    should_skip_artifact,
    write_frontend_artifact,
)

# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _make_stats_bytes(
    *,
    granger_executed: bool = True,
    granger_results: list[dict] | None = None,
    full_quality: str = "ok",
    core_quality: str = "ok",
    full_status: str = "ok",
    core_status: str = "ok",
) -> bytes:
    if granger_results is None:
        granger_results = [
            # 순방향: news_sentiment_mean → fng_value
            {
                "predictor": "news_sentiment_mean",
                "target": "fng_value",
                "lag": 1,
                "pvalue": 0.03,
                "pvalue_adjusted": 0.045,
                "significant": True,
            },
            {
                "predictor": "news_sentiment_mean",
                "target": "fng_value",
                "lag": 2,
                "pvalue": 0.07,
                "pvalue_adjusted": 0.09,
                "significant": False,
            },
            {
                "predictor": "news_sentiment_mean",
                "target": "fng_value",
                "lag": 3,
                "pvalue": 0.10,
                "pvalue_adjusted": 0.12,
                "significant": False,
            },
            # 역방향: btc_log_return → news_sentiment_mean
            {
                "predictor": "btc_log_return",
                "target": "news_sentiment_mean",
                "lag": 1,
                "pvalue": 0.02,
                "pvalue_adjusted": 0.035,
                "significant": True,
            },
            {
                "predictor": "btc_log_return",
                "target": "news_sentiment_mean",
                "lag": 2,
                "pvalue": 0.15,
                "pvalue_adjusted": 0.20,
                "significant": False,
            },
        ]

    payload = {
        "run_id": "sentiment-join-20260421",
        "generated_at_utc": "2026-04-21T08:00:00+00:00",
        "granger_executed": granger_executed,
        "granger_results": granger_results,
        "granger_correction": {
            "correction_method": "fdr_bh",
            "n_tests": 63,
        },
        "hybrid_indices": {
            "full": {
                "quality_status": full_quality,
                "quality_reasons": [],
                "pca_summary": {
                    "status": full_status,
                    "selected_features": ["news_sentiment_mean_lag1", "fng_value_lag1"],
                    "n_components": 1,
                    "explained_variance": 0.802,
                    "loadings": {
                        "news_sentiment_mean_lag1": 0.528,
                        "fng_value_lag1": -0.342,
                    },
                },
                "coverage": {"ratio": 0.91},
                "excluded_features": [
                    {"feature": "volume_change_pct_lag1", "reason": "vif>10"}
                ],
            },
            "core": {
                "quality_status": core_quality,
                "quality_reasons": [],
                "pca_summary": {
                    "status": core_status,
                    "selected_features": ["news_sentiment_mean_lag1", "fng_value_lag1"],
                    "n_components": 1,
                    "explained_variance": 0.751,
                    "loadings": {
                        "news_sentiment_mean_lag1": 0.542,
                        "fng_value_lag1": -0.328,
                    },
                },
                "coverage": {"ratio": 0.95},
                "excluded_features": [],
            },
        },
        # 허용되지 않는 키들 — 아티팩트에 나타나면 안 됨
        "walk_forward": {"index": "full", "folds": 3},
        "correlations": [{"feature": "fng_value", "pearson_r": 0.5}],
        "backtest": [{"index": "full", "horizon": 1, "sharpe": 0.7}],
        "adf": {"btc_log_return": {"adf_stat": -3.5, "pvalue": 0.01}},
        "structured_sources": {"btc_etf": {"mode": "gold_history"}},
    }
    return json.dumps(payload).encode("utf-8")


# ─── direction 매핑 ───────────────────────────────────────────────────────────

def test_direction_forward():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    forward_results = [
        r for r in artifact["granger"]["results"]
        if r["predictor"] == "news_sentiment_mean" and r["target"] == "fng_value"
    ]
    assert all(r["direction"] == "forward" for r in forward_results)


def test_direction_reverse():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    reverse_results = [
        r for r in artifact["granger"]["results"]
        if r["predictor"] == "btc_log_return" and r["target"] == "news_sentiment_mean"
    ]
    assert all(r["direction"] == "reverse" for r in reverse_results)


# ─── optimalLag 선정 ─────────────────────────────────────────────────────────

def test_optimal_lag_selects_lowest_pvalue_adj():
    """lag=1이 pvalue_adjusted 최솟값이므로 optimalLag=True여야 한다."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    fng_results = [
        r for r in artifact["granger"]["results"]
        if r["predictor"] == "news_sentiment_mean" and r["target"] == "fng_value"
    ]
    optimal = [r for r in fng_results if r["optimalLag"]]
    assert len(optimal) == 1
    assert optimal[0]["lag"] == 1


def test_optimal_lag_tie_break_smaller_lag():
    """동률 pvalue_adjusted에서 작은 lag가 optimalLag=True여야 한다."""
    tie_results = [
        {"predictor": "news_sentiment_mean", "target": "fng_value", "lag": 1,
         "pvalue": 0.05, "pvalue_adjusted": 0.08, "significant": False},
        {"predictor": "news_sentiment_mean", "target": "fng_value", "lag": 2,
         "pvalue": 0.05, "pvalue_adjusted": 0.08, "significant": False},
    ]
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(granger_results=tie_results),
        reference_date="2026-04-21",
    )
    optimal = [r for r in artifact["granger"]["results"] if r["optimalLag"]]
    assert len(optimal) == 1
    assert optimal[0]["lag"] == 1


def test_per_group_at_most_one_optimal_lag():
    """각 (predictor, target, direction) 그룹에서 optimalLag=True는 최대 1개."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    from collections import Counter
    group_counts: Counter[tuple[str, str, str]] = Counter()
    for r in artifact["granger"]["results"]:
        if r["optimalLag"]:
            group_counts[(r["predictor"], r["target"], r["direction"])] += 1
    assert all(v == 1 for v in group_counts.values())


# ─── 화이트리스트 검증 ─────────────────────────────────────────────────────────

DISALLOWED_TOP_KEYS = {"walk_forward", "correlations", "backtest", "adf", "structured_sources",
                       "exclusion_counts", "outlier_filtered_count", "outlier_filtered_ratio",
                       "rows_before_outlier_filter", "rows_after_outlier_filter"}


def test_disallowed_keys_not_in_artifact():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    found = DISALLOWED_TOP_KEYS & set(artifact.keys())
    assert not found, f"불허 키가 아티팩트에 포함됨: {found}"


# ─── loadings 키 == selectedFeatures ─────────────────────────────────────────

def test_loadings_keys_match_selected_features():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    for index_name in ("full", "core"):
        pca = artifact["pca"][index_name]
        assert set(pca["loadings"].keys()) == set(pca["selectedFeatures"]), (
            f"{index_name}: loadings 키와 selectedFeatures 불일치"
        )


# ─── should_skip_artifact ─────────────────────────────────────────────────────

def test_skip_both_critical():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(full_quality="critical", core_quality="critical"),
        reference_date="2026-04-21",
    )
    assert should_skip_artifact(artifact) is True


def test_no_skip_one_critical():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(full_quality="critical", core_quality="ok"),
        reference_date="2026-04-21",
    )
    assert should_skip_artifact(artifact) is False


def test_no_skip_both_ok():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    assert should_skip_artifact(artifact) is False


# ─── granger_executed=False 케이스 ────────────────────────────────────────────

def test_granger_not_executed_empty_results():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(granger_executed=False),
        reference_date="2026-04-21",
    )
    assert artifact["granger"]["executed"] is False
    assert artifact["granger"]["results"] == []


# ─── write_frontend_artifact ─────────────────────────────────────────────────

def test_write_creates_two_files(tmp_path: Path):
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    latest, dated = write_frontend_artifact(tmp_path, artifact, "20260421")
    assert latest.exists()
    assert dated.exists()
    assert latest.name == "latest.json"
    assert dated.name == "20260421.json"
    # 두 파일의 내용이 동일한지 확인
    assert json.loads(latest.read_text()) == json.loads(dated.read_text())
