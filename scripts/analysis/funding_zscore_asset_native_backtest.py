"""ETH/SOL 백테스트 — BTC공유 funding_zscore vs 자산고유 funding_zscore A/B (2026-08-01).

funding_zscore_asset_native_verify.py에서 확인된 저상관(ETH corr=0.476, SOL corr=0.082)이
실제 백테스트 결과(거래수·승률·가중수익)를 바꿀 만큼 유의미한지 확인한다. macro_rows의
regimeRaw.funding_zscore만 자산고유 값으로 치환하고 나머지(oi_divergence_flag 등)는
그대로 BTC-공유 유지(OI는 Binance 30일 제한으로 자산고유 히스토리 자체가 불가능 — 이미
확인된 제약, 2026-07-31).

재현:
  .venv/bin/python3 scripts/analysis/funding_zscore_asset_native_backtest.py \
      --symbol ETHUSDT --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from arena import backtest, frequency, parameters, positions  # noqa: E402
from morning_brief.analysis.sentiment_join import risk_overlay  # noqa: E402

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_MAX_LIMIT = 1000
_MACRO_WARMUP_DAYS = 90


def _ms(dt) -> int:
    return int(dt.timestamp() * 1000)


def build_macro_rows(parquet: Path) -> list[dict]:
    """backtest_with_macro_backfill.build_macro_rows와 동일 로직(중복 정의 — 스크립트 간
    임포트 의존을 피하기 위해 이 분석 스크립트 내부에 자기완결적으로 복제)."""
    df = pd.read_parquet(parquet).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    rows: list[dict] = []
    for i in range(len(df)):
        if i < _MACRO_WARMUP_DAYS:
            continue
        window = df.iloc[: i + 1]
        rs = risk_overlay.compute_regime_state(window)
        ve = risk_overlay.compute_vol_environment(window)
        d = df.loc[i, "date"].to_pydatetime().replace(tzinfo=timezone.utc)
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


def fetch_funding_history(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    all_rows: list[dict] = []
    cursor = start_ms
    for _ in range(20):
        resp = requests.get(
            BINANCE_FUNDING_URL,
            params={
                "symbol": symbol,
                "startTime": str(cursor),
                "endTime": str(end_ms),
                "limit": str(BINANCE_MAX_LIMIT),
            },
            timeout=20,
        )
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_rows.extend(page)
        if len(page) < BINANCE_MAX_LIMIT:
            break
        last_ts = page[-1].get("fundingTime")
        if last_ts is None:
            break
        next_cursor = int(last_ts) + 1
        if next_cursor >= end_ms:
            break
        cursor = next_cursor
        time.sleep(0.15)
    return all_rows


def aggregate_daily_funding(rows: list[dict]) -> dict[str, float]:
    daily: dict[str, list[float]] = {}
    for row in rows:
        ts_ms = row.get("fundingTime")
        rate_raw = row.get("fundingRate")
        if ts_ms is None or rate_raw is None:
            continue
        day = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        daily.setdefault(day, []).append(float(rate_raw))
    return {day: sum(rates) for day, rates in daily.items()}


def build_zscore_series(daily_funding: dict[str, float], date_index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(daily_funding).sort_index()
    s.index = pd.to_datetime(s.index)
    s = s.reindex(date_index)
    fr_roll = s.shift(1).rolling(30, min_periods=20)
    return (s - fr_roll.mean()) / fr_roll.std()


def override_funding_zscore(macro_rows: list[dict], symbol: str) -> list[dict]:
    dates = pd.DatetimeIndex([pd.Timestamp(r["reference_date"]) for r in macro_rows])
    start_ms = _ms(dates.min().to_pydatetime().replace(tzinfo=timezone.utc))
    end_ms = _ms(dates.max().to_pydatetime().replace(tzinfo=timezone.utc) + pd.Timedelta(days=1))

    rows = fetch_funding_history(symbol, start_ms, end_ms)
    daily = aggregate_daily_funding(rows)
    native_z = build_zscore_series(daily, dates)
    native_z.index = dates

    out = copy.deepcopy(macro_rows)
    for row, z in zip(out, native_z.values, strict=True):
        value = None if pd.isna(z) else float(z)
        row["risk_overlay"]["regimeRaw"]["funding_zscore"] = value
    return out


def summarize(label: str, trades: list) -> None:
    by_algo: dict[str, list] = defaultdict(list)
    for t in trades:
        by_algo[t.algo_id].append(t)
    print(f"\n=== {label} (trades={len(trades)}) ===")
    print(f"{'algo':16} {'n':>3} {'win%':>5} {'sum_w_ret%':>10} {'avg_ret%':>8}  exits")
    for algo in sorted(by_algo):
        ts = by_algo[algo]
        n = len(ts)
        wins = sum(1 for t in ts if t.ret_pct > 0)
        sret = sum(t.ret_pct * t.position_weight for t in ts) * 100
        aret = sum(t.ret_pct for t in ts) / n * 100
        exits = dict(Counter(t.exit_reason for t in ts))
        print(f"{algo:16} {n:>3} {wins / n * 100:>5.1f} {sret:>+10.2f} {aret:>+8.2f}  {exits}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="data/sentiment_join/master_20260710.parquet")
    ap.add_argument("--symbol", required=True, choices=["ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    macro_rows_shared = build_macro_rows(Path(args.parquet))
    print(f"macro 스냅샷: {len(macro_rows_shared)}일, symbol={args.symbol}")

    print(f"{args.symbol} 자산고유 funding 히스토리 조회 중...")
    macro_rows_native = override_funding_zscore(macro_rows_shared, args.symbol)

    await positions.init()
    db = positions.db()
    warmup = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
    profile_id = frequency.multi_asset_shadow_profile_id(args.symbol)
    profile = frequency.get_frequency_profile(profile_id)

    frames_shared = await backtest.load_frames_from_supabase(
        db,
        symbol=args.symbol,
        interval=profile.interval,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows_shared,
    )
    frames_native = await backtest.load_frames_from_supabase(
        db,
        symbol=args.symbol,
        interval=profile.interval,
        limit=2000,
        warmup_bars=warmup,
        indicator_profile_id=profile.default_indicator_profile_id,
        macro_rows=macro_rows_native,
    )
    if not frames_shared or not frames_native:
        print(f"frames 없음 — arena_ohlcv_bars에 {args.symbol} 히스토리 확인 필요.")
        return 1

    res_shared = backtest.run_replay(frames_shared, settings=backtest.BacktestSettings())
    res_native = backtest.run_replay(frames_native, settings=backtest.BacktestSettings())

    summarize(f"BTC-공유 funding_zscore ({args.symbol}, 현행)", res_shared.trades)
    summarize(f"자산고유 funding_zscore ({args.symbol}, 대안)", res_native.trades)
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
