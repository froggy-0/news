"""futures/cm/daily/liquidationSnapshot 아카이브 → 4h 청산 버킷 재구성 (D3, 2026-08-11 카탈로그 감사 후속).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D3 + §5(청산 백필 불가
확정 정정). USDT-M(우리가 라이브로 모으는 시장)에는 청산 히스토리가 없지만, COIN-M(cm)
아카이브에는 BTCUSD_PERP/ETHUSD_PERP/SOLUSD_PERP 2023-06-25~2024-10-14 구간이 존재한다.
이 구간은 역사적 상승장 백테스트 창(2023-08-04~2024-07-31, historical-bull-market-backtest-
20260803.md)을 완전히 포함해, 2026-08-10에 배선한 `_liquidation_exhaustion_sufficient()`
게이트(LIQUIDATION_EXHAUSTION_GATE_ENABLED=False, 검증 전 인프라)를 처음으로 백테스트 가능
하게 한다.

⚠️ 한계(그대로 유지 — 그리드 채택 판단 시 반드시 고려):
  1. cm(코인마진) ≠ um(우리가 라이브로 쓰는 USDT마진). 규모·참여자 다름 → 절대 USD 값은
     비교 불가, 자기 히스토리 대비 z-score·비율(asymmetry)만 유효.
  2. 2024-10-14 이후 데이터 없음 → 하락장 창 검증 불가. "게이트를 켤 근거"가 아니라
     "게이트를 끌 근거를 찾는 반증 목적"으로만 쓴다(D3 §4 한계 3).
  3. notional = last_fill_quantity(계약수) × 고정 계약단위(USD, `dapi/v1/exchangeInfo`
     실측: BTCUSD_PERP=100, ETHUSD_PERP=10, SOLUSD_PERP=10). average_price를 곱하는 방식은
     오답이다 — COIN-M 계약은 가격과 무관하게 고정 USD 단위라, price×quantity를 쓰면 구간
     내 가격추세(2023-08 ~$29k → 2024-07 ~$65k)가 그대로 z-score에 섞여 들어가 시계열
     비교가 왜곡된다.

forceOrder side 규약은 liquidation_stream.py와 동일: SELL=롱 청산, BUY=숏 청산.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DOWNLOAD_BASE = "https://data.binance.vision"
LIQ_PREFIX = "data/futures/cm/daily/liquidationSnapshot"

DEFAULT_CACHE_DIR = Path("/tmp/binance_liquidation_cm_cache")

# cm(코인마진) 심볼 → arena가 쓰는 USDT마진 심볼 라벨. 규모는 다르지만(한계 1 참조) 방향·타이밍은
# 공유하므로 프록시로 오버레이할 때 이 매핑으로 arena 프레임 심볼과 맞춘다.
CM_TO_ARENA_SYMBOL = {
    "BTCUSD_PERP": "BTCUSDT",
    "ETHUSD_PERP": "ETHUSDT",
    "SOLUSD_PERP": "SOLUSDT",
}

# dapi/v1/exchangeInfo 실측(2026-08-11) — COIN-M 계약당 고정 USD 명목가.
CM_CONTRACT_SIZE_USD = {
    "BTCUSD_PERP": 100.0,
    "ETHUSD_PERP": 10.0,
    "SOLUSD_PERP": 10.0,
}


def _day_url(cm_symbol: str, day: date) -> str:
    fname = f"{cm_symbol}-liquidationSnapshot-{day.isoformat()}.zip"
    return f"{DOWNLOAD_BASE}/{LIQ_PREFIX}/{cm_symbol}/{fname}"


def download_day(
    cm_symbol: str, day: date, cache_dir: Path = DEFAULT_CACHE_DIR
) -> pd.DataFrame | None:
    """1일치 청산 주문 원자료를 캐시(로컬 parquet) 또는 원격에서 받아 DataFrame으로 반환.

    미발행일(커버리지 밖 등)은 None.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cm_symbol}-{day.isoformat()}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    url = _day_url(cm_symbol, day)
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
    if df.empty:
        df = pd.DataFrame(columns=["time", "side", "last_fill_quantity"])
    else:
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df[["time", "side", "last_fill_quantity"]]
    df.to_parquet(cache_path)
    return df


def load_range(
    cm_symbol: str,
    start: date,
    end: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """[start, end] 구간(포함) 청산 주문 원자료를 이어붙임. 없는 날은 건너뜀(그레이스풀)."""
    frames = []
    missing: list[date] = []
    day = start
    while day <= end:
        df = download_day(cm_symbol, day, cache_dir=cache_dir)
        if df is not None and not df.empty:
            frames.append(df)
        elif df is None:
            missing.append(day)
        day += timedelta(days=1)
    if missing:
        print(
            f"  [liquidation_cm_archive] {cm_symbol}: {len(missing)}일 미발행/실패 "
            f"(예: {missing[:3]}{'...' if len(missing) > 3 else ''})"
        )
    if not frames:
        return pd.DataFrame(columns=["time", "side", "last_fill_quantity"])
    return pd.concat(frames, ignore_index=True).sort_values("time").reset_index(drop=True)


def _bucket_start(ts: pd.Timestamp) -> datetime:
    """4h 버킷 시작(0/4/8/12/16/20 UTC) — liquidation_stream._bucket_start와 동일 규약."""
    floored_hour = (ts.hour // 4) * 4
    dt = ts.to_pydatetime().replace(
        hour=floored_hour, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    return dt


def build_symbol_bars(
    cm_symbol: str,
    start: date,
    end: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict]:
    """다운로드 → 4h 버킷 집계까지 한 번에. liquidation_features 순수함수가 바로 소비 가능한
    dict 리스트(bar_start/long_liq_usd/short_liq_usd/long_liq_count/short_liq_count) 반환.
    """
    raw = load_range(cm_symbol, start, end, cache_dir=cache_dir)
    if raw.empty:
        return []
    contract_size = CM_CONTRACT_SIZE_USD[cm_symbol]
    buckets: dict[datetime, dict] = {}
    for row in raw.itertuples(index=False):
        bstart = _bucket_start(row.time)
        bucket = buckets.setdefault(
            bstart,
            {
                "bar_start": bstart,
                "long_liq_usd": 0.0,
                "short_liq_usd": 0.0,
                "long_liq_count": 0,
                "short_liq_count": 0,
            },
        )
        notional = float(row.last_fill_quantity) * contract_size
        if row.side == "SELL":  # 롱 강제청산
            bucket["long_liq_usd"] += notional
            bucket["long_liq_count"] += 1
        else:  # BUY — 숏 강제청산
            bucket["short_liq_usd"] += notional
            bucket["short_liq_count"] += 1
    return [buckets[k] for k in sorted(buckets)]


# liquidation_features.RECENT_WINDOW_HOURS(24h)/_DEFAULT_LOOKBACK_DAYS(30)/_DEFAULT_MIN_PERIODS(5)
# 와 동일 규약 — 프레임 수천 개에 순수함수(청크 루프)를 그대로 반복 호출하면 O(n²)로 느려
# 벡터화한다. 아래 __main__ 자체검증으로 두 구현의 동치를 확인함.
WINDOW_BARS = 6  # 24h / 4h
LOOKBACK_CHUNKS = 30  # 30일 / 24h 청크
MIN_HISTORY_CHUNKS = 5  # liquidation_features._DEFAULT_MIN_PERIODS


def compute_4h_features(bars: list[dict]) -> pd.DataFrame:
    """4h 버킷 리스트 → 연속 4h 그리드(빈 봉=0)에 재색인 후 liq_asymmetry_24h/
    liq_intensity_zscore_24h 산출. index: bar_close(=bar_start+4h, UTC).

    liquidation_features.liquidation_snapshot()의 청크 정의(현재 시점 기준 24h 트레일링
    합 vs 과거 30개 비중첩 24h 청크의 평균/표준편차)와 수학적으로 동일 — 24h 트레일링
    합 시퀀스를 6봉(24h) 간격으로 스트라이드하면 정확히 그 비중첩 청크 값과 일치한다.
    """
    if not bars:
        return pd.DataFrame(
            columns=["liq_asymmetry_24h", "liq_intensity_zscore_24h"],
            index=pd.DatetimeIndex([], tz="UTC", name="bar_close"),
        )
    df = pd.DataFrame(bars).set_index("bar_start").sort_index()
    df.index = pd.DatetimeIndex(df.index, tz="UTC")
    full_grid = pd.date_range(df.index.min(), df.index.max(), freq="4h", tz="UTC")
    df = df.reindex(full_grid).fillna(0.0)

    long_roll = df["long_liq_usd"].rolling(WINDOW_BARS, min_periods=1).sum()
    short_roll = df["short_liq_usd"].rolling(WINDOW_BARS, min_periods=1).sum()
    total_roll = long_roll + short_roll

    asymmetry = (long_roll - short_roll) / total_roll
    asymmetry[total_roll <= 0] = float("nan")

    hist_cols = [total_roll.shift(WINDOW_BARS * k) for k in range(1, LOOKBACK_CHUNKS)]
    hist = pd.concat(hist_cols, axis=1)
    hist_count = hist.notna().sum(axis=1)
    hist_mean = hist.mean(axis=1)
    hist_std = hist.std(axis=1, ddof=0)
    zscore = (total_roll - hist_mean) / hist_std
    zscore[(hist_count < MIN_HISTORY_CHUNKS) | (hist_std <= 0)] = float("nan")

    out = pd.DataFrame({"liq_asymmetry_24h": asymmetry, "liq_intensity_zscore_24h": zscore})
    out.index = out.index + pd.Timedelta(hours=4)  # bar_start → bar_close
    out.index.name = "bar_close"
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSD_PERP", choices=list(CM_TO_ARENA_SYMBOL))
    ap.add_argument("--start", default="2023-06-25")
    ap.add_argument("--end", default="2024-10-14")
    args = ap.parse_args()

    bars = build_symbol_bars(
        args.symbol, date.fromisoformat(args.start), date.fromisoformat(args.end)
    )
    print(f"bars={len(bars)}  arena_symbol={CM_TO_ARENA_SYMBOL[args.symbol]}")
    if bars:
        print(f"  {bars[0]['bar_start']} ~ {bars[-1]['bar_start']}")
        total_long = sum(b["long_liq_usd"] for b in bars)
        total_short = sum(b["short_liq_usd"] for b in bars)
        print(f"  total long_liq≈${total_long:,.0f}  short_liq≈${total_short:,.0f}")
