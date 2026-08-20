"""숏 포지션의 min_hold 시간하한 A/B (2026-08-20).

관측(2026-08-19 라이브): macd_momentum 숏이 BTC-PERP/ETH-PERP에서 12:08 사이클에
청산신호(flat)를 냈지만 MIN_HOLD_HOURS["macd_momentum"]=8h에 막혀 유지됐고,
14:47 급등 중 트레일링 손절로 -2.07%/-2.10% 확정. 신호 시점 청산이었다면 ~-0.34%.

가설: min_hold(과잉회전 방지 장치)는 롱 기준으로 설정됐는데, 크립토 숏은
급반등(momentum crash — Daniel&Moskowitz 2016, 본 저장소
short-entry-asymmetry-literature-review-20260815.md가 이미 정리)이 손실의 주경로라
"신호가 나갔는데 시간 때문에 못 나가는" 구간이 롱보다 비싸다.

검증: macd_momentum 숏(v41에서 BTC/ETH/SOL perp 라이브 승격, §8 설계=veto제거)을
min_hold {8h(현행), 4h, 0h}로 A/B. BacktestSettings.min_hold_hours만 교체 —
알고 로직·파라미터 파일 무변경. 숏 신호 정의는 기존 검증 스크립트를 그대로 재사용.

재현:
  .venv/bin/python3 scripts/analysis/short_min_hold_tuning.py
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import macd_momentum_short_backtest as mms  # noqa: E402  (숏 신호정의·사이징 패치 재사용)
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402

VARIANTS = {"min_hold_8h(현행)": 8.0, "min_hold_4h": 4.0, "min_hold_0h": 0.0}


def summarize(trades: list) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "win": 0.0, "sum_w": 0.0, "pf": 0.0, "sr": 0.0, "exits": {}}
    wins = [t for t in trades if t.ret_pct > 0]
    losses = [t for t in trades if t.ret_pct <= 0]
    gw = sum(t.ret_pct for t in wins)
    gl = -sum(t.ret_pct for t in losses)
    rets = [t.ret_pct for t in trades]
    sd = statistics.stdev(rets) if len(rets) > 1 else 0.0
    return {
        "n": n,
        "win": len(wins) / n * 100,
        "sum_w": sum(t.ret_pct * t.position_weight for t in trades) * 100,
        "pf": (gw / gl) if gl > 0 else float("inf"),
        "sr": (statistics.mean(rets) / sd) if sd > 0 else 0.0,
        "hold": sum(t.hold_hours for t in trades) / n,
        "exits": dict(Counter(t.exit_reason for t in trades)),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    # 숏 사이징 몽키패치(프로세스 로컬) — 기존 Phase B 스크립트와 동일 경로
    algorithms.tsmom_nl_position_multiplier = mms._tsmom_nl_position_multiplier_abs

    macro_rows = build_macro_rows(parquet)
    print(
        f"백필 macro: {len(macro_rows)}일 {macro_rows[0]['reference_date']}~{macro_rows[-1]['reference_date']}"
    )
    print("숏 신호: macd_momentum TSMOM_NL 대칭반전, risk-off veto 제거(§8 설계=라이브 v41 배선)\n")

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    strategy_fns = {"macd_momentum": mms.macd_momentum_short_noveto}

    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
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
            print(f"{symbol}: frames 없음")
            continue
        print(
            f"########## {symbol}  frames={len(frames)} "
            f"{frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()} ##########"
        )
        print(
            f"{'variant':18} {'n':>4} {'win%':>6} {'sum_w%':>8} {'PF':>6} {'SR/T':>8} {'평균h':>6}  exits"
        )
        for label, hours in VARIANTS.items():
            mh = dict(parameters.MIN_HOLD_HOURS)
            mh["macd_momentum"] = hours
            settings = backtest.BacktestSettings(
                product_type="usdm_perp", symbol=symbol, min_hold_hours=mh
            )
            res = backtest.run_replay(frames, strategy_fns=strategy_fns, settings=settings)
            s = summarize(res.trades)
            totals[label]["sum_w"] += s["sum_w"]
            totals[label]["n"] += s["n"]
            print(
                f"{label:18} {s['n']:>4} {s['win']:>6.1f} {s['sum_w']:>+8.2f} {s['pf']:>6.2f} "
                f"{s['sr']:>+8.4f} {s['hold']:>6.1f}  {s['exits']}"
            )
        print()

    print("########## 3자산 합산 ##########")
    base = totals["min_hold_8h(현행)"]["sum_w"]
    for label in VARIANTS:
        t = totals[label]
        print(
            f"  {label:18} n={t['n']:>4.0f}  sum_w={t['sum_w']:>+7.2f}%  Δ={t['sum_w'] - base:>+6.2f}%p"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
