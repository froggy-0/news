#!/usr/bin/env python3
"""Voting rule 군 평가 스크립트.

latest.json artifact의 horizon_metrics[7].hit_rates에서 research_rule 행을 추출해
voting rule 성능 요약 테이블을 출력한다.

사용법:
    python scripts/analysis/eval_voting_rules.py \\
        --artifact data/sentiment_join/latest.json \\
        --horizon 7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

_VOTING_LABELS = {
    "vote_vol_sent_fng5_2of3",
    "vote_vol_vix_sent_fng5_3of4",
    "vote_vix_fng_2of2",
    "vol_regime_v2_vix_realized_vol_2of2",
    "vol_regime_v3_vix_realized_vol_ma200_2of3",
    "vix_low_long_only",
}


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return f if f == f else None  # NaN 제거
    except (TypeError, ValueError):
        return None


def _fmt_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "  N/A  "
    return f"{v * 100:>6.{digits}f}%"


def _fmt_f(v: float | None, digits: int = 3) -> str:
    if v is None:
        return "  N/A  "
    return f"{v:>8.{digits}f}"


def _fmt_decision(d: str | None) -> str:
    if d == "promote":
        return "[PROMOTE]"
    if d == "research_only":
        return "[research]"
    if d is None:
        return "        "
    return f"[{d}]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Voting rule 성능 평가")
    parser.add_argument(
        "--artifact",
        type=Path,
        default=PROJECT_ROOT / "data" / "sentiment_join" / "latest.json",
        help="latest.json 경로",
    )
    parser.add_argument("--horizon", type=int, default=7, help="평가 horizon (days)")
    parser.add_argument("--all-rules", action="store_true", help="research_rule=True 행 모두 출력")
    args = parser.parse_args()

    if not args.artifact.exists():
        print(f"[ERROR] artifact 파일 없음: {args.artifact}")
        sys.exit(1)

    try:
        artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 파싱 실패: {e}")
        sys.exit(1)

    horizon_metrics = artifact.get("alpha", {}).get("horizonMetrics", {})
    horizon_key = str(args.horizon)
    horizon = horizon_metrics.get(horizon_key, {})
    if not horizon:
        print(f"[ERROR] horizonMetrics[{horizon_key}] 없음 — v2 artifact 필요")
        sys.exit(1)

    hit_rates: list[dict] = horizon.get("hit_rates", [])
    if not hit_rates:
        print("[ERROR] hit_rates 비어있음")
        sys.exit(1)

    # 일반 baseline hit_rates (bestBaseline 계산용)
    baseline_rows = [r for r in hit_rates if not r.get("research_rule")]
    best_baseline = max(
        (_safe_float(r.get("hit_rate")) or 0.0 for r in baseline_rows),
        default=None,
    )

    # voting rules 필터
    if args.all_rules:
        rows = [r for r in hit_rates if r.get("research_rule")]
    else:
        rows = [r for r in hit_rates if r.get("predictor") in _VOTING_LABELS]

    if not rows:
        print("[INFO] voting rule 행 없음 — v2 artifact 재실행 필요")
        sys.exit(0)

    print(f"\n=== Voting Rule 평가 · horizon={args.horizon}d ===")
    if best_baseline is not None:
        print(f"    best baseline hit_rate: {best_baseline * 100:.1f}%\n")

    header = (
        f"{'predictor':<46} {'hit_rate':>8} {'uplift':>7} "
        f"{'ci_lo':>7} {'ci_hi':>7} {'coverage':>9} {'fdr_q':>7} {'decision':<12} {'strict':<12}"
    )
    print(header)
    print("-" * len(header))

    rows_sorted = sorted(rows, key=lambda r: _safe_float(r.get("hit_rate")) or 0.0, reverse=True)
    for row in rows_sorted:
        predictor = str(row.get("predictor", "?"))[:46]
        hr = _safe_float(row.get("hit_rate"))
        uplift = (hr - best_baseline) if hr is not None and best_baseline is not None else None
        ci_lo = _safe_float(row.get("hit_rate_ci_lower"))
        ci_hi = _safe_float(row.get("hit_rate_ci_upper"))
        cov = _safe_float(row.get("masked_ratio_source") and None or row.get("coverage"))
        fdr_q = _safe_float(row.get("fdr_q"))
        decision = row.get("decision")
        strict = row.get("decision_strict")

        print(
            f"{predictor:<46} {_fmt_pct(hr)} {_fmt_pct(uplift):>7} "
            f"{_fmt_pct(ci_lo):>7} {_fmt_pct(ci_hi):>7} {_fmt_pct(cov):>9} "
            f"{_fmt_f(fdr_q, 3):>7} {_fmt_decision(decision):<12} {_fmt_decision(strict):<12}"
        )

    # kept/dropped diagnostics 요약
    print("\n=== Abstain Filter Diagnostics ===")
    for row in rows_sorted:
        predictor = str(row.get("predictor", "?"))
        diag = row.get("abstain_filter_diagnostics", {})
        if not diag:
            continue
        kept_hr = _safe_float(
            diag.get("kept_baseline_hit_rate") or row.get("kept_baseline_hit_rate")
        )
        dropped_hr = _safe_float(
            diag.get("dropped_baseline_hit_rate") or row.get("dropped_baseline_hit_rate")
        )
        p = _safe_float(diag.get("kept_gt_dropped_pvalue") or row.get("kept_gt_dropped_pvalue"))
        print(
            f"  {predictor[:44]:<44}  kept={_fmt_pct(kept_hr)}  dropped={_fmt_pct(dropped_hr)}  p={_fmt_f(p, 4)}"
        )

    print()


if __name__ == "__main__":
    main()
