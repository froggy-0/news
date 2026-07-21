"""§7.1/7.2 플래그 A/B — arena-status-review-20260721.md 계획서 검증.

wi_tuning.py와 동일 패턴(동일 macro 백필 frames, parameters 오버라이드만 바꿔 재실행)을
재사용해 두 신규 미검증 플래그를 그리드 검증한다:

  1) MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO — fng_contrarian·vix_rsi 독립 A/B
     (§7.2, momentum_not_worsening 매그니튜드 확장)
  2) UNKNOWN_REGIME_SIZE_MULT_BY_ALGO — fng_contrarian·vix_rsi 독립 A/B
     (§7.1, P4 unknown 레짐 사이징 완화)

fng·vix_rsi는 절대 같은 config로 묶지 않는다 — P4 문서 경고대로 vix_rsi는 구조 게이트
추가 시 항상 악화된 전례(WI-5 기각)가 있어 하나가 기각돼도 다른 알고는 별개 판단.

재현:
  .venv/bin/python3 scripts/analysis/p4_momentum_unknown_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet
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
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

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


def _line(label: str, base: dict, var: dict) -> str:
    d = var["sum_w_ret"] - base["sum_w_ret"]
    flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
    return (
        f"  {flag} {label:28} n {base['n']:>3}→{var['n']:<3} "
        f"win {base['win']:>4.0f}→{var['win']:<4.0f} "
        f"sum_w_ret {base['sum_w_ret']:>+6.2f}→{var['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
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

    base = _run(frames, {})
    b = {a: _algo_stats(base, a) for a in ALL_ALGOS}
    print("\n=== BASELINE (전 플래그 off, W1 13bps 하니스) ===")
    for a, s in b.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}")

    decisions: dict[str, dict] = {}

    def grid(name: str, target: str, configs: dict[str, dict]):
        print(f"\n=== {name} (target={target}) ===")
        results = {}
        for vname, ov in configs.items():
            trades = _run(frames, ov)
            st = _algo_stats(trades, target)
            results[vname] = st
            print(_line(vname, b[target], st))
            regress = []
            for a in b:
                if a == target:
                    continue
                sv = _algo_stats(trades, a)
                if abs(sv["sum_w_ret"] - b[a]["sum_w_ret"]) > 0.01:
                    regress.append(f"{a}:{b[a]['sum_w_ret']:+.2f}→{sv['sum_w_ret']:+.2f}")
            if regress:
                print(f"      ⚠️ 타 알고 변화: {regress}")
        usable = {k: v["rets"] for k, v in results.items() if v["n"] >= 5}
        best = max(results, key=lambda k: results[k]["sum_w_ret"])
        decisions[name] = {
            "target": target,
            "best": best,
            "results": {
                k: {"n": v["n"], "win": round(v["win"], 1), "sum_w_ret": round(v["sum_w_ret"], 3)}
                for k, v in results.items()
            },
        }
        if len(usable) >= 2 and best in usable:
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), len(usable))
            print(f"      best={best}  DSR sharpe={dsr['sharpe']:.3f} dsr={dsr['dsr']:.3f}")
            decisions[name]["dsr"] = round(dsr["dsr"], 3)
        return results

    # §7.2 momentum 매그니튜드 게이트 — fng·vix_rsi 독립. ATR 배수 그리드.
    grid(
        "7.2 fng momentum 매그니튜드",
        "fng_contrarian",
        {
            "A_baseline": {},
            "B_atr0.15": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"fng_contrarian": 0.15}},
            "C_atr0.25": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"fng_contrarian": 0.25}},
            "D_atr0.40": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"fng_contrarian": 0.40}},
        },
    )
    grid(
        "7.2 vix_rsi momentum 매그니튜드",
        "vix_rsi",
        {
            "A_baseline": {},
            "B_atr0.15": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"vix_rsi": 0.15}},
            "C_atr0.25": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"vix_rsi": 0.25}},
            "D_atr0.40": {"MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO": {"vix_rsi": 0.40}},
        },
    )

    # §7.1 unknown 레짐 사이징 완화 — fng·vix_rsi 독립. 배수 그리드(작을수록 강한 완화).
    grid(
        "7.1 fng unknown 사이징",
        "fng_contrarian",
        {
            "A_baseline": {},
            "B_mult0.5": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"fng_contrarian": 0.5}},
            "C_mult0.65": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"fng_contrarian": 0.65}},
            "D_mult0.8": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"fng_contrarian": 0.8}},
        },
    )
    grid(
        "7.1 vix_rsi unknown 사이징",
        "vix_rsi",
        {
            "A_baseline": {},
            "B_mult0.5": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"vix_rsi": 0.5}},
            "C_mult0.65": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"vix_rsi": 0.65}},
            "D_mult0.8": {"UNKNOWN_REGIME_SIZE_MULT_BY_ALGO": {"vix_rsi": 0.8}},
        },
    )

    out = (
        Path(__file__).resolve().parents[2]
        / "docs/arena/research/p4-momentum-unknown-tuning-results.json"
    )
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결정 요약 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
