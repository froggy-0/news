"""정성 분석 가설(2026-07-30) A/B 검증 — /arena-status 세션 발견.

라이브 39건 청산 거래를 signal_reason 원문으로 직접 읽어 발견한 3개 패턴 중,
파라미터화 가능한 2개를 20개월 macro 백필 백테스트로 검증:

1. multi_factor: 손실 6/7건이 arena_regime_state=sideways 진입에 집중(승률14%) —
   MULTI_FACTOR_ALLOW_SIDEWAYS=False(강세 전용)가 나은지 재검증(WI-1은 11개월
   데이터로 이미 True를 채택했으나, 이번 발견은 이후 5주 라이브 데이터 기반).
2. fng_contrarian / vix_rsi: "얕은" 신호(FNG가 30에 가까움/RSI가 50에 가까움)가
   "깊은" 신호보다 승률이 높은 교차알고 패턴 — 하한 밴드(FNG_CONTRARIAN_MIN_FEAR/
   VIX_RSI_MIN_RSI) 그리드로 검증.

wi_tuning.py와 동일 프레임·동일 오버라이드 패턴 재사용.

재현:
  .venv/bin/python3 scripts/analysis/qual_hypothesis_tuning.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import deflated_sharpe_ratio, effective_trial_count  # noqa: E402
from wi_tuning import _algo_stats, _line, _params  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALL_ALGOS = [
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
]


def _run(frames, overrides: dict) -> list:
    with _params(**overrides):
        return backtest.run_replay(frames, settings=backtest.BacktestSettings()).trades


def grid(frames, b: dict, name: str, target: str, configs: dict[str, dict]) -> None:
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
    if usable:
        best = max(results, key=lambda k: results[k]["sum_w_ret"])
        if len(usable) >= 2 and best in usable:
            n_trials = effective_trial_count(len(usable), algo_id=target)
            dsr = deflated_sharpe_ratio(np.asarray(usable[best]), n_trials)
            print(
                f"      best={best}  DSR sharpe={dsr['sharpe']:.3f} "
                f"dsr={dsr['dsr']:.3f} n_trials={n_trials}"
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
        limit=3800,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    base = _run(frames, {})
    b = {a: _algo_stats(base, a) for a in ALL_ALGOS}
    print("\n=== BASELINE ===")
    for a, s in b.items():
        pf_num = sum(r for r in s["rets"] if r > 0)
        pf_den = -sum(r for r in s["rets"] if r < 0)
        pf = (pf_num / pf_den) if pf_den > 0 else float("inf")
        print(
            f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+6.2f}  PF {pf:.2f}"
        )

    # 가설 1: multi_factor sideways 허용 여부
    grid(
        frames,
        b,
        "정성H1: multi_factor 횡보 허용 재검증(20개월)",
        "multi_factor",
        {
            "A_baseline(횡보허용,현행v31)": {},
            "B_강세전용(ALLOW_SIDEWAYS=False)": {"MULTI_FACTOR_ALLOW_SIDEWAYS": False},
        },
    )

    # 가설 2a: fng_contrarian 얕은-공포 하한 밴드
    grid(
        frames,
        b,
        "정성H2a: fng_contrarian 하한밴드(FNG_CONTRARIAN_MIN_FEAR)",
        "fng_contrarian",
        {
            "A_baseline(하한없음)": {},
            "B_min15": {"FNG_CONTRARIAN_MIN_FEAR": 15.0},
            "C_min20": {"FNG_CONTRARIAN_MIN_FEAR": 20.0},
            "D_min22": {"FNG_CONTRARIAN_MIN_FEAR": 22.0},
        },
    )

    # 가설 2b: vix_rsi 얕은-침체 하한 밴드
    grid(
        frames,
        b,
        "정성H2b: vix_rsi 하한밴드(VIX_RSI_MIN_RSI)",
        "vix_rsi",
        {
            "A_baseline(하한없음)": {},
            "B_min35": {"VIX_RSI_MIN_RSI": 35.0},
            "C_min40": {"VIX_RSI_MIN_RSI": 40.0},
            "D_min45": {"VIX_RSI_MIN_RSI": 45.0},
        },
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
