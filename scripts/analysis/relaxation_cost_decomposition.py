"""v33/v34 진입완화 × 비용모델(arena-cost-v3) 영향 분해 (2026-08-16).

계기: `evidence_criteria_audit.py` 실행 결과 롱 6알고가 이 창에서 **전부 거래당 SR
음수**로 나왔다. 그런데 P4 감사(2026-08-04)는 같은 parquet 창에서 `fng_contrarian`
+2.50%, `vix_rsi` +5.70%(둘 다 양수)였다. 그 사이 바뀐 것은 두 가지뿐이다:

  1. v33(2026-08-06)/v34(2026-08-07) 진입완화 — "표본 확보 우선" 결정.
  2. arena-cost-v3(2026-08-07) — FEE_BPS 5.0→10.0, 왕복 13→23bps.

둘 다 손익을 낮추는 방향이라 어느 쪽이 주범인지 분해하지 않으면 "표본 확보 결정이
엣지를 파괴했는가"라는 질문에 답할 수 없다. 2×2로 분해한다(그리드 탐색이 아니라
이미 내려진 두 결정의 사후 귀속 — 새 파라미터를 고르는 게 아님).

  A. 완화ON  + 23bps  = 현행
  B. 완화ON  + 13bps  = 비용만 되돌림
  C. 완화OFF + 23bps  = 완화만 되돌림
  D. 완화OFF + 13bps  = P4 감사 시점 조건

모든 토글은 이 프로세스 로컬(parameters 모듈 속성 재할당)이며 소스·라이브 무변경 —
기존 숏 백테스트 스크립트들이 쓰는 몽키패치 관행과 동일하다.

재현:
  .venv/bin/python3 scripts/analysis/relaxation_cost_decomposition.py
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

ALGOS = [
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
]

# v33/v34에서 완화된 값 → v32(완화 이전) 값.
RELAXED_V34 = {
    "REGIME_TREND_ENTRY_RELAXED_ENABLED": True,
    "MACD_MOMENTUM_ENTRY_RELAXED_ENABLED": True,
    "FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED": True,
    "VIX_RSI_ENTRY_RELAXED_ENABLED": True,
    "REGIME_TREND_ENTRY_MIN_SECONDARY_VOTES": 4,
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


def _apply(overrides: dict) -> dict:
    """parameters 속성 일괄 설정, 이전 값 반환(복구용)."""
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
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
    )

    # 비용: BacktestSettings 기본이 현행(23bps 상당). 구 비용은 fee 5bps로 재구성.
    cells = {
        "A 완화ON+신비용(현행)": (RELAXED_V34, 10.0),
        "B 완화ON+구비용": (RELAXED_V34, 5.0),
        "C 완화OFF+신비용": (STRICT_PRE_V33, 10.0),
        "D 완화OFF+구비용(P4조건)": (STRICT_PRE_V33, 5.0),
    }

    table: dict[str, dict[str, dict]] = {}
    for label, (flags, fee) in cells.items():
        prev = _apply({**flags, "FEE_BPS": fee})
        try:
            # slippage/spread는 base cost scenario 기본값 그대로 두고 fee만 토글
            # (arena-cost-v3의 실제 변경분이 FEE_BPS 5→10 하나뿐이므로).
            settings = backtest.BacktestSettings(product_type="spot", fee_bps=fee)
            result = backtest.run_replay(frames, settings=settings)
            table[label] = {a: _stats(result.trades, a) for a in ALGOS}
        finally:
            _apply(prev)

    print("\n" + "=" * 92)
    print("2×2 분해 — 거래수 / 가중수익합% / 거래당SR")
    print("=" * 92)
    for algo in ALGOS:
        print(f"\n{algo}")
        print(f"  {'셀':26s} {'n':>5s} {'sum%':>9s} {'SR':>9s}")
        for label in cells:
            s = table[label][algo]
            print(f"  {label:26s} {s['n']:>5d} {s['sum_pct']:>+9.2f} {s['sharpe']:>+9.3f}")

    print("\n" + "=" * 92)
    print("귀속 요약 — 각 효과의 단독 기여(가중수익합%p)")
    print("=" * 92)
    print(
        f"{'algo':16s} {'D(기준)':>10s} {'완화효과':>10s} {'비용효과':>10s} {'교호':>10s} {'A(현행)':>10s}"
    )
    for algo in ALGOS:
        d = table["D 완화OFF+구비용(P4조건)"][algo]["sum_pct"]
        c = table["C 완화OFF+신비용"][algo]["sum_pct"]
        b = table["B 완화ON+구비용"][algo]["sum_pct"]
        a = table["A 완화ON+신비용(현행)"][algo]["sum_pct"]
        relax_effect = b - d  # 구비용 고정, 완화만
        cost_effect = c - d  # 완화OFF 고정, 비용만
        interaction = a - d - relax_effect - cost_effect
        print(
            f"{algo:16s} {d:>+10.2f} {relax_effect:>+10.2f} {cost_effect:>+10.2f} "
            f"{interaction:>+10.2f} {a:>+10.2f}"
        )

    total_d = sum(table["D 완화OFF+구비용(P4조건)"][a]["sum_pct"] for a in ALGOS)
    total_a = sum(table["A 완화ON+신비용(현행)"][a]["sum_pct"] for a in ALGOS)
    total_b = sum(table["B 완화ON+구비용"][a]["sum_pct"] for a in ALGOS)
    total_c = sum(table["C 완화OFF+신비용"][a]["sum_pct"] for a in ALGOS)
    print(
        f"\n6알고 합산: D={total_d:+.2f}%  →  완화만={total_b:+.2f}%  "
        f"비용만={total_c:+.2f}%  현행A={total_a:+.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
