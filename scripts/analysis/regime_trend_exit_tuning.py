"""regime_trend 청산 히스테리시스 A/B — 5개 변형 × 2개 창(상승장/하락장).

entry-exit-separation-implementation-plan-20260804.md §6 명세 재현.
동일 frames에서 parameters 플래그만 뒤집어 run_replay 반복(wi_tuning.py 패턴).
채택 기준(§6-3): 엣지/비용 비율, 양쪽 창 동시 개선, 순열검정 — 이 스크립트는
1)(측정)만 수행하고 판정 문서화는 별도.

재현:
  .venv/bin/python3 scripts/analysis/regime_trend_exit_tuning.py \
      --bull-macro-json /tmp/bullval/macro_rows.json \
      --bull-symbol BTCUSDT --bull-from 2023-08-04 --bull-to 2024-07-31 \
      --bear-parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGO = "regime_trend"
RT_BPS = 2 * parameters.FEE_BPS + 2 * 1.0 + 1.0  # fee/leg*2 + slip/leg*2 + spread RT


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


VARIANTS: dict[str, dict] = {
    "baseline": {},
    "A1_state_no_slope": {
        "REGIME_TREND_EXIT_HYSTERESIS_ENABLED": True,
        "REGIME_TREND_EXIT_MODE": "state",
        "REGIME_TREND_EXIT_STATE_REQUIRE_SLOPE": False,
    },
    "A2_state_with_slope": {
        "REGIME_TREND_EXIT_HYSTERESIS_ENABLED": True,
        "REGIME_TREND_EXIT_MODE": "state",
        "REGIME_TREND_EXIT_STATE_REQUIRE_SLOPE": True,
    },
    "B1_donchian_exit": {
        "REGIME_TREND_EXIT_HYSTERESIS_ENABLED": True,
        "REGIME_TREND_EXIT_MODE": "donchian_exit",
    },
}


def _stats(trades: list) -> dict:
    ts = [t for t in trades if t.algo_id == ALGO]
    n = len(ts)
    if n == 0:
        return dict(
            n=0,
            win=0.0,
            sum_w_ret=0.0,
            pf=0.0,
            median_hold=0.0,
            max_hold=0.0,
            edge_per_trade_bp=0.0,
            cost_per_trade_bp=0.0,
            edge_cost_ratio=0.0,
        )
    wins = sum(1 for t in ts if t.ret_pct > 0)
    sum_w_ret = sum(t.ret_pct * t.position_weight for t in ts) * 100
    gp = sum(t.ret_pct for t in ts if t.ret_pct > 0)
    gl = -sum(t.ret_pct for t in ts if t.ret_pct <= 0)
    pf = gp / gl if gl > 0 else float("inf")
    net = sum_w_ret
    cost = sum(t.position_weight for t in ts) * RT_BPS / 100
    gross = net + cost
    edge_per_trade_bp = gross / n * 100
    cost_per_trade_bp = float(np.mean([t.position_weight for t in ts])) * RT_BPS
    ratio = edge_per_trade_bp / cost_per_trade_bp if cost_per_trade_bp else 0.0
    holds = [t.hold_hours for t in ts]
    return dict(
        n=n,
        win=wins / n * 100,
        sum_w_ret=sum_w_ret,
        pf=pf,
        median_hold=float(np.median(holds)),
        max_hold=float(max(holds)),
        edge_per_trade_bp=edge_per_trade_bp,
        cost_per_trade_bp=cost_per_trade_bp,
        edge_cost_ratio=ratio,
    )


def _print_window(label: str, results: dict[str, dict]) -> None:
    print(f"\n{'=' * 92}\n{label}\n{'=' * 92}")
    hdr = (
        f"{'variant':22} {'n':>4} {'win%':>6} {'sum_w_ret%':>11} {'PF':>6} "
        f"{'중앙보유h':>9} {'최대보유h':>9} {'엣지bp':>7} {'비용bp':>7} {'엣지/비용':>9}"
    )
    print(hdr)
    for name, s in results.items():
        print(
            f"{name:22} {s['n']:>4} {s['win']:>6.1f} {s['sum_w_ret']:>+11.2f} "
            f"{s['pf']:>6.2f} {s['median_hold']:>9.1f} {s['max_hold']:>9.1f} "
            f"{s['edge_per_trade_bp']:>7.1f} {s['cost_per_trade_bp']:>7.1f} "
            f"{s['edge_cost_ratio']:>9.2f}"
        )


async def _run_window(
    label: str,
    *,
    symbol: str,
    macro_rows: list[dict],
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
) -> dict[str, dict]:
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
        print(f"{label}: frames 없음 — 스킵")
        return {}
    bh = (frames[-1].bar.close - frames[0].bar.close) / frames[0].bar.close * 100
    print(
        f"\n[{label}] frames={len(frames)}  {frames[0].bar.close_time.date()}~"
        f"{frames[-1].bar.close_time.date()}  buy&hold={bh:+.2f}%"
    )

    results: dict[str, dict] = {}
    for name, overrides in VARIANTS.items():
        with _params(**overrides):
            trades = backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades
        results[name] = _stats(trades)

    # 교란변수 분리용: 히스테리시스 없이 MIN_HOLD만 12→24h 상향(§6-4).
    base_settings = backtest.BacktestSettings()
    mh = dict(base_settings.min_hold_hours)
    mh[ALGO] = 24.0
    control_settings = replace(base_settings, min_hold_hours=mh)
    trades_control = backtest.run_replay(frames, settings=control_settings).trades
    results["control_min_hold_24h"] = _stats(trades_control)

    _print_window(label, results)
    return results


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bull-macro-json", default="/tmp/bullval/macro_rows.json")
    ap.add_argument("--bull-symbol", default="BTCUSDT")
    ap.add_argument("--bull-from", default="2023-08-04")
    ap.add_argument("--bull-to", default="2024-07-31")
    ap.add_argument("--bear-parquet", default="data/sentiment_join/master_20260710.parquet")
    # priority-analysis-20260725.md/root-cause-diagnosis 문서와 동일한 정식 20개월 창.
    # limit/from_date/to_date 미지정 시 "최신 N봉"이 의도와 다른(더 최근·더 하락한) 창을
    # 잡을 수 있어 명시적으로 고정한다(이 스크립트 최초 실행에서 실제로 발생한 오류).
    ap.add_argument("--bear-from", default="2024-11-09")
    ap.add_argument("--bear-to", default="2026-07-25")
    ap.add_argument("--bear-limit", type=int, default=4000)
    ap.add_argument("--skip-bull", action="store_true")
    ap.add_argument("--skip-bear", action="store_true")
    args = ap.parse_args()

    await positions.init()

    all_results: dict[str, dict[str, dict]] = {}

    if not args.skip_bull:
        bull_path = Path(args.bull_macro_json)
        if not bull_path.exists():
            print(
                f"⚠️  {bull_path} 없음 — 상승장 창 스킵(historical-bull-market-backtest "
                f"§1.2 명세로 재생성 필요)"
            )
        else:
            bull_macro = json.loads(bull_path.read_text())
            from_dt = datetime.strptime(args.bull_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            to_dt = datetime.strptime(args.bull_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            r = await _run_window(
                f"상승장 {args.bull_from}~{args.bull_to} ({args.bull_symbol})",
                symbol=args.bull_symbol,
                macro_rows=bull_macro,
                from_date=from_dt,
                to_date=to_dt,
                limit=2000,
            )
            if r:
                all_results["bull"] = r

    if not args.skip_bear:
        bear_parquet = Path(args.bear_parquet)
        if not bear_parquet.exists():
            print(f"⚠️  {bear_parquet} 없음 — 하락장 창 스킵")
        else:
            bear_macro = build_macro_rows(bear_parquet)
            bear_from = datetime.strptime(args.bear_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            bear_to = datetime.strptime(args.bear_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            r = await _run_window(
                f"하락장 {args.bear_from}~{args.bear_to} (명시적 창)",
                symbol=parameters.BINANCE_SYMBOL,
                macro_rows=bear_macro,
                from_date=bear_from,
                to_date=bear_to,
                limit=args.bear_limit,
            )
            if r:
                all_results["bear"] = r

    if "bull" in all_results and "bear" in all_results:
        print(f"\n{'=' * 92}\n[판정 보조] 양쪽 창 동시 개선 여부 (§6-3 기준2)\n{'=' * 92}")
        print(f"{'variant':22} {'상승장Δsum%':>12} {'하락장Δsum%':>12} {'양쪽개선?':>10}")
        base_bull = all_results["bull"]["baseline"]["sum_w_ret"]
        base_bear = all_results["bear"]["baseline"]["sum_w_ret"]
        for name in VARIANTS:
            if name == "baseline":
                continue
            d_bull = all_results["bull"][name]["sum_w_ret"] - base_bull
            d_bear = all_results["bear"][name]["sum_w_ret"] - base_bear
            both = "✅" if (d_bull > 0 and d_bear > 0) else "❌"
            print(f"{name:22} {d_bull:>+12.2f} {d_bear:>+12.2f} {both:>10}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
