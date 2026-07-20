"""알고별 청산 파라미터(time_stop·min_hold) 그리드 튜닝 + MFE 포착률 비교 하니스.

배경: /arena-status 진단(2026-07-14)에서 vix_rsi(MFE포착률 -34%)·multi_factor(-92%)가
fng_contrarian(fng_optimize.py로 이미 튜닝됨)과 달리 청산 파라미터를 한 번도 탐색한 적이
없다는 것이 확인됨. TIME_STOP_HOURS_BY_ALGO·MIN_HOLD_HOURS는 algo_id 키 기반 범용 dict라
algorithms.py 코드 변경 없이 그리드 가능 — fng_optimize.py의 패턴을 임의 알고로 일반화.

⚠️ 이 스크립트는 "Tier 1"(제로 코드 변경) 튜닝만 다룬다. target-exit(목표가 익절)처럼
fng_contrarian/omnibus에만 있는 알고별 전용 메커니즘은 이 하니스로 그리드할 수 없다
(vix_rsi·multi_factor용 target-exit은 별도 설계·구현 필요 — arena-exit-tuning SKILL.md 참조).

재현:
  .venv/bin/python3 scripts/analysis/exit_tuning.py --algo vix_rsi
  .venv/bin/python3 scripts/analysis/exit_tuning.py --algo multi_factor \
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

# (label, time_stop_hours|None, min_hold_hours|None) — None = 해당 파라미터 미변경(기존값 유지).
DEFAULT_GRID: list[tuple[str, float | None, float | None]] = [
    ("baseline (현행)", None, None),
    ("ts24", 24.0, None),
    ("ts48", 48.0, None),
    ("ts72", 72.0, None),
    ("ts96", 96.0, None),
    ("mh12", None, 12.0),
    ("mh24", None, 24.0),
    ("ts48_mh24", 48.0, 24.0),
    ("ts72_mh24", 72.0, 24.0),
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

    o_ts = dict(parameters.TIME_STOP_HOURS_BY_ALGO)
    o_mh = dict(parameters.MIN_HOLD_HOURS)

    rows = []
    for label, ts_h, mh_h in DEFAULT_GRID:
        parameters.TIME_STOP_HOURS_BY_ALGO = dict(o_ts)
        parameters.MIN_HOLD_HOURS = dict(o_mh)
        if ts_h is not None:
            parameters.TIME_STOP_HOURS_BY_ALGO[args.algo] = ts_h
        if mh_h is not None:
            parameters.MIN_HOLD_HOURS[args.algo] = mh_h
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        target = _stats(res.trades, args.algo, frames)
        others = {a: _stats(res.trades, a, frames)["sum_w"] for a in ALGOS if a != args.algo}
        rows.append((label, target, others))

    parameters.TIME_STOP_HOURS_BY_ALGO = o_ts
    parameters.MIN_HOLD_HOURS = o_mh

    print(f"\n=== {args.algo} 청산 그리드 (n·win%·가중합%·MFE·MAE·포착률) ===")
    print(
        f"{'config':16} {'n':>3} {'win%':>5} {'sum_w%':>7} "
        f"{'MFE%':>6} {'MAE%':>6} {'포착%':>6}  타알고 최대|Δ|(격리 확인용)"
    )
    base_others = rows[0][2]
    for label, s, others in rows:
        d_other = max((abs(others[a] - base_others[a]) for a in others), default=0.0)
        flag = "" if d_other < 0.01 else f"  ⚠️ {d_other:.2f} (타알고 변화 — 격리 확인 필요)"
        print(
            f"{label:16} {s['n']:>3} {s['win']:>5.0f} {s['sum_w']:>+7.2f} "
            f"{s['avg_mfe']:>+6.2f} {s['avg_mae']:>+6.2f} {s['cap']:>6.0f}{flag}"
        )
    print(
        "\n주의: 단일 프레임 그리드(과적합 가능) — 유망 config는 "
        "walk_forward_validate.py 패턴으로 롤링 검증 후 채택할 것."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
