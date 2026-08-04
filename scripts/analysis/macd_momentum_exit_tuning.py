"""macd_momentum 청산 히스테리시스(WI-6, 기존 구현) A/B — 2개 창.

regime_trend_exit_tuning.py와 동일 방법론. macd_momentum은 변형이 하나뿐
(MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED on/off)이라 하니스가 더 단순하다.
entry-exit-separation-implementation-plan-20260804.md §11 재현.

재현:
  .venv/bin/python3 scripts/analysis/macd_momentum_exit_tuning.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGO = "macd_momentum"
RT_BPS = 2 * parameters.FEE_BPS + 2 * 1.0 + 1.0

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


def _stats(trades: list, algo: str = ALGO) -> dict:
    ts = [t for t in trades if t.algo_id == algo]
    n = len(ts)
    if n == 0:
        return dict(
            n=0,
            win=0.0,
            sum_w_ret=0.0,
            pf=0.0,
            median_hold=0.0,
            max_hold=0.0,
            edge_bp=0.0,
            cost_bp=0.0,
            ratio=0.0,
        )
    wins = sum(1 for t in ts if t.ret_pct > 0)
    sum_w_ret = sum(t.ret_pct * t.position_weight for t in ts) * 100
    gp = sum(t.ret_pct for t in ts if t.ret_pct > 0)
    gl = -sum(t.ret_pct for t in ts if t.ret_pct <= 0)
    pf = gp / gl if gl > 0 else float("inf")
    cost = sum(t.position_weight for t in ts) * RT_BPS / 100
    gross = sum_w_ret + cost
    edge_bp = gross / n * 100
    cost_bp = float(np.mean([t.position_weight for t in ts])) * RT_BPS
    return dict(
        n=n,
        win=wins / n * 100,
        sum_w_ret=sum_w_ret,
        pf=pf,
        median_hold=float(np.median([t.hold_hours for t in ts])),
        max_hold=float(max(t.hold_hours for t in ts)),
        edge_bp=edge_bp,
        cost_bp=cost_bp,
        ratio=edge_bp / cost_bp if cost_bp else 0.0,
    )


async def _run_window(label, *, symbol, macro_rows, from_date, to_date, limit) -> dict:
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    pid = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    profile = frequency.get_frequency_profile(pid)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=symbol,
        interval=profile.interval,
        limit=limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_date,
        to_date=to_date,
    )
    if not frames:
        print(f"{label}: frames 없음")
        return {}
    bh = (frames[-1].bar.close - frames[0].bar.close) / frames[0].bar.close * 100
    print(
        f"\n[{label}] frames={len(frames)}  {frames[0].bar.close_time.date()}~"
        f"{frames[-1].bar.close_time.date()}  buy&hold={bh:+.2f}%"
    )

    base_trades = backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades
    with _params(MACD_MOMENTUM_EXIT_HYSTERESIS_ENABLED=True):
        hyst_trades = backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades

    base = _stats(base_trades)
    hyst = _stats(hyst_trades)
    print(
        f"{'variant':10} {'n':>4} {'win%':>6} {'sum_w_ret%':>11} {'PF':>6} "
        f"{'중앙h':>7} {'최대h':>7} {'엣지bp':>7} {'엣지/비용':>9}"
    )
    for name, s in [("baseline", base), ("hysteresis", hyst)]:
        print(
            f"{name:10} {s['n']:>4} {s['win']:>6.1f} {s['sum_w_ret']:>+11.2f} "
            f"{s['pf']:>6.2f} {s['median_hold']:>7.1f} {s['max_hold']:>7.1f} "
            f"{s['edge_bp']:>7.1f} {s['ratio']:>9.2f}"
        )

    # 특이성 검증: 같은 히스테리시스 개념(단, 실제로는 각 알고 고유 로직)이 아니라,
    # "청산을 지연시키면 다른 알고도 좋아지는가"를 MIN_HOLD 비교로 간접 확인.
    print("  [특이성] 다른 알고에 MIN_HOLD만 늘렸을 때 대비 macd_momentum 개선폭 비교:")
    from dataclasses import replace

    mh = dict(backtest.BacktestSettings().min_hold_hours)
    mh[ALGO] = mh.get(ALGO, 8.0) * 2
    ctrl_trades = backtest.run_replay(
        frames, settings=replace(backtest.BacktestSettings(), min_hold_hours=mh)
    ).trades
    ctrl = _stats(ctrl_trades)
    print(
        f"    control(MIN_HOLD 2x, 히스테리시스 없음): n={ctrl['n']} "
        f"sum_w_ret={ctrl['sum_w_ret']:+.2f}%  (히스테리시스 Δ={hyst['sum_w_ret'] - base['sum_w_ret']:+.2f} "
        f"vs control Δ={ctrl['sum_w_ret'] - base['sum_w_ret']:+.2f})"
    )

    return dict(
        frames=frames,
        base_trades=base_trades,
        hyst_trades=hyst_trades,
        base=base,
        hyst=hyst,
        ctrl=ctrl,
    )


def _bootstrap_ci(
    trades: list, algo: str = ALGO, n_boot: int = 5000, seed: int = 2026
) -> tuple[float, float]:
    ts = [t for t in trades if t.algo_id == algo]
    if not ts:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    r = np.array([t.ret_pct for t in ts])
    w = np.array([t.position_weight for t in ts])
    boot = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(r), len(r))
        boot.append((r[idx] * w[idx]).sum() * 100)
    return tuple(np.percentile(boot, [2.5, 97.5]))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-macro-json", default="/tmp/bullval/macro_rows.json")
    ap.add_argument("--bear-parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--bear-from", default="2024-11-09")
    ap.add_argument("--bear-to", default="2026-07-25")
    ap.add_argument("--bear-limit", type=int, default=4000)
    args = ap.parse_args()

    await positions.init()
    results = {}

    bull_path = Path(args.bull_macro_json)
    if bull_path.exists():
        bull_macro = json.loads(bull_path.read_text())
        results["bull"] = await _run_window(
            "상승장 2023-08-04~2024-07-31 (BTCUSDT)",
            symbol="BTCUSDT",
            macro_rows=bull_macro,
            from_date=datetime(2023, 8, 4, tzinfo=timezone.utc),
            to_date=datetime(2024, 7, 31, tzinfo=timezone.utc),
            limit=2000,
        )

    bear_parquet = Path(args.bear_parquet)
    if bear_parquet.exists():
        bear_macro = build_macro_rows(bear_parquet)
        results["bear"] = await _run_window(
            f"하락장 {args.bear_from}~{args.bear_to} (명시적 창)",
            symbol=parameters.BINANCE_SYMBOL,
            macro_rows=bear_macro,
            from_date=datetime.strptime(args.bear_from, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            to_date=datetime.strptime(args.bear_to, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            limit=args.bear_limit,
        )

    print(f"\n{'=' * 80}\n[판정] 양쪽 창 개선 + 부트스트랩 검증\n{'=' * 80}")
    for win_name, r in results.items():
        if not r:
            continue
        d = r["hyst"]["sum_w_ret"] - r["base"]["sum_w_ret"]
        lo, hi = _bootstrap_ci(r["base_trades"])
        outside_ci = r["hyst"]["sum_w_ret"] > hi or r["hyst"]["sum_w_ret"] < lo
        print(
            f"  {win_name}: Δsum_w_ret={d:+.2f}%p  baseline 95%CI=[{lo:+.2f},{hi:+.2f}]  "
            f"hysteresis={r['hyst']['sum_w_ret']:+.2f}%  → "
            f"{'CI 밖(구분됨)' if outside_ci else 'CI 안(노이즈와 구분 어려움)'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
