"""트레일링 거리 분리(TRAIL_DISTANCE_MULT_BY_ALGO) 그리드 튜닝 + MFE 포착률 비교.

배경: /arena-status MFE/MAE 재진단(2026-08-10) — vix_rsi 7건 중 5건, multi_factor 11건 중
10건이 MFE(보유중 최대유리이동) < 초기손절거리(=현재 trail_distance). ratchet_trailing_stop()
이 trail_distance=진입 시 손절거리를 그대로 재사용하므로, MFE가 그 거리에 못 미치는 대다수
거래에서 래칫이 사실상 손실구간에 머물러 익절 보호를 전혀 못 함. Tier2(TARGET_EXIT_ATR_MULT_
BY_ALGO, 전량 익절)는 PBO 0.877~0.921로 기각됐지만, 이번 설계는 손절과 독립적으로 트레일링
거리만 좁히는 것(자유도 1개, 승자를 일찍 자르는 캡 없음)이라 다른 실패모드.

⚠️ 단일 프레임 그리드는 과적합 가능 — 유망 config는 walk_forward_validate.py 패턴으로
롤링 검증 후 채택할 것(arena-exit-tuning SKILL.md §4).

재현:
  .venv/bin/python3 scripts/analysis/trail_distance_tuning.py --algo vix_rsi
  .venv/bin/python3 scripts/analysis/trail_distance_tuning.py --algo multi_factor
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

# (label, mult|None) — None = baseline(현행, mult=1.0과 동일 효과).
DEFAULT_GRID: list[tuple[str, float | None]] = [
    ("baseline (mult=1.0)", None),
    ("mult=0.7", 0.7),
    ("mult=0.6", 0.6),
    ("mult=0.5", 0.5),
    ("mult=0.4", 0.4),
    ("mult=0.3", 0.3),
    ("mult=0.2", 0.2),
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
        return {
            "n": 0, "sum_w": 0.0, "win": 0.0, "avg_mfe": 0.0, "avg_mae": 0.0,
            "cap": 0.0, "expectancy": 0.0, "payoff": 0.0,
        }  # fmt: skip
    rets = [t.ret_pct for t in ts]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    sum_w = sum(t.ret_pct * t.position_weight for t in ts) * 100
    win = len(wins) / n * 100
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = abs(statistics.mean(losses)) if losses else 0.0
    avg_mfe, avg_mae, cap = _mfe_capture(ts, frames)
    return {
        "n": n,
        "sum_w": sum_w,
        "win": win,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "cap": cap,
        "expectancy": (len(wins) / n * avg_win - len(losses) / n * avg_loss) * 100,
        "payoff": (avg_win / avg_loss) if avg_loss > 0 else 0.0,
    }


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

    o_mult = dict(parameters.TRAIL_DISTANCE_MULT_BY_ALGO)

    rows = []
    for label, mult in DEFAULT_GRID:
        parameters.TRAIL_DISTANCE_MULT_BY_ALGO = dict(o_mult)
        if mult is not None:
            parameters.TRAIL_DISTANCE_MULT_BY_ALGO[args.algo] = mult
        res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        target = _stats(res.trades, args.algo, frames)
        others = {a: _stats(res.trades, a, frames)["sum_w"] for a in ALGOS if a != args.algo}
        rows.append((label, target, others))

    parameters.TRAIL_DISTANCE_MULT_BY_ALGO = o_mult

    print(f"\n=== {args.algo} 트레일거리 그리드 (n·win%·가중합%·기대값·payoff·MFE·MAE·포착률) ===")
    print(
        f"{'config':22} {'n':>3} {'win%':>5} {'sum_w%':>7} {'exp%':>6} {'payoff':>6} "
        f"{'MFE%':>6} {'MAE%':>6} {'포착%':>6}  타알고 최대|Δ|(격리 확인용)"
    )
    base_others = rows[0][2]
    for label, s, others in rows:
        d_other = max((abs(others[a] - base_others[a]) for a in others), default=0.0)
        flag = "" if d_other < 0.01 else f"  ⚠️ {d_other:.2f} (타알고 변화 — 격리 확인 필요)"
        print(
            f"{label:22} {s['n']:>3} {s['win']:>5.0f} {s['sum_w']:>+7.2f} {s['expectancy']:>+6.2f} "
            f"{s['payoff']:>6.2f} {s['avg_mfe']:>+6.2f} {s['avg_mae']:>+6.2f} {s['cap']:>6.0f}{flag}"
        )
    print(
        "\n주의: 단일 프레임 그리드(과적합 가능) — 유망 config는 "
        "walk_forward_validate.py 패턴으로 롤링 검증 후 채택할 것."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
