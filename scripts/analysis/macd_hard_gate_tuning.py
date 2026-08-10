"""macd_momentum hard gate 완화 A/B (2026-08-08).

배경: 라이브 60일간 macd_momentum 거래 0건(paper_positions). arena_decisions 차단사유
top은 bb_width_sufficient > not_risk_off > above_ema200_4h(secondary) > funding_not_hot
(secondary). gate_block_rates.py near-miss 분석(20개월경 OHLCV, 2024-07~2026-08)에서는
bb_width_sufficient/not_risk_off가 "유효 필터"(단독차단 시 이후수익 음수)로 나와 완화
대상에서 제외. 반대로 macd_hist_increasing/macd_hist_positive/adx_sufficient는
"dead weight 후보"(단독차단 시 이후수익 ~0, 승률 50%+)로 표시됨 — core_trigger 후보 완화.

이 스크립트는 wi_tuning.py와 동일 하니스(플래그 오버라이드 + 동일 frames 재실행)로
WI-6(zero_cross, 기존에 11개월 n=4로 기각됨)를 20개월 규모 데이터로 재검증하고,
ADX_MIN 그리드를 추가 검증한다. bb_width_min은 근거상 건드리지 않는다.

재현:
  .venv/bin/python3 scripts/analysis/macd_hard_gate_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet --limit 6000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402


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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--limit", type=int, default=6000)
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
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    all_algos = [
        "regime_trend",
        "fng_contrarian",
        "vix_rsi",
        "macd_momentum",
        "multi_factor",
        "omnibus",
    ]
    base = _run(frames, {})
    b = {a: _algo_stats(base, a) for a in all_algos}
    print("\n=== BASELINE (arena-params-v34) ===")
    for a, s in b.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}")

    target = "macd_momentum"
    configs = {
        "A_baseline": {},
        "B_zero_cross": {
            "MACD_MOMENTUM_TRIGGER_MODE": "zero_cross",
            "MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED": True,
        },
        "C_zero_cross_noBB": {
            "MACD_MOMENTUM_TRIGGER_MODE": "zero_cross",
            "MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED": True,
            "MACD_MOMENTUM_ZERO_CROSS_DROP_BB_GATE": True,
        },
        "D_adx15": {"MACD_MOMENTUM_ADX_MIN": 15.0},
        "E_adx20": {"MACD_MOMENTUM_ADX_MIN": 20.0},
        "F_adx15_zero_cross": {
            "MACD_MOMENTUM_ADX_MIN": 15.0,
            "MACD_MOMENTUM_TRIGGER_MODE": "zero_cross",
            "MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED": True,
        },
    }

    print(f"\n=== macd_momentum hard gate 완화 (target={target}) ===")
    results = {}
    decisions = {}
    for vname, ov in configs.items():
        trades = _run(frames, ov)
        st = _algo_stats(trades, target)
        results[vname] = st
        d = st["sum_w_ret"] - b[target]["sum_w_ret"]
        flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
        print(
            f"  {flag} {vname:24} n {b[target]['n']:>3}→{st['n']:<3} "
            f"win {b[target]['win']:>4.0f}→{st['win']:<4.0f} "
            f"sum_w_ret {b[target]['sum_w_ret']:>+6.2f}→{st['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
        )
        regress = []
        for a in all_algos:
            if a == target:
                continue
            sv = _algo_stats(trades, a)
            if abs(sv["sum_w_ret"] - b[a]["sum_w_ret"]) > 0.01:
                regress.append(f"{a}:{b[a]['sum_w_ret']:+.2f}→{sv['sum_w_ret']:+.2f}")
        if regress:
            print(f"      ⚠️ 타 알고 변화: {regress}")

    usable = {k: v["rets"] for k, v in results.items() if v["n"] >= 5}
    if usable:
        best = max(results, key=lambda k: results[k]["sum_w_ret"])
        if best in usable:
            n_trials = effective_trial_count(len(usable), algo_id=target)
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
            print(
                f"\n  best={best}  DSR sharpe={dsr['sharpe']:.3f} "
                f"dsr={dsr['dsr']:.3f} n_trials={n_trials}"
            )
            decisions["dsr"] = round(dsr["dsr"], 3)
            decisions["n_trials"] = n_trials
            decisions["best"] = best

    decisions["results"] = {
        k: {"n": v["n"], "win": round(v["win"], 1), "sum_w_ret": round(v["sum_w_ret"], 3)}
        for k, v in results.items()
    }
    out = (
        Path(__file__).resolve().parents[2]
        / "docs/arena/research/macd-hard-gate-tuning-20260808.json"
    )
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결정 요약 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
