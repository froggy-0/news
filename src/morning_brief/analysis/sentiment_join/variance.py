"""Variance decomposition & ANOVA report for outlier-ablation experiments (Phase 4).

주요 함수:
- run_anova(df, metric)    : 2-way C(scaler)*C(mask) + C(fold_id) ANOVA, η² 계산
- run_horizon_anova(df, metric) : 1-way C(horizon) ANOVA
- bootstrap_ci(df, metric) : fold-level bootstrap 95% CI (n=500)
- bh_correct(p_values)     : Benjamini-Hochberg FDR 보정
- fisher_z(r)              : Pearson→Fisher-z 변환
- evaluate_promotion_gate(delta, baseline, ci_lower) : 5개 AND 조건 평가
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Promotion gate 임계값 (design.md 사전 등록)
# ─────────────────────────────────────────────────────────────────────────────

GATE_HIT_RATE_DELTA_PP = 0.02  # hit_rate Δ ≥ +2pp
GATE_SHARPE_DELTA = 0.10  # Sharpe Δ ≥ +0.10
GATE_MAX_MASKED_RATIO = 0.10  # masked_ratio ≤ 10%
GATE_FDR_Q = 0.10  # FDR q < 0.10
GATE_MIN_STABILITY = 0.50  # fold stability ≥ 0.50
GATE_CONDITIONAL_HIT_RATE_PP = 0.01  # CI 하단 ≥ +1pp → conditional_promote


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
    """승격 게이트 평가 결과."""

    decision: str  # "promote" | "conditional_promote" | "research_only"
    hit_rate_ok: bool
    sharpe_ok: bool
    masked_ratio_ok: bool
    fdr_ok: bool
    stability_ok: bool
    # 입력 값 보존
    hit_rate_delta: float
    sharpe_delta: float
    masked_ratio: float
    fdr_q: float
    stability: float
    hit_rate_ci_lower: float


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
    masked_ratio: float,
    fdr_q: float,
    stability: float,
    hit_rate_ci_lower: float,
) -> PromotionGateResult:
    """5개 AND 조건 평가.

    promote             : 5개 모두 충족
    conditional_promote : CI 하단 ≥ +1pp (GATE_CONDITIONAL_HIT_RATE_PP) + 나머지 4개 충족
    research_only       : 그 외
    """
    hit_rate_ok = hit_rate_delta >= GATE_HIT_RATE_DELTA_PP
    sharpe_ok = sharpe_delta >= GATE_SHARPE_DELTA
    masked_ratio_ok = masked_ratio <= GATE_MAX_MASKED_RATIO
    fdr_ok = fdr_q < GATE_FDR_Q
    stability_ok = stability >= GATE_MIN_STABILITY

    if hit_rate_ok and sharpe_ok and masked_ratio_ok and fdr_ok and stability_ok:
        decision = "promote"
    elif (
        hit_rate_ci_lower >= GATE_CONDITIONAL_HIT_RATE_PP
        and sharpe_ok
        and masked_ratio_ok
        and fdr_ok
        and stability_ok
    ):
        decision = "conditional_promote"
    else:
        decision = "research_only"

    return PromotionGateResult(
        decision=decision,
        hit_rate_ok=hit_rate_ok,
        sharpe_ok=sharpe_ok,
        masked_ratio_ok=masked_ratio_ok,
        fdr_ok=fdr_ok,
        stability_ok=stability_ok,
        hit_rate_delta=hit_rate_delta,
        sharpe_delta=sharpe_delta,
        masked_ratio=masked_ratio,
        fdr_q=fdr_q,
        stability=stability,
        hit_rate_ci_lower=hit_rate_ci_lower,
    )


__all__ = [
    "AnovaResult",
    "BootstrapCI",
    "PromotionGateResult",
    "GATE_HIT_RATE_DELTA_PP",
    "GATE_SHARPE_DELTA",
    "GATE_MAX_MASKED_RATIO",
    "GATE_FDR_Q",
    "GATE_MIN_STABILITY",
    "GATE_CONDITIONAL_HIT_RATE_PP",
    "bh_correct",
    "bootstrap_ci",
    "evaluate_promotion_gate",
    "fisher_z",
    "run_anova",
    "run_horizon_anova",
]
