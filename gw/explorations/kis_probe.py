"""
한국투자증권 Open API — KIS 마이그레이션 대상 티커 수집 검증 스크립트
참고: https://github.com/koreainvestment/open-trading-api

Usage:
    .venv/bin/python gw/explorations/kis_probe.py --app-key YOUR_KEY --app-secret YOUR_SECRET
    KIS_APP_KEY=... KIS_APP_SECRET=... .venv/bin/python gw/explorations/kis_probe.py

기본: 실전투자 서버. 모의투자 테스트는 --paper 옵션 추가.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ── 서버 주소 ────────────────────────────────────────────────
REAL_BASE = "https://openapi.koreainvestment.com:9443"
PAPER_BASE = "https://openapivts.koreainvestment.com:29443"

# ── 해외주식 현재가 TR ────────────────────────────────────────
QUOTE_PATH = "/uapi/overseas-price/v1/quotations/price"
QUOTE_TR_ID = "HHDFS00000300"  # 실전/모의 동일

# ── 대상 티커 (KIS 마이그레이션 대상 18개) ─────────────────────
# fmt: (심볼, 거래소코드, 설명)
# 거래소코드: NAS=나스닥, NYS=뉴욕증권거래소, AMS=AMEX/NYSE Arca
FAILING_TICKERS: list[tuple[str, str, str]] = [
    # 지수 ETF (3)
    ("SPY", "AMS", "S&P 500 ETF"),
    ("QQQ", "NAS", "NASDAQ-100 ETF"),
    ("SOXX", "NAS", "반도체 섹터 ETF"),
    # 빅테크 (10)
    ("NVDA", "NAS", "NVIDIA"),
    ("MSFT", "NAS", "Microsoft"),
    ("AAPL", "NAS", "Apple"),
    ("AMZN", "NAS", "Amazon"),
    ("GOOGL", "NAS", "Alphabet"),
    ("META", "NAS", "Meta"),
    ("AMD", "NAS", "AMD"),
    ("TSM", "NYS", "TSMC"),
    ("ASML", "NAS", "ASML"),
    ("AVGO", "NAS", "Broadcom"),
    # BTC ETF (5)
    ("IBIT", "NAS", "iShares BTC Trust"),
    ("FBTC", "AMS", "Fidelity BTC"),
    ("ARKB", "AMS", "ARK BTC ETF"),
    ("BITB", "AMS", "Bitwise BTC ETF"),
    ("GBTC", "AMS", "Grayscale BTC Trust"),
]

# 거래소 코드가 맞지 않으면 자동 재시도할 후보들
EXCD_FALLBACKS = ["NAS", "NYS", "AMS"]


def api_post(base: str, path: str, body: dict, headers: dict) -> Any:
    url = base + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body_text[:200]}") from None


def api_get(base: str, path: str, params: dict, headers: dict) -> Any:
    url = base + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        body_text = body_bytes.decode(errors="replace")
        # EGW00201 은 rate limit — 호출자에서 retry 처리
        try:
            parsed = json.loads(body_bytes)
        except Exception:
            parsed = {}
        if parsed.get("message") == "EGW00201":
            raise RateLimitError() from None
        raise RuntimeError(f"HTTP {e.code}: {body_text[:200]}") from None


class RateLimitError(Exception):
    """KIS EGW00201: 초당 거래건수 초과"""


def get_access_token(base: str, app_key: str, app_secret: str) -> str:
    """OAuth2 client_credentials → access_token 발급"""
    print("토큰 발급 중...", end=" ", flush=True)
    resp = api_post(
        base,
        "/oauth2/tokenP",
        body={
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        },
        headers={"Content-Type": "application/json"},
    )
    token = resp.get("access_token", "")
    if not token:
        raise RuntimeError(f"토큰 발급 실패: {resp}")
    expires = resp.get("access_token_token_expired", "")
    print(f"완료 (만료: {expires})")
    return token


def quote_headers(app_key: str, app_secret: str, token: str, tr_id: str) -> dict:
    # kis_auth.py _base_headers 기준 (Accept, charset 필수)
    return {
        "Content-Type": "application/json",
        "Accept": "text/plain",
        "charset": "UTF-8",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "tr_cont": "",
    }


def fetch_quote(base: str, headers: dict, excd: str, symb: str, retries: int = 5) -> dict[str, Any]:
    """해외주식 현재가 단건 조회 — EGW00201 rate limit 자동 retry"""
    delay = 1.0
    for attempt in range(retries):
        try:
            return api_get(
                base,
                QUOTE_PATH,
                params={"AUTH": "", "EXCD": excd, "SYMB": symb},
                headers=headers,
            )
        except RateLimitError:
            if attempt == retries - 1:
                raise
            print(
                f"    ↻ rate limit — {delay:.0f}초 대기 후 재시도 ({attempt + 1}/{retries - 1})",
                end="\r",
                flush=True,
            )
            time.sleep(delay)
            delay = min(delay * 2, 8.0)  # 1 → 2 → 4 → 8초 backoff
    raise RuntimeError("unreachable")


def fmt_quote(output: dict) -> str:
    last = output.get("last", "N/A")  # 현재가
    diff = output.get("diff", "N/A")  # 대비
    rate = output.get("rate", "N/A")  # 등락율
    tvol = output.get("tvol", "N/A")  # 거래량
    return f"price={last:<12} change={diff}  rate={rate}%  vol={tvol}"


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS Open API 해외주식 수집 테스트")
    parser.add_argument("--app-key", default=os.environ.get("KIS_APP_KEY", ""))
    parser.add_argument("--app-secret", default=os.environ.get("KIS_APP_SECRET", ""))
    parser.add_argument("--paper", action="store_true", help="모의투자 서버 사용")
    args = parser.parse_args()

    if not args.app_key or not args.app_secret:
        print("필요: --app-key, --app-secret  (또는 KIS_APP_KEY / KIS_APP_SECRET 환경변수)")
        sys.exit(1)

    base = PAPER_BASE if args.paper else REAL_BASE
    mode = "모의투자" if args.paper else "실전투자"
    print(f"KIS Open API 테스트  [{mode}]  ({base})")
    print("─" * 60)

    # 토큰 발급
    try:
        token = get_access_token(base, args.app_key, args.app_secret)
    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        sys.exit(1)

    hdrs = quote_headers(args.app_key, args.app_secret, token, QUOTE_TR_ID)

    print(f"\n대상: {len(FAILING_TICKERS)}개 티커\n")

    ok: list[str] = []
    fail: list[str] = []

    for symb, excd, name in FAILING_TICKERS:
        time.sleep(0.4)  # 초당 2~3건 — EGW00201 예방
        try:
            resp = fetch_quote(base, hdrs, excd, symb)

            rt_cd = resp.get("rt_cd", "?")
            msg = resp.get("msg1", "")
            output = resp.get("output", {})

            if rt_cd == "0" and output.get("last"):
                print(f"  ✅ {symb:6} [{excd}] ({name:22}) {fmt_quote(output)}")
                ok.append(symb)

            elif rt_cd != "0":
                # 거래소 코드 오류일 경우 fallback 시도
                if any(k in msg for k in ("종목코드", "거래소", "EXCD", "없")):
                    fixed = False
                    for alt_excd in EXCD_FALLBACKS:
                        if alt_excd == excd:
                            continue
                        time.sleep(0.1)
                        try:
                            r2 = fetch_quote(base, hdrs, alt_excd, symb)
                            if r2.get("rt_cd") == "0" and r2.get("output", {}).get("last"):
                                out2 = r2["output"]
                                print(
                                    f"  ✅ {symb:6} [{alt_excd}✓] ({name:22}) {fmt_quote(out2)}  (원래 {excd} → {alt_excd})"
                                )
                                ok.append(symb)
                                fixed = True
                                break
                        except Exception:
                            pass
                    if not fixed:
                        print(f"  ❌ {symb:6} [{excd}] ({name:22}) rt_cd={rt_cd}  {msg}")
                        fail.append(symb)
                else:
                    print(f"  ❌ {symb:6} [{excd}] ({name:22}) rt_cd={rt_cd}  {msg}")
                    fail.append(symb)

            else:
                print(f"  ⚠️  {symb:6} [{excd}] ({name:22}) 가격 없음  {msg}")
                fail.append(symb)

        except RateLimitError:
            print(f"  ❌ {symb:6} [{excd}] ({name:22}) rate limit — retry 소진")
            fail.append(symb)
        except Exception as e:
            print(f"  ❌ {symb:6} [{excd}] ({name:22}) 예외: {e}")
            fail.append(symb)

    # 최종 요약
    print(f"\n{'=' * 60}")
    print(f"결과: {len(ok)}/{len(FAILING_TICKERS)} 성공")
    if fail:
        print(f"실패: {', '.join(fail)}")
    else:
        print("전체 수집 가능 → KIS 마이그레이션 대상 검증 완료 ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
