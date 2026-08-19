"""v33/v34 진입완화 개별 알고 전/후반 분할 재검증 (2026-08-19).

계기: v38(2026-08-16)이 4개 알고(regime_trend/multi_factor/macd_momentum)만
개별 분해했고 fng_contrarian/vix_rsi/omnibus 3개는 미검증 상태로 완화가
그대로 유지돼 있었다. `relaxation_cost_decomposition.py` 재실행 결과
(2026-08-19) 이 3개 전부 완화효과가 음수로 나왔다:

  fng_contrarian  -2.25%p
  vix_rsi         -2.93%p
  omnibus         -1.83%p

regime_trend 롤백 때 쓴 기준(개별 귀속 + 전/후반 분할 방향 일관)을 동일하게
적용해 이 3개도 전/후반에서 일관되게 해로운지 확인한다. B(완화ON+구비용)
vs D(완화OFF+구비용) — 비용효과를 배제하고 완화 자체만 격리.

재현:
  .venv/bin/python3 scripts/analysis/relaxation_split_period_check.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGET_ALGOS = ["fng_contrarian", "vix_rsi", "omnibus"]

RELAXED_V34 = {
    "REGIME_TREND_ENTRY_RELAXED_ENABLED": False,  # v38 기준 유지(이미 롤백됨)
    "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED": True,
    "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED": True,
    "VIX_RSI_ENTRY_RELAXED_ENABLED": True,
    "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES": 5,
    "MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES": 3,
    "MULTI_FACTOR_MIN_VOTES_EX_REGIME": 2,
    "OMNIBUS_REBOUND_MIN_VOTES": 2,
}
STRICT_PRE_V33 = {
    "REGIME_TREND_ENTRY_RELAXED_ENABLED": False,
    "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED": False,
    "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED": False,
    "VIX_RSI_ENTRY_RELAXED_ENABLED": False,
    "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES": 5,
    "MACD_MOMENTUM_ENTRY_MIN_SECONDARY_VOTES": 4,
    "MULTI_FACTOR_MIN_VOTES_EX_REGIME": 3,
    "OMNIBUS_REBOUND_MIN_VOTES": 3,
}
OLD_FEE_BPS = 5.0


def _apply(overrides: dict) -> dict:
    prev = {}
    for k, v in overrides.items():
        prev[k] = getattr(parameters, k)
        setattr(parameters, k, v)
    return prev


def _stats(trades: list, algo_id: str) -> dict:
    rets = np.asarray(
        [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo_id], dtype=float
    )
    n = rets.size
    if n == 0:
        return {"n": 0, "sum_pct": 0.0, "sharpe": 0.0}
    sd = rets.std(ddof=1) if n > 1 else 0.0
    return {
        "n": n,
        "sum_pct": float(rets.sum() * 100),
        "sharpe": float(rets.mean() / sd) if sd > 0 else 0.0,
    }


def _run(frames: list, flags: dict) -> dict:
    prev = _apply({**flags, "FEE_BPS": OLD_FEE_BPS})
    try:
        settings = backtest.BacktestSettings(product_type="spot", fee_bps=OLD_FEE_BPS)
        result = backtest.run_replay(frames, settings=settings)
        return {a: _stats(result.trades, a) for a in TARGET_ALGOS}
    finally:
        _apply(prev)


async def main() -> int:
    parquet = Path("data/sentiment_join/master_20260710.parquet")
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1
    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=profile.interval,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
        from_date=from_dt,
        to_date=to_dt,
    )
    frames = sorted(frames, key=lambda f: f.bar.close_time)
    mid = len(frames) // 2
    halves = {
        "전반": frames[:mid],
        "후반": frames[mid:],
        "전체": frames,
    }
    print(
        f"전체 frames={len(frames)}  {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
    )
    for label, hf in halves.items():
        print(
            f"  {label}: n={len(hf)}  {hf[0].bar.close_time.date()}~{hf[-1].bar.close_time.date()}"
        )

    table: dict[str, dict[str, dict]] = {}
    for label, hf in halves.items():
        table[f"{label}/B(완화ON)"] = _run(hf, RELAXED_V34)
        table[f"{label}/D(완화OFF)"] = _run(hf, STRICT_PRE_V33)

    print("\n" + "=" * 88)
    print("전/후반 분할 — 완화효과(B-D, 가중수익합%p) 방향 일관성")
    print("=" * 88)
    print(
        f"{'algo':16s} {'전반 B':>9s} {'전반 D':>9s} {'전반효과':>9s} "
        f"{'후반 B':>9s} {'후반 D':>9s} {'후반효과':>9s} {'일관?':>6s}"
    )
    for algo in TARGET_ALGOS:
        fb = table["전반/B(완화ON)"][algo]["sum_pct"]
        fd = table["전반/D(완화OFF)"][algo]["sum_pct"]
        hb = table["후반/B(완화ON)"][algo]["sum_pct"]
        hd = table["후반/D(완화OFF)"][algo]["sum_pct"]
        fe = fb - fd
        he = hb - hd
        consistent = "일관" if (fe < 0 and he < 0) or (fe > 0 and he > 0) else "불일치"
        print(
            f"{algo:16s} {fb:>+9.2f} {fd:>+9.2f} {fe:>+9.2f} "
            f"{hb:>+9.2f} {hd:>+9.2f} {he:>+9.2f} {consistent:>6s}"
        )

    print("\n전체 구간(참고, 비분할):")
    for algo in TARGET_ALGOS:
        b = table["전체/B(완화ON)"][algo]
        d = table["전체/D(완화OFF)"][algo]
        print(
            f"  {algo:16s} B: n={b['n']:>4d} sum={b['sum_pct']:>+7.2f}%  "
            f"D: n={d['n']:>4d} sum={d['sum_pct']:>+7.2f}%  효과={b['sum_pct'] - d['sum_pct']:>+7.2f}%p"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
