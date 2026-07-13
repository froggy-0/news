"""WI-3: 게이트 차단률 진단 — 각 알고가 백테스트 기간 중 '무엇에 막혔는지' 정량화.

regime_trend(11-AND)·macd_momentum 등 롱온리 알고가 하락장에서 무거래인 이유를 조건별로
분해한다. explain_signal(algorithms.py)이 이미 조건별 pass/fail/veto를 구조화 반환하므로
그대로 집계한다. 코드 동작 변경 없음(분석 전용).

핵심 산출:
  1) 조건별 실패율 — 전 bar 기준 각 조건이 얼마나 자주 막았나.
  2) near-miss 분석 — raw_signal=None인데 '단 하나의 veto만 실패'한 bar. 그 조건만
     통과했으면 롱이었음 → 그 조건이 진짜 나쁜 진입을 막았는지 이후 N봉 수익으로 검증.
     near-miss 이후 수익 분포가 (+)면 알파를 막는 dead weight 후보, (-)면 유효 필터.

재현:
  .venv/bin/python3 scripts/analysis/gate_block_rates.py \
      --parquet data/sentiment_join/sentiment_join_master_20260502.parquet \
      --algos regime_trend,macd_momentum --forward-bars 6
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import algorithms, backtest, frequency, parameters, positions, regime  # noqa: E402

# 이 스크립트는 build_macro_rows를 backfill 스크립트와 공유한다(중복 방지).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402


def _inject_regime(frame) -> dict:
    macro = dict(frame.macro)
    macro["arena_regime_state"] = regime.classify_regime_variant(
        frame.indicators, {}, macro, variant=regime.REGIME_VARIANT_STRICT
    ).regime_state
    return macro


def _forward_return(frames: list, idx: int, bars: int) -> float | None:
    if idx + bars >= len(frames):
        return None
    base = frames[idx].bar.close
    if base <= 0:
        return None
    return frames[idx + bars].bar.close / base - 1.0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--parquet", default="data/sentiment_join/sentiment_join_master_20260502.parquet"
    )
    ap.add_argument("--algos", default="regime_trend,macd_momentum,multi_factor,vix_rsi,omnibus")
    ap.add_argument("--forward-bars", type=int, default=6)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1
    algo_ids = [a.strip() for a in args.algos.split(",") if a.strip()]

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )

    lines: list[str] = []
    span = f"{frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    lines.append(f"# 게이트 차단률 진단 ({datetime.utcnow().date()})\n")
    lines.append(f"- frames: {len(frames)} ({span}), forward_bars={args.forward_bars}\n")

    for algo_id in algo_ids:
        fail_counter: Counter = Counter()
        veto_counter: Counter = Counter()
        n_long = 0
        n_total = 0
        near_miss: dict[str, list[float]] = defaultdict(list)  # 조건명 → 이후수익 목록
        for idx, frame in enumerate(frames):
            macro = _inject_regime(frame)
            diag = algorithms.explain_signal(algo_id, macro, frame.indicators)
            n_total += 1
            if diag.get("raw_signal") is not None:
                n_long += 1
                continue
            for c in diag.get("failed_conditions") or []:
                fail_counter[c] += 1
            vetoes = diag.get("vetoes") or []
            for c in vetoes:
                veto_counter[c] += 1
            # near-miss: 단 하나의 veto만 실패 → 그 조건이 유일한 차단자.
            if len(vetoes) == 1:
                fret = _forward_return(frames, idx, args.forward_bars)
                if fret is not None:
                    near_miss[vetoes[0]].append(fret)

        lines.append(f"\n## {algo_id}\n")
        lines.append(f"- long 신호: {n_long}/{n_total} bars ({n_long / n_total * 100:.1f}%)\n")
        lines.append("\n### 조건별 차단 빈도 (flat bar 기준)\n")
        lines.append("| 조건 | 실패(veto) 횟수 |")
        lines.append("|---|---|")
        for cond, cnt in veto_counter.most_common():
            lines.append(f"| {cond} | {cnt} |")
        lines.append("\n### near-miss 분석 (유일 차단자 → 이후 수익 분포)\n")
        lines.append("| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |")
        lines.append("|---|---|---|---|---|")
        for cond, rets in sorted(near_miss.items(), key=lambda kv: -len(kv[1])):
            n = len(rets)
            avg = sum(rets) / n * 100
            win = sum(1 for r in rets if r > 0) / n * 100
            verdict = "dead weight 후보(알파 차단)" if avg > 0 else "유효 필터"
            lines.append(f"| {cond} | {n} | {avg:+.2f} | {win:.0f} | {verdict} |")

    report = "\n".join(lines)
    print(report)
    if args.out:
        out = Path(args.out)
    else:
        out = (
            Path(__file__).resolve().parents[2]
            / "docs/arena/research"
            / f"gate-block-rates-{datetime.utcnow().strftime('%Y%m%d')}.md"
        )
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\n리포트 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
