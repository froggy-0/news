"""
Twelve Data API — KIS 마이그레이션 대상 18개 티커 비교용 탐색 스크립트

Usage:
    .venv/bin/python gw/explorations/twelvedata_probe.py --api-key YOUR_KEY
    TWELVEDATA_API_KEY=YOUR_KEY .venv/bin/python gw/explorations/twelvedata_probe.py

Free tier: 8 credits/min → 18심볼을 3배치로 나눠 분당 대기 자동 처리
Paid tier: --no-wait 으로 대기 없이 실행
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://api.twelvedata.com"

# KIS 마이그레이션 대상 티커만 유지
FAILING_TICKERS: dict[str, str] = {
    # 지수 ETF (3)
    "SPY": "S&P 500 ETF",
    "QQQ": "NASDAQ-100 ETF",
    "SOXX": "반도체 섹터 ETF",
    # 빅테크 (10)
    "NVDA": "NVIDIA",
    "MSFT": "Microsoft",
    "AAPL": "Apple",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "AMD": "AMD",
    "TSM": "TSMC",
    "ASML": "ASML",
    "AVGO": "Broadcom",
    # BTC ETF (5)
    "IBIT": "iShares BTC Trust",
    "FBTC": "Fidelity BTC",
    "ARKB": "ARK BTC ETF",
    "BITB": "Bitwise BTC ETF",
    "GBTC": "Grayscale BTC Trust",
}

# Free tier: 8 credits/min, 개별 요청으로 안전하게
CREDITS_PER_MIN = 8


def api_get(path: str, params: dict[str, str], api_key: str) -> Any:
    params["apikey"] = api_key
    url = f"{BASE_URL}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; market-data-test/1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:120]}") from None


def parse_quotes(data: Any) -> tuple[dict[str, dict], str | None]:
    """(symbol→quote_dict, error_message | None) 반환"""
    if not isinstance(data, dict):
        return {}, f"예상치 못한 응답 타입: {type(data)}"
    # rate limit / top-level error
    if "code" in data and "symbol" not in data and "values" not in data:
        return {}, data.get("message", str(data))
    # 단일 심볼
    if "symbol" in data:
        return {data["symbol"]: data}, None
    # 멀티 심볼: {SYMBOL: {symbol:..., close:...}, ...}
    result = {v["symbol"]: v for v in data.values() if isinstance(v, dict) and "symbol" in v}
    return result, None


def fmt(q: dict) -> str:
    close = q.get("close", "N/A")
    change = q.get("percent_change", "N/A")
    volume = q.get("volume", "N/A")
    return f"close={close:<10} change={change}%  vol={volume}"


def countdown(seconds: int) -> None:
    print(f"  ⏳ rate limit 대기 {seconds}초 ", end="", flush=True)
    for _ in range(seconds):
        time.sleep(1)
        print(".", end="", flush=True)
    print(" 재개")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.environ.get("TWELVEDATA_API_KEY", ""))
    parser.add_argument("--no-wait", action="store_true", help="Paid tier: rate limit 대기 스킵")
    args = parser.parse_args()

    if not args.api_key:
        print("API 키 필요: --api-key YOUR_KEY")
        sys.exit(1)

    symbols = list(FAILING_TICKERS.keys())
    print(f"대상: {len(symbols)}개 티커 (개별 요청)")
    if not args.no_wait:
        print(f"Free tier {CREDITS_PER_MIN} credits/min → {CREDITS_PER_MIN}개마다 62초 대기")
    print(f"{'─' * 60}")

    ok: list[str] = []
    fail: list[str] = []

    for i, sym in enumerate(symbols):
        # 매 8번째마다 (첫 번째 제외) 대기
        if i > 0 and i % CREDITS_PER_MIN == 0 and not args.no_wait:
            countdown(62)

        try:
            data = api_get("/quote", {"symbol": sym, "dp": "2"}, args.api_key)
            quotes, err = parse_quotes(data)

            if err:
                print(f"  ❌ {sym:6} ({FAILING_TICKERS[sym]:22}) ⚠️  {err[:70]}")
                fail.append(sym)
                continue

            q = quotes.get(sym, {})
            if q and q.get("status") != "error":
                print(f"  ✅ {sym:6} ({FAILING_TICKERS[sym]:22}) {fmt(q)}")
                ok.append(sym)
            else:
                msg = q.get("message", "응답 없음") if q else "응답 없음"
                print(f"  ❌ {sym:6} ({FAILING_TICKERS[sym]:22}) {msg[:60]}")
                fail.append(sym)

        except Exception as e:
            print(f"  ❌ {sym:6} ({FAILING_TICKERS[sym]:22}) 예외: {e}")
            fail.append(sym)

    print(f"\n{'=' * 60}")
    print(f"결과: {len(ok)}/{len(symbols)} 성공")
    if fail:
        print(f"실패: {', '.join(fail)}")
    else:
        print("전체 수집 가능 → 비교용 탐색 결과 확보 ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
