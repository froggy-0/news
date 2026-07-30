"""P1: omnibus UP_TREND/RANGE 레그가 구조적으로 죽었는지, 라이브 국면 휴면인지 판정.

배경: 라이브 arena_decisions 전수조회(2026-06-19~07-25) 결과 omnibus 라우터가
UP_TREND 42.0%(96/226사이클)·RANGE 19.0%(43/226)로 자주 분류됐는데도 진입이 0건이었다.
이 스크립트는 11개월+ macro 백필 백테스트에서 동일 분해를 수행해, 이 두 레그가
(a) 다른 국면에서는 정상 발화하는지, (b) 발화한다면 순양(+)인지를 확인한다.

코드 동작 변경 없음 — 백테스트 실행 후 트레이드의 macro_snapshot/indicator_snapshot으로
omni_regime을 재계산해 집계만 한다(explain_signal과 동일 순수함수 재사용).

재현:
  .venv/bin/python3 scripts/analysis/p1_omnibus_regime_decompose.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402


def _omni_state(macro: dict, ind: dict) -> tuple[str, str]:
    omni = algorithms._omnibus_regime(macro, ind)  # noqa: SLF001
    sub = "-"
    if omni == algorithms._OMNIBUS_DOWN_TREND:  # noqa: SLF001
        sub, _ = algorithms._downtrend_sub_state(ind)  # noqa: SLF001
    elif omni == algorithms._OMNIBUS_RANGE:  # noqa: SLF001
        sub = algorithms._range_sub_state(ind)  # noqa: SLF001
    return omni, sub


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    args = ap.parse_args()

    parquet = Path(args.parquet)
    macro_rows = build_macro_rows(parquet)
    print(
        f"macro 스냅샷 {len(macro_rows)}일  {macro_rows[0]['reference_date']} ~ {macro_rows[-1]['reference_date']}"
    )

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)

    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=6000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    res = backtest.run_replay(frames, settings=backtest.BacktestSettings())

    # (A) bar 단위 omni_regime 분포 — 로컬 strict_v1 레짐 주입 후(라이브와 동일 패리티)
    from arena import regime  # noqa: E402

    bar_state = Counter()
    for f in frames:
        macro = dict(f.macro)
        macro["arena_regime_state"] = regime.classify_regime_variant(
            f.indicators, {}, macro, variant=regime.REGIME_VARIANT_STRICT
        ).regime_state
        omni, sub = _omni_state(macro, f.indicators)
        bar_state[(omni, sub)] += 1

    total_bars = len(frames)
    print(f"\n=== (A) bar 단위 omni_regime 분포 (n={total_bars}) ===")
    for (omni, sub), n in sorted(bar_state.items(), key=lambda x: -x[1]):
        print(f"  {omni:12s} {sub:20s} {n:5d}  ({n / total_bars * 100:5.1f}%)")

    # (B) omnibus 실현 트레이드 — macro_snapshot/indicator_snapshot으로 재분류
    omni_trades = [t for t in res.trades if t.algo_id == "omnibus"]
    print(f"\n=== (B) omnibus 백테스트 실현 트레이드 (n={len(omni_trades)}) ===")

    by_state: dict[tuple[str, str], list] = defaultdict(list)
    for t in omni_trades:
        omni, sub = _omni_state(t.macro_snapshot, t.indicator_snapshot)
        by_state[(omni, sub)].append(t)

    for (omni, sub), ts in sorted(by_state.items(), key=lambda x: -len(x[1])):
        n = len(ts)
        wins = sum(1 for t in ts if t.ret_pct > 0)
        sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
        avg = sum(t.ret_pct for t in ts) / n * 100
        exits = dict(Counter(t.exit_reason for t in ts))
        print(
            f"  {omni:12s} {sub:20s} n={n:3d} win%={wins / n * 100:5.1f} "
            f"가중합%={sum_w:+7.2f} 평균%={avg:+6.2f}  exits={exits}"
        )

    # 전체 omnibus 합계(대조)
    if omni_trades:
        n = len(omni_trades)
        wins = sum(1 for t in omni_trades if t.ret_pct > 0)
        sum_w = sum(t.ret_pct * t.position_weight for t in omni_trades) * 100
        print(f"\n  [전체] n={n} win%={wins / n * 100:.1f} 가중합%={sum_w:+.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
