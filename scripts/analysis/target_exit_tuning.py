"""Tier2 목표가 익절(TARGET_EXIT_ATR_MULT_BY_ALGO) ATR배수 그리드 튜닝 + MFE 포착률 비교.

배경: exit_tuning.py(Tier1, time_stop/min_hold)로 vix_rsi(-34%)·multi_factor(-92%) MFE
포착률을 실측했으나 개선 없었음 — 시간 배리어는 이익을 붙잡는 메커니즘이 아니기 때문.
arena-exit-tuning SKILL.md Tier2 설계에 따라 vix_rsi/multi_factor에 범용 목표가 익절
(algorithms.atr_target_price, parameters.TARGET_EXIT_ATR_MULT_BY_ALGO)을 배선한 뒤,
이 스크립트로 ATR 배수를 그리드한다. exit_tuning.py와 동일 패턴(같은 프레임 재사용,
타알고 무회귀 확인)이며 기본 dict는 빈 상태이므로 이 스크립트 실행 자체는 읽기 전용
백테스트만 수행(parameters 오버라이드는 함수 종료 전 원복).

⚠️ 목표가를 너무 타이트하게 잡으면 포착률은 오르지만 payoff가 무너져 기대값이 악화될 수
있음 — sum_w·win%·MFE포착률을 함께 확인할 것. 단일 프레임 그리드는 과적합 가능하므로
유망 config는 walk_forward_validate.py 롤링 검증 → validation_stats.py DSR/PBO를 거친 뒤
parameters.py에 반영할 것.

재현:
  .venv/bin/python3 scripts/analysis/target_exit_tuning.py --algo vix_rsi
  .venv/bin/python3 scripts/analysis/target_exit_tuning.py --algo multi_factor \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]

# (label, atr_mult|None) — None = 목표가 익절 미적용(baseline, 기존 트레일링/flat 청산만).
DEFAULT_GRID: list[tuple[str, float | None]] = [
    ("baseline (현행, 목표가 없음)", None),
    ("atr1.5", 1.5),
    ("atr2.0", 2.0),
    ("atr2.5", 2.5),
    ("atr3.0", 3.0),
]


def _mfe_capture(trades: list, frames: list) -> tuple[float, float, float]:
    """(평균MFE%, 평균MAE%, MFE포착률%) — 4h봉 high/low 기준, arena_status._mfe_mae와 동일 정의."""
    bars = [(f.bar.close_time, f.bar.high, f.bar.low) for f in frames]
    caps, mfes, maes = [], [], []
    for t in trades:
        hi = lo = None
        for bt, h, low in bars:
            if bt < t.open_time or bt > t.close_time:
                continue
            hi = h if hi is None else max(hi, h)
            lo = low if lo is None else min(lo, low)
        if hi is None or lo is None or t.open_price <= 0:
            continue
        mfe = hi / t.open_price - 1.0
        mae = lo / t.open_price - 1.0
        mfes.append(mfe)
        maes.append(mae)
        if mfe > 0.003:
            caps.append(t.ret_pct / mfe)
    avg_mfe = statistics.mean(mfes) * 100 if mfes else 0.0
    avg_mae = statistics.mean(maes) * 100 if maes else 0.0
    cap = statistics.mean(caps) * 100 if caps else 0.0
    return avg_mfe, avg_mae, cap


def _stats(trades: list, algo_id: str, frames: list) -> dict:
    ts = [t for t in trades if t.algo_id == algo_id]
    n = len(ts)
    if n == 0:
        return {"n": 0, "sum_w": 0.0, "win": 0.0, "avg_mfe": 0.0, "avg_mae": 0.0, "cap": 0.0}
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = sum(1 for t in ts if t.ret_pct > 0) / n * 100
    avg_mfe, avg_mae, cap = _mfe_capture(ts, frames)
    return {"n": n, "sum_w": sum_w, "win": win, "avg_mfe": avg_mfe, "avg_mae": avg_mae, "cap": cap}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", required=True, choices=ALGOS)
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
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    print(
        f"frames={len(frames)}  {frames[0].bar.close_time.date()} ~ {frames[-1].bar.close_time.date()}"
    )

    o_map = dict(parameters.TARGET_EXIT_ATR_MULT_BY_ALGO)

    rows = []
    for label, mult in DEFAULT_GRID:
        parameters.TARGET_EXIT_ATR_MULT_BY_ALGO = dict(o_map)
        if mult is not None:
            parameters.TARGET_EXIT_ATR_MULT_BY_ALGO[args.algo] = mult
        else:
            parameters.TARGET_EXIT_ATR_MULT_BY_ALGO.pop(args.algo, None)
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        target = _stats(res.trades, args.algo, frames)
        others = {a: _stats(res.trades, a, frames)["sum_w"] for a in ALGOS if a != args.algo}
        rows.append((label, target, others))

    parameters.TARGET_EXIT_ATR_MULT_BY_ALGO = o_map

    print(f"\n=== {args.algo} Tier2 목표가 익절 ATR배수 그리드 (n·win%·가중합%·MFE·MAE·포착률) ===")
    print(
        f"{'config':28} {'n':>3} {'win%':>5} {'sum_w%':>7} "
        f"{'MFE%':>6} {'MAE%':>6} {'포착%':>6}  타알고 최대|Δ|(격리 확인용)"
    )
    base_others = rows[0][2]
    for label, s, others in rows:
        d_other = max((abs(others[a] - base_others[a]) for a in others), default=0.0)
        flag = "" if d_other < 0.01 else f"  ⚠️ {d_other:.2f} (타알고 변화 — 격리 확인 필요)"
        print(
            f"{label:28} {s['n']:>3} {s['win']:>5.0f} {s['sum_w']:>+7.2f} "
            f"{s['avg_mfe']:>+6.2f} {s['avg_mae']:>+6.2f} {s['cap']:>6.0f}{flag}"
        )
    print(
        "\n주의: 단일 프레임 그리드(과적합 가능) — 유망 config는 "
        "walk_forward_validate.py 패턴으로 롤링 검증 후 채택할 것. "
        "목표가가 타이트할수록 승률↑하지만 payoff가 무너질 수 있음(sum_w·기대값 함께 확인)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
