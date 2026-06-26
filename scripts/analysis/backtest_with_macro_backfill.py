"""arena 백테스트 + 히스토리 macro 백필.

문제: arena_macro_snapshots는 실가동 시점(2026-06-19~)부터만 존재해, 6개월 OHLCV
백테스트의 대부분 구간에서 macro가 비어 모든 macro 게이트(fng 낙폭·MA200·LSR·taker·
breadth·stablecoin)가 None→스킵된다. 즉 라이브와 다른 전략을 검증하게 됨.

해결: sentiment_join master parquet(일간, lag1 누수방지 피처 보유)에서 각 날짜의
regimeRaw를 risk_overlay.compute_regime_state()로 재구성 → 일간 macro 스냅샷을 만들고
backtest.load_frames_from_supabase(macro_rows=...)로 주입. 4H 봉에는 _latest_macro_for_time
이 일간 macro를 forward-fill(라이브 동작과 동일).

재현:
  .venv/bin/python3 scripts/analysis/backtest_with_macro_backfill.py \
      --parquet data/sentiment_join/sentiment_join_master_20260502.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import backtest, frequency, parameters, positions  # noqa: E402
from morning_brief.analysis.sentiment_join import risk_overlay  # noqa: E402

# regimeRaw가 안정적으로 계산되려면 롤링 윈도(VIX 90일 등) 워밍업 필요.
_MACRO_WARMUP_DAYS = 90


def build_macro_rows(parquet: Path) -> list[dict]:
    """parquet에서 날짜별 regimeRaw를 재구성해 arena_macro_snapshots 형태의 행 리스트로."""
    df = pd.read_parquet(parquet).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    rows: list[dict] = []
    for i in range(len(df)):
        if i < _MACRO_WARMUP_DAYS:
            continue
        window = df.iloc[: i + 1]
        rs = risk_overlay.compute_regime_state(window)
        ve = risk_overlay.compute_vol_environment(window)
        d: datetime = df.loc[i, "date"].to_pydatetime().replace(tzinfo=timezone.utc)
        # macro는 해당 날짜 데이터로 다음날 아침 발행 → 누수 방지 위해 D+1 00:00 UTC에 가용.
        # (parquet 피처는 이미 lag1 backward-looking, compute는 window 종료행 기준.)
        fetched = d.replace(hour=0, minute=0) + pd.Timedelta(days=1)
        rows.append(
            {
                "fetched_at": fetched.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "reference_date": d.strftime("%Y-%m-%d"),
                "stale_hours": 0,
                "risk_overlay": {
                    "regimeState": rs.label,
                    "regimeRaw": rs.raw,
                    "volLevel": ve.level,
                    "volTrend": ve.trend,
                },
            }
        )
    return rows


def summarize(label: str, trades: list) -> None:
    by_algo: dict[str, list] = defaultdict(list)
    for t in trades:
        by_algo[t.algo_id].append(t)
    print(f"\n=== {label} (trades={len(trades)}) ===")
    print(
        f"{'algo':16} {'n':>3} {'win%':>5} {'sum_w_ret%':>10} {'avg_ret%':>8} {'avg_w':>6}  exits"
    )
    for algo in sorted(by_algo):
        ts = by_algo[algo]
        n = len(ts)
        wins = sum(1 for t in ts if t.ret_pct > 0)
        sret = sum(t.ret_pct * t.position_weight for t in ts) * 100
        aret = sum(t.ret_pct for t in ts) / n * 100
        aw = sum(t.position_weight for t in ts) / n
        exits = dict(Counter(t.exit_reason for t in ts))
        print(
            f"{algo:16} {n:>3} {wins / n * 100:>5.1f} {sret:>+10.2f} {aret:>+8.2f} {aw:>6.3f}  {exits}"
        )


def dump_fng(trades: list) -> None:
    fng = [t for t in trades if t.algo_id == "fng_contrarian"]
    print(f"\n=== fng_contrarian 상세 ({len(fng)}건) ===")
    for t in fng:
        print(
            f"  open {t.open_time.date()} @ {t.open_price:.0f}  w={t.position_weight:.3f}  "
            f"close {t.close_time.date()} @ {t.close_price:.0f}  "
            f"ret={t.ret_pct * 100:+.2f}%  hold={t.hold_hours:.0f}h  exit={t.exit_reason}"
        )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--parquet", default="data/sentiment_join/sentiment_join_master_20260502.parquet"
    )
    args = ap.parse_args()

    parquet = Path(args.parquet)
    if not parquet.exists():
        print(f"parquet 없음: {parquet}")
        return 1

    macro_rows = build_macro_rows(parquet)
    print(
        f"백필 macro 스냅샷: {len(macro_rows)}일  "
        f"{macro_rows[0]['reference_date']} ~ {macro_rows[-1]['reference_date']}"
    )

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)

    # (1) 백필 macro 주입
    frames_bf = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows,
    )
    covered = sum(1 for f in frames_bf if f.macro.get("btc_drawdown_90d") is not None)
    print(
        f"frames={len(frames_bf)}  {frames_bf[0].bar.close_time.date()} ~ "
        f"{frames_bf[-1].bar.close_time.date()}  "
        f"낙폭 macro 커버: {covered}/{len(frames_bf)}"
    )
    res_bf = backtest.run_replay(frames_bf, settings=backtest.BacktestSettings())
    summarize("macro 백필 (라이브 게이트 적용)", res_bf.trades)
    dump_fng(res_bf.trades)

    # (2) 대조군: macro 없음(기존 동작 — 게이트 스킵)
    frames_none = await backtest.load_frames_from_supabase(
        db,
        symbol=parameters.BINANCE_SYMBOL,
        interval=parameters.BINANCE_KLINE_INTERVAL,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=[],
    )
    res_none = backtest.run_replay(frames_none, settings=backtest.BacktestSettings())
    summarize("대조군: macro 없음(게이트 스킵)", res_none.trades)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
