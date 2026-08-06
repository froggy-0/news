from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/analysis"))

from validation_stats import (
    deflated_sharpe_ratio,
    documented_trial_count,
    effective_trial_count,
)


def test_documented_trial_count_uses_cumulative_ledger_lower_bound() -> None:
    assert documented_trial_count("fng_contrarian") == 34
    assert documented_trial_count("vix_rsi") == 26
    assert documented_trial_count("unknown_algo") == 0


def test_effective_trial_count_never_uses_less_than_local_grid() -> None:
    assert effective_trial_count(5, algo_id="fng_contrarian") == 34
    assert effective_trial_count(40, algo_id="fng_contrarian") == 40
    assert effective_trial_count(3, algo_id="unknown_algo") == 3
    with pytest.raises(ValueError, match="local_n_trials"):
        effective_trial_count(0, algo_id="fng_contrarian")


def test_cumulative_trials_deflate_dsr_more_than_single_trial() -> None:
    returns = np.asarray([0.03, 0.02, -0.01, 0.025, -0.005, 0.015, 0.01, -0.004])

    naive = deflated_sharpe_ratio(returns, 1)
    audited = deflated_sharpe_ratio(returns, 34)

    assert audited["dsr"] < naive["dsr"]
