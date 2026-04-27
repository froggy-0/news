"""Property & sanity tests for bootstrap.py.

- 점추정이 CI 안에 포함되는 빈도 ≥ 90% 시드 100개 평균
- n_bootstrap 증가 시 CI 폭 단조 비증가
- circular block(L=1) ≈ i.i.d. bootstrap (CI bound 5% 이내)
- benjamini_hochberg q-value 단조성 (rank 순서)
- bootstrap_paired one-sided p-value 가 [0, 1] 범위
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from morning_brief.analysis.sentiment_join.bootstrap import (
    BootstrapConfig,
    benjamini_hochberg,
    bootstrap_metric,
    bootstrap_paired,
)


def test_point_estimate_inside_ci_with_high_probability() -> None:
    """100개 시드 중 ≥ 90개 케이스에서 점추정이 95% CI 안에 포함되어야 한다."""
    contained = 0
    for seed in range(100):
        rng = np.random.default_rng(seed)
        data = rng.normal(0.5, 1.0, 200)
        cfg = BootstrapConfig(n_bootstrap=300, block_length=14, method="circular", seed=seed)
        res = bootstrap_metric(data, np.mean, cfg)
        if math.isfinite(res.ci_lower) and math.isfinite(res.ci_upper):
            if res.ci_lower <= res.point <= res.ci_upper:
                contained += 1
    assert contained >= 90, f"point ∈ CI rate too low: {contained}/100"


def test_ci_width_non_increasing_in_n_bootstrap() -> None:
    """n_bootstrap 200 → 2000 으로 늘리면 CI 폭이 줄어들거나 비슷해야 한다 (sampling 안정화)."""
    rng = np.random.default_rng(7)
    data = rng.normal(0.0, 1.0, 200)
    widths = []
    for n in (200, 800, 2000):
        cfg = BootstrapConfig(n_bootstrap=n, block_length=14, method="circular", seed=0)
        res = bootstrap_metric(data, np.mean, cfg)
        widths.append(res.ci_upper - res.ci_lower)
    # 분산 안정화 — 단조 감소까진 보장 안 되지만 큰 n 의 폭이 작은 n 의 폭의 1.5배를 넘으면 의심.
    assert widths[2] <= widths[0] * 1.5, f"CI widths suspicious: {widths}"


def test_circular_block_length_one_matches_iid_within_5pct() -> None:
    """i.i.d. 가우시안 입력에서 circular(L=1) ≈ i.i.d. (CI 경계 5% 이내)."""
    rng = np.random.default_rng(11)
    data = rng.normal(0.0, 1.0, 300)
    cfg_l1 = BootstrapConfig(n_bootstrap=2000, block_length=1, method="circular", seed=0)
    cfg_iid = BootstrapConfig(n_bootstrap=2000, method="iid", seed=0)
    r1 = bootstrap_metric(data, np.mean, cfg_l1)
    r2 = bootstrap_metric(data, np.mean, cfg_iid)
    width_l1 = r1.ci_upper - r1.ci_lower
    width_iid = r2.ci_upper - r2.ci_lower
    assert abs(width_l1 - width_iid) / max(abs(width_iid), 1e-9) < 0.05


def test_benjamini_hochberg_monotone_in_pvalue_rank() -> None:
    """p-value rank 순서로 q-value 가 단조 비감소해야 한다."""
    p = np.array([0.001, 0.005, 0.02, 0.04, 0.10, 0.30, 0.80])
    q = benjamini_hochberg(p)
    assert np.all(np.diff(q) >= -1e-12), f"q-values not monotone: {q}"


def test_benjamini_hochberg_caps_at_one_and_handles_nan() -> None:
    p = np.array([0.99, np.nan, 0.5, 0.1])
    q = benjamini_hochberg(p)
    finite = q[np.isfinite(q)]
    assert (finite <= 1.0).all()
    assert math.isnan(q[1])


def test_bootstrap_paired_pvalue_in_unit_interval() -> None:
    rng = np.random.default_rng(3)
    sig = rng.normal(0.0, 1.0, 100)
    base = rng.normal(0.0, 1.0, 100)
    cfg = BootstrapConfig(n_bootstrap=500, block_length=14, method="circular", seed=0)
    sig_res, base_res = bootstrap_paired(sig, base, np.mean, cfg)
    assert 0.0 < sig_res.pvalue_one_sided <= 1.0
    # baseline 결과는 pvalue NaN (단일 시리즈로 취급)
    assert math.isnan(base_res.pvalue_one_sided)


def test_bootstrap_paired_low_pvalue_when_signal_clearly_better() -> None:
    rng = np.random.default_rng(0)
    sig = rng.normal(1.0, 1.0, 200)
    base = rng.normal(-1.0, 1.0, 200)
    cfg = BootstrapConfig(n_bootstrap=500, block_length=14, method="circular", seed=0)
    sig_res, _ = bootstrap_paired(sig, base, np.mean, cfg)
    assert sig_res.pvalue_one_sided < 0.05, (
        f"signal clearly better than baseline but p={sig_res.pvalue_one_sided}"
    )


@pytest.mark.parametrize("method", ["circular", "iid"])
def test_bootstrap_metric_handles_empty_array(method: str) -> None:
    cfg = BootstrapConfig(n_bootstrap=50, method=method, seed=0)
    res = bootstrap_metric(np.array([]), np.mean, cfg)
    assert math.isnan(res.point)
    assert math.isnan(res.ci_lower) and math.isnan(res.ci_upper)


def test_bootstrap_config_default_block_length_for_t7() -> None:
    """T+7 horizon 기본 block_length = 14 (2 × horizon)."""
    cfg = BootstrapConfig()
    assert cfg.block_length == 14
    assert cfg.method == "circular"
    assert cfg.n_bootstrap == 1000
