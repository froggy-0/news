"""ETH/SOL 자산고유 funding_zscore 백테스트 재검증 (2026-08-01).

배경: 라이브 shadow는 이미 futures_baseline.py로 ETH/SOL 자산고유 funding_zscore를
계산해 쓰고 있는데(2026-07-31 배포), 백테스트(backtest_with_macro_backfill.py)는
여전히 BTC-공유 regimeRaw의 funding_zscore를 ETH/SOL에도 그대로 적용한다
(Track A/B 설계 §3.1의 의도된 공유 원칙과, 실제로 backtestable한 데이터가 BTC
parquet뿐이었던 현실적 제약이 겹친 결과). 이 스크립트는 그 괴리가 실제로 결론을
바꿀 만큼 큰지 정량 확인한다.

방법: Binance 펀딩비 히스토리는 심볼 무관하게 전체 보존(OI/LSR과 달리 30일 제한
없음, 2026-07-31 세션에서 실측 확인)이므로 ETH/SOL도 BTC와 동일 방법론
(join.py:145-159과 동일: 일별 3건 합산 → rolling(30, min_periods=20) 평균/표준편차,
shift(1)로 lookahead 차단)으로 자산고유 z-score를 재구성해 BTC-공유 값과 직접 비교한다.

재현:
  .venv/bin/python3 scripts/analysis/funding_zscore_asset_native_verify.py \
      --parquet data/sentiment_join/master_20260710.parquet
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import parameters  # noqa: E402

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_MAX_LIMIT = 1000


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


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
    """join.py의 sentiment_join 방법론과 동일: 일별 3건 합산(평균 아님)."""
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
    """join.py:156-158과 동일 공식: fr.shift(1).rolling(30, min_periods=20)."""
    s = pd.Series(daily_funding).sort_index()
    s.index = pd.to_datetime(s.index)
    s = s.reindex(date_index)
    fr_roll = s.shift(1).rolling(30, min_periods=20)
    return (s - fr_roll.mean()) / fr_roll.std()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", type=Path, required=True)
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    date_index = pd.DatetimeIndex(df["date"])
    start_ms = _ms(date_index.min().to_pydatetime().replace(tzinfo=timezone.utc))
    end_ms = _ms(datetime.now(timezone.utc))

    btc_shared = df.set_index("date")["funding_rate_zscore_30d"]

    print(f"기간: {date_index.min().date()} ~ {date_index.max().date()} ({len(df)}일)")
    print(f"funding_hot 임계: FUNDING_HOT_ZSCORE={parameters.FUNDING_HOT_ZSCORE}\n")

    for symbol in ("ETHUSDT", "SOLUSDT"):
        print(f"=== {symbol} 자산고유 vs BTC-공유 funding_zscore ===")
        rows = fetch_funding_history(symbol, start_ms, end_ms)
        daily = aggregate_daily_funding(rows)
        print(f"  수집 funding 이벤트: {len(rows)}건, 일별 집계: {len(daily)}일")

        native_z = build_zscore_series(daily, date_index)
        native_z.index = date_index

        cmp_df = pd.DataFrame(
            {"btc_shared": btc_shared.values, "native": native_z.values}, index=date_index
        )
        cmp_df = cmp_df.dropna()

        corr = cmp_df["btc_shared"].corr(cmp_df["native"])
        btc_hot = cmp_df["btc_shared"] >= parameters.FUNDING_HOT_ZSCORE
        native_hot = cmp_df["native"] >= parameters.FUNDING_HOT_ZSCORE
        agree = (btc_hot == native_hot).mean()
        btc_hot_days = int(btc_hot.sum())
        native_hot_days = int(native_hot.sum())
        both_hot = int((btc_hot & native_hot).sum())

        print(f"  비교 가능일: {len(cmp_df)}일")
        print(f"  상관계수: {corr:.3f}")
        print(
            f"  funding_hot 베토 발동일: BTC공유={btc_hot_days}일, 자산고유={native_hot_days}일, 둘다={both_hot}일"
        )
        print(f"  베토 판정 일치율: {agree:.1%}")
        print()


if __name__ == "__main__":
    main()
