#!/usr/bin/env python3
"""vol_regime_v2 드리프트 추적 JSONL을 분석해 rolling 지표를 출력한다.

14일치 이상 쌓이면:
  - rolling median kept_gt_dropped_pvalue (< 0.10이면 정상)
  - coverage 안정성 (0.45 ~ 0.70이면 정상)
  - hit_rate trend

사용법 (로컬):
    python scripts/analysis/check_vol_regime_v2_drift.py \\
        --jsonl data/sentiment_join/vol_regime_v2_drift.jsonl \\
        --window 14

사용법 (R2):
    python scripts/analysis/check_vol_regime_v2_drift.py --from-r2
    python scripts/analysis/check_vol_regime_v2_drift.py --from-r2 --r2-key analytics/sentiment/vol_regime_v2_drift.jsonl

로컬 → R2 백필 (최초 1회):
    python scripts/analysis/check_vol_regime_v2_drift.py --sync-to-r2
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

_DEFAULT_R2_KEY = "analytics/sentiment/vol_regime_v2_drift.jsonl"


def _run(args: argparse.Namespace) -> None:
    if not args.from_r2 and not args.jsonl.exists():
        print(f"[WARN] drift 파일 없음: {args.jsonl}")
        print("       파이프라인이 최소 1회 실행되어야 생성됩니다.")
        sys.exit(0)

    records = []
    for line in args.jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    n = len(records)
    src_label = f"r2://{args.r2_key or _DEFAULT_R2_KEY}" if args.from_r2 else str(args.jsonl)
    print(f"총 {n}일 기록 (소스: {src_label})\n")

    def _safe_float(v: object) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)  # type: ignore[arg-type]
            return f if f == f else None  # NaN 제거
        except (TypeError, ValueError):
            return None

    # 전체 요약
    print("=== 전체 기록 요약 ===")
    print(f"{'run_date':<12} {'hit_rate':>9} {'coverage':>9} {'kept_p':>10} {'kept_lift':>10}")
    print("-" * 55)
    for r in records[-20:]:  # 최근 20개만 출력
        hr = _safe_float(r.get("vol_regime_v2_hit_rate"))
        cov = _safe_float(r.get("vol_regime_v2_coverage"))
        p = _safe_float(r.get("kept_gt_dropped_pvalue"))
        lift = _safe_float(r.get("kept_baseline_hit_rate_lift"))
        date_str = str(r.get("run_date", "?"))
        hr_str = f"{hr:>9.3f}" if hr is not None else f"{'N/A':>9}"
        cov_str = f" {cov:>9.3f}" if cov is not None else f" {'N/A':>9}"
        p_str = f" {p:>10.4f}" if p is not None else f" {'N/A':>10}"
        lift_str = f" {lift:>10.4f}" if lift is not None else f" {'N/A':>10}"
        print(f"{date_str:<12} {hr_str}{cov_str}{p_str}{lift_str}")

    if n < args.window:
        print(f"\n[INFO] {n}일 기록 — rolling 분석에 {args.window}일 이상 필요")
        if args.from_r2:
            local_path = PROJECT_ROOT / "data" / "sentiment_join" / "vol_regime_v2_drift.jsonl"
            if local_path.exists():
                local_n = sum(
                    1 for ln in local_path.read_text(encoding="utf-8").splitlines() if ln.strip()
                )
                if local_n >= args.window:
                    print(
                        f"\n[TIP] 로컬 파일에 {local_n}일치 기록이 있습니다. "
                        "다음 명령으로 R2에 백필하세요:\n"
                        f"      python scripts/analysis/check_vol_regime_v2_drift.py --sync-to-r2"
                    )
        sys.exit(0)

    # Rolling 분석
    recent = records[-args.window :]
    print(f"\n=== 최근 {args.window}일 Rolling 분석 ===")

    p_vals = [_safe_float(r.get("kept_gt_dropped_pvalue")) for r in recent]
    p_vals_clean = [v for v in p_vals if v is not None]
    rolling_p = sorted(p_vals_clean)[len(p_vals_clean) // 2] if p_vals_clean else None

    cov_vals = [_safe_float(r.get("vol_regime_v2_coverage")) for r in recent]
    cov_vals_clean = [v for v in cov_vals if v is not None]
    rolling_cov = sum(cov_vals_clean) / len(cov_vals_clean) if cov_vals_clean else None

    hr_vals = [_safe_float(r.get("vol_regime_v2_hit_rate")) for r in recent]
    hr_vals_clean = [v for v in hr_vals if v is not None]
    rolling_hr = sum(hr_vals_clean) / len(hr_vals_clean) if hr_vals_clean else None

    if rolling_p is not None:
        status = "OK" if rolling_p < 0.10 else "DRIFT 의심"
        print(f"  kept>dropped p-value median: {rolling_p:.4f}  [{status}]")
    else:
        print("  kept>dropped p-value: N/A")

    if rolling_cov is not None:
        status = "OK" if 0.45 <= rolling_cov <= 0.70 else "OUT OF RANGE"
        print(f"  coverage mean:               {rolling_cov:.3f}    [{status}]")
    else:
        print("  coverage mean: N/A")

    if rolling_hr is not None:
        status = "OK" if rolling_hr >= 0.55 else "BELOW TARGET"
        print(f"  hit_rate mean:               {rolling_hr:.3f}    [{status}]")
    else:
        print("  hit_rate mean: N/A")

    # 승격 가능 여부 preliminary 판단
    print()
    all_ok = (
        rolling_p is not None
        and rolling_p < 0.10
        and rolling_cov is not None
        and 0.45 <= rolling_cov <= 0.70
        and rolling_hr is not None
        and rolling_hr >= 0.55
    )
    if all_ok:
        print("[PROMOTE 후보] 모든 rolling 기준 충족. evaluate_regime_overlay_gate() 실행 고려.")
    else:
        print("[MONITOR] 아직 모든 조건 미충족 — 추적 계속.")


def main() -> None:
    parser = argparse.ArgumentParser(description="vol_regime_v2 drift 분석")
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=PROJECT_ROOT / "data" / "sentiment_join" / "vol_regime_v2_drift.jsonl",
        help="drift JSONL 파일 경로 (로컬)",
    )
    parser.add_argument("--window", type=int, default=14, help="rolling window 일수")
    parser.add_argument("--from-r2", action="store_true", help="R2에서 직접 읽기")
    parser.add_argument(
        "--r2-key",
        default=None,
        help=f"R2 키 오버라이드 (기본값: {_DEFAULT_R2_KEY})",
    )
    parser.add_argument(
        "--sync-to-r2",
        action="store_true",
        help="로컬 JSONL을 R2에 업로드 후 R2 기준으로 분석 실행 (최초 백필 용도)",
    )
    args = parser.parse_args()

    if args.sync_to_r2:
        from morning_brief.analysis.sentiment_join.storage import upload_to_r2
        from morning_brief.r2_env import load_public_r2_env

        r2 = load_public_r2_env()
        local_path = args.jsonl
        if not local_path.exists():
            print(f"[ERROR] 로컬 JSONL 없음: {local_path}")
            sys.exit(1)
        r2_key = args.r2_key or _DEFAULT_R2_KEY
        upload_to_r2(
            local_path,
            r2_key,
            r2_s3_endpoint=r2.s3_endpoint,
            r2_access_key_id=r2.access_key_id,
            r2_secret_access_key=r2.secret_access_key,
            r2_public_bucket=r2.public_bucket,
        )
        print(f"[OK] {local_path} → r2://{r2_key} 업로드 완료")
        args.from_r2 = True  # 이후 R2에서 읽어 분석

    if args.from_r2:
        from morning_brief.analysis.sentiment_join.storage import r2_tempfile
        from morning_brief.r2_env import load_public_r2_env

        r2 = load_public_r2_env()
        r2_key = args.r2_key or _DEFAULT_R2_KEY
        with r2_tempfile(
            r2_key,
            suffix=".jsonl",
            r2_s3_endpoint=r2.s3_endpoint,
            r2_access_key_id=r2.access_key_id,
            r2_secret_access_key=r2.secret_access_key,
            r2_public_bucket=r2.public_bucket,
        ) as tmp:
            args.jsonl = tmp
            _run(args)
    else:
        _run(args)


if __name__ == "__main__":
    main()
