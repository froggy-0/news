"""validate_latest_artifact.py sanity check 단위 테스트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# scripts 경로 추가
SCRIPTS_PATH = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

import validate_latest_artifact as vla  # noqa: E402


def _make_good_row(predictor: str = "vix_regime_score_lag1") -> dict:
    return {
        "predictor": predictor,
        "hit_rate": 0.55,
        "hit_rate_ci_lower": 0.48,
        "hit_rate_ci_upper": 0.62,
        "sharpe_ci_lower": 0.2,
        "sharpe_ci_upper": 1.4,
        "fdr_q": 0.08,
        "pvalue_vs_baselines": {"vol_regime": 0.12, "always_up": 0.23},
        "bootstrap_n": 1000,
    }


def _reset() -> None:
    vla._ERRORS.clear()
    vla._WARNINGS.clear()


def test_good_row_produces_no_errors() -> None:
    _reset()
    vla.check_hit_rate_rows([_make_good_row()])
    assert vla._ERRORS == []
    assert vla._WARNINGS == []


def test_nan_ci_lower_produces_error() -> None:
    _reset()
    row = _make_good_row()
    row["hit_rate_ci_lower"] = None
    vla.check_hit_rate_rows([row])
    assert any("hit_rate_ci_lower" in e for e in vla._ERRORS)


def test_nan_sharpe_ci_with_zero_exposure_produces_warning_not_error() -> None:
    _reset()
    row = _make_good_row()
    row["strategy_sharpe"] = None
    row["sharpe_ci_lower"] = None
    row["sharpe_ci_upper"] = None
    row["payoff_diagnostics"] = {"exposure_ratio": 0.0}
    vla.check_hit_rate_rows([row])
    assert vla._ERRORS == []
    assert any("exposure=0" in w for w in vla._WARNINGS)


def test_hit_rate_outside_ci_produces_error() -> None:
    _reset()
    row = _make_good_row()
    row["hit_rate"] = 0.70  # CI는 [0.48, 0.62]이므로 밖
    vla.check_hit_rate_rows([row])
    assert any("CI" in e or "밖" in e for e in vla._ERRORS)


def test_zero_ci_width_produces_warning() -> None:
    _reset()
    row = _make_good_row()
    row["hit_rate_ci_lower"] = 0.55
    row["hit_rate_ci_upper"] = 0.55
    vla.check_hit_rate_rows([row])
    assert any("폭=0" in w or "edge case" in w for w in vla._WARNINGS)


def test_fdr_q_out_of_range_produces_error() -> None:
    _reset()
    row = _make_good_row()
    row["fdr_q"] = 1.5
    vla.check_hit_rate_rows([row])
    assert any("fdr_q" in e for e in vla._ERRORS)


def test_all_pvalues_one_produces_warning() -> None:
    _reset()
    row = _make_good_row()
    row["pvalue_vs_baselines"] = {"vol_regime": 1.0, "always_up": 1.0}
    vla.check_hit_rate_rows([row])
    assert any("pvalue_vs_baselines" in w or "1.0" in w for w in vla._WARNINGS)


def test_bootstrap_n_zero_produces_error() -> None:
    _reset()
    row = _make_good_row()
    row["bootstrap_n"] = 0
    vla.check_hit_rate_rows([row])
    assert any("bootstrap_n==0" in e for e in vla._ERRORS)


def test_bootstrap_config_wrong_method_produces_warning() -> None:
    _reset()
    vla.check_bootstrap_config({"method": "iid", "block_length": 14, "n_bootstrap": 1000})
    assert any("method" in w for w in vla._WARNINGS)


def test_bootstrap_config_correct_produces_no_warning() -> None:
    _reset()
    vla.check_bootstrap_config({"method": "circular", "block_length": 14, "n_bootstrap": 1000})
    assert vla._WARNINGS == []


def test_bootstrap_config_accepts_frontend_camel_case() -> None:
    _reset()
    vla.check_bootstrap_config({"method": "circular", "blockLength": 14, "nBootstrap": 1000})
    assert vla._WARNINGS == []


def test_run_checks_missing_file_returns_1(tmp_path: Path) -> None:
    _reset()
    code = vla.run_checks(tmp_path / "nonexistent.json")
    assert code == 1


def test_run_checks_good_artifact_returns_0(tmp_path: Path) -> None:
    _reset()
    artifact = {
        "alpha": {
            "horizonMetrics": {
                "7": {
                    "hit_rates": [_make_good_row()],
                }
            },
            "baselineMetrics": {
                "7": {"vol_regime_v2": {"hit_rate": 0.61, "coverage": 0.56, "sharpe": 5.7}}
            },
        },
        "bootstrapConfig": {"method": "circular", "block_length": 14, "n_bootstrap": 1000},
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(artifact))
    code = vla.run_checks(path)
    assert code == 0


def test_run_checks_error_artifact_returns_1(tmp_path: Path) -> None:
    _reset()
    bad_row = _make_good_row()
    bad_row["bootstrap_n"] = 0  # ERROR 유발
    artifact = {
        "alpha": {
            "horizonMetrics": {"7": {"hit_rates": [bad_row]}},
            "baselineMetrics": {"7": {}},
        },
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(artifact))
    code = vla.run_checks(path)
    assert code == 1
