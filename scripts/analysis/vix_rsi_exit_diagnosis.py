"""vix_rsi 청산 사유 분해 진단 (D5 후속, 2026-08-11).

배경: D5(mfe_1m_backtest.py)가 vix_rsi 포착률이 4h·1m 양쪽에서 뚜렷이 음수(-59%/-35%,
n=67)임을 확인했다 — 2026-07-21의 "해상도 아티팩트, 재시도 금지" 결론이 큰 표본에서
재현 안 됨. 그런데 vix_rsi는 이미 Tier1(시간배리어)·Tier2(ATR목표가)·트레일링거리 좁히기·
WI-5(MA200게이트) 네 번의 파라미터 그리드 캠페인이 전부 실패했고, DSR=0.134(2026-08-04
과최적화 감사, 기준 0.95 미달)로 엣지 자체도 통계적으로 미확인 상태다.

그리드서치를 다시 돌리기 전에, 2026-07-30 정성분석(multi_factor 손실이 sideways 레짐에
집중된다는 발견)과 같은 방식으로 **왜** 포착률이 음수인지부터 싸게 진단한다:
  1. exit_reason별 분해 — 어떤 청산 경로가 손실/미포착을 지배하는가.
  2. 진입 시점 레짐별 분해 — 손실이 특정 레짐에 몰리는가.
  3. exit_reason × MFE_1m — flat_signal이 큰 MFE를 흘리는지, stop_loss가 정당한 손절인지.

읽기 전용 진단 — 코드/파라미터 변경 없음.

재현:
  .venv/bin/python3 scripts/analysis/vix_rsi_exit_diagnosis.py
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_with_macro_backfill import build_macro_rows  # noqa: E402
from spot_klines_1m_archive import load_range  # noqa: E402

from arena import backtest, frequency, parameters, positions  # noqa: E402

ALGO = "vix_rsi"
COVERAGE_MIN = 80.0


def _mfe_mae_1m(trade, klines_1m) -> tuple[float, float, float] | None:
    op = trade.open_price
    if op <= 0 or trade.close_time <= trade.open_time:
        return None
    window = klines_1m[
        (klines_1m["open_time"] >= trade.open_time) & (klines_1m["open_time"] <= trade.close_time)
    ]
    if window.empty:
        return None
    expected_minutes = max((trade.close_time - trade.open_time).total_seconds() / 60.0, 1.0)
    coverage = len(window) / expected_minutes * 100
    mfe = float(window["high"].max()) / op - 1.0
    mae = float(window["low"].min()) / op - 1.0
    return mfe, mae, coverage


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--limit", type=int, default=5000)
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
        symbol=args.symbol,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=args.limit,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    result = backtest.run_replay(frames, settings=backtest.BacktestSettings())
    trades = [t for t in result.trades if t.algo_id == ALGO]
    print(
        f"vix_rsi 거래: {len(trades)}건 ({frames[0].bar.close_time.date()}~{frames[-1].bar.close_time.date()})"
    )

    range_start = min(t.open_time for t in trades).date()
    range_end = max(t.close_time for t in trades).date() + timedelta(days=1)
    klines_1m = load_range(args.symbol, range_start, range_end)  # D5 캐시 재사용
    print(f"1m 봉 {len(klines_1m)}건 로드(캐시)")

    rows = []
    for t in trades:
        mm = _mfe_mae_1m(t, klines_1m)
        mfe = mae = cov = None
        if mm is not None and mm[2] >= COVERAGE_MIN:
            mfe, mae, cov = mm
        regime_label = (
            t.macro_snapshot.get("arena_regime_state")
            or t.macro_snapshot.get("regime_state")
            or "unknown"
        )
        rows.append(
            {
                "exit_reason": t.exit_reason,
                "regime": regime_label,
                "ret_pct": t.ret_pct,
                "win": t.ret_pct > 0,
                "hold_hours": t.hold_hours,
                "mfe": mfe,
                "mae": mae,
            }
        )

    print("\n=== exit_reason별 분해 ===")
    by_reason = defaultdict(list)
    for r in rows:
        by_reason[r["exit_reason"]].append(r)
    for reason, rs in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        win = sum(1 for r in rs if r["win"]) / n * 100
        avg_ret = statistics.mean(r["ret_pct"] for r in rs) * 100
        sum_ret = sum(r["ret_pct"] for r in rs) * 100
        avg_hold = statistics.mean(r["hold_hours"] for r in rs)
        mfes = [r["mfe"] for r in rs if r["mfe"] is not None]
        avg_mfe = statistics.mean(mfes) * 100 if mfes else float("nan")
        caps = [r["ret_pct"] / r["mfe"] for r in rs if r["mfe"] is not None and r["mfe"] > 0.003]
        cap = statistics.mean(caps) * 100 if caps else None
        cap_str = f"{cap:+.0f}%" if cap is not None else "n/a"
        print(
            f"  {reason:16} n={n:>3} win={win:>5.1f}% avg_ret={avg_ret:>+6.2f}% "
            f"sum_ret={sum_ret:>+7.2f}% avg_hold={avg_hold:>5.1f}h avg_MFE_1m={avg_mfe:>+6.2f}% "
            f"capture={cap_str}"
        )

    print("\n=== 진입 레짐별 분해 ===")
    by_regime = defaultdict(list)
    for r in rows:
        by_regime[r["regime"]].append(r)
    for regime_label, rs in sorted(by_regime.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        win = sum(1 for r in rs if r["win"]) / n * 100
        avg_ret = statistics.mean(r["ret_pct"] for r in rs) * 100
        sum_ret = sum(r["ret_pct"] for r in rs) * 100
        print(
            f"  {regime_label:12} n={n:>3} win={win:>5.1f}% avg_ret={avg_ret:>+6.2f}% sum_ret={sum_ret:>+7.2f}%"
        )

    print("\n=== exit_reason × 레짐 교차표 (건수) ===")
    reasons = sorted(by_reason.keys())
    regimes = sorted(by_regime.keys())
    header = "regime".ljust(12) + "".join(r.ljust(16) for r in reasons)
    print("  " + header)
    for regime_label in regimes:
        counts = []
        for reason in reasons:
            c = sum(1 for r in rows if r["regime"] == regime_label and r["exit_reason"] == reason)
            counts.append(str(c).ljust(16))
        print("  " + regime_label.ljust(12) + "".join(counts))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
