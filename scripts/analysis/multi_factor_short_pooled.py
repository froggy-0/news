"""multi_factor 숏 direction_soft — 3자산 풀링 DSR 재검증 (2026-08-16, 신규 가설).

배경: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md §11이
`multi_factor` 숏 direction_soft를 자산별로 검증했을 때 BTC/ETH/SOL 전부 방향이 양(+)이고
DSR도 0.38~0.44로 서로 밀집돼 있었는데(표본 n=10~12로 작아 개별로는 0.95 기준 미달),
자산을 풀링해 표본을 합친 적은 없었다 — 이 스크립트가 그 갭을 메운다.

방법: multi_factor_short_backtest.multi_factor_short_direction_soft를 그대로 재사용
(로직 무변경), 3자산 각각 run_replay 실행 후 거래 리스트를 하나로 합쳐 풀링 DSR·부트스트랩
CI·전/후반 분할을 계산한다. 그리드 아님, 단일 사양 재실행 — n_trials=1(이 풀링 자체가
새 가설이라 direction_soft의 자산별 검정과는 별개 시도).

⚠️ 해석 주의: 풀링된 거래가 시간적으로 겹치면(같은 4H 봉 근처에 BTC/ETH/SOL이 동시에
진입) 크립토 자산 간 상관성 때문에 "독립 표본 n개"라는 DSR의 암묵적 가정이 낙관적으로
깨진다 — 이 스크립트는 겹침 비율도 함께 출력해 이 위험을 정량화한다.

재현:
  .venv/bin/python3 scripts/analysis/multi_factor_short_pooled.py
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
from macd_momentum_short_backtest import _bootstrap_ci, _split_half  # noqa: E402
from multi_factor_short_backtest import VARIANTS_A, _run_symbol  # noqa: E402
from validation_stats import deflated_sharpe_ratio  # noqa: E402

from arena import backtest, positions  # noqa: E402


async def main() -> int:
    parquet = Path("data/sentiment_join/master_20260710.parquet")
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    from_dt = pd.Timestamp(macro_rows[0]["reference_date"], tz=timezone.utc).to_pydatetime()
    to_dt = pd.Timestamp(macro_rows[-1]["reference_date"], tz=timezone.utc).to_pydatetime()

    settings_perp = backtest.BacktestSettings(product_type="usdm_perp")
    await positions.init()
    db = positions.db()

    pooled: list = []
    per_symbol: dict[str, list] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        frames = await _run_symbol(db, symbol, macro_rows, from_dt, to_dt)
        if not frames:
            print(f"  frames 없음 — {symbol}")
            continue
        result = backtest.run_replay(frames, strategy_fns=VARIANTS_A, settings=settings_perp)
        trades = [t for t in result.trades if t.algo_id == "multi_factor"]
        per_symbol[symbol] = trades
        pooled.extend(trades)
        print(f"{symbol}: n={len(trades)}")

    if not pooled:
        print("풀링할 거래 없음")
        return 1

    # 시간 겹침 정량화: 다른 자산의 거래와 보유기간이 겹치는 거래 비율.
    overlap_count = 0
    for t in pooled:
        for other in pooled:
            if other is t:
                continue
            if t.open_time < other.open_time + pd.Timedelta(hours=other.hold_hours) and (
                t.open_time + pd.Timedelta(hours=t.hold_hours) > other.open_time
            ):
                overlap_count += 1
                break
    overlap_pct = overlap_count / len(pooled) * 100

    n = len(pooled)
    wins = [t for t in pooled if t.ret_pct > 0]
    win_rate = len(wins) / n * 100
    sum_w = sum(t.ret_pct * t.position_weight for t in pooled) * 100
    gross_win = sum(t.ret_pct for t in wins)
    gross_loss = -sum(t.ret_pct for t in pooled if t.ret_pct <= 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    point, lo, hi = _bootstrap_ci(pooled)
    first = second = 0.0
    if n >= 6:
        first, second = _split_half(pooled)
    returns = np.array([t.ret_pct for t in pooled])
    dsr = deflated_sharpe_ratio(returns, n_trials=1)

    print(f"\n{'=' * 70}\n풀링 결과 (BTC+ETH+SOL, multi_factor_short direction_soft)\n{'=' * 70}")
    print(f"n={n}  win%={win_rate:.1f}  sum_w%={sum_w:+.2f}  PF={pf:.2f}")
    print(
        f"가중합 부트스트랩95%CI: [{lo * 100:+.2f}%, {hi * 100:+.2f}%] (point={point * 100:+.2f}%)"
    )
    print(f"전/후반 분할: 전반={first:+.2f}%  후반={second:+.2f}%")
    print(f"DSR(n_trials=1)={dsr['dsr']:.3f}  sharpe={dsr['sharpe']:.3f}")
    print(f"보유기간 겹침(타자산과 동시보유) 거래 비율: {overlap_pct:.1f}%  ({overlap_count}/{n})")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
