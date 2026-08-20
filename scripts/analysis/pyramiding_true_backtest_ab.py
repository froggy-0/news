"""피라미딩(승자 불타기) — 진짜 백테스트 엔진 A/B (사후시뮬 아님) (2026-08-20).

배경: pyramiding_feasibility.py는 청산 시점을 baseline 그대로 고정한 사후
시뮬레이션이었다(진입 트랜치만 추가). 이 스크립트는 그 한계를 없앤다 —
`parameters.PYRAMID_UP_ENABLED_ALGOS`를 프로세스에서 직접 토글해 `backtest.run_replay`
(실제 엔진, `algorithms.ALGORITHMS` 그대로)를 두 번 돌린다. 청산도 진짜로
재시뮬레이션되므로(트랜치가 체결되면 그 시점부터 신호·손절·트레일링이 실제 엔진
로직으로 굴러간다) 사후 시뮬의 근사 오차가 없다. `test_pyramid_up_does_not_change_
trailing_stop_distance`(tests/test_arena_backtest.py)가 이미 단위 테스트로 확인한
"트레일링은 절대 trail_distance만 참조, 평단·비중과 무관"이 실제로 이 결과에도
반영된다.

대상: 추세계열 4개(macd_momentum·regime_trend·omnibus·multi_factor) — 문헌상
평균회귀(fng_contrarian·vix_rsi)엔 피라미딩이 부적합해 대상에서 제외.

재현:
  .venv/bin/python3 scripts/analysis/pyramiding_true_backtest_ab.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TREND_ALGOS = ("macd_momentum", "regime_trend", "omnibus", "multi_factor")


def bootstrap_ci(rets: list[float], n_resamples: int = 3000, seed: int = 42) -> tuple[float, float]:
    if len(rets) < 3:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    arr = np.asarray(rets)
    draws = rng.choice(arr, size=(n_resamples, arr.size), replace=True).sum(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(lo), float(hi)


def split_half(trades: list) -> tuple[float, float]:
    if len(trades) < 4:
        return float("nan"), float("nan")
    ordered = sorted(trades, key=lambda t: t.open_time)
    mid = len(ordered) // 2
    first = sum(t.ret_pct * t.position_weight for t in ordered[:mid]) * 100
    second = sum(t.ret_pct * t.position_weight for t in ordered[mid:]) * 100
    return first, second


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
    print(f"백필 macro: {len(macro_rows)}일  대상: {TREND_ALGOS}")
    print(f"PYRAMID_UP_LEVELS: {parameters.PYRAMID_UP_LEVELS}\n")

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    per_algo_trades: dict[str, dict[str, list]] = {a: {"off": [], "on": []} for a in TREND_ALGOS}

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

        parameters.PYRAMID_UP_ENABLED_ALGOS = frozenset()
        res_off = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        parameters.PYRAMID_UP_ENABLED_ALGOS = frozenset(TREND_ALGOS)
        res_on = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        parameters.PYRAMID_UP_ENABLED_ALGOS = frozenset()  # 복구(다음 심볼·타 알고 무영향)

        print(f"########## {symbol} ##########")
        print(f"{'algo':16} {'n(off/on)':>12} {'sum_w off':>10} {'sum_w on':>10} {'Δ':>8}")
        for algo in TREND_ALGOS:
            off = [t for t in res_off.trades if t.algo_id == algo]
            on = [t for t in res_on.trades if t.algo_id == algo]
            per_algo_trades[algo]["off"].extend(off)
            per_algo_trades[algo]["on"].extend(on)
            sw_off = sum(t.ret_pct * t.position_weight for t in off) * 100
            sw_on = sum(t.ret_pct * t.position_weight for t in on) * 100
            print(
                f"{algo:16} {len(off):>5}/{len(on):<5} {sw_off:>+10.2f} {sw_on:>+10.2f} {sw_on - sw_off:>+8.2f}"
            )
        print()

    print("########## 3자산 합산 — 진짜 엔진 재시뮬레이션 결과 ##########")
    print(
        f"{'algo':16} {'n_off':>6} {'n_on':>6} {'sum_off%':>10} {'sum_on%':>10} {'Δ%p':>8} {'CI(Δ,거래합)':>24} {'DSR_on':>8}"
    )
    grand_off = grand_on = 0.0
    for algo in TREND_ALGOS:
        off = per_algo_trades[algo]["off"]
        on = per_algo_trades[algo]["on"]
        sw_off = sum(t.ret_pct * t.position_weight for t in off) * 100
        sw_on = sum(t.ret_pct * t.position_weight for t in on) * 100
        grand_off += sw_off
        grand_on += sw_on
        # Δ의 부트스트랩은 페어링이 안 되므로(트랜치가 체결되면 청산 시점 자체가 달라져
        # 거래 개수도 바뀔 수 있음) on/off 각각의 거래단위 합을 리샘플링해 분포 차 추정.
        on_rets = [t.ret_pct * t.position_weight for t in on]
        off_rets = [t.ret_pct * t.position_weight for t in off]
        lo_on, hi_on = bootstrap_ci(on_rets)
        lo_off, hi_off = bootstrap_ci(off_rets)
        rets_on_raw = [t.ret_pct for t in on]
        dsr_on = (
            deflated_sharpe_ratio(np.asarray(rets_on_raw), n_trials=1)["dsr"]
            if len(rets_on_raw) >= 5
            else float("nan")
        )
        ci_str = f"on[{lo_on * 100:+.1f},{hi_on * 100:+.1f}]"
        print(
            f"{algo:16} {len(off):>6} {len(on):>6} {sw_off:>+10.2f} {sw_on:>+10.2f} "
            f"{sw_on - sw_off:>+8.2f} {ci_str:>24} {dsr_on:>8.3f}"
        )
        fh_off, sh_off = split_half(off)
        fh_on, sh_on = split_half(on)
        print(
            f"{'':16} 전/후반: off[{fh_off:+.2f}/{sh_off:+.2f}]  on[{fh_on:+.2f}/{sh_on:+.2f}]  "
            f"off CI[{lo_off * 100:+.1f},{hi_off * 100:+.1f}]"
        )
    print(
        f"\n  4알고 합계: off {grand_off:+.2f}%  on {grand_on:+.2f}%  Δ{grand_on - grand_off:+.2f}%p"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
