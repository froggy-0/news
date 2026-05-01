"""Variance decomposition & ANOVA report for outlier-ablation experiments (Phase 4).

주요 함수:
- run_anova(df, metric)    : 2-way C(scaler)*C(mask) + C(fold_id) ANOVA, η² 계산
- run_horizon_anova(df, metric) : 1-way C(horizon) ANOVA
- bootstrap_ci(df, metric) : fold-level bootstrap 95% CI (n=500)
- bh_correct(p_values)     : Benjamini-Hochberg FDR 보정
- fisher_z(r)              : Pearson→Fisher-z 변환
- evaluate_promotion_gate(delta, baseline) : 5개 AND 조건 평가
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Promotion gate 임계값 (design.md 사전 등록)
# ─────────────────────────────────────────────────────────────────────────────

GATE_HIT_RATE_DELTA_PP = 0.02  # hit_rate Δ ≥ +2pp
GATE_SHARPE_DELTA = 0.10  # Sharpe Δ ≥ +0.10
GATE_MIN_COVERAGE = 0.85  # coverage ≥ 85%
GATE_MAX_MASKED_RATIO = 0.10  # masked_ratio ≤ 10%
GATE_MIN_STABILITY = 0.50  # fold stability ≥ 0.50

# CI-strict gate (decision_strict) — overlapping sample 환경에서의 보수적 비교
GATE_HIT_RATE_CI_DELTA_PP = 0.0  # signal CI 하한 ≥ baseline CI 상한 (hard separation)
GATE_SHARPE_CI_DELTA = 0.0  # 동일
GATE_FDR_Q = 0.10  # BH-FDR q ≤ 0.10 (탐색적 finance 표준)


@dataclass
class AnovaResult:
    """2-way / 1-way ANOVA 결과."""

    metric: str
    factor: str  # "scaler_mask" | "horizon"
    eta_sq: dict[str, float]  # effect → η²
    f_pvalue: dict[str, float]  # effect → p-value
    ss: dict[str, float]  # effect → sum of squares
    n_obs: int
    raw: Any = field(default=None, repr=False)  # statsmodels RegressionResultsWrapper (선택적)


@dataclass
class BootstrapCI:
    metric: str
    spec_id: str
    mean: float
    ci_lower: float
    ci_upper: float
    n_bootstrap: int = 500


@dataclass
class PromotionGateResult:
    """승격 게이트 평가 결과.

    decision        : 기존 5조건 (hit_rate / Sharpe / coverage / masked / stability) AND.
    decision_strict : 위 + CI hard separation (hit_rate / Sharpe) + BH-FDR q ≤ GATE_FDR_Q.
                       advisory — 운영 결정은 decision 으로 유지. calibration 후 승격 검토.
    """

    decision: str  # "promote" | "research_only"
    hit_rate_ok: bool
    sharpe_ok: bool
    coverage_ok: bool
    masked_ratio_ok: bool
    stability_ok: bool
    # 입력 값 보존
    hit_rate_delta: float
    sharpe_delta: float
    coverage: float
    masked_ratio: float
    stability: float
    hit_rate_ci_lower: float = float("nan")
    fdr_q: float = float("nan")
    # CI-strict 추가 필드
    hit_rate_ci_upper: float = float("nan")
    sharpe_ci_lower: float = float("nan")
    sharpe_ci_upper: float = float("nan")
    baseline_hit_rate_ci_upper: float = float("nan")
    baseline_sharpe_ci_upper: float = float("nan")
    hit_rate_ci_ok: bool = False
    sharpe_ci_ok: bool = False
    fdr_ok: bool = False
    decision_strict: str = "research_only"


@dataclass
class PowerAnalysisResult:
    effect_size: float
    n_obs: int
    alpha: float
    target_power: float
    achieved_power: float
    min_sample_size: int


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────


def fisher_z(r: float) -> float:
    """Pearson r → Fisher-z 변환. |r| ≥ 1 은 clip."""
    r_clipped = max(-0.9999, min(0.9999, r))
    return 0.5 * math.log((1 + r_clipped) / (1 - r_clipped))


def bh_correct(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR 보정. 입력 순서 유지하여 q-value 반환."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adj = [0.0] * m
    for rank_0, orig_idx in enumerate(order):
        rank = rank_0 + 1
        adj[rank_0] = min(p_values[orig_idx] * m / rank, 1.0)
    # 단조 감소 강제 (step-up)
    for i in range(m - 2, -1, -1):
        adj[i] = min(adj[i], adj[i + 1])
    # 원래 순서로 복원
    result = [0.0] * m
    for rank_0, orig_idx in enumerate(order):
        result[orig_idx] = adj[rank_0]
    return result


def estimate_min_sample_size(
    effect_size: float,
    *,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> int:
    """Normal-approx minimum n for detecting standardized mean difference."""
    from scipy.stats import norm

    effect = abs(effect_size)
    if effect <= 0:
        return sys.maxsize
    z_alpha = float(norm.ppf(1 - alpha / 2))
    z_power = float(norm.ppf(target_power))
    return int(math.ceil(((z_alpha + z_power) / effect) ** 2))


def power_analysis(
    *,
    effect_size: float,
    n_obs: int,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> PowerAnalysisResult:
    from scipy.stats import norm

    effect = abs(effect_size)
    if effect <= 0 or n_obs <= 0:
        achieved = 0.0
    else:
        z_alpha = float(norm.ppf(1 - alpha / 2))
        achieved = float(norm.cdf(math.sqrt(n_obs) * effect - z_alpha))
    return PowerAnalysisResult(
        effect_size=effect_size,
        n_obs=n_obs,
        alpha=alpha,
        target_power=target_power,
        achieved_power=achieved,
        min_sample_size=estimate_min_sample_size(
            effect_size,
            alpha=alpha,
            target_power=target_power,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ANOVA
# ─────────────────────────────────────────────────────────────────────────────


def run_anova(df: pd.DataFrame, metric: str) -> AnovaResult:
    """2-way ANOVA: metric ~ C(scaler) + C(mask) + C(scaler):C(mask) + C(fold_id).

    statsmodels OLS + Type II SS (anova_lm) 기반.
    Returns AnovaResult with η² per effect.
    """
    from statsmodels.formula.api import ols

    sub = df[["scaler", "mask", "fold", metric]].copy()
    sub = sub.dropna(subset=[metric])
    sub["fold_id"] = sub["fold"].astype(str)

    if len(sub) < 8:
        return AnovaResult(
            metric=metric,
            factor="scaler_mask",
            eta_sq={},
            f_pvalue={},
            ss={},
            n_obs=len(sub),
        )

    formula = f"{metric} ~ C(scaler) + C(mask) + C(scaler):C(mask) + C(fold_id)"
    try:
        model = ols(formula, data=sub).fit()
        from statsmodels.stats.anova import anova_lm

        anova_table = anova_lm(model, typ=2)
    except Exception:
        return AnovaResult(
            metric=metric,
            factor="scaler_mask",
            eta_sq={},
            f_pvalue={},
            ss={},
            n_obs=len(sub),
        )

    ss_total = float(anova_table["sum_sq"].sum())
    eta_sq: dict[str, float] = {}
    f_pvalue: dict[str, float] = {}
    ss_dict: dict[str, float] = {}

    effect_map = {
        "C(scaler)": "scaler",
        "C(mask)": "mask",
        "C(scaler):C(mask)": "interaction",
        "C(fold_id)": "fold_id",
        "Residual": "residual",
    }

    for idx in anova_table.index:
        key = effect_map.get(str(idx), str(idx))
        ss_val = float(anova_table.loc[idx, "sum_sq"])
        ss_dict[key] = ss_val
        if ss_total > 0:
            eta_sq[key] = ss_val / ss_total
        else:
            eta_sq[key] = float("nan")
        pr_col = "PR(>F)"
        if pr_col in anova_table.columns:
            pv = anova_table.loc[idx, pr_col]
            f_pvalue[key] = float(pv) if not pd.isna(pv) else float("nan")

    return AnovaResult(
        metric=metric,
        factor="scaler_mask",
        eta_sq=eta_sq,
        f_pvalue=f_pvalue,
        ss=ss_dict,
        n_obs=len(sub),
        raw=anova_table,
    )


def run_horizon_anova(df: pd.DataFrame, metric: str) -> AnovaResult:
    """1-way ANOVA: metric ~ C(horizon). horizon 은 타겟이 달라 2-way 교차 X."""
    import statsmodels.api as sm  # noqa: F401
    from statsmodels.formula.api import ols

    sub = df[["horizon", metric]].copy()
    sub = sub.dropna(subset=[metric])

    if len(sub) < 4:
        return AnovaResult(
            metric=metric,
            factor="horizon",
            eta_sq={},
            f_pvalue={},
            ss={},
            n_obs=len(sub),
        )

    formula = f"{metric} ~ C(horizon)"
    try:
        model = ols(formula, data=sub).fit()
        from statsmodels.stats.anova import anova_lm

        anova_table = anova_lm(model, typ=1)
    except Exception:
        return AnovaResult(
            metric=metric,
            factor="horizon",
            eta_sq={},
            f_pvalue={},
            ss={},
            n_obs=len(sub),
        )

    ss_total = float(anova_table["sum_sq"].sum())
    eta_sq: dict[str, float] = {}
    f_pvalue: dict[str, float] = {}
    ss_dict: dict[str, float] = {}

    for idx in anova_table.index:
        key = "horizon" if "horizon" in str(idx).lower() else "residual"
        ss_val = float(anova_table.loc[idx, "sum_sq"])
        ss_dict[key] = ss_val
        eta_sq[key] = ss_val / ss_total if ss_total > 0 else float("nan")
        pr_col = "PR(>F)"
        if pr_col in anova_table.columns:
            pv = anova_table.loc[idx, pr_col]
            f_pvalue[key] = float(pv) if not pd.isna(pv) else float("nan")

    return AnovaResult(
        metric=metric,
        factor="horizon",
        eta_sq=eta_sq,
        f_pvalue=f_pvalue,
        ss=ss_dict,
        n_obs=len(sub),
        raw=anova_table,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap CI
# ─────────────────────────────────────────────────────────────────────────────


def bootstrap_ci(
    df: pd.DataFrame,
    metric: str,
    *,
    n_bootstrap: int = 500,
    rng_seed: int = 0,
) -> list[BootstrapCI]:
    """각 spec_id 별 fold-level bootstrap 95% CI.

    fold 단위 재샘플링. CI 하단이 승격 게이트의 보수적 Δ 기준에 사용됨.
    """
    results: list[BootstrapCI] = []
    rng = np.random.default_rng(rng_seed)

    for spec_id, group in df.groupby("spec_id"):
        values = group[metric].dropna().to_numpy(dtype=float)
        if len(values) == 0:
            results.append(
                BootstrapCI(
                    metric=metric,
                    spec_id=str(spec_id),
                    mean=float("nan"),
                    ci_lower=float("nan"),
                    ci_upper=float("nan"),
                    n_bootstrap=n_bootstrap,
                )
            )
            continue
        boot_means = np.array(
            [rng.choice(values, size=len(values), replace=True).mean() for _ in range(n_bootstrap)]
        )
        results.append(
            BootstrapCI(
                metric=metric,
                spec_id=str(spec_id),
                mean=float(values.mean()),
                ci_lower=float(np.percentile(boot_means, 2.5)),
                ci_upper=float(np.percentile(boot_means, 97.5)),
                n_bootstrap=n_bootstrap,
            )
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Promotion gate
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_promotion_gate(
    *,
    hit_rate_delta: float,
    sharpe_delta: float,
    coverage: float,
    masked_ratio: float,
    stability: float,
    hit_rate_ci_lower: float = float("nan"),
    fdr_q: float = float("nan"),
    hit_rate_ci_upper: float = float("nan"),
    sharpe_ci_lower: float = float("nan"),
    sharpe_ci_upper: float = float("nan"),
    baseline_hit_rate_ci_upper: float = float("nan"),
    baseline_sharpe_ci_upper: float = float("nan"),
) -> PromotionGateResult:
    """5개 AND 조건 평가 + CI-strict advisory.

    decision        : hit_rate / Sharpe / coverage / masked_ratio / stability 모두 충족.
                       기존 운영 결정 (변경 없음).
    decision_strict : decision == "promote" AND
                       (signal hit_rate CI 하한 - baseline hit_rate CI 상한) ≥ GATE_HIT_RATE_CI_DELTA_PP AND
                       (signal sharpe CI 하한 - baseline sharpe CI 상한) ≥ GATE_SHARPE_CI_DELTA AND
                       fdr_q ≤ GATE_FDR_Q (NaN 이면 False).
                       overlapping sample 보정 후의 보수적 결정. advisory 로 보고.
    """
    hit_rate_ok = hit_rate_delta >= GATE_HIT_RATE_DELTA_PP
    sharpe_ok = sharpe_delta >= GATE_SHARPE_DELTA
    coverage_ok = coverage >= GATE_MIN_COVERAGE
    masked_ratio_ok = masked_ratio <= GATE_MAX_MASKED_RATIO
    # stability 가 NaN 이면 walk-forward 미산출 predictor (non-hybrid) → 조건 미적용 (pass)
    stability_ok = not math.isfinite(stability) or stability >= GATE_MIN_STABILITY

    if hit_rate_ok and sharpe_ok and coverage_ok and masked_ratio_ok and stability_ok:
        decision = "promote"
    else:
        decision = "research_only"

    def _ci_separated(signal_lower: float, baseline_upper: float, threshold: float) -> bool:
        if not (math.isfinite(signal_lower) and math.isfinite(baseline_upper)):
            return False
        return (signal_lower - baseline_upper) >= threshold

    hit_rate_ci_ok = _ci_separated(
        hit_rate_ci_lower, baseline_hit_rate_ci_upper, GATE_HIT_RATE_CI_DELTA_PP
    )
    sharpe_ci_ok = _ci_separated(sharpe_ci_lower, baseline_sharpe_ci_upper, GATE_SHARPE_CI_DELTA)
    fdr_ok = math.isfinite(fdr_q) and fdr_q <= GATE_FDR_Q

    if decision == "promote" and hit_rate_ci_ok and sharpe_ci_ok and fdr_ok:
        decision_strict = "promote"
    else:
        decision_strict = "research_only"

    return PromotionGateResult(
        decision=decision,
        hit_rate_ok=hit_rate_ok,
        sharpe_ok=sharpe_ok,
        coverage_ok=coverage_ok,
        masked_ratio_ok=masked_ratio_ok,
        stability_ok=stability_ok,
        hit_rate_delta=hit_rate_delta,
        sharpe_delta=sharpe_delta,
        coverage=coverage,
        masked_ratio=masked_ratio,
        stability=stability,
        hit_rate_ci_lower=hit_rate_ci_lower,
        fdr_q=fdr_q,
        hit_rate_ci_upper=hit_rate_ci_upper,
        sharpe_ci_lower=sharpe_ci_lower,
        sharpe_ci_upper=sharpe_ci_upper,
        baseline_hit_rate_ci_upper=baseline_hit_rate_ci_upper,
        baseline_sharpe_ci_upper=baseline_sharpe_ci_upper,
        hit_rate_ci_ok=hit_rate_ci_ok,
        sharpe_ci_ok=sharpe_ci_ok,
        fdr_ok=fdr_ok,
        decision_strict=decision_strict,
    )


# ─────────────────────────────────────────────────────────────────────────────
# vol_regime_v2 Overlay Promotion Gate (P4-T11)
# ─────────────────────────────────────────────────────────────────────────────

# 승격 기준 (check_vol_regime_v2_drift.py와 동기화)
_OVERLAY_GATE_MIN_HIT_RATE = 0.55
_OVERLAY_GATE_P_MAX = 0.10
_OVERLAY_GATE_COV_MIN = 0.45
_OVERLAY_GATE_COV_MAX = 0.70
_OVERLAY_GATE_MIN_RECORDS = 14  # rolling window 최소 일수


@dataclass
class OverlayGateResult:
    """vol_regime_v2 승격 게이트 평가 결과."""

    decision: str  # "promote" | "monitor" | "insufficient_data"
    n_records: int
    rolling_hit_rate: float
    rolling_coverage: float
    rolling_p_median: float
    hit_rate_ok: bool
    coverage_ok: bool
    p_value_ok: bool
    message: str


def evaluate_regime_overlay_gate(
    records: list[dict],
    *,
    window: int = _OVERLAY_GATE_MIN_RECORDS,
) -> OverlayGateResult:
    """vol_regime_v2 drift JSONL 레코드를 분석해 승격 여부를 결정한다.

    records : read_drift_records() 반환값 (시간순 정렬).
    window  : rolling 분석 window (일수). 기본 14일.

    기준:
      - hit_rate mean ≥ 0.55
      - coverage mean ∈ [0.45, 0.70]
      - kept_gt_dropped_pvalue rolling median < 0.10
      → 3개 조건 모두 충족 시 decision="promote"
    """
    n = len(records)
    if n < window:
        return OverlayGateResult(
            decision="insufficient_data",
            n_records=n,
            rolling_hit_rate=float("nan"),
            rolling_coverage=float("nan"),
            rolling_p_median=float("nan"),
            hit_rate_ok=False,
            coverage_ok=False,
            p_value_ok=False,
            message=f"롤링 분석에 최소 {window}일 필요 — 현재 {n}일 기록",
        )

    recent = records[-window:]

    def _vals(key: str) -> list[float]:
        result = []
        for r in recent:
            v = r.get(key)
            if v is None:
                continue
            try:
                f = float(v)
                if math.isfinite(f):
                    result.append(f)
            except (TypeError, ValueError):
                pass
        return result

    hr_vals = _vals("vol_regime_v2_hit_rate")
    cov_vals = _vals("vol_regime_v2_coverage")
    p_vals = _vals("kept_gt_dropped_pvalue")

    rolling_hr = sum(hr_vals) / len(hr_vals) if hr_vals else float("nan")
    rolling_cov = sum(cov_vals) / len(cov_vals) if cov_vals else float("nan")
    rolling_p = sorted(p_vals)[len(p_vals) // 2] if p_vals else float("nan")

    hit_rate_ok = math.isfinite(rolling_hr) and rolling_hr >= _OVERLAY_GATE_MIN_HIT_RATE
    coverage_ok = (
        math.isfinite(rolling_cov) and _OVERLAY_GATE_COV_MIN <= rolling_cov <= _OVERLAY_GATE_COV_MAX
    )
    p_value_ok = math.isfinite(rolling_p) and rolling_p < _OVERLAY_GATE_P_MAX

    if hit_rate_ok and coverage_ok and p_value_ok:
        decision = "promote"
        message = "3개 rolling 기준 충족 — 승격 검토 가능"
    else:
        decision = "monitor"
        failed = []
        if not hit_rate_ok:
            failed.append(f"hit_rate={rolling_hr:.3f} < {_OVERLAY_GATE_MIN_HIT_RATE}")
        if not coverage_ok:
            failed.append(
                f"coverage={rolling_cov:.3f} not in [{_OVERLAY_GATE_COV_MIN},{_OVERLAY_GATE_COV_MAX}]"
            )
        if not p_value_ok:
            failed.append(f"p={rolling_p:.4f} ≥ {_OVERLAY_GATE_P_MAX}")
        message = "조건 미충족: " + "; ".join(failed)

    return OverlayGateResult(
        decision=decision,
        n_records=n,
        rolling_hit_rate=rolling_hr,
        rolling_coverage=rolling_cov,
        rolling_p_median=rolling_p,
        hit_rate_ok=hit_rate_ok,
        coverage_ok=coverage_ok,
        p_value_ok=p_value_ok,
        message=message,
    )


__all__ = [
    "AnovaResult",
    "BootstrapCI",
    "OverlayGateResult",
    "PromotionGateResult",
    "PowerAnalysisResult",
    "GATE_HIT_RATE_DELTA_PP",
    "GATE_SHARPE_DELTA",
    "GATE_MIN_COVERAGE",
    "GATE_MAX_MASKED_RATIO",
    "GATE_MIN_STABILITY",
    "bh_correct",
    "bootstrap_ci",
    "evaluate_promotion_gate",
    "evaluate_regime_overlay_gate",
    "fisher_z",
    "estimate_min_sample_size",
    "power_analysis",
    "run_anova",
    "run_horizon_anova",
]
