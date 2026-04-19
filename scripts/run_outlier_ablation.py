#!/usr/bin/env python3
"""Outlier Policy × Scaler × Horizon × Index Ablation Runner.

Usage:
    python scripts/run_outlier_ablation.py --master data/sentiment_join/master_YYYYMMDD.parquet
    python scripts/run_outlier_ablation.py --master <path> --out-dir data/sentiment_join/experiments

Output:
    {out_dir}/{run_id}/folds.parquet   — fold-level 지표
    {out_dir}/{run_id}/spec.json       — 실행 config · git sha
    {out_dir}/{run_id}/summary.md      — cell-level 요약 (hit_rate/Sharpe/coverage)

Grid 기본값: 2 scaler × 4 mask × 3 horizon × 2 index = 48 cell.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "nogit"


def main() -> int:
    import pandas as pd

    from morning_brief.analysis.sentiment_join.experiments import (
        ExperimentRunner,
        default_grid,
    )
    from morning_brief.logging_utils import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master",
        type=Path,
        required=True,
        help="raw master_*.parquet 경로 (pre-mask: is_outlier 만 marker, 수치 컬럼은 원본 값 유지)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "sentiment_join" / "experiments",
    )
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument(
        "--horizons",
        type=str,
        default="1,3,7",
        help="쉼표 구분 horizon 리스트 (예: 1,3,7)",
    )
    parser.add_argument(
        "--scalers",
        type=str,
        default="standard,robust",
        help="standard,robust",
    )
    parser.add_argument(
        "--masks",
        type=str,
        default="row,column,winsorize,none",
        help="row,column,winsorize,none",
    )
    parser.add_argument(
        "--indices",
        type=str,
        default="full,core",
        help="full,core",
    )
    args = parser.parse_args()

    if not args.master.exists():
        print(f"❌ master parquet 없음: {args.master}")
        return 2

    print(f"[1/4] master 로드: {args.master}")
    raw = pd.read_parquet(args.master)
    print(f"  - rows: {len(raw)}, date range: {raw['date'].min()} ~ {raw['date'].max()}")

    # grid 구성
    scalers = tuple(s.strip() for s in args.scalers.split(",") if s.strip())
    masks = tuple(m.strip() for m in args.masks.split(",") if m.strip())
    horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
    indices = tuple(i.strip() for i in args.indices.split(",") if i.strip())
    grid = default_grid(
        scalers=scalers,  # type: ignore[arg-type]
        masks=masks,  # type: ignore[arg-type]
        horizons=horizons,
        indices=indices,
    )
    print(f"[2/4] grid: {len(grid)} cells ({scalers} × {masks} × {horizons} × {indices})")

    # run_id
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    sha = _git_sha()
    run_id = f"{ts}-{sha}"
    run_dir = args.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[3/4] run_id = {run_id} → {run_dir}")

    # snapshot spec
    spec_payload = {
        "run_id": run_id,
        "git_sha": sha,
        "generated_at": datetime.now().isoformat(),
        "master_parquet": str(args.master),
        "master_rows": int(len(raw)),
        "train_days": args.train_days,
        "test_days": args.test_days,
        "scalers": list(scalers),
        "masks": list(masks),
        "horizons": list(horizons),
        "indices": list(indices),
        "n_cells": len(grid),
    }
    (run_dir / "spec.json").write_text(
        json.dumps(spec_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 실행
    runner = ExperimentRunner(raw, train_days=args.train_days, test_days=args.test_days)
    print(f"[4/4] 실행 중... ({len(grid)} cells)")
    folds_df = runner.run_many(grid)
    folds_path = run_dir / "folds.parquet"
    folds_df.to_parquet(folds_path, index=False)
    print(f"  - folds.parquet: {len(folds_df)} rows → {folds_path}")

    # 경량 summary.md
    summary = _build_summary(folds_df)
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(f"  - summary.md: {run_dir / 'summary.md'}")

    print(f"\n✅ 완료: {run_dir}")
    return 0


def _build_summary(folds_df):  # type: ignore[no-untyped-def]
    """cell 별 hit_rate/Sharpe/coverage 평균 요약."""
    if folds_df.empty:
        return "# Ablation Summary\n\n(결과 없음)\n"

    agg = (
        folds_df.dropna(subset=["hit_rate"])
        .groupby("spec_id")
        .agg(
            n_folds=("fold", "count"),
            hit_rate=("hit_rate", "mean"),
            cumret=("cumret", "mean"),
            sharpe=("sharpe", "mean"),
            coverage=("coverage", "mean"),
            masked_ratio=("masked_ratio", "first"),
            stability=("stability", "first"),
        )
        .reset_index()
        .sort_values("hit_rate", ascending=False)
    )

    lines = ["# Ablation Summary", "", f"Total cells: {len(agg)}", ""]
    lines.append(
        "| spec_id | n_folds | hit_rate | sharpe | cumret | coverage | masked_ratio | stability |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in agg.iterrows():
        lines.append(
            f"| {r['spec_id']} | {int(r['n_folds'])} | {r['hit_rate']:.3f} | "
            f"{r['sharpe']:.3f} | {r['cumret']:.3f} | {r['coverage']:.3f} | "
            f"{r['masked_ratio']:.3f} | {r['stability']:.3f} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
