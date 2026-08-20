"""하방 STRESS 시 risk-off 전면차단 완화 A/B (2026-08-20).

배경(stress_asymmetry_diagnosis.py 결과, 3자산 19,950봉):
  하방 STRESS 이후 forward return이 측정한 모든 버킷 중 최고 —
  +24h 평균 +0.65% / 중앙 +0.45% / 승률 57% (기저 +0.12% / +0.06% / 51%).
  그런데 STRESS ∈ _RISK_OFF_REGIMES라 롱 전 알고가 `veto:not_risk_off`로 차단된다.
  즉 "매도 소진 후 반등" 구간을 평균회귀 알고가 통째로 놓치고 있을 가능성.

변형: arena_regime_state == "stress" AND return_24h < 0 인 프레임에서만
      레짐을 "sideways"(non-risk-off·non-bullish 중립값)로 치환해 알고 자체
      진입조건이 판단하게 한다. 상방 STRESS·bear_trend·BearPanic 차단은 그대로.
      (상방 STRESS는 같은 진단에서 기저 대비 엣지 없음이 확인돼 완화 대상 아님.)

scope:
  mr   = 평균회귀 3종(fng_contrarian, vix_rsi, omnibus)에만 적용
  all  = 8개 알고 전부 적용 (추세계열 회귀 확인용)

재현:
  .venv/bin/python3 scripts/analysis/downside_stress_gate_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet --symbols BTCUSDT ETHUSDT SOLUSDT

읽기 전용 — parameters.py 무변경, run_replay(strategy_fns=...) 오버라이드만 사용.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import algorithms, backtest, frequency, parameters, positions, regime  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

MEAN_REVERSION_ALGOS = ("fng_contrarian", "vix_rsi", "omnibus")
NEUTRAL_STATE = regime.REGIME_SIDEWAYS


def _relaxed(fn):
    """하방 STRESS 프레임에서만 레짐을 중립으로 치환해 원 진입함수를 호출."""

    def wrapped(macro: dict, ind: dict) -> str | None:
        if (
            macro.get("arena_regime_state") == regime.REGIME_STRESS
            and float(ind.get("return_24h") or 0.0) < 0
        ):
            macro = {**macro, "arena_regime_state": NEUTRAL_STATE}
        return fn(macro, ind)

    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    return wrapped


def build_variant(scope: str) -> dict:
    targets = MEAN_REVERSION_ALGOS if scope == "mr" else tuple(algorithms.ALGORITHMS)
    return {
        algo_id: (_relaxed(fn) if algo_id in targets else fn)
        for algo_id, fn in algorithms.ALGORITHMS.items()
    }


def stats(trades: list) -> dict[str, dict]:
    by_algo: dict[str, list] = defaultdict(list)
    for t in trades:
        by_algo[t.algo_id].append(t)
    out = {}
    for algo, ts in by_algo.items():
        n = len(ts)
        wins = [t for t in ts if t.ret_pct > 0]
        losses = [t for t in ts if t.ret_pct <= 0]
        gross_win = sum(t.ret_pct for t in wins)
        gross_loss = -sum(t.ret_pct for t in losses)
        out[algo] = {
            "n": n,
            "win": len(wins) / n * 100,
            "sum_w": sum(t.ret_pct * t.position_weight for t in ts) * 100,
            "pf": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
            "rets": [t.ret_pct for t in ts],
        }
    return out


def sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    sd = statistics.stdev(rets)
    return statistics.mean(rets) / sd if sd > 0 else 0.0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1
    macro_rows = build_macro_rows(parquet)
    print(
        f"백필 macro: {len(macro_rows)}일 "
        f"{macro_rows[0]['reference_date']} ~ {macro_rows[-1]['reference_date']}"
    )

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    variants = {
        "baseline": algorithms.ALGORITHMS,
        "mr": build_variant("mr"),
        "all": build_variant("all"),
    }
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    per_symbol: dict[str, dict[str, dict]] = {}

    for symbol in args.symbols:
        profile_id = (
            frequency.LIVE_4H_PROFILE_ID
            if symbol == parameters.BINANCE_SYMBOL
            else frequency.multi_asset_shadow_profile_id(symbol)
        )
        profile = frequency.get_frequency_profile(profile_id)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=2000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        if not frames:
            print(f"{symbol}: frames 없음 — 건너뜀")
            continue
        n_stress_down = sum(
            1
            for f in frames
            if regime.classify_regime(f.indicators, macro={}).regime_state == regime.REGIME_STRESS
            and float(f.indicators.get("return_24h") or 0.0) < 0
        )
        print(
            f"\n########## {symbol}  frames={len(frames)} "
            f"{frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()} "
            f"(하방STRESS {n_stress_down}봉) ##########"
        )
        res = {}
        for name, fns in variants.items():
            out = backtest.run_replay(
                frames, strategy_fns=fns, settings=backtest.BacktestSettings()
            )
            res[name] = stats(out.trades)
        per_symbol[symbol] = res

        algos = sorted({a for r in res.values() for a in r})
        print(f"{'algo':16} {'baseline n/win/sum_w/PF':>34} {'mr':>28} {'all':>28}")
        for algo in algos:
            cells = []
            for name in ("baseline", "mr", "all"):
                s = res[name].get(algo)
                cells.append(
                    "-"
                    if not s
                    else f"{s['n']:>3} {s['win']:>4.0f}% {s['sum_w']:>+7.2f}% PF{s['pf']:>5.2f}"
                )
            print(f"{algo:16} {cells[0]:>34} {cells[1]:>28} {cells[2]:>28}")
            for name in ("baseline", "mr", "all"):
                s = res[name].get(algo)
                if s:
                    totals[name][algo] += s["sum_w"]

    print("\n########## 3자산 합산 sum_w% ##########")
    print(f"{'algo':16} {'baseline':>10} {'mr':>10} {'Δmr':>9} {'all':>10} {'Δall':>9}")
    algos = sorted({a for v in totals.values() for a in v})
    for algo in algos:
        b, m, a = totals["baseline"][algo], totals["mr"][algo], totals["all"][algo]
        print(f"{algo:16} {b:>+10.2f} {m:>+10.2f} {m - b:>+9.2f} {a:>+10.2f} {a - b:>+9.2f}")
    for name in ("baseline", "mr", "all"):
        print(f"  총합 {name:9}: {sum(totals[name].values()):+.2f}%")

    # 대상 알고 거래단위 Sharpe (표본 확대 여부 확인용)
    print("\n########## 평균회귀 3종 거래단위 SR (3자산 풀링) ##########")
    for algo in MEAN_REVERSION_ALGOS:
        for name in ("baseline", "mr"):
            rets = [
                r for sym in per_symbol.values() for r in sym[name].get(algo, {}).get("rets", [])
            ]
            print(f"  {algo:16} {name:9} n={len(rets):>3} SR/trade={sharpe(rets):+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
