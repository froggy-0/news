#!/usr/bin/env python3
"""R2 데이터 통합 모니터링 스크립트.

로컬 파일 없이 R2에 올라간 최신 데이터로 4가지 분석을 순서대로 실행한다.

사용법:
    python scripts/monitor_r2.py                       # 전체 4개 검사
    python scripts/monitor_r2.py --checks drift,voting  # 일부 선택
    python scripts/monitor_r2.py --checks cost          # 단일 검사

검사 목록:
    drift   - vol_regime_v2 드리프트 rolling 분석 (14일 기록 필요)
    voting  - Voting rule coverage / hit_rate 평가
    cost    - 거래비용 민감도 및 breakeven fee 분석
    acf     - Bootstrap block_length ACF 검증
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "analysis"

_CHECKS: dict[str, tuple[str, list[str]]] = {
    "drift": ("check_vol_regime_v2_drift.py", ["--from-r2"]),
    "voting": ("eval_voting_rules.py", ["--from-r2", "--all-rules"]),
    "cost": ("vol_regime_v2_cost_sensitivity.py", ["--from-r2"]),
    "acf": ("check_acf_block_length.py", ["--from-r2"]),
}

_CHECK_NAMES = list(_CHECKS.keys())


def _divider(title: str) -> None:
    line = "=" * 60
    print(f"\n{line}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{line}\n", flush=True)


def run_check(name: str, extra_args: list[str]) -> int:
    script_file, default_args = _CHECKS[name]
    script_path = SCRIPTS_DIR / script_file
    cmd = [sys.executable, str(script_path)] + default_args + extra_args
    result = subprocess.run(cmd, check=False)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="R2 데이터 통합 모니터링")
    parser.add_argument(
        "--checks",
        default=",".join(_CHECK_NAMES),
        help=f"실행할 검사 (콤마 구분, 기본값: 전체). 선택: {', '.join(_CHECK_NAMES)}",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=14,
        help="drift rolling window 일수 (기본값: 14)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=7,
        help="voting rule 평가 horizon (기본값: 7)",
    )
    parser.add_argument(
        "--sync-drift",
        action="store_true",
        help="drift 검사 전 로컬 JSONL을 R2에 백필 업로드 (최초 1회 권장)",
    )
    args = parser.parse_args()

    requested = [c.strip() for c in args.checks.split(",") if c.strip()]
    unknown = [c for c in requested if c not in _CHECKS]
    if unknown:
        print(f"[ERROR] 알 수 없는 검사: {unknown}. 선택 가능: {_CHECK_NAMES}")
        sys.exit(1)

    results: dict[str, int] = {}
    for name in requested:
        extra: list[str] = []
        if name == "drift":
            extra = ["--window", str(args.window)]
            if args.sync_drift:
                extra = ["--sync-to-r2", "--window", str(args.window)]
        elif name == "voting":
            extra = ["--horizon", str(args.horizon)]

        _divider(f"[{name.upper()}] {_CHECKS[name][0]}")
        rc = run_check(name, extra)
        results[name] = rc
        if rc != 0:
            print(f"\n[SKIP] {name} 검사 비정상 종료 (exit code {rc})")

    # 최종 요약
    _divider("요약")
    all_ok = True
    for name, rc in results.items():
        status = "OK" if rc == 0 else f"FAIL (exit {rc})"
        print(f"  {name:<10} {status}")
        if rc != 0:
            all_ok = False
    print()
    if all_ok:
        print("[완료] 모든 검사 정상 종료.")
    else:
        print("[주의] 일부 검사 실패 — 위 출력을 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
