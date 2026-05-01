#!/usr/bin/env python3
"""latest.json artifact sanity check.

파이프라인 실행 직후 아래 7개 항목을 검증한다:
  1. CI 필드가 NaN이 아닌지
  2. 점추정값이 CI 내부에 위치하는지
  3. CI 폭이 0인지 (position 0 edge case 경고)
  4. fdr_q가 [0,1] 범위인지
  5. pvalue_vs_baselines가 전부 1.0인지 (baseline mismatch 경고)
  6. bootstrap_n == 0인 셀이 있는지
  7. bootstrap_config 설정값이 기댓값과 일치하는지

종료 코드:
  0 = 정상 (WARNING 있어도 통과)
  1 = ERROR 발생 (CI/CD에서 블로킹 가능)

사용법:
  python scripts/validate_latest_artifact.py [--path data/sentiment_join/latest.json]
  python scripts/build_sentiment_join.py && python scripts/validate_latest_artifact.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_PATH = PROJECT_ROOT / "data" / "sentiment_join" / "latest.json"

EXPECTED_BOOTSTRAP_CONFIG = {
    "method": "circular",
    "block_length": 14,
    "n_bootstrap": 1000,
}

_ERRORS: list[str] = []
_WARNINGS: list[str] = []


def _err(msg: str) -> None:
    _ERRORS.append(msg)
    print(f"[ERROR] {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    _WARNINGS.append(msg)
    print(f"[WARN]  {msg}")


def _is_nan(v: object) -> bool:
    if v is None:
        return True
    try:
        return math.isnan(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _get_bootstrap_cfg(cfg: dict, key: str) -> object:
    aliases = {
        "block_length": "blockLength",
        "n_bootstrap": "nBootstrap",
    }
    return cfg.get(key, cfg.get(aliases.get(key, key)))


def _get_gate_value(gate: dict, key: str) -> object:
    aliases = {
        "decision_promote_count": "decisionPromoteCount",
        "decision_strict_promote_count": "decisionStrictPromoteCount",
    }
    return gate.get(key, gate.get(aliases.get(key, key), 0))


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _has_no_exposure(row: dict) -> bool:
    payoff = row.get("payoff_diagnostics")
    if not isinstance(payoff, dict):
        return False
    exposure = payoff.get("exposure_ratio")
    try:
        return float(exposure) == 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def check_hit_rate_rows(rows: list[dict]) -> None:
    """개별 hit_rate row에 대해 5개 항목 검증."""
    for row in rows:
        pred = row.get("predictor", "?")

        # Check 1: CI 필드가 None/NaN이 아닌지
        for field in ("hit_rate_ci_lower", "hit_rate_ci_upper"):
            if _is_nan(row.get(field)):
                _err(f"{pred}: {field}가 NaN — bootstrap 미실행 또는 데이터 부족 가능성")
        for field in ("sharpe_ci_lower", "sharpe_ci_upper"):
            if not _is_nan(row.get(field)):
                continue
            if _is_nan(row.get("strategy_sharpe")) and _has_no_exposure(row):
                _warn(f"{pred}: {field}=NaN — exposure=0이라 Sharpe CI 정의 불가")
            else:
                _err(f"{pred}: {field}가 NaN — bootstrap 미실행 또는 데이터 부족 가능성")

        # Check 2: 점추정이 CI 내부에 있는지
        hr = row.get("hit_rate")
        lo = row.get("hit_rate_ci_lower")
        hi = row.get("hit_rate_ci_upper")
        if not (_is_nan(hr) or _is_nan(lo) or _is_nan(hi)):
            if not (float(lo) <= float(hr) <= float(hi)):  # type: ignore[arg-type]
                _err(f"{pred}: hit_rate={hr:.3f}이 CI [{lo:.3f}, {hi:.3f}] 밖에 있음")

        # Check 3: CI 폭이 0 (position 0 edge case)
        if not (_is_nan(lo) or _is_nan(hi)):
            if abs(float(hi) - float(lo)) < 1e-9:  # type: ignore[arg-type]
                _warn(f"{pred}: hit_rate CI 폭=0 — position 0 edge case 가능성")

        # Check 4: fdr_q 범위
        q = row.get("fdr_q")
        if not _is_nan(q):
            q_f = float(q)  # type: ignore[arg-type]
            if not (0.0 <= q_f <= 1.0):
                _err(f"{pred}: fdr_q={q_f:.3f}이 [0,1] 범위 밖")

        # Check 5: pvalue_vs_baselines가 전부 1.0
        pvals = row.get("pvalue_vs_baselines")
        if isinstance(pvals, (int, float)) and not _is_nan(pvals):
            # 단일 값인 경우
            if abs(float(pvals) - 1.0) < 1e-9:
                _warn(f"{pred}: pvalue_vs_baselines==1.0 — baseline paired bootstrap 실패 가능성")
        elif isinstance(pvals, dict) and pvals:
            if all(not _is_nan(v) and abs(float(v) - 1.0) < 1e-9 for v in pvals.values()):
                _warn(f"{pred}: 모든 pvalue_vs_baselines==1.0 — baseline alignment 실패 가능성")

        # Check 6: bootstrap_n == 0
        bn = row.get("bootstrap_n", -1)
        if bn == 0:
            _err(f"{pred}: bootstrap_n==0 — bootstrap이 스킵됨 (입력 배열 비어 있음)")


def check_bootstrap_config(cfg: dict) -> None:
    """bootstrap_config 설정값 검증."""
    for key, expected in EXPECTED_BOOTSTRAP_CONFIG.items():
        actual = _get_bootstrap_cfg(cfg, key)
        if actual != expected:
            _warn(f"bootstrap_config.{key}={actual!r} (기대값: {expected!r})")


def check_gate_stats(data: dict) -> None:
    """decision vs decision_strict 갭 경고."""
    gate = data.get("alpha", {}).get("gateStats", {})
    if not gate:
        return
    gap = _as_int(_get_gate_value(gate, "gap"))
    decision_n = _as_int(_get_gate_value(gate, "decision_promote_count"))
    strict_n = _as_int(_get_gate_value(gate, "decision_strict_promote_count"))
    print(
        f"[INFO]  gateStats: decision_promote={decision_n}, decision_strict_promote={strict_n}, gap={gap}"
    )
    if gap > 5:
        _warn(f"decision vs decision_strict gap={gap} — 기존 alpha 후보 통계적 강도 재검토 필요")
    if decision_n > 0 and strict_n == 0:
        _warn("decision_strict promote=0 — 모든 후보가 CI/FDR 불통과")


def check_vol_regime_v2(data: dict) -> None:
    """vol_regime_v2 baseline metrics 기본 검증."""
    bm = data.get("alpha", {}).get("baselineMetrics", {}).get("7", {})
    v2 = bm.get("vol_regime_v2")
    if v2 is None:
        _warn(
            "baselineMetrics[7].vol_regime_v2 없음 — realized-vol 컬럼 누락 또는 계산 실패 가능성"
        )
        return
    cov = v2.get("coverage", 0.0)
    if cov == 0.0:
        _err("vol_regime_v2 coverage=0 — threshold 계산 실패 가능성")
    elif cov > 0.80:
        _warn(
            f"vol_regime_v2 coverage={cov:.2%} > 80% — sparse overlay가 아닌 일반 baseline처럼 변질 가능성"
        )


def check_sparse_rules(data: dict) -> None:
    """research_rule sparse rows의 kept/dropped 검정 필드 검증."""
    hit_rates = data.get("alpha", {}).get("horizonMetrics", {}).get("7", {}).get("hit_rates", [])
    for row in hit_rates:
        if not row.get("research_rule"):
            continue
        pred = row.get("predictor", "?")
        kept_n = row.get("kept_n")
        dropped_n = row.get("dropped_n")
        p = row.get("kept_gt_dropped_pvalue")
        if kept_n == 0:
            _warn(f"research sparse {pred}: kept_n==0 — signal이 전부 abstain")
        if dropped_n == 0:
            _warn(
                f"research sparse {pred}: dropped_n==0 — filter가 baseline과 동일해 kept/dropped 검정 불가"
            )
        if _is_nan(p):
            _warn(f"research sparse {pred}: kept_gt_dropped_pvalue=NaN")


def run_checks(path: Path) -> int:
    """모든 검증 실행. 0=정상, 1=오류."""
    if not path.exists():
        _err(f"artifact 파일을 찾을 수 없음: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    hit_rates = data.get("alpha", {}).get("horizonMetrics", {}).get("7", {}).get("hit_rates", [])

    if not hit_rates:
        _err("horizonMetrics[7].hit_rates가 비어 있음 — 파이프라인 산출물 이상")
        return 1

    print(f"[INFO]  검증 대상: {path} ({len(hit_rates)}개 predictor rows)")

    # 개별 row 검증
    check_hit_rate_rows(hit_rates)

    # bootstrap_config 검증
    cfg = data.get("bootstrapConfig") or data.get("bootstrap_config") or {}
    check_bootstrap_config(cfg)

    # gate stats 검증
    check_gate_stats(data)

    # vol_regime_v2 검증
    check_vol_regime_v2(data)

    # sparse rules 검증
    check_sparse_rules(data)

    if _ERRORS:
        print(
            f"\n[SUMMARY] ERROR {len(_ERRORS)}개, WARNING {len(_WARNINGS)}개 — 파이프라인 출력 확인 필요"
        )
        return 1

    print(f"\n[SUMMARY] OK — WARNING {len(_WARNINGS)}개 (ERROR 없음)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="latest.json artifact sanity check")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_ARTIFACT_PATH,
        help="검증할 latest.json 경로",
    )
    args = parser.parse_args()
    sys.exit(run_checks(args.path))


if __name__ == "__main__":
    main()
