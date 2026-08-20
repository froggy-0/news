"""레버리지 여부 진단 — 실제 수익분포에서 Kelly 최적비율 역산 (2026-08-20).

질문: 선물 트랙에 레버리지를 쓸 근거가 있나? (현재 1x, Phase A에서 사용자 결정 후 미검토)

방법: 레버리지는 알파를 만들지 않고 μ와 σ를 같은 배수로 늘린다. 성장률 최적 비율은
Kelly f* = μ/σ²(거래당 로그성장 최대화). f* < 현재 사이징이면 레버리지는커녕 축소가
정답이고, f*가 음수면 그 전략은 방향 자체가 틀린 것.

주의(문헌): full Kelly는 50%+ 드로다운이 일상이고, μ 추정 오차가 그대로 레버리지 오차로
증폭된다(μ를 50% 과대추정 → 최적 레버리지 50% 과대). 그래서 실무는 half-Kelly 이하를 쓴다.
이 스크립트는 half-Kelly도 함께 출력한다.

읽기 전용 — 라이브 청산 거래 + (옵션) 백테스트 분포 양쪽에서 계산.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from arena import parameters  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_criteria as ec  # noqa: E402


def kelly(rets: list[float]) -> tuple[float, float, float, float]:
    """(f*, mean, sd, SR/trade). f* = μ/σ² — 거래당 로그성장 최대 비율."""
    if len(rets) < 2:
        return 0.0, 0.0, 0.0, 0.0
    mu = statistics.mean(rets)
    sd = statistics.stdev(rets)
    if sd <= 0:
        return 0.0, mu, 0.0, 0.0
    return mu / (sd**2), mu, sd, mu / sd


def kelly_ci(rets: list[float], *, n_resamples: int = 3000, seed: int = 42) -> tuple[float, float]:
    """f*의 부트스트랩 95% CI — 점추정만 보면 소표본에서 무의미한 값이 나온다."""
    if len(rets) < 3:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    arr = np.asarray(rets, dtype=float)
    draws = rng.choice(arr, size=(n_resamples, arr.size), replace=True)
    mu = draws.mean(axis=1)
    var = draws.var(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        fs = np.where(var > 0, mu / var, np.nan)
    fs = fs[np.isfinite(fs)]
    if fs.size == 0:
        return float("nan"), float("nan")
    return float(np.percentile(fs, 2.5)), float(np.percentile(fs, 97.5))


def report(label: str, groups: dict[str, list[float]], weights: dict[str, list[float]]) -> None:
    print(f"\n===== {label} =====")
    print(
        f"{'algo':16} {'n':>4} {'평균%':>7} {'SR/T':>8} {'Kelly f*':>10} "
        f"{'f* 95%CI':>22} {'MDE_SR':>7} {'현재비중':>7} 판정"
    )
    for algo in sorted(groups):
        rets = groups[algo]
        f, mu, sd, sr = kelly(rets)
        lo, hi = kelly_ci(rets)
        cur = statistics.mean(weights[algo]) if weights.get(algo) else 0.0
        mde = ec.minimum_detectable_sharpe(len(rets)) if len(rets) >= 2 else float("nan")
        # 판정은 점추정이 아니라 CI 하단으로 — 레버리지는 하방이 결정한다
        if not (lo == lo):  # NaN
            verdict = "표본 부족 — 판정 불가"
        elif lo <= 0:
            verdict = "CI가 0 포함 → 레버리지 근거 없음"
        elif lo / 2 < cur:
            verdict = "현재 사이징이 이미 CI 상한 근처"
        else:
            verdict = f"하단 half-K {lo / 2:.1f}x"
        ci = f"[{lo:>+8.1f},{hi:>+8.1f}]" if lo == lo else " " * 22
        print(
            f"{algo:16} {len(rets):>4} {mu * 100:>+7.3f} {sr:>+8.4f} {f:>10.2f} "
            f"{ci:>22} {mde:>7.3f} {cur:>7.2f} {verdict}"
        )
    allr = [r for v in groups.values() for r in v]
    allw = [w for v in weights.values() for w in v]
    f, mu, sd, sr = kelly(allr)
    lo, hi = kelly_ci(allr)
    cur = statistics.mean(allw) if allw else 0.0
    mde = ec.minimum_detectable_sharpe(len(allr))
    print(
        f"{'[전체 풀링]':16} {len(allr):>4} {mu * 100:>+7.3f} {sr:>+8.4f} {f:>10.2f} "
        f"{f'[{lo:>+8.1f},{hi:>+8.1f}]':>22} {mde:>7.3f} {cur:>7.2f} "
        f"{'CI가 0 포함 → 레버리지 근거 없음' if lo <= 0 else ''}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["all", "spot", "perp"], default="all")
    args = ap.parse_args()

    load_dotenv(dotenv_path=".env")
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = (
        client.table("paper_positions")
        .select("algo_id,symbol,direction,ret_pct,position_weight,close_reason,params_version")
        .eq("status", "closed")
        .execute()
        .data
    )
    suffix = parameters.PERP_TRACK_SUFFIX

    def in_market(sym: str) -> bool:
        if args.market == "spot":
            return not sym.endswith(suffix)
        if args.market == "perp":
            return sym.endswith(suffix)
        return True

    rows = [r for r in rows if in_market(r["symbol"]) and r.get("ret_pct") is not None]

    groups: dict[str, list[float]] = defaultdict(list)
    weights: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        groups[r["algo_id"]].append(float(r["ret_pct"]))
        weights[r["algo_id"]].append(float(r["position_weight"] or 1.0))
    report(f"라이브 청산 거래 ({args.market}, n={len(rows)})", groups, weights)

    # 방향별 — 숏이 레버리지 판단에서 롱과 다른가
    dgroups: dict[str, list[float]] = defaultdict(list)
    dweights: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        key = r.get("direction") or "long"
        dgroups[key].append(float(r["ret_pct"]))
        dweights[key].append(float(r["position_weight"] or 1.0))
    report("방향별", dgroups, dweights)

    print(
        "\n해석: f*는 '거래당 수익분포가 지지하는 최대 자본비율'이다. 1.0이 곧 1x 노출.\n"
        "  · f*가 음수/0 근방 → 레버리지는 손실만 증폭(알파를 만들지 않음).\n"
        "  · half-Kelly(f*/2)가 현재 평균 비중보다 작으면 현재 사이징이 이미 과대.\n"
        "  · μ 추정오차가 f*에 선형 증폭되므로, 표본이 작으면 f* 자체를 신뢰하면 안 된다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
