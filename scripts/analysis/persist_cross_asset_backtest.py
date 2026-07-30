"""BTC·ETH·SOL 백테스트 결과를 arena_backtest_runs/trades/equity_curve에 저장한다.

cross_asset_report.py는 콘솔 출력 전용이라, 실행할 때마다 결과가 사라진다. 이 스크립트는
동일한 백테스트를 돌리되 backtest.save_result_to_supabase()로 영구 저장한다 —
arena_backtest_runs/arena_backtest_trades/arena_backtest_equity_curve는 이미
BacktestSettings.symbol을 통해 심볼별로 구분 저장되도록 설계돼 있었음(마이그레이션
불필요, 기존 스키마 그대로 재사용).

목적: ETH/SOL은 라이브 shadow 누적에 수 주가 걸리므로(P1-7 대시보드가 보류된 이유),
이미 존재하는 20개월 백테스트 결과를 "backtest" 라벨을 명확히 붙여 조회 가능한 형태로
저장해둔다 — 나중에 대시보드나 분석이 이 테이블을 그대로 읽을 수 있다.

⚠️ 이 결과는 라이브 트랙레코드가 아니라 백테스트다 — 조회·표시 시 반드시 "backtest"로
구분 표기할 것(라이브와 혼동 시 제품 신뢰성 훼손).

재현:
  .venv/bin/python3 scripts/analysis/persist_cross_asset_backtest.py \
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

from arena import backtest, frequency, parameters, positions  # noqa: E402

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _profile_for(symbol: str) -> frequency.FrequencyProfile:
    profile_id = (
        frequency.LIVE_4H_PROFILE_ID
        if symbol == parameters.BINANCE_SYMBOL
        else frequency.multi_asset_shadow_profile_id(symbol)
    )
    return frequency.get_frequency_profile(profile_id)


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

    for symbol in ASSETS:
        profile = _profile_for(symbol)
        frames = await backtest.load_frames_from_supabase(
            db,
            symbol=symbol,
            interval=profile.interval,
            limit=4000,
            warmup_bars=warmup,
            indicator_profile_id=profile.default_indicator_profile_id,
            macro_rows=macro_rows,
        )
        if not frames:
            print(f"⚠️ {symbol}: frames 없음 — 스킵")
            continue

        settings = backtest.BacktestSettings(
            frequency_profile_id=profile.frequency_profile_id,
            indicator_profile_id=profile.default_indicator_profile_id,
            symbol=symbol,
            interval=profile.interval,
        )
        result = backtest.run_replay(frames, settings=settings)
        await backtest.save_result_to_supabase(db, result)
        print(
            f"저장 완료: {symbol}  backtest_run_id={result.backtest_run_id}  "
            f"frames={len(frames)}  trades={len(result.trades)}  "
            f"equity_points={len(result.equity_curve)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
