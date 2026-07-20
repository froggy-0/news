"""Tier2 목표가 익절(TARGET_EXIT_ATR_MULT_BY_ALGO) walk-forward 검증 + DSR/PBO 입력 생성.

target_exit_tuning.py(단일 프레임 그리드)에서 vix_rsi·multi_factor 결과가 비단조/약함으로
나와 과적합 여부를 확인해야 함(walk_forward_validate.py는 fng 전용 하드코딩이라 재사용
불가 — 이 스크립트가 동일 원리를 TARGET_EXIT_ATR_MULT_BY_ALGO 일반 알고에 적용).

1) 비중첩 N개 윈도로 나눠 config별 윈도 sum_w의 양(+)윈도 비율·평균·표준편차 확인
   (walk_forward_validate.py와 동일 판정 기준).
2) 전체 프레임에서 config별 대상 알고 트레이드의 가중수익 시계열을 JSON으로 저장 →
   validation_stats.py --json으로 DSR/PBO 계산(다중검정 보정).

재현:
  .venv/bin/python3 scripts/analysis/target_exit_walk_forward.py --algo vix_rsi
  .venv/bin/python3 scripts/analysis/target_exit_walk_forward.py --algo multi_factor
  .venv/bin/python3 scripts/analysis/validation_stats.py \
      --json /tmp/target_exit_wf_vix_rsi.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]
GRID: list[tuple[str, float | None]] = [
    ("baseline", None),
    ("atr1.5", 1.5),
    ("atr2.0", 2.0),
    ("atr2.5", 2.5),
    ("atr3.0", 3.0),
]


@contextmanager
def _target_mult(algo: str, mult: float | None):
    saved = dict(parameters.TARGET_EXIT_ATR_MULT_BY_ALGO)
    try:
        parameters.TARGET_EXIT_ATR_MULT_BY_ALGO = dict(saved)
        if mult is None:
            parameters.TARGET_EXIT_ATR_MULT_BY_ALGO.pop(algo, None)
        else:
            parameters.TARGET_EXIT_ATR_MULT_BY_ALGO[algo] = mult
        yield
    finally:
        parameters.TARGET_EXIT_ATR_MULT_BY_ALGO = saved


def _weighted_returns(trades, algo: str) -> list[float]:
    return [t.ret_pct * t.position_weight for t in trades if t.algo_id == algo]


def _per_bar_returns(result, algo: str) -> list[float]:
    """프레임별 realized_ret_pct(가중) — 모든 config에서 길이가 len(frames)로 동일해
    PBO(CSCV)가 요구하는 정렬된 시계열로 쓸 수 있다(트레이드 단위 배열은 config마다
    체결 수가 달라 정렬이 깨짐)."""
    return [p.realized_ret_pct for p in result.equity_curve if p.algo_id == algo]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", required=True, choices=ALGOS)
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--out-json", default=None, help="기본 /tmp/target_exit_wf_<algo>.json")
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    warm = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    prof = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        positions.db(),
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warm,
        indicator_profile_id=prof.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    W = args.windows
    size = len(frames) // W
    windows = [frames[i * size : (i + 1) * size] for i in range(W)]
    print(
        f"frames={len(frames)} {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
        f"  → {W}개 윈도(각 ~{size}봉)  target={args.algo}"
    )

    per_config_full_returns: dict[str, list[float]] = {}

    print(f"\n=== {args.algo} walk-forward (윈도별 가중수익 합, 견고성) ===")
    for label, mult in GRID:
        window_sums = []
        window_ns = []
        for w in windows:
            with _target_mult(args.algo, mult):
                res = backtest.run_replay(w, settings=backtest.BacktestSettings())
            rets = _weighted_returns(res.trades, args.algo)
            window_sums.append(sum(rets) * 100)
            window_ns.append(len(rets))
        with _target_mult(args.algo, mult):
            full_res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
        # per-bar 정렬 시계열(PBO용) — 모든 config가 len(frames)로 동일 길이.
        per_config_full_returns[label] = _per_bar_returns(full_res, args.algo)

        pos_w = sum(1 for x in window_sums if x > 0)
        print(
            f"[{label:10}] 윈도합%: {['%+.1f' % x for x in window_sums]}  n={window_ns}  "
            f"양의윈도 {pos_w}/{W}  평균{statistics.mean(window_sums):+.2f}  "
            f"표준편차{statistics.pstdev(window_sums):.2f}"
        )

    out_path = (
        Path(args.out_json) if args.out_json else Path(f"/tmp/target_exit_wf_{args.algo}.json")
    )
    out_path.write_text(json.dumps(per_config_full_returns, indent=2))
    print(f"\nDSR/PBO 입력 저장: {out_path}")
    print(f"다음: .venv/bin/python3 scripts/analysis/validation_stats.py --json {out_path}")
    print(
        "\n판정 기준: 양의윈도 비율↑·표준편차↓·평균↑ = 견고. 특정 윈도에만 몰린 이익은 과적합 의심."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
