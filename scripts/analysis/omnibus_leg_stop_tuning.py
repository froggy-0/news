"""omnibus DOWN_TREND 레그 손절 재설계(변형 X) A/B — 2개 창 × 레그별 분해.

omnibus-stop-distance-design-20260804.md §6 명세 재현. regime_trend_exit_tuning.py/
macd_momentum_exit_tuning.py와 동일 방법론 + 레그 태깅(§2 진단 스크립트 방식 재사용,
algorithms.omnibus_regime_for(trade.macro_snapshot, trade.indicator_snapshot)).

채택 기준(설계 §6-1):
  1) 엣지/비용 비율 — DOWN_TREND 레그 단독
  2) 양쪽 창(상승장/하락장) 동시 개선
  3) 특이성 — UP_TREND/RANGE 레그가 (의도대로) 불변인지
  4) 부트스트랩 95% CI — DOWN_TREND 레그 거래풀
  5) 전/후반 분할 — 2026-07-25 실패 재현 여부(레그 분리로 해소되는지가 핵심 가설)

재현:
  .venv/bin/python3 scripts/analysis/omnibus_leg_stop_tuning.py \
      --bull-macro-json /tmp/bullval/macro_rows.json \
      --bear-parquet data/sentiment_join/master_20260710.parquet
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

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402

ALGO = "omnibus"
RT_BPS = 2 * parameters.FEE_BPS + 2 * 1.0 + 1.0

# 변형 X 시간손절 그리드 — fng_contrarian v22의 72h를 시작값으로, 좌우 대조 포함.
TIME_STOP_GRID = [48.0, 72.0, 96.0]


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


def _leg_of(t) -> str:
    return algorithms.omnibus_regime_for(t.macro_snapshot, t.indicator_snapshot)


def _stats(trades: list, leg: str | None = None) -> dict:
    ts = [t for t in trades if t.algo_id == ALGO]
    if leg is not None:
        ts = [t for t in ts if _leg_of(t) == leg]
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
            stop_share=0.0,
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
    stop_n = sum(1 for t in ts if t.exit_reason in ("stop_loss", "trailing_stop"))
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
        stop_share=stop_n / n * 100,
    )


def _bootstrap_ci(
    trades: list, leg: str, n_boot: int = 5000, seed: int = 2026
) -> tuple[float, float]:
    ts = [t for t in trades if t.algo_id == ALGO and _leg_of(t) == leg]
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


def _print_leg_table(label: str, base_trades: list, variant_trades: dict[str, list]) -> None:
    print(f"\n{'=' * 100}\n{label}\n{'=' * 100}")
    hdr = (
        f"{'variant':16} {'leg':10} {'n':>4} {'win%':>6} {'sum_w_ret%':>11} {'PF':>6} "
        f"{'중앙h':>7} {'최대h':>7} {'손절비중%':>9} {'엣지/비용':>9}"
    )
    print(hdr)
    all_variants = {"baseline": base_trades, **variant_trades}
    for vname, trades in all_variants.items():
        for leg in ("DOWN_TREND", "UP_TREND", "RANGE"):
            s = _stats(trades, leg=leg)
            print(
                f"{vname:16} {leg:10} {s['n']:>4} {s['win']:>6.1f} {s['sum_w_ret']:>+11.2f} "
                f"{s['pf']:>6.2f} {s['median_hold']:>7.1f} {s['max_hold']:>7.1f} "
                f"{s['stop_share']:>9.1f} {s['ratio']:>9.2f}"
            )


def _half_split_stats(trades: list, leg: str) -> tuple[dict, dict]:
    ts = sorted(
        (t for t in trades if t.algo_id == ALGO and _leg_of(t) == leg),
        key=lambda t: t.open_time,
    )
    mid = len(ts) // 2
    return _stats(ts[:mid], leg=None) | {"_n_raw": len(ts[:mid])}, _stats(ts[mid:], leg=None) | {
        "_n_raw": len(ts[mid:])
    }


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

    variant_trades: dict[str, list] = {}
    for ts_hours in TIME_STOP_GRID:
        name = f"X_ts{int(ts_hours)}h"
        with _params(
            OMNIBUS_PRICE_STOP_DISABLED_LEGS=("DOWN_TREND",),
            OMNIBUS_LEG_TIME_STOP_HOURS={"DOWN_TREND": ts_hours},
        ):
            variant_trades[name] = backtest.run_replay(
                frames, settings=backtest.BacktestSettings()
            ).trades

    _print_leg_table(label, base_trades, variant_trades)

    # 특이성: UP_TREND/RANGE는 baseline과 동일해야(레그 태깅이 손절 스위치와만 결합)
    print("  [특이성 체크] UP_TREND/RANGE가 baseline과 동일한가:")
    for vname, trades in variant_trades.items():
        for leg in ("UP_TREND", "RANGE"):
            b = _stats(base_trades, leg=leg)
            v = _stats(trades, leg=leg)
            same = "✅동일" if abs(v["sum_w_ret"] - b["sum_w_ret"]) < 1e-9 else "❌변동"
            print(
                f"    {vname:16} {leg:10} baseline={b['sum_w_ret']:+.2f}% "
                f"variant={v['sum_w_ret']:+.2f}%  {same}"
            )

    # 전/후반 분할 — DOWN_TREND 레그만(2026-07-25 실패 재현 여부 핵심 체크)
    print("  [전/후반 분할] DOWN_TREND 레그:")
    base_front, base_back = _half_split_stats(base_trades, "DOWN_TREND")
    for vname, trades in variant_trades.items():
        v_front, v_back = _half_split_stats(trades, "DOWN_TREND")
        d_front = v_front["sum_w_ret"] - base_front["sum_w_ret"]
        d_back = v_back["sum_w_ret"] - base_back["sum_w_ret"]
        both = "✅양쪽개선" if (d_front > 0 and d_back > 0) else "❌불일치/악화"
        print(
            f"    {vname:16} 전반Δ={d_front:+.2f}%(n={base_front['_n_raw']}) "
            f"후반Δ={d_back:+.2f}%(n={base_back['_n_raw']})  {both}"
        )

    return dict(base_trades=base_trades, variant_trades=variant_trades)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-macro-json", default="/tmp/bullval/macro_rows.json")
    ap.add_argument("--bear-parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--bear-from", default="2024-11-09")
    ap.add_argument("--bear-to", default="2026-07-25")
    ap.add_argument("--bear-limit", type=int, default=4000)
    args = ap.parse_args()

    await positions.init()
    results: dict[str, dict] = {}

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
    else:
        print(f"⚠️  {bull_path} 없음 — 상승장 창 스킵")

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
    else:
        print(f"⚠️  {bear_parquet} 없음 — 하락장 창 스킵")

    print(f"\n{'=' * 100}\n[판정] DOWN_TREND 레그 — 양쪽 창 개선 + 부트스트랩\n{'=' * 100}")
    for win_name, r in results.items():
        if not r:
            continue
        base_stats = _stats(r["base_trades"], leg="DOWN_TREND")
        lo, hi = _bootstrap_ci(r["base_trades"], "DOWN_TREND")
        for vname, trades in r["variant_trades"].items():
            v_stats = _stats(trades, leg="DOWN_TREND")
            d = v_stats["sum_w_ret"] - base_stats["sum_w_ret"]
            outside_ci = v_stats["sum_w_ret"] > hi or v_stats["sum_w_ret"] < lo
            print(
                f"  [{win_name}] {vname:16} Δsum_w_ret={d:+.2f}%p  "
                f"baseline 95%CI=[{lo:+.2f},{hi:+.2f}]  variant={v_stats['sum_w_ret']:+.2f}%  → "
                f"{'CI 밖(구분됨)' if outside_ci else 'CI 안(노이즈와 구분 어려움)'}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
