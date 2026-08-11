"""VIX(FRED)→BVOL(크립토 옵션 IV) 대체 A/B — D2 아카이브 백필 (2026-08-11).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D2. `vix_rsi`·`multi_factor`
(f3)·vix_rsi 청산 히스테리시스가 읽는 macro['vix_now']/['vix_q40']을 주식 VIX(FRED, 일간,
미국 장중만 갱신) 대신 BVOL(바이낸스 옵션 내재변동성, 24/7, BTC 전용 커버리지 사용)로
바꿨을 때 백테스트 성과가 달라지는지 탐색한다.

⚠️ **이건 탐색적 백테스트일 뿐, 라이브 배선 결정은 이 스크립트의 스코프 밖이다** — BVOL은
라이브 엔드포인트가 없어(아카이브 T+1 전용) 실제로 채택하려면 (a) T+1 지연을 감수하거나
(b) eapi markIV로 별도 라이브 지수를 만들어야 하는데 산출식이 달라 패리티가 깨진다.
이 트레이드오프는 사용자 결정이 필요하다(bvol_archive.py 모듈독스트링 참조).

방법: master_20260710.parquet 표준 macro 백필(D1/D3와 동일 11개월 창) + BVOL 아카이브
overlay(dataclasses.replace, baseline 무변형). vix_rsi·multi_factor 비교, 나머지 알고
무회귀 확인.

재현:
  .venv/bin/python3 scripts/analysis/bvol_backfill_tuning.py
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from bvol_archive import build_vix_analog  # noqa: E402
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGET_ALGOS = ["vix_rsi", "multi_factor"]
ALL_ALGOS = [*TARGET_ALGOS, "regime_trend", "macd_momentum", "omnibus", "fng_contrarian"]


def _algo_stats(trades: list, algo_id: str) -> dict:
    ts = [t for t in trades if t.algo_id == algo_id]
    n = len(ts)
    if n == 0:
        return {"n": 0, "sum_w_ret": 0.0, "win": 0.0, "rets": []}
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = sum(1 for t in ts if t.ret_pct > 0) / n * 100
    return {"n": n, "sum_w_ret": sum_w, "win": win, "rets": [t.ret_pct for t in ts]}


def _line(label: str, base: dict, var: dict) -> str:
    d = var["sum_w_ret"] - base["sum_w_ret"]
    flag = "✅" if d > 0.01 else ("➖" if abs(d) <= 0.01 else "❌")
    return (
        f"  {flag} {label:16} n {base['n']:>3}→{var['n']:<3} "
        f"win {base['win']:>4.0f}→{var['win']:<4.0f} "
        f"sum_w_ret {base['sum_w_ret']:>+6.2f}→{var['sum_w_ret']:<+6.2f}  Δ{d:+.2f}"
    )


def _bucket_key(close_time) -> "pd.Timestamp":
    return pd.Timestamp(close_time) + pd.Timedelta(seconds=1)


def overlay_frames(frames: list, bvol_df: pd.DataFrame) -> list:
    """프레임 close date → 그날의 BVOL vix_now/vix_q40 대응값(lag1 이미 반영됨)."""
    out = []
    covered = 0
    for f in frames:
        d = f.bar.close_time.date()
        if d in bvol_df.index:
            row = bvol_df.loc[d]
            if pd.notna(row["vix_now"]):
                overrides = {"vix_now": float(row["vix_now"])}
                if pd.notna(row["vix_q40"]):
                    overrides["vix_q40"] = float(row["vix_q40"])
                out.append(dataclasses.replace(f, macro={**f.macro, **overrides}))
                covered += 1
                continue
        out.append(f)
    return out, covered


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--bvol-symbol", default="BTCBVOLUSDT")
    ap.add_argument("--limit", type=int, default=2000)
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
        symbol=args.symbol,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ "
        f"{frames[-1].bar.close_time.date()}"
    )

    vix_base_n = sum(1 for f in frames if f.macro.get("vix_now") is not None)
    print(f"baseline(FRED VIX) 커버리지: {vix_base_n}/{len(frames)}")

    cache_start = frames[0].bar.close_time.date() - timedelta(days=100)
    cache_end = frames[-1].bar.close_time.date()
    bvol_df = build_vix_analog(args.bvol_symbol, cache_start, cache_end)
    variant_frames, bvol_covered = overlay_frames(frames, bvol_df)
    print(f"variant(BVOL) 커버리지: {bvol_covered}/{len(frames)}")

    base_trades = backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades
    var_trades = backtest.run_replay(variant_frames, settings=backtest.BacktestSettings()).trades

    print("\n=== VIX(FRED) → BVOL(크립토 IV) 대체 A/B ===")
    decisions = {}
    for algo in TARGET_ALGOS:
        b = _algo_stats(base_trades, algo)
        v = _algo_stats(var_trades, algo)
        print(_line(algo, b, v))
        decisions[algo] = {
            "baseline": {k: v2 for k, v2 in b.items() if k != "rets"},
            "variant": {k: v2 for k, v2 in v.items() if k != "rets"},
        }
        usable = {"baseline": b["rets"], "variant": v["rets"]}
        usable = {k: r for k, r in usable.items() if len(r) >= 5}
        if len(usable) == 2:
            best = "variant" if v["sum_w_ret"] > b["sum_w_ret"] else "baseline"
            n_trials = effective_trial_count(2, algo_id=f"{algo}_bvol")
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
            print(f"      best={best} dsr={dsr['dsr']:.3f} n_trials={n_trials}")
            decisions[algo]["dsr"] = round(dsr["dsr"], 3)
            decisions[algo]["best"] = best

    print("\n비대상 알고 무회귀 확인:")
    for algo in ["regime_trend", "macd_momentum", "omnibus", "fng_contrarian"]:
        b = _algo_stats(base_trades, algo)
        v = _algo_stats(var_trades, algo)
        d = v["sum_w_ret"] - b["sum_w_ret"]
        tag = "OK" if abs(d) < 0.01 else "⚠️ 변화 감지"
        print(f"  {algo:16} Δ{d:+.4f}  {tag}")

    out = Path(__file__).resolve().parents[2] / "docs/arena/research/d2-bvol-backfill-results.json"
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
