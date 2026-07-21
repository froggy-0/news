"""P3/W5: fng_days_below_30 사이징/게이트 A/B + walk-forward.

return-improvement-priorities-20260715.md P3 / implementation-plan-w-series-20260715.md W5
설계 그대로: FNG_DURATION_FEATURE_ENABLED 기반 sizing(0.5/0.3)·gate(N=2/3/5) 그리드를
단일 프레임 + walk-forward 6윈도(견고성)로 검증. 13bps 하니스(W1 기본값)로 실행.

재현:
  .venv/bin/python3 scripts/analysis/fng_duration_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet --windows 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGET = "fng_contrarian"
ALL_ALGOS = [
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
]


@contextmanager
def _params(**overrides):
    saved = {k: getattr(parameters, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(parameters, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(parameters, k, v)


def _algo_stats(trades: list, algo_id: str) -> dict:
    ts = [t for t in trades if t.algo_id == algo_id]
    n = len(ts)
    if n == 0:
        return {"n": 0, "sum_w_ret": 0.0, "win": 0.0, "rets": []}
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = sum(1 for t in ts if t.ret_pct > 0) / n * 100
    return {"n": n, "sum_w_ret": sum_w, "win": win, "rets": [t.ret_pct for t in ts]}


def _run(frames, overrides: dict) -> list:
    with _params(**overrides):
        return backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades


CONFIGS: dict[str, dict] = {
    "A_baseline(off)": {},
    "B_sizing0.5": {
        "FNG_DURATION_FEATURE_ENABLED": True,
        "FNG_DURATION_MODE": "sizing",
        "FNG_DAY1_SIZE_MULT": 0.5,
    },
    "C_sizing0.3": {
        "FNG_DURATION_FEATURE_ENABLED": True,
        "FNG_DURATION_MODE": "sizing",
        "FNG_DAY1_SIZE_MULT": 0.3,
    },
    "D_gateN2": {
        "FNG_DURATION_FEATURE_ENABLED": True,
        "FNG_DURATION_MODE": "gate",
        "FNG_DURATION_MIN_DAYS": 2,
    },
    "E_gateN3": {
        "FNG_DURATION_FEATURE_ENABLED": True,
        "FNG_DURATION_MODE": "gate",
        "FNG_DURATION_MIN_DAYS": 3,
    },
    "F_gateN5": {
        "FNG_DURATION_FEATURE_ENABLED": True,
        "FNG_DURATION_MODE": "gate",
        "FNG_DURATION_MIN_DAYS": 5,
    },
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--windows", type=int, default=6)
    args = ap.parse_args()
    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

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
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    baseline_trades = _run(frames, {})
    base = {a: _algo_stats(baseline_trades, a) for a in ALL_ALGOS}
    print("\n=== BASELINE (전 플래그 off, W1 13bps 하니스) ===")
    for a, s in base.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}")

    # ── 1) 단일 프레임 그리드 ──────────────────────────────────
    print(f"\n=== 단일 프레임 그리드 (target={TARGET}) ===")
    single_results: dict[str, dict] = {}
    for cname, ov in CONFIGS.items():
        trades = _run(frames, ov)
        st = _algo_stats(trades, TARGET)
        single_results[cname] = st
        d = st["sum_w_ret"] - base[TARGET]["sum_w_ret"]
        flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
        print(
            f"  {flag} {cname:16} n {base[TARGET]['n']:>3}→{st['n']:<3} "
            f"win {base[TARGET]['win']:>4.0f}→{st['win']:<4.0f} "
            f"sum_w_ret {base[TARGET]['sum_w_ret']:>+6.2f}→{st['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
        )
        regress = []
        for a in ALL_ALGOS:
            if a == TARGET:
                continue
            sv = _algo_stats(trades, a)
            if abs(sv["sum_w_ret"] - base[a]["sum_w_ret"]) > 0.01:
                regress.append(f"{a}:{base[a]['sum_w_ret']:+.2f}→{sv['sum_w_ret']:+.2f}")
        if regress:
            print(f"      ⚠️ 타 알고 변화: {regress}")

    # ── 2) walk-forward 6윈도 ────────────────────────────────
    W = args.windows
    size = len(frames) // W
    windows = [frames[i * size : (i + 1) * size] for i in range(W)]
    print(f"\n=== Walk-forward ({W}윈도, 각 ~{size}봉) ===")
    wf_results: dict[str, dict] = {}
    for cname, ov in CONFIGS.items():
        tgt_sums, tgt_ns = [], []
        for w in windows:
            trades = _run(w, ov)
            tgt_sums.append(_algo_stats(trades, TARGET)["sum_w_ret"])
            tgt_ns.append(_algo_stats(trades, TARGET)["n"])
        pos = sum(1 for x in tgt_sums if x > 0)
        mean = statistics.mean(tgt_sums)
        stdev = statistics.pstdev(tgt_sums)
        wf_results[cname] = {
            "per_window": [round(x, 2) for x in tgt_sums],
            "n_per_window": tgt_ns,
            "pos_windows": pos,
            "mean": round(mean, 3),
            "stdev": round(stdev, 3),
        }
        print(
            f"  {cname:16} {['%+.1f' % x for x in tgt_sums]}  n={tgt_ns}  "
            f"양의윈도 {pos}/{W}  평균{mean:+.2f} 표준편차{stdev:.2f}"
        )

    # ── 3) DSR (단일 프레임 최선 config, n>=5 거래만) ─────────
    usable = {k: v["rets"] for k, v in single_results.items() if v["n"] >= 5}
    dsr_out: dict[str, float] = {}
    if usable:
        best = max(single_results, key=lambda k: single_results[k]["sum_w_ret"])
        if best in usable:
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), len(usable))
            print(
                f"\n  best(단일프레임)={best}  DSR sharpe={dsr['sharpe']:.3f} dsr={dsr['dsr']:.3f}"
            )
            dsr_out = {"best": best, "sharpe": round(dsr["sharpe"], 3), "dsr": round(dsr["dsr"], 3)}

    out = {
        "single_frame": {
            k: {"n": v["n"], "win": round(v["win"], 1), "sum_w_ret": round(v["sum_w_ret"], 3)}
            for k, v in single_results.items()
        },
        "walk_forward": wf_results,
        "dsr": dsr_out,
    }
    out_path = (
        Path(__file__).resolve().parents[2] / "docs/arena/research/fng-duration-tuning-results.json"
    )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n결정 요약 저장: {out_path}")
    print(
        "\n판정 가이드: sizing형은 거래수 불변이 정상(사이징만 변경). gate형은 거래수 급감 시 "
        "검증 불능(WI-4 전례) 우선 확인. 채택 기준: sum_w_ret 개선 + 양의윈도 비율↑ + 타알고 무회귀."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
