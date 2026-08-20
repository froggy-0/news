"""숏 진입 최소신호 하한(TSMOM_NL_SHORT_MIN_SIGNAL) A/B (2026-08-20).

배경: v41이 macd_momentum 숏을 승격하면서 롱의 `TSMOM_NL_MIN_SIGNAL=0.0`
(v35, "거래량 우선" 선택, `parameters.py:927` 주석에 이미 "수익률 우선이면 {0.2,0.5}"
라고 기록돼 있었음)을 그대로 재사용했다. 사이징 f(s)=|s|/(s²+1)는 s가 0에 가까우면
같이 0에 수렴하므로, 라이브 10건 중 8건이 position_weight<0.10(1건은 0.000)으로
찍혔다 — 슬롯·표본만 소모하고 손익 기여가 없는 "유령 거래". 롱은 0.0이 이미 검증된
선택(v35 그리드)이라 그대로 두고, **숏 전용** 하한을 신설해 이 결함만 고친다.

검증: TSMOM_NL_SHORT_MIN_SIGNAL 후보 {0.0(현행), 0.05, 0.10, 0.15, 0.20}을
macd_momentum_short_noveto(v41 배선, risk-off veto 제거)에 적용해 3자산 A/B.
사이징도 후보 하한에 맞춰 최소 f(s) 보장 방식이 아니라 **진입 자체를 거른다**
(하한 미달 신호는 애초에 숏을 열지 않음 — 사이징만 손대면 여전히 소액 포지션이
열려 슬롯을 점유하는 문제가 안 풀림).

재현:
  .venv/bin/python3 scripts/analysis/short_min_signal_tuning.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import algorithms, backtest, frequency, parameters, positions  # noqa: E402
from arena.algorithms import _tsmom_nl_signal  # noqa: E402

CANDIDATES = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)


def _sizing_abs(macro: dict, ind: dict) -> float:
    if not parameters.TSMOM_NL_ENABLED:
        return 1.0
    s = _tsmom_nl_signal(ind)
    if s is None:
        return 0.0
    f = s / (s * s + 1.0)
    return max(0.0, min(parameters.TSMOM_NL_WEIGHT_CAP, abs(f)))


def make_short_fn(min_signal: float) -> backtest.StrategyFn:
    def fn(macro: dict, ind: dict) -> str | None:
        s = _tsmom_nl_signal(ind)
        if s is None:
            return None
        return "short" if s < -min_signal else None

    fn.__name__ = f"macd_momentum_short_min{min_signal}"
    return fn


def bootstrap_ci(rets: list[float], n_resamples: int = 3000, seed: int = 42) -> tuple[float, float]:
    if len(rets) < 3:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    arr = np.asarray(rets)
    draws = rng.choice(arr, size=(n_resamples, arr.size), replace=True).sum(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(lo), float(hi)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    algorithms.tsmom_nl_position_multiplier_abs = _sizing_abs

    macro_rows = build_macro_rows(parquet)
    print(f"백필 macro: {len(macro_rows)}일  후보: {CANDIDATES}\n")

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD

    totals: dict[float, list] = defaultdict(list)
    weight_hist: dict[float, list[float]] = defaultdict(list)

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
            continue
        print(f"########## {symbol} ##########")
        print(f"{'min_signal':12} {'n':>4} {'n(w<0.10)':>10} {'win%':>6} {'sum_w%':>8} {'PF':>6}")
        for cand in CANDIDATES:
            fns = {"macd_momentum": make_short_fn(cand)}
            settings = backtest.BacktestSettings(product_type="usdm_perp", symbol=symbol)
            res = backtest.run_replay(frames, strategy_fns=fns, settings=settings)
            trades = res.trades
            totals[cand].extend(trades)
            weight_hist[cand].extend(t.position_weight for t in trades)
            if not trades:
                print(f"{cand:<12} {0:>4}")
                continue
            n = len(trades)
            tiny = sum(1 for t in trades if t.position_weight < 0.10)
            win = sum(1 for t in trades if t.ret_pct > 0) / n * 100
            sw = sum(t.ret_pct * t.position_weight for t in trades) * 100
            gw = sum(t.ret_pct for t in trades if t.ret_pct > 0)
            gl = -sum(t.ret_pct for t in trades if t.ret_pct <= 0)
            pf = (gw / gl) if gl > 0 else float("inf")
            print(f"{cand:<12} {n:>4} {tiny:>10} {win:>6.1f} {sw:>+8.2f} {pf:>6.2f}")
        print()

    print("########## 3자산 합산 ##########")
    print(
        f"{'min_signal':12} {'n':>4} {'유령거래(w<0.10)':>16} {'sum_w%':>8} {'95%CI':>22} {'DSR(n_trials=1)':>16}"
    )
    base_n = len(totals[0.0])
    for cand in CANDIDATES:
        trades = totals[cand]
        n = len(trades)
        tiny = sum(1 for t in trades if t.position_weight < 0.10)
        sw_list = [t.ret_pct * t.position_weight for t in trades]
        sw = sum(sw_list) * 100
        lo, hi = bootstrap_ci(sw_list)
        rets = [t.ret_pct for t in trades]
        dsr_val = (
            deflated_sharpe_ratio(np.asarray(rets), n_trials=1)["dsr"]
            if len(rets) >= 5
            else float("nan")
        )
        ci_str = f"[{lo * 100:>+6.2f},{hi * 100:>+6.2f}]"
        print(f"{cand:<12} {n:>4} {tiny:>16} {sw:>+8.2f} {ci_str:>22} {dsr_val:>16.3f}")
    print(
        f"\n(참고: 후보 0.0 = 현행 라이브, n={base_n}건 중 유령거래 비중은 위 표의 "
        "'유령거래' 열 — 라이브 실측 8/10=80%와 이 백필 표본 비율이 비슷한지 대조)"
    )
    for cand in (0.3, 0.4, 0.5):
        ws = sorted(weight_hist[cand])
        print(f"min_signal={cand} weight 분포(오름차순 10개): {[round(w, 3) for w in ws[:10]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
