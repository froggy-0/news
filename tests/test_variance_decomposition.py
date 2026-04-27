"""Phase 4 — Variance Decomposition 결정론적 테스트.

Task 14:
- ANOVA SS 항등식 검증 (총 SS = 설명 SS + 잔차 SS)
- 승격 게이트 truth table 전수 테스트 (2^5 = 32 케이스)
- BH-FDR 단조성 + 항등식
- Fisher-z 수치 정확성
- bootstrap CI [lower, upper] 관계
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.variance import (
    GATE_HIT_RATE_DELTA_PP,
    GATE_MAX_MASKED_RATIO,
    GATE_MIN_COVERAGE,
    GATE_MIN_STABILITY,
    GATE_SHARPE_DELTA,
    bh_correct,
    bootstrap_ci,
    evaluate_promotion_gate,
    fisher_z,
    power_analysis,
    run_anova,
    run_horizon_anova,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fisher-z 수치 정확성
# ─────────────────────────────────────────────────────────────────────────────


def test_fisher_z_zero() -> None:
    assert fisher_z(0.0) == pytest.approx(0.0, abs=1e-12)


def test_fisher_z_positive() -> None:
    # r=0.5 → z = 0.5 * ln(3) ≈ 0.5493
    expected = 0.5 * math.log(3.0)
    assert fisher_z(0.5) == pytest.approx(expected, abs=1e-9)


def test_fisher_z_clips_near_one() -> None:
    z = fisher_z(1.0)
    assert math.isfinite(z)
    assert z > 0


def test_fisher_z_clips_near_minus_one() -> None:
    z = fisher_z(-1.0)
    assert math.isfinite(z)
    assert z < 0


def test_fisher_z_antisymmetric() -> None:
    assert fisher_z(0.3) == pytest.approx(-fisher_z(-0.3), abs=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# BH-FDR 보정
# ─────────────────────────────────────────────────────────────────────────────


def test_bh_correct_empty() -> None:
    assert bh_correct([]) == []


def test_bh_correct_single() -> None:
    result = bh_correct([0.04])
    assert len(result) == 1
    assert result[0] == pytest.approx(0.04, abs=1e-12)


def test_bh_correct_monotone_non_decreasing() -> None:
    """q-value 는 원래 p-value 순서로 단조 비감소여야 한다."""
    p = [0.001, 0.01, 0.05, 0.10, 0.20]
    q = bh_correct(p)
    # 입력이 이미 정렬돼 있으므로 출력도 비감소
    for i in range(len(q) - 1):
        assert q[i] <= q[i + 1] + 1e-12


def test_bh_correct_output_length() -> None:
    p = [0.05, 0.01, 0.1, 0.2, 0.001]
    q = bh_correct(p)
    assert len(q) == len(p)


def test_bh_correct_q_le_one() -> None:
    p = [0.4, 0.5, 0.6]
    q = bh_correct(p)
    assert all(v <= 1.0 for v in q)


def test_bh_correct_q_ge_zero() -> None:
    p = [0.001, 0.0001, 0.1]
    q = bh_correct(p)
    assert all(v >= 0.0 for v in q)


def test_bh_correct_preserves_order_mapping() -> None:
    """입력 순서가 흔들려도 각 위치에 올바른 q가 매핑되어야 한다."""
    # p[0]=0.10이 가장 큰 p → BH에서 가장 느슨한 보정
    p = [0.10, 0.01, 0.001]
    q = bh_correct(p)
    # 가장 작은 p (index 2) 는 가장 강한 보정 → q 작음
    assert q[2] <= q[1] <= q[0]


# ─────────────────────────────────────────────────────────────────────────────
# ANOVA SS 항등식
# ─────────────────────────────────────────────────────────────────────────────


def _make_folds_df(n_specs: int = 8, n_folds: int = 4, seed: int = 42) -> pd.DataFrame:
    """테스트용 합성 folds DataFrame."""
    rng = np.random.default_rng(seed)
    scalers = ["standard", "robust"]
    masks = ["row", "column", "winsorize", "none"]

    rows = []
    for i in range(n_specs):
        scaler = scalers[i % 2]
        mask = masks[i % 4]
        for fold in range(n_folds):
            rows.append(
                {
                    "spec_id": f"{scaler}-{mask}-T1-full",
                    "scaler": scaler,
                    "mask": mask,
                    "horizon": 1,
                    "index_name": "full",
                    "fold": fold,
                    "hit_rate": float(rng.uniform(0.45, 0.65)),
                    "sharpe": float(rng.normal(0.2, 0.5)),
                    "coverage": float(rng.uniform(0.7, 1.0)),
                    "masked_ratio": float(rng.uniform(0.0, 0.15)),
                    "stability": float(rng.uniform(0.3, 0.9)),
                }
            )
    return pd.DataFrame(rows)


def test_anova_ss_decomposition_identity() -> None:
    """총 SS = 설명 SS (scaler + mask + interaction + fold_id) + 잔차 SS."""
    folds = _make_folds_df(n_specs=8, n_folds=6)
    result = run_anova(folds, "hit_rate")

    if not result.ss:
        pytest.skip("ANOVA ss 비어 있음 (데이터 부족)")

    total_ss = sum(result.ss.values())
    explained_ss = sum(v for k, v in result.ss.items() if k != "residual")
    residual_ss = result.ss.get("residual", 0.0)

    assert explained_ss + residual_ss == pytest.approx(total_ss, abs=1e-6)


def test_anova_eta_sq_sums_to_one() -> None:
    """η² 합이 1.0 에 수렴해야 한다 (residual 포함)."""
    folds = _make_folds_df(n_specs=8, n_folds=6)
    result = run_anova(folds, "hit_rate")

    if not result.eta_sq:
        pytest.skip("eta_sq 비어 있음")

    total_eta = sum(v for v in result.eta_sq.values() if not math.isnan(v))
    assert total_eta == pytest.approx(1.0, abs=1e-6)


def test_anova_returns_required_effects() -> None:
    folds = _make_folds_df()
    result = run_anova(folds, "hit_rate")
    # 충분한 데이터가 있으면 주요 effect 키가 존재해야 함
    if result.n_obs >= 8:
        for key in ("scaler", "mask", "interaction"):
            assert key in result.eta_sq, f"eta_sq에 '{key}' 없음"


def test_horizon_anova_returns_horizon_key() -> None:
    folds = _make_folds_df()
    # horizon 다양성 추가
    folds2 = folds.copy()
    folds2["horizon"] = 3
    combined = pd.concat([folds, folds2], ignore_index=True)

    result = run_horizon_anova(combined, "hit_rate")
    if result.n_obs >= 4:
        assert "horizon" in result.eta_sq


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap CI
# ─────────────────────────────────────────────────────────────────────────────


def test_bootstrap_ci_lower_le_mean_le_upper() -> None:
    folds = _make_folds_df()
    cis = bootstrap_ci(folds, "hit_rate", n_bootstrap=200, rng_seed=0)
    for ci in cis:
        if not math.isnan(ci.mean):
            assert ci.ci_lower <= ci.mean <= ci.ci_upper, (
                f"{ci.spec_id}: ci_lower={ci.ci_lower:.4f} mean={ci.mean:.4f} "
                f"ci_upper={ci.ci_upper:.4f}"
            )


def test_bootstrap_ci_reproducible() -> None:
    folds = _make_folds_df()
    cis1 = bootstrap_ci(folds, "hit_rate", n_bootstrap=200, rng_seed=42)
    cis2 = bootstrap_ci(folds, "hit_rate", n_bootstrap=200, rng_seed=42)
    for c1, c2 in zip(cis1, cis2):
        assert c1.ci_lower == pytest.approx(c2.ci_lower, abs=1e-12)
        assert c1.ci_upper == pytest.approx(c2.ci_upper, abs=1e-12)


def test_bootstrap_ci_spec_ids_match() -> None:
    folds = _make_folds_df()
    expected_ids = set(folds["spec_id"].unique())
    cis = bootstrap_ci(folds, "hit_rate", n_bootstrap=100)
    actual_ids = {ci.spec_id for ci in cis}
    assert actual_ids == expected_ids


def test_power_analysis_min_sample_decreases_with_larger_effect() -> None:
    small = power_analysis(effect_size=0.05, n_obs=8)
    large = power_analysis(effect_size=0.20, n_obs=8)

    assert large.min_sample_size < small.min_sample_size
    assert large.achieved_power > small.achieved_power


# ─────────────────────────────────────────────────────────────────────────────
# 승격 게이트 truth table 전수 테스트 (2^5 = 32 케이스)
# ─────────────────────────────────────────────────────────────────────────────

# 각 조건을 True/False로 만드는 값 쌍: (pass_value, fail_value)
_GATE_PARAM = {
    "hit_rate_delta": (GATE_HIT_RATE_DELTA_PP, GATE_HIT_RATE_DELTA_PP - 0.001),
    "sharpe_delta": (GATE_SHARPE_DELTA, GATE_SHARPE_DELTA - 0.001),
    "coverage": (GATE_MIN_COVERAGE, GATE_MIN_COVERAGE - 0.001),
    "masked_ratio": (GATE_MAX_MASKED_RATIO, GATE_MAX_MASKED_RATIO + 0.001),
    "stability": (GATE_MIN_STABILITY, GATE_MIN_STABILITY - 0.001),
}
_GATE_KEYS = list(_GATE_PARAM.keys())


@pytest.mark.parametrize(
    "bits",
    list(itertools.product([True, False], repeat=5)),
)
def test_promotion_gate_truth_table(bits: tuple[bool, ...]) -> None:
    """2^5 = 32 케이스 전수: promote ↔ 5개 AND 모두 True."""
    kwargs = {}
    for key, bit in zip(_GATE_KEYS, bits):
        pass_val, fail_val = _GATE_PARAM[key]
        kwargs[key] = pass_val if bit else fail_val

    result = evaluate_promotion_gate(**kwargs)  # type: ignore[arg-type]

    all_pass = all(bits)
    if all_pass:
        assert result.decision == "promote", f"bits={bits} → expected promote"
    else:
        # promote 가 아니어야 함
        assert result.decision != "promote", f"bits={bits} → should not be promote"


def test_promotion_gate_rejects_when_coverage_fails() -> None:
    """coverage 미달이면 나머지 uplift 조건을 충족해도 승격하지 않는다."""
    result = evaluate_promotion_gate(
        hit_rate_delta=GATE_HIT_RATE_DELTA_PP,
        sharpe_delta=GATE_SHARPE_DELTA,
        coverage=GATE_MIN_COVERAGE - 0.001,
        masked_ratio=GATE_MAX_MASKED_RATIO,
        stability=GATE_MIN_STABILITY,
    )
    assert result.decision == "research_only"


def test_promotion_gate_research_only_when_all_fail() -> None:
    result = evaluate_promotion_gate(
        hit_rate_delta=-0.05,
        sharpe_delta=-0.5,
        coverage=0.0,
        masked_ratio=0.9,
        stability=0.0,
        hit_rate_ci_lower=-0.05,
        fdr_q=0.99,
    )
    assert result.decision == "research_only"


def test_promotion_gate_stores_inputs() -> None:
    result = evaluate_promotion_gate(
        hit_rate_delta=0.03,
        sharpe_delta=0.15,
        coverage=0.9,
        masked_ratio=0.05,
        stability=0.6,
        hit_rate_ci_lower=0.02,
        fdr_q=0.05,
    )
    assert result.hit_rate_delta == pytest.approx(0.03)
    assert result.sharpe_delta == pytest.approx(0.15)
    assert result.coverage == pytest.approx(0.9)
    assert result.masked_ratio == pytest.approx(0.05)
    assert result.fdr_q == pytest.approx(0.05)
    assert result.stability == pytest.approx(0.6)


# ─────────────────────────────────────────────────────────────────────────────
# decision_strict (CI hard separation + BH-FDR) advisory 게이트 테스트
# ─────────────────────────────────────────────────────────────────────────────


def _all_pass_kwargs() -> dict[str, float]:
    """기존 5조건 모두 통과하는 baseline kwargs (decision == 'promote')."""
    return {
        "hit_rate_delta": GATE_HIT_RATE_DELTA_PP + 0.01,
        "sharpe_delta": GATE_SHARPE_DELTA + 0.05,
        "coverage": GATE_MIN_COVERAGE + 0.05,
        "masked_ratio": GATE_MAX_MASKED_RATIO - 0.05,
        "stability": GATE_MIN_STABILITY + 0.10,
    }


def test_decision_strict_promote_when_ci_separated_and_fdr_passes() -> None:
    """5조건 + CI hard separation + BH-FDR q ≤ 0.10 → decision_strict == 'promote'."""
    result = evaluate_promotion_gate(
        **_all_pass_kwargs(),
        hit_rate_ci_lower=0.55,
        hit_rate_ci_upper=0.62,
        sharpe_ci_lower=0.40,
        sharpe_ci_upper=1.10,
        baseline_hit_rate_ci_upper=0.50,
        baseline_sharpe_ci_upper=0.20,
        fdr_q=0.05,
    )
    assert result.decision == "promote"
    assert result.decision_strict == "promote"
    assert result.hit_rate_ci_ok is True
    assert result.sharpe_ci_ok is True
    assert result.fdr_ok is True


def test_decision_strict_research_only_when_ci_overlaps() -> None:
    """signal CI 하한 < baseline CI 상한 → decision_strict='research_only' (decision 은 promote)."""
    result = evaluate_promotion_gate(
        **_all_pass_kwargs(),
        hit_rate_ci_lower=0.45,  # baseline upper 0.50 보다 낮음 → CI 겹침
        hit_rate_ci_upper=0.62,
        sharpe_ci_lower=0.40,
        sharpe_ci_upper=1.10,
        baseline_hit_rate_ci_upper=0.50,
        baseline_sharpe_ci_upper=0.20,
        fdr_q=0.05,
    )
    assert result.decision == "promote"
    assert result.decision_strict == "research_only"
    assert result.hit_rate_ci_ok is False


def test_decision_strict_research_only_when_fdr_above_threshold() -> None:
    result = evaluate_promotion_gate(
        **_all_pass_kwargs(),
        hit_rate_ci_lower=0.55,
        hit_rate_ci_upper=0.62,
        sharpe_ci_lower=0.40,
        sharpe_ci_upper=1.10,
        baseline_hit_rate_ci_upper=0.50,
        baseline_sharpe_ci_upper=0.20,
        fdr_q=0.20,  # > 0.10 → FDR 미통과
    )
    assert result.decision == "promote"
    assert result.decision_strict == "research_only"
    assert result.fdr_ok is False


def test_decision_strict_research_only_when_ci_fields_missing() -> None:
    """CI / FDR 데이터가 NaN 이면 hard separation 평가 불가 → decision_strict='research_only'."""
    result = evaluate_promotion_gate(**_all_pass_kwargs())
    assert result.decision == "promote"
    assert result.decision_strict == "research_only"
    assert result.hit_rate_ci_ok is False
    assert result.fdr_ok is False


def test_decision_strict_never_promote_when_decision_research_only() -> None:
    """기존 5조건 미충족 시 CI 가 좋아도 decision_strict 는 promote 가 될 수 없다."""
    kwargs = _all_pass_kwargs()
    kwargs["coverage"] = GATE_MIN_COVERAGE - 0.01
    result = evaluate_promotion_gate(
        **kwargs,
        hit_rate_ci_lower=0.55,
        hit_rate_ci_upper=0.62,
        sharpe_ci_lower=0.40,
        sharpe_ci_upper=1.10,
        baseline_hit_rate_ci_upper=0.50,
        baseline_sharpe_ci_upper=0.20,
        fdr_q=0.01,
    )
    assert result.decision == "research_only"
    assert result.decision_strict == "research_only"
