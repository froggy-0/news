"""spot/monthly/klines 1m 아카이브 다운로드·캐시 (D5, 2026-08-11 카탈로그 감사 후속).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D5. 2026-07-21 P2(1분
정밀화, arena-status-review-20260721.md §9)는 `arena_realtime_feature_bars`(라이브 가동
이후만 존재, last_price만 있음)로 MFE/MAE를 재검증해 `vix_rsi`의 4h 진단이 해상도
아티팩트였음을 밝혔지만, 라이브 구간이 짧아 표본이 작았다(`scripts/analysis/mfe_1m.py`).
이 모듈은 spot 1m klines 월간 아카이브(2017-08~, high/low 포함 — last_price보다 정밀)로
같은 분석을 **전체 백테스트 구간**에서 재현할 수 있게 한다.

컬럼(헤더 없음, 바이낸스 표준 kline 12필드): open_time_ms,open,high,low,close,volume,
close_time_ms,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

DOWNLOAD_BASE = "https://data.binance.vision"
KLINES_PREFIX = "data/spot/monthly/klines"

DEFAULT_CACHE_DIR = Path("/tmp/binance_spot_1m_cache")

_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def _month_url(symbol: str, year: int, month: int) -> str:
    fname = f"{symbol}-1m-{year:04d}-{month:02d}.zip"
    return f"{DOWNLOAD_BASE}/{KLINES_PREFIX}/{symbol}/1m/{fname}"


def download_month(
    symbol: str, year: int, month: int, cache_dir: Path = DEFAULT_CACHE_DIR
) -> pd.DataFrame | None:
    """1개월치 1m klines를 캐시(parquet, high/low/open_time만 축약) 또는 원격에서 받는다.

    미발행 월(현재월 등)은 None.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}-{year:04d}-{month:02d}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    url = _month_url(symbol, year, month)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read()
    except Exception:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            name = archive.namelist()[0]
            df = pd.read_csv(io.BytesIO(archive.read(name)), header=None, names=_COLUMNS)
    except Exception:
        return None
    # open_time이 ms 또는 us로 섞여 나오는 바이낸스 아카이브 이슈(2025년 이후 파일 일부가
    # 마이크로초 단위) — 자릿수로 판별해 항상 ms로 정규화.
    unit = "us" if df["open_time"].iloc[0] > 10**14 else "ms"
    df["open_time"] = pd.to_datetime(df["open_time"], unit=unit, utc=True)
    df = df[["open_time", "high", "low"]].astype({"high": "float32", "low": "float32"})
    df.to_parquet(cache_path)
    return df


def load_range(
    symbol: str,
    start: date,
    end: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """[start, end] 구간(포함, 월 단위로 잘라 다운로드)의 1m high/low를 이어붙임."""
    frames = []
    missing: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        df = download_month(symbol, year, month, cache_dir=cache_dir)
        if df is not None and not df.empty:
            frames.append(df)
        else:
            missing.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    if missing:
        print(f"  [spot_klines_1m_archive] {symbol}: {len(missing)}개월 미발행/실패: {missing}")
    if not frames:
        return pd.DataFrame(columns=["open_time", "high", "low"])
    out = pd.concat(frames, ignore_index=True).sort_values("open_time").reset_index(drop=True)
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return out[(out["open_time"] >= start_ts) & (out["open_time"] < end_ts)].reset_index(drop=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default="2025-09-01")
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = ap.parse_args()

    df = load_range(args.symbol, date.fromisoformat(args.start), date.fromisoformat(args.end))
    print(f"rows={len(df)}")
    if not df.empty:
        print(f"  {df['open_time'].min()} ~ {df['open_time'].max()}")
