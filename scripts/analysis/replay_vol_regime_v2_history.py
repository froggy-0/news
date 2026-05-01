#!/usr/bin/env python3
"""vol_regime_v2 historical as-of replay.

긴 master parquet 하나를 날짜별 as-of snapshot처럼 잘라 현재 alpha validation을
재실행한다. T+7 target은 as_of 이후 미래 수익률을 보지 않도록 cutoff 이후 행을
NaN 처리한다.

사용법:
    python scripts/analysis/replay_vol_regime_v2_history.py \
        --parquet data/sentiment_join/remote_snapshot/master_20260430.parquet \
        --start-date 2026-04-10 \
        --end-date 2026-04-30
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

_TARGET_HORIZONS: dict[int, str] = {
    7: "btc_fwd_ret_7d",
}
_SPARSE_LABEL = "vol_regime_v2_vix_realized_vol_2of2"


def main() -> None:
    parser = argparse.ArgumentParser(description="vol_regime_v2 history replay")
    parser.add_argument(
        "--parquet",
        type=Path,
        required=True,
        help="긴 기간을 포함한 master parquet 경로",
    )
    parser.add_argument("--start-date", required=True, help="replay 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="replay 종료일 (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "sentiment_join" / "vol_regime_v2_replay",
        help="replay artifact 출력 디렉터리",
    )
    parser.add_argument(
        "--min-history-rows",
        type=int,
        default=180,
        help="alpha validation 실행에 필요한 최소 과거 행 수",
    )
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="날짜별 frontend artifact JSON 저장 생략",
    )
    parser.add_argument(
        "--verbose-validation",
        action="store_true",
        help="alpha validation 내부 경고/진단 출력을 그대로 표시",
    )
    args = parser.parse_args()

    if not args.parquet.exists():
        print(f"[ERROR] parquet 없음: {args.parquet}")
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = args.output_dir / "artifacts"
    if not args.no_artifacts:
        artifact_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.parquet)
    if "date" not in df.columns:
        print("[ERROR] date 컬럼 없음")
        sys.exit(1)

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values("date").reset_index(drop=True)

    start = pd.Timestamp(args.start_date).normalize()
    end = pd.Timestamp(args.end_date).normalize()
    as_of_dates = [
        d
        for d in sorted(
            df.loc[(df["date"] >= start) & (df["date"] <= end), "date"].dropna().unique()
        )
    ]

    records: list[dict[str, Any]] = []
    for as_of in as_of_dates:
        snapshot = _build_as_of_snapshot(df, pd.Timestamp(as_of))
        run_date = pd.Timestamp(as_of).strftime("%Y%m%d")
        if len(snapshot) < args.min_history_rows:
            print(f"[SKIP] {run_date}: rows={len(snapshot)} < {args.min_history_rows}")
            continue

        try:
            artifact = _run_replay(snapshot, run_date, verbose=args.verbose_validation)
        except Exception as exc:
            print(f"[WARN] {run_date}: replay 실패: {exc}")
            continue

        if not args.no_artifacts:
            (artifact_dir / f"{run_date}.json").write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        record = _extract_drift_record(artifact, run_date)
        if _is_valid_record(record):
            records.append(record)
            print(
                "[OK] "
                f"{run_date}: hit={record['vol_regime_v2_hit_rate']:.3f} "
                f"coverage={record['vol_regime_v2_coverage']:.3f} "
                f"p={record['kept_gt_dropped_pvalue']:.4f}"
            )
        else:
            print(f"[SKIP] {run_date}: drift 지표 부족")

    drift_path = args.output_dir / "vol_regime_v2_drift_replayed.jsonl"
    drift_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    summary_path = args.output_dir / "summary.csv"
    pd.DataFrame(records).to_csv(summary_path, index=False)
    latest_path = _write_latest_artifact(args.output_dir, artifact_dir, records, args.no_artifacts)
    print(f"\n[DONE] valid_records={len(records)}")
    print(f"       drift={drift_path}")
    print(f"       summary={summary_path}")
    if latest_path is not None:
        print(f"       latest={latest_path}")


def _build_as_of_snapshot(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    snapshot = df.loc[df["date"] <= as_of].copy()
    for horizon_days, return_col in _TARGET_HORIZONS.items():
        if return_col not in snapshot.columns:
            continue
        target_cutoff = as_of - pd.Timedelta(days=horizon_days)
        snapshot.loc[snapshot["date"] > target_cutoff, return_col] = pd.NA
    return snapshot.reset_index(drop=True)


def _run_replay(snapshot: pd.DataFrame, run_date: str, *, verbose: bool) -> dict[str, Any]:
    from morning_brief.analysis.sentiment_join.frontend_artifact import build_frontend_artifact
    from morning_brief.analysis.sentiment_join.statistical_tests import run_alpha_validation
    from morning_brief.data.etf_storage import build_stats_metadata_payload

    with _validation_output_context(verbose):
        alpha = run_alpha_validation(
            snapshot,
            stationarity_results=None,
            granger_results=None,
            granger_executed=False,
            outlier_mask_summary=None,
        )
    stats = build_stats_metadata_payload(
        run_id=f"replay-sentiment-join-{run_date}",
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        adf={},
        granger_results=[],
        hybrid_indices={},
        granger_executed=False,
        hit_rates=alpha.get("hit_rates"),
        correlations=alpha.get("correlations"),
        backtest=alpha.get("backtest"),
        walk_forward=alpha.get("walk_forward"),
        walk_forward_legacy_1d=alpha.get("walk_forward_legacy_1d"),
        baseline_metrics=alpha.get("baseline_metrics"),
        horizon_metrics=alpha.get("horizon_metrics"),
        walk_forward_horizons=alpha.get("walk_forward_horizons"),
        feature_group_summary=alpha.get("feature_group_summary"),
        baseline_gap_summary=alpha.get("baseline_gap_summary"),
        next_research_candidates=alpha.get("next_research_candidates"),
        outlier_mask_summary=alpha.get("outlier_mask_summary"),
    )
    reference_date = f"{run_date[:4]}-{run_date[4:6]}-{run_date[6:]}"
    return build_frontend_artifact(stats_metadata_bytes=stats, reference_date=reference_date)


@contextlib.contextmanager
def _validation_output_context(verbose: bool):
    if verbose:
        yield
        return

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="An input array is constant; the correlation coefficient is not defined.",
        )
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield


def _extract_drift_record(artifact: dict[str, Any], run_date: str) -> dict[str, Any]:
    alpha = artifact.get("alpha") or {}
    v2 = ((alpha.get("baselineMetrics") or {}).get("7") or {}).get("vol_regime_v2") or {}
    hit_rates = ((alpha.get("horizonMetrics") or {}).get("7") or {}).get("hit_rates") or []
    sparse_row = next(
        (
            row
            for row in hit_rates
            if isinstance(row, dict) and row.get("predictor") == _SPARSE_LABEL
        ),
        {},
    )
    return {
        "run_date": run_date,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "vol_regime_v2_hit_rate": v2.get("hit_rate"),
        "vol_regime_v2_coverage": v2.get("coverage"),
        "vol_regime_v2_sharpe": v2.get("sharpe"),
        "vol_regime_v2_hit_rate_ci_lower": v2.get("hit_rate_ci_lower"),
        "vol_regime_v2_hit_rate_ci_upper": v2.get("hit_rate_ci_upper"),
        "kept_baseline_hit_rate": sparse_row.get("kept_baseline_hit_rate"),
        "dropped_baseline_hit_rate": sparse_row.get("dropped_baseline_hit_rate"),
        "kept_baseline_hit_rate_lift": sparse_row.get("kept_baseline_hit_rate_lift"),
        "kept_gt_dropped_pvalue": sparse_row.get("kept_gt_dropped_pvalue"),
        "kept_n": sparse_row.get("kept_n"),
        "dropped_n": sparse_row.get("dropped_n"),
    }


def _is_valid_record(record: dict[str, Any]) -> bool:
    required = (
        "vol_regime_v2_hit_rate",
        "vol_regime_v2_coverage",
        "kept_gt_dropped_pvalue",
    )
    return all(record.get(key) is not None for key in required)


def _write_latest_artifact(
    output_dir: Path,
    artifact_dir: Path,
    records: list[dict[str, Any]],
    no_artifacts: bool,
) -> Path | None:
    if no_artifacts or not records:
        return None

    from morning_brief.analysis.sentiment_join.pipeline import (
        _apply_vol_regime_v2_overlay_promotion,
    )
    from morning_brief.analysis.sentiment_join.variance import evaluate_regime_overlay_gate

    latest_run_date = str(records[-1]["run_date"])
    source_path = artifact_dir / f"{latest_run_date}.json"
    if not source_path.exists():
        return None

    artifact = json.loads(source_path.read_text(encoding="utf-8"))
    gate_result = evaluate_regime_overlay_gate(records)
    print(f"[GATE] {gate_result.decision}: {gate_result.message}")
    _apply_vol_regime_v2_overlay_promotion(artifact, gate_result)

    latest_path = output_dir / "latest.json"
    latest_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest_path


if __name__ == "__main__":
    main()
