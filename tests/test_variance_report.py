from __future__ import annotations

import json

import pandas as pd
from scripts.variance_report import _build_report_md


def test_variance_report_includes_advanced_feature_sections(tmp_path) -> None:
    (tmp_path / "tracking.json").write_text(
        json.dumps(
            {
                "lineage": {
                    "funding_source": ["binance"],
                    "vix_source": ["fred"],
                }
            }
        ),
        encoding="utf-8",
    )
    cell_means = pd.DataFrame(
        [
            {
                "spec_id": "standard-row-T1-full",
                "index_name": "full",
                "feature_set": "baseline",
                "n_folds": 3,
                "hit_rate": 0.52,
                "net_sharpe": 0.10,
                "gross_sharpe": 0.12,
                "worst_fold_sharpe": -0.05,
                "turnover": 0.20,
                "coverage": 0.95,
                "masked_ratio": 0.01,
                "stability": 0.80,
            },
            {
                "spec_id": "standard-row-T1-core",
                "index_name": "core",
                "feature_set": "baseline",
                "n_folds": 3,
                "hit_rate": 0.51,
                "net_sharpe": 0.08,
                "gross_sharpe": 0.10,
                "worst_fold_sharpe": -0.08,
                "turnover": 0.18,
                "coverage": 0.94,
                "masked_ratio": 0.01,
                "stability": 0.75,
            },
            {
                "spec_id": "lightgbm-model-T1-full",
                "index_name": "full",
                "feature_set": "oi_divergence_all",
                "n_folds": 3,
                "hit_rate": 0.56,
                "net_sharpe": 0.14,
                "gross_sharpe": 0.18,
                "worst_fold_sharpe": 0.01,
                "turnover": 0.30,
                "coverage": 0.93,
                "masked_ratio": 0.02,
                "stability": 0.70,
            },
            {
                "spec_id": "always_up-baseline",
                "index_name": "baseline",
                "feature_set": "baseline",
                "n_folds": 3,
                "hit_rate": 0.50,
                "net_sharpe": 0.00,
                "gross_sharpe": 0.00,
                "worst_fold_sharpe": 0.00,
                "turnover": 0.00,
                "coverage": 1.00,
                "masked_ratio": 0.00,
                "stability": 1.00,
            },
        ]
    )

    report = _build_report_md(tmp_path, cell_means, [], {}, "standard-row-T1-full")

    assert "## Index Family Comparison" in report
    assert "## Feature Set Comparison" in report
    assert "## Baseline / Model Comparison" in report
    assert "## Lineage Summary" in report
    assert "net_sharpe" in report
    assert "worst_fold_sharpe" in report
    assert "turnover" in report
    assert "| oi_divergence_all |" in report
    assert "| full |" in report
    assert "| model |" in report
    assert "| funding_source | binance |" in report
