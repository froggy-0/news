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
                "excluded_features": [{"feature": "volume_change_pct_lag1", "reason": "vif>10"}],
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
        "rows_before_outlier_filter": 365,
        "rows_after_outlier_filter": 352,
        "outlier_filtered_count": 13,
        "outlier_filtered_ratio": 0.0356,
        "granger_eligible_rows": 352,
        "granger_skips": [],
        "granger_skip_summary": {},
        "ffill_breakdown": {"btc": 0, "usdkrw": 117, "vix": 108},
        "exclusion_counts": {"vif": 1},
        "target_diagnostics": {
            "btc_large_move_3d": {"valid_rows": 350, "null_ratio": 0.01, "positive_rate": 0.38},
            "btc_large_move_3d_vol_adj": {
                "valid_rows": 350,
                "null_ratio": 0.01,
                "positive_rate": 0.16,
            },
        },
        "hit_rates": [{"predictor": "news_sentiment_mean_lag1", "hit_rate": 0.53}],
        "baseline_metrics": {"1": {"always_up": {"hit_rate": 0.51}}},
        "horizon_metrics": {
            "1": {
                "return_col": "btc_log_return",
                "hit_rates": [
                    {
                        "predictor": "news_sentiment_mean_lag1",
                        "hit_rate": 0.53,
                        "decision": "research_only",
                        "decision_strict": "research_only",
                        "best_baseline": "always_up",
                        "best_hit_rate_baseline": "always_up",
                        "best_sharpe_baseline": "always_up",
                        "baseline_hit_rate": 0.51,
                        "baseline_hit_rate_ci_upper": 0.58,
                        "baseline_sharpe": 0.1,
                        "baseline_sharpe_ci_upper": 0.3,
                        "strategy_sharpe": 0.2,
                        "hit_rate_lift_vs_best_baseline": 0.02,
                        "sharpe_lift_vs_best_baseline": 0.1,
                        "pvalue_vs_baselines": 0.4,
                        "fdr_q": 0.4,
                        "paired_baseline_alignment": {
                            "always_up": {
                                "alignment_key": "date",
                                "signal_rows": 100,
                                "baseline_rows": 100,
                                "paired_rows": 100,
                            }
                        },
                    }
                ],
                "backtest": [],
            }
        },
        "walk_forward_horizons": {"full": {"1": {"avg_hit_rate": 0.52, "stability": 0.45}}},
        "walk_forward_legacy_1d": {"full": {"avg_hit_rate": 0.49, "horizon_days": 1}},
        "feature_group_summary": {"7": {"stationary": {"avg_hit_rate": 0.54}}},
        "baseline_gap_summary": {"7": {"best_baseline": "vol_regime"}},
        "next_research_candidates": {"7": [{"predictor": "sentiment_momentum_lag1"}]},
        # 원본 metadata — v2 artifact에서는 rawStats에 보존되어야 함
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
        r
        for r in artifact["granger"]["results"]
        if r["predictor"] == "news_sentiment_mean" and r["target"] == "fng_value"
    ]
    assert all(r["direction"] == "forward" for r in forward_results)


def test_direction_reverse():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    reverse_results = [
        r
        for r in artifact["granger"]["results"]
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
        r
        for r in artifact["granger"]["results"]
        if r["predictor"] == "news_sentiment_mean" and r["target"] == "fng_value"
    ]
    optimal = [r for r in fng_results if r["optimalLag"]]
    assert len(optimal) == 1
    assert optimal[0]["lag"] == 1


def test_optimal_lag_tie_break_smaller_lag():
    """동률 pvalue_adjusted에서 작은 lag가 optimalLag=True여야 한다."""
    tie_results = [
        {
            "predictor": "news_sentiment_mean",
            "target": "fng_value",
            "lag": 1,
            "pvalue": 0.05,
            "pvalue_adjusted": 0.08,
            "significant": False,
        },
        {
            "predictor": "news_sentiment_mean",
            "target": "fng_value",
            "lag": 2,
            "pvalue": 0.05,
            "pvalue_adjusted": 0.08,
            "significant": False,
        },
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


# ─── v2 진단 metadata 검증 ────────────────────────────────────────────────────

SNAKE_CASE_TOP_KEYS = {
    "walk_forward",
    "correlations",
    "backtest",
    "adf",
    "structured_sources",
    "exclusion_counts",
    "outlier_filtered_count",
    "outlier_filtered_ratio",
    "rows_before_outlier_filter",
    "rows_after_outlier_filter",
}


def test_snake_case_stats_not_promoted_to_top_level():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )
    found = SNAKE_CASE_TOP_KEYS & set(artifact.keys())
    assert not found, f"snake_case stats가 top-level에 포함됨: {found}"


def test_v2_artifact_exposes_dashboard_diagnostics_and_raw_stats():
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-21",
    )

    assert artifact["schemaVersion"] == "sentiment-insight-v2"
    assert artifact["summary"]["rowsAfterOutlierFilter"] == 352
    assert artifact["summary"]["alphaCandidateCount"] == 1
    assert artifact["dataQuality"]["ffillBreakdown"] == {"btc": 0, "usdkrw": 117, "vix": 108}
    assert artifact["dataQuality"]["structuredSources"]["btc_etf"]["mode"] == "gold_history"
    assert artifact["alpha"]["baselineMetrics"]["1"]["always_up"]["hit_rate"] == 0.51
    horizon_row = artifact["alpha"]["horizonMetrics"]["1"]["hit_rates"][0]
    assert horizon_row["decision_strict"] == "research_only"
    assert horizon_row["paired_baseline_alignment"]["always_up"]["alignment_key"] == "date"
    assert artifact["alpha"]["walkForwardLegacy1d"]["full"]["horizon_days"] == 1
    assert artifact["alpha"]["featureGroupSummary"]["7"]["stationary"]["avg_hit_rate"] == 0.54
    assert artifact["alpha"]["baselineGapSummary"]["7"]["best_baseline"] == "vol_regime"
    assert artifact["alpha"]["nextResearchCandidates"]["7"][0]["predictor"] == (
        "sentiment_momentum_lag1"
    )
    assert artifact["targets"]["diagnostics"]["btc_large_move_3d_vol_adj"]["positive_rate"] == 0.16
    assert artifact["stationarity"]["adf"]["btc_log_return"]["pvalue"] == 0.01
    assert artifact["rawStats"]["structured_sources"]["btc_etf"]["mode"] == "gold_history"


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


# ─── gateStats / meta / bootstrapConfig ─────────────────────────────────────


def test_artifact_contains_gate_stats() -> None:
    """alpha.gateStats 필드가 존재하고 필수 키를 포함해야 한다."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-30",
    )
    gate = artifact.get("alpha", {}).get("gateStats", {})
    assert "totalPredictors" in gate
    assert "decisionPromoteCount" in gate
    assert "decisionStrictPromoteCount" in gate
    assert "gap" in gate
    assert "gapRatio" in gate


def test_gate_stats_gap_equals_promote_difference() -> None:
    """gap = decisionPromoteCount - decisionStrictPromoteCount."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-30",
    )
    gate = artifact["alpha"]["gateStats"]
    assert gate["gap"] == gate["decisionPromoteCount"] - gate["decisionStrictPromoteCount"]


def test_artifact_contains_meta_with_annualization_info() -> None:
    """meta 필드에 annualizationFactor, annualizationNote, sharpeBasisChangeDate가 있어야 한다."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-30",
    )
    meta = artifact.get("meta", {})
    assert meta.get("annualizationFactor") == 365
    assert "2026-04-30" in str(meta.get("sharpeBasisChangeDate", ""))
    assert "365" in str(meta.get("annualizationNote", ""))


def test_artifact_contains_bootstrap_config() -> None:
    """bootstrapConfig 필드가 method, blockLength, nBootstrap을 포함해야 한다."""
    artifact = build_frontend_artifact(
        stats_metadata_bytes=_make_stats_bytes(),
        reference_date="2026-04-30",
    )
    cfg = artifact.get("bootstrapConfig", {})
    assert "method" in cfg
    assert "blockLength" in cfg
    assert "nBootstrap" in cfg
