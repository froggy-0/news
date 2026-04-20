#!/usr/bin/env python3
"""Variance Decomposition & Promotion Report Generator.

Usage:
    python scripts/variance_report.py --run-dir data/sentiment_join/experiments/{run_id}
    python scripts/variance_report.py --run-dir data/sentiment_join/experiments/{run_id} \\
        --baseline standard-row-T1-full

Output (모두 --run-dir 아래에 생성):
    report.md       — 전체 요약 + 승격 게이트 결론
    waterfall.md    — driver 기여도 분해 waterfall
    anova.json      — ANOVA η², p-value, FDR q-value 원시 데이터
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


BASELINE_SPEC_ID = "standard-row-T1-full"
METRICS = ["hit_rate", "sharpe", "coverage", "masked_ratio", "stability"]
BOOTSTRAP_N = 500


def _load_folds(run_dir: Path) -> Any:
    import pandas as pd

    folds_path = run_dir / "folds.parquet"
    if not folds_path.exists():
        raise FileNotFoundError(f"folds.parquet 없음: {folds_path}")
    return pd.read_parquet(folds_path)


def _cell_means(folds: Any) -> Any:
    """spec_id 별 fold 평균."""
    return (
        folds.dropna(subset=["hit_rate"])
        .groupby("spec_id")
        .agg(
            scaler=("scaler", "first"),
            mask=("mask", "first"),
            horizon=("horizon", "first"),
            index_name=("index_name", "first"),
            n_folds=("fold", "count"),
            hit_rate=("hit_rate", "mean"),
            sharpe=("sharpe", "mean"),
            coverage=("coverage", "mean"),
            masked_ratio=("masked_ratio", "first"),
            stability=("stability", "first"),
        )
        .reset_index()
    )


def _approach_label(spec_id: str, index_name: str) -> str:
    lower = f"{spec_id} {index_name}".lower()
    if any(
        token in lower for token in ("always_up", "contrarian", "momo", "vol_regime", "baseline")
    ):
        return "baseline"
    if any(token in lower for token in ("logistic", "elastic", "lightgbm", "lgbm", "model")):
        return "model"
    return "hybrid"


def _lineage_summary(run_dir: Path) -> dict[str, list[str]]:
    candidates = (run_dir / "tracking.json", run_dir / "backfill_manifest.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        lineage = payload.get("lineage") or payload.get("column_lineage") or {}
        if isinstance(lineage, dict):
            return {
                str(key): sorted(str(v) for v in values)
                for key, values in lineage.items()
                if isinstance(values, list)
            }
    return {}


def _build_anova_json(folds: Any) -> dict:
    from morning_brief.analysis.sentiment_join.variance import (
        bh_correct,
        run_anova,
        run_horizon_anova,
    )

    out: dict = {}
    for metric in ["hit_rate", "sharpe", "coverage"]:
        anova = run_anova(folds, metric)
        horizon_anova = run_horizon_anova(folds, metric)

        p_vals = list(anova.f_pvalue.values())
        q_vals = bh_correct(p_vals)
        q_map = {k: q for k, q in zip(anova.f_pvalue.keys(), q_vals)}

        out[metric] = {
            "scaler_mask_anova": {
                "eta_sq": anova.eta_sq,
                "f_pvalue": anova.f_pvalue,
                "bh_q": q_map,
                "ss": anova.ss,
                "n_obs": anova.n_obs,
            },
            "horizon_anova": {
                "eta_sq": horizon_anova.eta_sq,
                "f_pvalue": horizon_anova.f_pvalue,
                "ss": horizon_anova.ss,
                "n_obs": horizon_anova.n_obs,
            },
        }
    return out


def _build_bootstrap(folds: Any) -> dict:
    """spec_id별 hit_rate bootstrap CI."""
    from morning_brief.analysis.sentiment_join.variance import bootstrap_ci

    cis = bootstrap_ci(folds, "hit_rate", n_bootstrap=BOOTSTRAP_N)
    return {
        ci.spec_id: {"mean": ci.mean, "ci_lower": ci.ci_lower, "ci_upper": ci.ci_upper}
        for ci in cis
    }


def _evaluate_gate(
    cell_means: Any,
    baseline_id: str,
    bootstrap_map: dict,
    anova_data: dict,
) -> list[dict]:
    from morning_brief.analysis.sentiment_join.variance import evaluate_promotion_gate

    baseline = cell_means[cell_means["spec_id"] == baseline_id]
    if baseline.empty:
        return []

    base_hit = float(baseline["hit_rate"].iloc[0])
    base_sharpe = float(baseline["sharpe"].iloc[0])

    # hit_rate ANOVA 에서 scaler+mask 결합 q-value (보수적: 최대 q)
    hit_anova = anova_data.get("hit_rate", {}).get("scaler_mask_anova", {})
    q_values = hit_anova.get("bh_q", {})
    treatment_q = max(
        (v for k, v in q_values.items() if k not in ("residual", "fold_id") and v == v),
        default=float("nan"),
    )

    results = []
    for _, row in cell_means.iterrows():
        spec_id = str(row["spec_id"])
        if spec_id == baseline_id:
            continue
        hit_delta = float(row["hit_rate"]) - base_hit
        sharpe_delta = float(row["sharpe"]) - base_sharpe
        masked = float(row["masked_ratio"])
        stability = float(row["stability"])
        ci_lower = bootstrap_map.get(spec_id, {}).get("ci_lower", float("nan"))
        ci_lower_delta = ci_lower - base_hit if ci_lower == ci_lower else float("nan")

        gate = evaluate_promotion_gate(
            hit_rate_delta=hit_delta,
            sharpe_delta=sharpe_delta,
            masked_ratio=masked,
            fdr_q=treatment_q,
            stability=stability,
            hit_rate_ci_lower=ci_lower_delta,
        )
        results.append(
            {
                "spec_id": spec_id,
                "hit_rate_delta": hit_delta,
                "sharpe_delta": sharpe_delta,
                "masked_ratio": masked,
                "stability": stability,
                "fdr_q": treatment_q,
                "ci_lower_delta": ci_lower_delta,
                "decision": gate.decision,
            }
        )
    return sorted(results, key=lambda r: -r["hit_rate_delta"])


def _build_report_md(
    run_dir: Path,
    cell_means: Any,
    gate_results: list[dict],
    anova_data: dict,
    baseline_id: str,
) -> str:
    lines = ["# Ablation Variance Report", ""]
    lines.append(f"**run_dir**: `{run_dir}`  ")
    lines.append(f"**baseline**: `{baseline_id}`  ")
    lines.append(f"**cells**: {len(cell_means)}  ")
    lines.append("")

    # 승격 게이트 요약
    promote = [r for r in gate_results if r["decision"] == "promote"]
    conditional = [r for r in gate_results if r["decision"] == "conditional_promote"]
    research = [r for r in gate_results if r["decision"] == "research_only"]
    lines.append("## Promotion Gate Summary")
    lines.append("")
    lines.append(f"- **promote**: {len(promote)}")
    lines.append(f"- **conditional_promote**: {len(conditional)}")
    lines.append(f"- **research_only**: {len(research)}")
    lines.append("")

    if promote:
        lines.append("### Promoted Treatments")
        lines.append("")
        lines.append("| spec_id | hit_rate Δ | sharpe Δ | masked | stability | q |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for r in promote:
            lines.append(
                f"| {r['spec_id']} | {r['hit_rate_delta']:+.4f} | "
                f"{r['sharpe_delta']:+.4f} | {r['masked_ratio']:.3f} | "
                f"{r['stability']:.3f} | {r['fdr_q']:.4f} |"
            )
        lines.append("")

    # 전체 cell 테이블
    lines.append("## All Cells (sorted by hit_rate Δ)")
    lines.append("")
    lines.append("| spec_id | hit_rate | sharpe | coverage | masked_ratio | stability | decision |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for _, row in cell_means.sort_values("hit_rate", ascending=False).iterrows():
        sid = str(row["spec_id"])
        dec = next((r["decision"] for r in gate_results if r["spec_id"] == sid), "baseline")
        lines.append(
            f"| {sid} | {row['hit_rate']:.4f} | {row['sharpe']:.4f} | "
            f"{row['coverage']:.4f} | {row['masked_ratio']:.4f} | "
            f"{row['stability']:.4f} | {dec} |"
        )
    lines.append("")

    power = _build_power_summary(cell_means, baseline_id)
    if power:
        lines.append("## Sample Size / Power")
        lines.append("")
        lines.append("| spec_id | effect size | folds | achieved power | min n @80% |")
        lines.append("|---|---:|---:|---:|---:|")
        for row in power[:10]:
            lines.append(
                f"| {row['spec_id']} | {row['effect_size']:+.4f} | "
                f"{row['n_obs']} | {row['achieved_power']:.3f} | {row['min_sample_size']} |"
            )
        lines.append("")

    lines.extend(_build_index_family_section(cell_means))
    lines.extend(_build_approach_section(cell_means))
    lines.extend(_build_lineage_section(run_dir))

    # ANOVA 요약
    lines.append("## ANOVA Effect Sizes (η²)")
    lines.append("")
    lines.append("| metric | scaler η² | mask η² | interaction η² | horizon η² |")
    lines.append("|---|---:|---:|---:|---:|")
    for metric in ["hit_rate", "sharpe", "coverage"]:
        sm = anova_data.get(metric, {}).get("scaler_mask_anova", {})
        ha = anova_data.get(metric, {}).get("horizon_anova", {})
        eta = sm.get("eta_sq", {})
        h_eta = ha.get("eta_sq", {})
        lines.append(
            f"| {metric} | {eta.get('scaler', float('nan')):.4f} | "
            f"{eta.get('mask', float('nan')):.4f} | "
            f"{eta.get('interaction', float('nan')):.4f} | "
            f"{h_eta.get('horizon', float('nan')):.4f} |"
        )
    lines.append("")

    return "\n".join(lines)


def _build_index_family_section(cell_means: Any) -> list[str]:
    if "index_name" not in cell_means.columns or cell_means.empty:
        return []
    grouped = (
        cell_means.groupby("index_name")
        .agg(
            cells=("spec_id", "count"),
            hit_rate=("hit_rate", "mean"),
            sharpe=("sharpe", "mean"),
            coverage=("coverage", "mean"),
        )
        .reset_index()
        .sort_values("hit_rate", ascending=False)
    )
    lines = ["## Index Family Comparison", ""]
    lines.append("| index | cells | hit_rate | sharpe | coverage |")
    lines.append("|---|---:|---:|---:|---:|")
    for _, row in grouped.iterrows():
        lines.append(
            f"| {row['index_name']} | {int(row['cells'])} | {row['hit_rate']:.4f} | "
            f"{row['sharpe']:.4f} | {row['coverage']:.4f} |"
        )
    lines.append("")
    return lines


def _build_approach_section(cell_means: Any) -> list[str]:
    if cell_means.empty:
        return []
    work = cell_means.copy()
    work["approach"] = [
        _approach_label(str(row["spec_id"]), str(row.get("index_name", "")))
        for _, row in work.iterrows()
    ]
    grouped = (
        work.groupby("approach")
        .agg(
            cells=("spec_id", "count"),
            hit_rate=("hit_rate", "mean"),
            sharpe=("sharpe", "mean"),
            stability=("stability", "mean"),
        )
        .reset_index()
        .sort_values("hit_rate", ascending=False)
    )
    lines = ["## Baseline / Model Comparison", ""]
    lines.append("| approach | cells | hit_rate | sharpe | stability |")
    lines.append("|---|---:|---:|---:|---:|")
    for _, row in grouped.iterrows():
        lines.append(
            f"| {row['approach']} | {int(row['cells'])} | {row['hit_rate']:.4f} | "
            f"{row['sharpe']:.4f} | {row['stability']:.4f} |"
        )
    lines.append("")
    return lines


def _build_lineage_section(run_dir: Path) -> list[str]:
    lineage = _lineage_summary(run_dir)
    if not lineage:
        return []
    lines = ["## Lineage Summary", ""]
    lines.append("| column | sources |")
    lines.append("|---|---|")
    for column, sources in sorted(lineage.items()):
        lines.append(f"| {column} | {', '.join(sources)} |")
    lines.append("")
    return lines


def _build_power_summary(cell_means: Any, baseline_id: str) -> list[dict]:
    from morning_brief.analysis.sentiment_join.variance import power_analysis

    baseline = cell_means[cell_means["spec_id"] == baseline_id]
    if baseline.empty:
        return []
    base_hit = float(baseline["hit_rate"].iloc[0])
    rows = []
    for _, row in cell_means.iterrows():
        sid = str(row["spec_id"])
        if sid == baseline_id:
            continue
        effect = float(row["hit_rate"]) - base_hit
        result = power_analysis(effect_size=effect, n_obs=int(row["n_folds"]))
        rows.append(
            {
                "spec_id": sid,
                "effect_size": effect,
                "n_obs": result.n_obs,
                "achieved_power": result.achieved_power,
                "min_sample_size": result.min_sample_size,
            }
        )
    return sorted(rows, key=lambda r: -abs(r["effect_size"]))


def _build_waterfall_md(
    cell_means: Any,
    baseline_id: str,
    anova_data: dict,
) -> str:
    """Driver별 Δ 기여도 waterfall."""
    baseline = cell_means[cell_means["spec_id"] == baseline_id]
    if baseline.empty:
        return "# Waterfall\n\n(baseline 없음)\n"

    base_hit = float(baseline["hit_rate"].iloc[0])

    # driver별 한계 기여: 각 축 marginal mean vs baseline
    def _marginal_delta(col: str, value: object) -> float:
        sub = cell_means[cell_means[col] == value]["hit_rate"]
        if sub.empty:
            return float("nan")
        return float(sub.mean()) - base_hit

    scaler_vals = cell_means["scaler"].unique()
    mask_vals = cell_means["mask"].unique()
    horizon_vals = cell_means["horizon"].unique()

    scaler_deltas = {str(v): _marginal_delta("scaler", v) for v in scaler_vals}
    mask_deltas = {str(v): _marginal_delta("mask", v) for v in mask_vals}
    horizon_deltas = {str(v): _marginal_delta("horizon", v) for v in horizon_vals}

    # ANOVA η² (interaction 포함)
    sm = anova_data.get("hit_rate", {}).get("scaler_mask_anova", {})
    eta = sm.get("eta_sq", {})

    lines = ["# Waterfall — hit_rate Driver Decomposition", ""]
    lines.append(f"Baseline (`{baseline_id}`): hit_rate = {base_hit:.4f}")
    lines.append("")

    lines.append("## Scaler Effect")
    lines.append(f"η² = {eta.get('scaler', float('nan')):.4f}")
    lines.append("")
    lines.append("| scaler | Δ hit_rate |")
    lines.append("|---|---:|")
    for k, v in scaler_deltas.items():
        lines.append(f"| {k} | {v:+.4f} |")
    lines.append("")

    lines.append("## Mask Effect")
    lines.append(f"η² = {eta.get('mask', float('nan')):.4f}")
    lines.append("")
    lines.append("| mask | Δ hit_rate |")
    lines.append("|---|---:|")
    for k, v in mask_deltas.items():
        lines.append(f"| {k} | {v:+.4f} |")
    lines.append("")

    lines.append("## Horizon Effect")
    ha = anova_data.get("hit_rate", {}).get("horizon_anova", {})
    h_eta = ha.get("eta_sq", {})
    lines.append(f"η² = {h_eta.get('horizon', float('nan')):.4f}")
    lines.append("")
    lines.append("| horizon | Δ hit_rate |")
    lines.append("|---|---:|")
    for k, v in horizon_deltas.items():
        lines.append(f"| T+{k} | {v:+.4f} |")
    lines.append("")

    lines.append("## Interaction Effect")
    lines.append(f"η² = {eta.get('interaction', float('nan')):.4f}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="experiments/{run_id} 디렉토리 경로",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=BASELINE_SPEC_ID,
        help=f"기준 spec_id (기본: {BASELINE_SPEC_ID})",
    )
    args = parser.parse_args()

    run_dir: Path = args.run_dir.resolve()
    if not run_dir.is_dir():
        print(f"❌ run-dir 없음: {run_dir}")
        return 2

    print(f"[1/5] folds 로드: {run_dir}")
    folds = _load_folds(run_dir)
    print(f"  - rows: {len(folds)}, specs: {folds['spec_id'].nunique()}")

    print("[2/5] cell 평균 집계")
    cell_means = _cell_means(folds)

    print("[3/5] ANOVA + FDR 계산")
    anova_data = _build_anova_json(folds)
    anova_path = run_dir / "anova.json"
    anova_path.write_text(
        json.dumps(anova_data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"  - anova.json → {anova_path}")

    print("[4/5] Bootstrap CI 계산")
    bootstrap_map = _build_bootstrap(folds)

    print("[5/5] 리포트 생성")
    gate_results = _evaluate_gate(cell_means, args.baseline, bootstrap_map, anova_data)
    report_md = _build_report_md(run_dir, cell_means, gate_results, anova_data, args.baseline)
    waterfall_md = _build_waterfall_md(cell_means, args.baseline, anova_data)

    (run_dir / "report.md").write_text(report_md, encoding="utf-8")
    (run_dir / "waterfall.md").write_text(waterfall_md, encoding="utf-8")

    print(f"\n✅ 완료: {run_dir}")
    print("   report.md / waterfall.md / anova.json")

    # 결정 요약
    promote = [r for r in gate_results if r["decision"] == "promote"]
    cond = [r for r in gate_results if r["decision"] == "conditional_promote"]
    print(
        f"\n승격 게이트: promote={len(promote)}, conditional={len(cond)}, "
        f"research_only={len(gate_results) - len(promote) - len(cond)}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
