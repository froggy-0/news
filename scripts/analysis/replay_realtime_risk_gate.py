"""replay_realtime_risk_gate.py — 실시간 risk 게이트 효용 검증 하니스.

질문: arena_realtime_risk_states의 BLOCK_ENTRY/CAUTION 상태가 실제로 직후
       forward 수익을 악화시키는가? (= 게이트가 나쁜 진입을 막아주는가)

방법론(validate-data 스킬 준수):
- look-ahead bias 방지: forward 가격은 상태 시점 t '이후'(at-or-after)만 사용.
- 선택편향 없음: risk_state는 결과(forward ret)로 정의되지 않음(비순환).
- 표본 독립성 경고: 1분 상태 × 수시간 forward window = 심하게 중첩.
  유효 독립표본 ≈ (관측기간 / window). 결론 시 반드시 명시.
- 두 가지 모집단:
  (A) 전체 1분 상태별 forward 수익 (빠름, 신호 일반성)
  (B) 실제 4H long 진입 시점의 동시 risk_state 조건부 (정의적, 느림)

사용:
  .venv/bin/python3 scripts/analysis/replay_realtime_risk_gate.py \
      --windows 60,120,240 --buckets NORMAL,CAUTION,BLOCK_ENTRY,EXIT_CANDIDATE

환경: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (arena .env) 필요.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from statistics import mean, median, pstdev

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from arena import positions  # noqa: E402


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def _fetch_all(table: str, columns: str, order: str = "window_start") -> list[dict]:
    db = positions.db()
    rows: list[dict] = []
    off = 0
    while True:
        chunk = (
            await db.table(table).select(columns).order(order).range(off, off + 999).execute()
        ).data
        if not chunk:
            break
        rows += chunk
        off += 1000
        if len(chunk) < 1000:
            break
    return rows


def _price_lookup(price: list[tuple[datetime, float]]):
    price = sorted(price)

    def at_or_after(t: datetime) -> tuple[float | None, datetime | None]:
        for ts, p in price:
            if ts >= t:
                return p, ts
        return None, None

    return at_or_after, (price[0][0] if price else None), (price[-1][0] if price else None)


def _summarize(values: list[float]) -> str:
    if not values:
        return "  (no data)"
    neg = 100 * sum(1 for x in values if x < 0) / len(values)
    sd = pstdev(values) if len(values) > 1 else 0.0
    return "%5d %8.3f %8.3f %8.3f %8.3f %6.0f%%" % (
        len(values),
        mean(values),
        median(values),
        sd,
        min(values),
        neg,
    )


def _two_prop_p(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """두 비율 차이의 양측 p-value (정규근사, scipy 불필요).

    독립 표본 가정 — 반드시 비중첩 샘플에만 적용할 것.
    """
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def _nonoverlap_samples(states, at_or_after, window_min: int, max_gap_min: int):
    """비중첩 forward 표본 (독립성 확보) — 그리디로 window마다 1개만 채택."""
    win = timedelta(minutes=window_min)
    out: list[tuple[str, float]] = []
    last_end: datetime | None = None
    for t, st in states:
        if last_end is not None and t < last_end:
            continue
        p0, _ = at_or_after(t)
        p1, t1 = at_or_after(t + win)
        if p0 is None or p1 is None:
            continue
        if t1 - (t + win) > timedelta(minutes=max_gap_min):
            continue
        out.append((st, (p1 / p0 - 1.0) * 100))
        last_end = t + win
    return out


def _verdict(samples, *, min_indep: int, min_block: int, neg_gap_pp: float, alpha: float):
    """결정적 판정 (LLM 불필요). NORMAL vs BLOCK_ENTRY의 4H %neg 비교."""
    norm = [r for st, r in samples if st == "NORMAL"]
    block = [r for st, r in samples if st == "BLOCK_ENTRY"]
    total = len(samples)
    n_norm, n_block = len(norm), len(block)
    if total < min_indep or n_block < min_block or n_norm == 0:
        return (
            "INSUFFICIENT_DATA",
            f"독립표본 부족 (total={total}<{min_indep} 또는 block={n_block}<{min_block})",
        )
    x_norm = sum(1 for r in norm if r < 0)
    x_block = sum(1 for r in block if r < 0)
    neg_norm = 100 * x_norm / n_norm
    neg_block = 100 * x_block / n_block
    gap = neg_block - neg_norm
    p = _two_prop_p(x_block, n_block, x_norm, n_norm)
    detail = (
        f"block %neg={neg_block:.0f}% (n={n_block}) vs normal %neg={neg_norm:.0f}% "
        f"(n={n_norm}), gap={gap:+.0f}pp, p={p:.3f}"
    )
    if gap >= neg_gap_pp and p is not None and p < alpha:
        return "GATE_HELPS", detail
    if gap <= 0:
        return "GATE_NOISE_OR_HARMFUL", detail
    return "INCONCLUSIVE", detail


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="60,120,240", help="forward window(분) CSV")
    ap.add_argument(
        "--buckets", default="NORMAL,CAUTION,BLOCK_ENTRY,EXIT_CANDIDATE,FORCE_EXIT_CANDIDATE"
    )
    ap.add_argument("--max-gap-min", type=int, default=10, help="forward 가격 허용 갭(분)")
    ap.add_argument(
        "--verdict-window", type=int, default=240, help="판정 forward window(분, 기본 4H)"
    )
    ap.add_argument("--min-indep", type=int, default=30, help="판정 최소 비중첩 총표본")
    ap.add_argument("--min-block", type=int, default=10, help="판정 최소 BLOCK_ENTRY 표본")
    ap.add_argument("--neg-gap-pp", type=float, default=10.0, help="합격 %neg 격차(%p)")
    ap.add_argument("--alpha", type=float, default=0.05, help="유의수준")
    args = ap.parse_args()
    windows = [int(w) for w in args.windows.split(",")]
    buckets = args.buckets.split(",")

    await positions.init()
    fb = await _fetch_all("arena_realtime_feature_bars", "window_start,last_price")
    price = [(_parse(r["window_start"]), float(r["last_price"])) for r in fb if r.get("last_price")]
    at_or_after, p_start, p_end = _price_lookup(price)

    rr = await _fetch_all("arena_realtime_risk_states", "window_start,risk_state")
    states = [(_parse(r["window_start"]), r["risk_state"]) for r in rr]

    print("=== 데이터 커버리지 ===")
    print("가격 bars:", len(price), p_start, "~", p_end)
    print("risk states:", len(states))
    if states:
        span_h = (states[-1][0] - states[0][0]).total_seconds() / 3600
        print("상태 기간:", states[0][0], "~", states[-1][0], f"({span_h:.1f}h)")
        for k, v in Counter(s for _, s in states).most_common():
            print("  %-22s %5d (%.1f%%)" % (k, v, 100 * v / len(states)))

    for win_min in windows:
        win = timedelta(minutes=win_min)
        b: dict[str, list[float]] = {}
        for t, st in states:
            p0, _ = at_or_after(t)
            p1, t1 = at_or_after(t + win)
            if p0 is None or p1 is None:
                continue
            if t1 - (t + win) > timedelta(minutes=args.max_gap_min):
                continue
            b.setdefault(st, []).append((p1 / p0 - 1.0) * 100)
        eff = (span_h * 60 / win_min) if states else 0
        print(f"\n=== forward +{win_min}min 수익률(%) — 유효독립표본 ≈ {eff:.1f} ===")
        print(
            "  %-16s %5s %8s %8s %8s %8s %7s" % ("state", "n", "mean", "med", "sd", "min", "%neg")
        )
        for st in buckets:
            print("  %-16s %s" % (st, _summarize(b.get(st, []))))

    # --- 결정적 판정 (비중첩 4H 표본, LLM 불필요) ---
    indep = _nonoverlap_samples(states, at_or_after, args.verdict_window, args.max_gap_min)
    verdict, detail = _verdict(
        indep,
        min_indep=args.min_indep,
        min_block=args.min_block,
        neg_gap_pp=args.neg_gap_pp,
        alpha=args.alpha,
    )
    print(f"\n=== 판정 (비중첩 +{args.verdict_window}min, 독립표본={len(indep)}) ===")
    print(f"VERDICT: {verdict} — {detail}")
    print(
        "의미: INSUFFICIENT_DATA=누적 부족 / GATE_HELPS=live 검토 가능 / "
        "GATE_NOISE_OR_HARMFUL=게이트 무효·역효과 / INCONCLUSIVE=경계"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
