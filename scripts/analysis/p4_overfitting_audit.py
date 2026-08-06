"""P4 과최적화 감사: 현재 채택 전략의 DSR를 누적 사양탐색 횟수로 재계산.

문서로 복원 가능한 시행횟수는 완전한 실제 N이 아니라 보수적 하한이다. 현재 기본 설정을
동일 프레임에서 한 번 재생하고, 알고별 거래 가중수익으로 N=1과 누적 N의 DSR를 비교한다.

재현:
  .venv/bin/python3 scripts/analysis/p4_overfitting_audit.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from validation_stats import (  # noqa: E402
    deflated_sharpe_ratio,
    documented_trial_count,
)

from arena import backtest, frequency, parameters, positions  # noqa: E402

TARGETS = ("fng_contrarian", "vix_rsi")


def _weighted_returns(trades: list, algo_id: str) -> np.ndarray:
    return np.asarray(
        [trade.ret_pct * trade.position_weight for trade in trades if trade.algo_id == algo_id],
        dtype=float,
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--limit", type=int, default=3800)
    ap.add_argument(
        "--out",
        default="docs/arena/research/p4-overfitting-audit-results-20260804.json",
    )
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    await positions.init()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
    frames = await backtest.load_frames_from_supabase(
        positions.db(),
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    result = backtest.run_replay(frames, settings=backtest.BacktestSettings())

    output: dict[str, object] = {
        "data": {
            "frames": len(frames),
            "start": frames[0].bar.close_time.isoformat(),
            "end": frames[-1].bar.close_time.isoformat(),
            "returns": "trade_ret_pct_times_position_weight",
        },
        "algorithms": {},
    }
    algorithms = output["algorithms"]
    assert isinstance(algorithms, dict)

    print(
        f"frames={len(frames)} {frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()}"
    )
    for algo_id in TARGETS:
        returns = _weighted_returns(result.trades, algo_id)
        n_trials = documented_trial_count(algo_id)
        naive = deflated_sharpe_ratio(returns, 1)
        audited = deflated_sharpe_ratio(returns, n_trials)
        verdict = "pass" if audited["dsr"] >= 0.95 else "fail"
        algorithms[algo_id] = {
            "trades": int(returns.size),
            "sum_weighted_return_pct": round(float(returns.sum() * 100), 6),
            "documented_n_trials_lower_bound": n_trials,
            "naive_dsr_n1": round(naive["dsr"], 6),
            "audited_dsr": round(audited["dsr"], 6),
            "sharpe_per_trade": round(audited["sharpe"], 6),
            "threshold": 0.95,
            "verdict": verdict,
        }
        print(
            f"{algo_id:16} trades={returns.size:3} N>={n_trials:2} "
            f"DSR(N=1)={naive['dsr']:.3f} DSR(audit)={audited['dsr']:.3f} {verdict}"
        )

    out = Path(args.out)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
