"""futures/um/daily/metrics 아카이브 → 4h 해상도 피처 재구성 (D1, 2026-08-11 카탈로그 감사 후속).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D1. `/futures/data/*`
REST(openInterestHist·globalLongShortAccountRatio·takerlongshortRatio 등)는 과거 startTime을
거부(30일 제한)해 WI-10(`TAKER_CONFIRM_4H_ENABLED`)과 `_lsr_crowded`/`_oi_diverged`의 4h
해상도 버전을 한 번도 백테스트로 검증하지 못했다. `data.binance.vision`의 daily metrics
아카이브(5분 해상도, BTC 2020-09~)가 정확히 같은 데이터를 담고 있어 이 문서를 백필한다.

컬럼 매핑 — REST `/futures/data/*?period=4h`와 실측 대조 완료(2026-08-11, 최근 16일
96봉, 정렬은 `live_timestamp == bucket_start + 4h`, 즉 REST period timestamp가 버킷의
"닫히는 시각"이다 — 처음엔 반대로 가정해 taker가 전부 어긋나 보이는 오탐이 있었다):

  count_long_short_ratio            ↔ globalLongShortAccountRatio.longShortRatio   mean|Δ|=0.00018 ✅
  count_toptrader_long_short_ratio  ↔ topLongShortAccountRatio.longShortRatio      mean|Δ|=0.00016 ✅
  sum_toptrader_long_short_ratio    ↔ topLongShortPositionRatio.longShortRatio     mean|Δ|=0.00003 ✅
  sum_open_interest_value           ↔ openInterestHist.sumOpenInterestValue        mean|Δ|=0.0000%  ✅
  sum_taker_long_short_vol_ratio    ↔ (4개 엔드포인트 전부와) 최선조차 mean|Δ|=0.53   ❌

**`sum_taker_long_short_vol_ratio`는 WI-10의 `taker_ratio_4h`(REST `takerlongshortRatio.
buySellRatio`)와 다른 값이다** — 4개 REST 엔드포인트 전부와 대조했으나 어느 것과도 매칭되지
않았다(최선조차 mean|Δ|≈0.53, 나머지 3개 컬럼은 0.0002 이하로 사실상 완벽 일치한 것과 대비).
즉 **WI-10(`taker_ratio_4h`)은 이 아카이브로 백필 불가** — `TAKER_CONFIRM_4H_ENABLED`는
여전히 라이브 전용으로 남는다(재현: 이 파일 하단 `if __name__` 블록 또는
docs/arena/research/binance-data-catalog-audit-20260811.md §부록 참조). 반대로 **LSR
3종(글로벌/탑트레이더 계정·포지션)과 OI는 백필 가능이 실측으로 확정**됐다.

이 모듈은 다운로드(캐시)·5분→4h 리샘플·롤링 z-score 계산만 담당하는 순수 유틸리티.
백테스트 macro 주입·A/B는 별도 스크립트(`lsr_oi_backfill_tuning.py`)에서
`ReplayFrame.macro`를 오버레이하는 방식으로 수행 — backtest.py의 일간 macro_rows 메커니즘은
건드리지 않는다(라이브 scheduler.py:698-700이 동일 패턴으로 daily macro 위에 taker_ratio_4h만
사후 주입하는 것과 동일 원리, 단 우리는 taker 대신 lsr/oi를 그 자리에 주입한다).
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DOWNLOAD_BASE = "https://data.binance.vision"
METRICS_PREFIX = "data/futures/um/daily/metrics"

# risk_overlay._last_rolling_zscore와 동일 규약(30일 window/15일 min_periods)을
# 4h 해상도(6봉/일)로 환산 — 정의를 최대한 일치시켜 라이브·백테스트 패리티를 유지.
ROLLING_WINDOW_BARS = 30 * 6
ROLLING_MIN_PERIODS = 15 * 6
OI_DIVERGENCE_LOOKBACK_BARS = 7 * 6  # 7일 방향 비교(algorithms._oi_diverged와 동일 지평)

DEFAULT_CACHE_DIR = Path("/tmp/binance_metrics_cache")


def _day_url(symbol: str, day: date) -> str:
    fname = f"{symbol}-metrics-{day.isoformat()}.zip"
    return f"{DOWNLOAD_BASE}/{METRICS_PREFIX}/{symbol}/{fname}"


def download_day(
    symbol: str, day: date, cache_dir: Path = DEFAULT_CACHE_DIR
) -> pd.DataFrame | None:
    """1일치 5분 metrics를 캐시(로컬 parquet) 또는 원격에서 받아 DataFrame으로 반환.

    미발행일(오늘·상장 이전 등)은 None.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}-{day.isoformat()}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    url = _day_url(symbol, day)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read()
    except Exception:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            name = archive.namelist()[0]
            df = pd.read_csv(io.BytesIO(archive.read(name)))
    except Exception:
        return None
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df = df[
        [
            "create_time",
            "sum_open_interest_value",
            "count_long_short_ratio",
        ]
    ]
    df.to_parquet(cache_path)
    return df


def load_range(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """[start, end] 구간(포함) 5분 데이터를 이어붙임. 없는 날은 건너뜀(그레이스풀)."""
    frames = []
    missing: list[date] = []
    day = start
    while day <= end:
        df = download_day(symbol, day, cache_dir=cache_dir)
        if df is not None and not df.empty:
            frames.append(df)
        else:
            missing.append(day)
        day += timedelta(days=1)
    if missing:
        print(
            f"  [metrics_archive] {symbol}: {len(missing)}일 미발행/실패 "
            f"(예: {missing[:3]}{'...' if len(missing) > 3 else ''})"
        )
    if not frames:
        return pd.DataFrame(
            columns=["create_time", "sum_open_interest_value", "count_long_short_ratio"]
        )
    out = pd.concat(frames, ignore_index=True).sort_values("create_time").reset_index(drop=True)
    return out


def _bucket_start(ts: pd.Timestamp) -> pd.Timestamp:
    """4h 버킷 시작(0/4/8/12/16/20 UTC) — arena_ohlcv_bars 봉 경계와 동일 규약."""
    floored_hour = (ts.hour // 4) * 4
    return ts.replace(hour=floored_hour, minute=0, second=0, microsecond=0)


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    """5분 원자료 → 4h 버킷의 마지막 관측치(봉 종가 시점 스냅샷, 라이브와 동일 방식)."""
    if df.empty:
        return df.assign(bar_close=pd.Series(dtype="datetime64[ns, UTC]"))
    d = df.copy()
    d["bucket_start"] = d["create_time"].apply(_bucket_start)
    d["bar_close"] = d["bucket_start"] + pd.Timedelta(hours=4)
    last_per_bucket = d.sort_values("create_time").groupby("bucket_start", as_index=False).last()
    return last_per_bucket.sort_values("bar_close").reset_index(drop=True)


def compute_4h_features(df_4h: pd.DataFrame) -> pd.DataFrame:
    """long_short_ratio_zscore_4h + oi_change_7d_4h 산출(taker는 §모듈 docstring 참조 — 배제).

    - long_short_ratio_zscore_4h: count_long_short_ratio의 롤링 z(30일/180봉, 15일/90봉 최소).
    - oi_change_7d_4h: OI 자체의 7일 변화율만 우선 산출 — 가격과의 다이버전스 판정(flag)은
      오버레이 단계에서 별도 OHLCV close 시리즈와 결합해야 하므로 이 함수 밖에서 완성한다.
    """
    if df_4h.empty:
        return df_4h.assign(
            long_short_ratio_zscore_4h=pd.Series(dtype=float),
            oi_change_7d_4h=pd.Series(dtype=float),
        )
    out = df_4h.copy()
    roll = out["count_long_short_ratio"].rolling(
        ROLLING_WINDOW_BARS, min_periods=ROLLING_MIN_PERIODS
    )
    mean = roll.mean()
    std = roll.std()
    out["long_short_ratio_zscore_4h"] = (out["count_long_short_ratio"] - mean) / std
    out.loc[std.isna() | (std == 0), "long_short_ratio_zscore_4h"] = None
    out["oi_change_7d_4h"] = out["sum_open_interest_value"].pct_change(OI_DIVERGENCE_LOOKBACK_BARS)
    return out


def build_symbol_features(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """다운로드 → 4h 리샘플 → 피처 계산까지 한 번에. index: bar_close(UTC, tz-aware)."""
    raw = load_range(symbol, start, end, cache_dir=cache_dir)
    bars_4h = resample_4h(raw)
    feats = compute_4h_features(bars_4h)
    return feats.set_index("bar_close")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = ap.parse_args()

    feats = build_symbol_features(
        args.symbol,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
    )
    print(feats.describe())
    print(f"\nrows={len(feats)}  {feats.index.min()} ~ {feats.index.max()}")
    print(
        f"long_short_ratio_zscore_4h non-null: {feats['long_short_ratio_zscore_4h'].notna().sum()}"
    )
