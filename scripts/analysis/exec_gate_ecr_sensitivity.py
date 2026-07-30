"""execution_gate ecr_multiple 민감도 — Bysik & Ślepaczuk(2026, arXiv:2606.00060) 재현.

이 논문의 H2(cost-aware execution filter, |forecast|>λ·cost·turnover)와 §6.1
λ 민감도 그리드(Table 16)를 아레나의 evaluate_execution_gate()(ecr_multiple=λ에
대응)에 그대로 적용한다. P8(dormant-data-audit-20260726)에서 발견된 실행게이트는
현재 섀도우 전용이라 실거래 경로를 안 바꾸므로, 20개월 macro 백필 백테스트에서
생성된 거래를 사후(post-hoc) 필터링해 "이 게이트를 그 λ로 실제 강제했다면 살아남았을
거래만으로 성과가 어떻게 바뀌는가"를 본다(qual_hypothesis_tuning.py와 동일한
사후-서브셋 기법, 실행 경로 자체는 미변경).

논문과의 차이(한계): 논문은 필터가 막은 봉에서 "직전 포지션 유지"라 전체 수익경로가
재생성되지만, 여기서는 거래 단위로 allow/reject만 판정 — 막힌 거래를 제거한 나머지
거래들의 집계 성과를 본다(포지션 유지에 따른 후속 재상관 효과는 미반영, 근사치).

재현:
  .venv/bin/python3 scripts/analysis/exec_gate_ecr_sensitivity.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, execution_gate, frequency, parameters, positions  # noqa: E402

ALL_ALGOS = [
    "regime_trend",
    "fng_contrarian",
    "vix_rsi",
    "macd_momentum",
    "multi_factor",
    "omnibus",
]

# 논문 Table 16 그리드(λ∈{0,0.5,...,5.0})에 아레나 현재값(3.0)을 끼워넣은 버전.
ECR_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


def _stats(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "win": 0.0, "sum_w_ret": 0.0}
    sum_w = sum(t.net_ret_pct * t.position_weight for t in trades) * 100
    win = sum(1 for t in trades if t.net_ret_pct > 0) / n * 100
    return {"n": n, "win": win, "sum_w_ret": sum_w}


def _allowed(trade, cost_scenario: frequency.CostScenario, ecr_multiple: float) -> bool:
    decision = execution_gate.evaluate_execution_gate(
        algo_id=trade.algo_id,
        signal=trade.direction,
        macro=trade.macro_snapshot or {},
        indicators=trade.indicator_snapshot or {},
        realtime_features=None,
        cost_scenario=cost_scenario,
        risk_decision=None,
        evaluated_at=trade.open_time,
        policy=execution_gate.ExecutionGatePolicy(ecr_multiple=ecr_multiple),
    )
    return decision.allowed


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
    cost_scenario = frequency.get_cost_scenario(profile.frequency_profile_id)
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
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}  "
        f"cost_scenario={cost_scenario.cost_scenario_id} round_trip={cost_scenario.trading_cost_bps_round_trip:.1f}bps"
    )

    result = backtest.run_replay(frames, settings=backtest.BacktestSettings())
    all_trades = result.trades
    baseline = {a: _stats([t for t in all_trades if t.algo_id == a]) for a in ALL_ALGOS}
    print("\n=== BASELINE (게이트 미적용, 현행 백테스트) ===")
    for a, s in baseline.items():
        print(f"  {a:16} n {s['n']:>3}  win {s['win']:>4.0f}  sum_w_ret {s['sum_w_ret']:>+7.2f}")

    total_base = sum(s["sum_w_ret"] for s in baseline.values())
    print(f"\n  전체합(6알고) baseline sum_w_ret = {total_base:+.2f}")

    print("\n=== λ(ecr_multiple) 민감도 — 논문 Table 16 스타일 (사후 allow-필터) ===")
    header = (
        f"{'λ':>5} | " + " | ".join(f"{a:>13}" for a in ALL_ALGOS) + " |   전체합 | 전체거부율%"
    )
    print(header)
    print("-" * len(header))
    for ecr in ECR_GRID:
        per_algo = {}
        total_n = 0
        total_allowed = 0
        for algo in ALL_ALGOS:
            algo_trades = [t for t in all_trades if t.algo_id == algo]
            allowed_trades = [t for t in algo_trades if _allowed(t, cost_scenario, ecr)]
            per_algo[algo] = _stats(allowed_trades)
            total_n += len(algo_trades)
            total_allowed += len(allowed_trades)
        total_sum_w = sum(per_algo[a]["sum_w_ret"] for a in ALL_ALGOS)
        reject_rate = (1 - total_allowed / total_n) * 100 if total_n else 0.0
        cells = " | ".join(
            f"n{per_algo[a]['n']:>3} {per_algo[a]['sum_w_ret']:>+6.1f}" for a in ALL_ALGOS
        )
        marker = " <- 현행" if ecr == parameters.EXEC_GATE_ECR_MULTIPLE else ""
        print(f"{ecr:>5.1f} | {cells} | {total_sum_w:>+7.2f} | {reject_rate:>9.1f}{marker}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
