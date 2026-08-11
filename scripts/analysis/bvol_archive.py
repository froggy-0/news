"""option/daily/BVOLIndex 아카이브 → 일간 크립토 IV 시리즈 (D2, 2026-08-11 카탈로그 감사 후속).

배경: docs/arena/research/binance-data-catalog-audit-20260811.md D2. `vix_rsi`는 주식시장
VIX(FRED VIXCLS, 일간, 미국 장중에만 갱신)를 외생 매크로 필터로 쓰는데, 크립토는 24/7이라
구조적 불일치가 있다. BVOL(바이낸스 옵션 내재변동성 지수, 1초 해상도, BTC/ETH만,
2023-06-20~2026-08-09)로 대체했을 때 백테스트 성과가 바뀌는지 탐색한다.

⚠️ 이 모듈은 **아카이브(T+1) 전용**이다 — 라이브 엔드포인트가 없다(§실측: eapi -1128,
BVOL 토큰 상장폐지). VIX 대체를 실제로 라이브 배포하려면 (a) 아카이브 T+1을 그대로 쓰거나
(b) `eapi/v1/mark`의 옵션별 markIV로 자체 지수를 만들어야 하는데 산출식이 BVOL과 달라
히스토리·라이브 패리티가 깨진다 — **이 결정은 사용자 판단이 필요한 지점이라 이 세션에서는
백테스트 탐색까지만 하고 라이브 배선은 하지 않는다.**

`risk_overlay.py`의 vix_q40 정의(90일 롤링·최소30일·40th percentile)를 그대로 재사용해
"vix_now"/"vix_q40" 대응값을 만든다 — VIX 대체품으로 바로 오버레이 가능하게.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DOWNLOAD_BASE = "https://data.binance.vision"
BVOL_PREFIX = "data/option/daily/BVOLIndex"

DEFAULT_CACHE_DIR = Path("/tmp/binance_bvol_cache")

# risk_overlay._VIX_WINDOW/_VIX_MIN_PERIODS/_VIX_QUANTILE_MID와 동일 규약 — VIX 대체품이라
# 기존 임계값 정의를 그대로 재사용해야 비교가 공정하다.
ROLLING_WINDOW_DAYS = 90
ROLLING_MIN_PERIODS = 30
QUANTILE_MID = 0.40


def _day_url(symbol: str, day: date) -> str:
    fname = f"{symbol}-BVOLIndex-{day.isoformat()}.zip"
    return f"{DOWNLOAD_BASE}/{BVOL_PREFIX}/{symbol}/{fname}"


def download_day(symbol: str, day: date, cache_dir: Path = DEFAULT_CACHE_DIR) -> float | None:
    """1일치 BVOL(1초 해상도)의 그날 마지막 관측치(일간 종가류 스냅샷)만 캐시·반환."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}-{day.isoformat()}.txt"
    if cache_path.exists():
        content = cache_path.read_text().strip()
        return float(content) if content else None
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
    if df.empty:
        cache_path.write_text("")
        return None
    last_value = float(df.sort_values("calc_time")["index_value"].iloc[-1])
    cache_path.write_text(str(last_value))
    return last_value


def load_daily_series(
    symbol: str, start: date, end: date, cache_dir: Path = DEFAULT_CACHE_DIR
) -> pd.Series:
    """[start, end] 구간 일간 BVOL 종가류 시리즈(index: date, tz-naive)."""
    values: dict[date, float] = {}
    day = start
    while day <= end:
        v = download_day(symbol, day, cache_dir=cache_dir)
        if v is not None:
            values[day] = v
        day += timedelta(days=1)
    if not values:
        return pd.Series(dtype=float)
    return pd.Series(values).sort_index()


def build_vix_analog(symbol: str, start: date, end: date) -> pd.DataFrame:
    """BVOL 일간 시리즈 → vix_now/vix_q40 대응 컬럼(둘 다 lag1 — 당일 값은 다음날부터
    가용, 프로젝트 표준 daily macro lag1 규약과 동일). index: date."""
    daily = load_daily_series(symbol, start, end)
    if daily.empty:
        return pd.DataFrame(columns=["vix_now", "vix_q40"])
    lagged = daily.shift(1)  # T+1 아카이브 + lag1 관례(이중이 아니라, 파일 자체가 이미
    # 그날 데이터이므로 "다음날부터 반영 가능"이라는 의미의 단일 lag)
    rolling = lagged.rolling(ROLLING_WINDOW_DAYS, min_periods=ROLLING_MIN_PERIODS)
    q40 = rolling.quantile(QUANTILE_MID)
    return pd.DataFrame({"vix_now": lagged, "vix_q40": q40})


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCBVOLUSDT", choices=["BTCBVOLUSDT", "ETHBVOLUSDT"])
    ap.add_argument("--start", default="2023-06-20")
    ap.add_argument("--end", default="2026-08-09")
    args = ap.parse_args()

    df = build_vix_analog(args.symbol, date.fromisoformat(args.start), date.fromisoformat(args.end))
    print(df.describe())
    print(f"rows={len(df)}  q40 non-null={df['vix_q40'].notna().sum()}")
