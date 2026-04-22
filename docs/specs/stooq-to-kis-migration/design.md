# Design Document: Stooq → KIS Migration

## Overview

`stooq.py`를 삭제하고 `kis.py`를 신설하여 해외주식 18개와 `usdkrw`를 KIS API로 수집한다. `nq_futures`는 프론트월 계약 선택 규칙이 확정되기 전까지 기존 yfinance 경로를 유지한다. `market.py`의 내부 함수(`_point_from_stooq`, `_safe_stooq_point`, `_safe_stooq_point_and_volume`, `fetch_korea_investor_points`)만 교체하며, 이를 호출하는 상위 함수(`fetch_us_index_points`, `fetch_tech_stock_points` 등)와 `MarketPoint` 모델은 변경하지 않는다. EGW00201(초당 건수 초과)은 body 파싱으로 감지하여 기존 `execute_with_provider_retry` 인프라를 통해 처리한다.

---

## Research-backed Constraints (2026-04-05)

- KIS 공식 상세 문서에서 해외주식 현재체결가 경로는 `/uapi/overseas-price/v1/quotations/price`, TR ID는 `HHDFS00000300`으로 확인된다. 이 TR은 실전/모의 모두 지원한다.
- KIS 공식 상세 문서에서 해외선물종목현재가 경로는 `/uapi/overseas-futureoption/v1/quotations/inquire-price`, TR ID는 `HHDFC55010000`으로 확인된다. 이 TR은 모의투자 미지원이다.
- KIS 공식 API 목록에서 환율은 별도 `exchange-rate` 현재가 API가 아니라 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`의 `FID_COND_MRKT_DIV_CODE="X"` 경로로 문서화되어 있다.
- KIS 공식 예시의 해외선물 코드는 `BRNF25`, `BONU25`, `ESZ23`처럼 `SRS_CD` 계약코드 체계이며, `NQ=F` 같은 Yahoo ticker는 직접 사용할 수 없다.
- KIS 공식 상세 문서에서 해외선물 현재가 응답의 `last_price`, `prev_price`, `prev_diff_rate`는 `ffcode.mst`의 `sCalcDesz`를 적용해 해석해야 한다.
- KIS 공식 GitHub README는 access token 재발급을 분당 1회로 안내한다. 따라서 한 실행 내 토큰 재사용은 최적화가 아니라 안정성 요구사항이다.
- KIS 공식 공지(2026-03-20)는 신규 실전 고객에게 신청 후 3일간 초당 3건 제한을 적용한다. `min_interval_seconds=0.4`는 이 제한보다 보수적이지만, 모의투자 유량은 별도로 더 낮을 수 있다.
- 위 제약을 근거로 1차 범위에서는 `usdkrw`만 KIS로 전환하고, `nq_futures` KIS 이관은 2차 작업으로 분리한다.

---

## Architecture

```
pipeline.py
  └─ market.py
       ├─ fetch_macro_points()           FRED (변경 없음)
       ├─ fetch_us_index_points()        _safe_kis_point()       [교체]
       ├─ fetch_tech_stock_points()      _safe_kis_point()       [교체]
       ├─ fetch_newsletter_display_data()
       │    ├─ fetch_tech_stock_points() _safe_kis_point()       [교체]
       │    └─ _safe_kis_point_and_volume()                      [교체]
       ├─ fetch_korea_investor_points()  usdkrw만 kis.fetch_usdkrw_point() [부분 교체]
       │                                 nq_futures는 yfinance 유지
       └─ fetch_bitcoin_snapshot()       CoinGecko (변경 없음)

sources/
  ├─ kis.py       ← 신설 (핵심)
  ├─ stooq.py     ← 삭제
  ├─ fred.py         변경 없음
  └─ coingecko.py    변경 없음

config.py          kis_app_key, kis_app_secret 필드 추가
provider_runtime.py "stooq" → "kis" 정책 교체
briefing.py        usdkrw 출처 라벨을 실제 source에 맞게 교체
docs/data-sources.md, docs/data-flow.md  usdkrw source 문서 갱신
.github/workflows/  KIS_APP_KEY, KIS_APP_SECRET 시크릿 추가
```

---

## Components and Interfaces

### 1. `src/morning_brief/data/sources/kis.py` (신설)

#### 1-1. 상수 및 EXCD 매핑

```python
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
_QUOTE_PATH   = "/uapi/overseas-price/v1/quotations/price"
_TOKEN_PATH   = "/oauth2/tokenP"
_QUOTE_TR_ID  = "HHDFS00000300"

# ticker → KIS 거래소 코드
_EXCD_MAP: dict[str, str] = {
    "SPY":  "AMS", "QQQ":  "NAS", "SOXX": "NAS",
    "NVDA": "NAS", "MSFT": "NAS", "AAPL": "NAS",
    "AMZN": "NAS", "GOOGL":"NAS", "META": "NAS",
    "AMD":  "NAS", "TSM":  "NYS", "ASML": "NAS", "AVGO": "NAS",
    "IBIT": "NAS", "FBTC": "AMS", "ARKB": "AMS",
    "BITB": "AMS", "GBTC": "AMS",
}
```

> **Design Decision — EXCD 하드코딩:**
> KIS는 잘못된 EXCD를 `rt_cd != "0"`으로 반환하므로 런타임 조회보다 정적 매핑이 안전하다. 테스트 결과(2026-04-05)로 검증된 값을 사용하며, 신규 티커 추가 시 명시적으로 업데이트한다.

#### 1-2. 인증

```python
_token: str | None = None   # 프로세스 내 메모리에만 보유

def is_available() -> bool:
    """KIS_APP_KEY, KIS_APP_SECRET 환경변수 존재 여부"""
    ...

def _get_token(app_key: str, app_secret: str) -> str:
    """POST /oauth2/tokenP → access_token 발급. 실패 시 HttpFetchError."""
    ...

def _ensure_token() -> str:
    """첫 호출 시 토큰 발급 후 모듈 변수에 보관 (lazy init).
    이후 호출은 기존 토큰 반환. 파일 캐시 없음."""
    global _token
    if _token is None:
        _token = _get_token(app_key, app_secret)  # 환경변수에서 읽음
    return _token
```

> **Design Decision — Lazy init:**
> 파이프라인 실행마다 새 프로세스이므로 매번 토큰이 발급된다. 파일 캐시는 추가 I/O와 만료 판단 로직을 요구하므로 채택하지 않는다. `_ensure_token()`은 실제 API 호출 직전에만 실행되어 KIS 미설정 환경에서 불필요한 네트워크 호출을 방지하고, 공식 README에 명시된 분당 1회 재발급 제한도 자연스럽게 피한다.

#### 1-3. EGW00201 감지 — 커스텀 예외

```python
class _KisRateLimitError(HttpFetchError):
    """KIS EGW00201 초당 거래건수 초과 전용 예외.
    retryable=True로 설정하여 execute_with_provider_retry가 자동 재시도한다."""
    def __init__(self) -> None:
        super().__init__(
            "KIS 초당 거래건수를 초과했어요 (EGW00201)",
            provider="kis",
            retryable=True,
            rate_limited=True,
        )
```

> **Design Decision — 전용 예외 클래스:**
> `_request_with_retry`는 HTTP 500 body를 파싱하지 않는다. KIS는 HTTP 500으로 EGW00201을 반환하므로 `kis.py` 내부에서 body를 직접 파싱해 전용 예외를 발생시킨다. 이를 통해 기존 `execute_with_provider_retry`의 `should_retry` 콜백이 자연스럽게 EGW00201을 재시도 대상으로 인식한다.

#### 1-4. HTTP 요청

```python
def _kis_get(path: str, params: dict, headers: dict) -> dict[str, Any]:
    """KIS GET 요청. HTTP 500 body를 파싱해 EGW00201이면 _KisRateLimitError 발생.
    그 외 4xx/5xx는 HttpFetchError(retryable=...) 발생."""

    resp = requests.get(
        KIS_BASE_URL + path,
        params=params,
        headers=headers,
        timeout=15,
    )

    if resp.status_code == 500:
        try:
            body = resp.json()
        except Exception:
            body = {}
        if body.get("message") == "EGW00201":
            raise _KisRateLimitError()
        raise HttpFetchError(
            f"KIS HTTP 500: {body.get('msg1', '')}",
            status_code=500, provider="kis", retryable=True,
        )

    if resp.status_code >= 400:
        raise HttpFetchError(
            f"KIS HTTP {resp.status_code}",
            status_code=resp.status_code,
            provider="kis",
            retryable=resp.status_code in {408, 429, 502, 503, 504},
        )

    return resp.json()
```

#### 1-5. 공개 함수 — 해외주식

```python
def fetch_close_change_and_volume(ticker: str) -> tuple[float, float, int]:
    """KIS 해외주식 현재가 조회.
    반환: (close, change_pct, volume) — stooq.fetch_close_change_and_volume()과 동일 계약.
    실패 시 HttpFetchError 발생 → 호출부(_safe_kis_point)에서 yfinance fallback."""

    token = _ensure_token()
    excd  = _EXCD_MAP.get(ticker.upper())
    if not excd:
        raise HttpFetchError(f"KIS EXCD 매핑 없음: {ticker}", provider="kis")

    headers = _build_headers(token, tr_id=_QUOTE_TR_ID)
    params  = {"AUTH": "", "EXCD": excd, "SYMB": ticker.upper()}

    def _fetch() -> dict:
        return _kis_get(_QUOTE_PATH, params, headers)

    data = execute_with_provider_retry(
        provider="kis",
        operation=_fetch,
        should_retry=lambda exc: isinstance(exc, HttpFetchError) and exc.retryable,
        on_retry=_log_retry,
        # retry_after_seconds_for_error는 None을 반환해야 한다.
        # 1.0을 반환하면 retry_delay_seconds()가 policy.respect_retry_after=True에 의해
        # 모든 재시도를 flat 1초로 고정한다. None을 반환하면 policy의 base_backoff_seconds=1.0과
        # max_backoff_seconds=8.0 기반의 1→2→4→8초 exponential backoff가 적용된다.
    )

    rt_cd  = data.get("rt_cd", "1")
    output = data.get("output", {})
    last   = output.get("last", "")

    if rt_cd != "0" or not last or last == "0":
        raise HttpFetchError(
            f"KIS 유효 데이터 없음: {ticker} rt_cd={rt_cd} last={last!r}",
            provider="kis",
        )

    close  = float(last)
    base   = float(output.get("base", "0") or "0")   # 전일 종가
    change_pct = ((close - base) / base * 100) if base else 0.0
    volume = int(output.get("tvol", "0") or "0")

    return round(close, 4), round(change_pct, 2), volume
```

> **Design Decision — change_pct 계산에 `base` 사용:**
> KIS 응답의 `rate` 필드(등락률)가 있지만 부호 처리가 불안정하다. `last`(현재가)와 `base`(전일종가)로 직접 계산하는 것이 Stooq 방식(최신 - 이전)과 동일하고 신뢰도가 높다.

> **Design Decision — EGW00201 backoff:**
> `retry_after_seconds_for_error`에 `_KisRateLimitError`에 대해 고정값(1.0)을 반환하면 `retry_delay_seconds()`가 `policy.respect_retry_after=True`에 의해 모든 재시도를 flat 1초로 고정한다. `None`을 반환해야 provider policy(`base_backoff_seconds=1.0`, `max_backoff_seconds=8.0`)의 자연스러운 exponential backoff(1→2→4→8초)가 적용된다.

#### 1-6. 공개 함수 — USD/KRW

```python
def fetch_usdkrw_point() -> tuple[float, float]:
    """1차 범위에서는 USD/KRW KIS 조회만 담당.
    반환: (price, change_pct)
    실패 시 HttpFetchError → 호출부에서 yfinance fallback."""
    ...
```

> **Design Decision — 1차 범위는 USD/KRW만 KIS 전환:**
> USD/KRW는 공개 문서에 확인된 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice` 경로를 우선 사용한다. 환율은 `FID_COND_MRKT_DIV_CODE="X"`로 분기되며, `output1`/`output2` 중 최신 가용 값을 `MarketPoint`로 변환한다. concrete `FID_INPUT_ISCD`는 `FX@KRW`로 고정하고, 런타임에서 값을 추측하거나 fallback 검색하지 않는다.
> `nq_futures`는 실전 계정이 있더라도 KIS가 요구하는 `SRS_CD` 프론트월 선택 규칙과 가격 스케일(`sCalcDesz`) 검증이 남아 있으므로, 1차에서는 기존 yfinance primary를 유지한다.

> **Blocking Prerequisite — USD/KRW 종목코드:**
> 공개 문서는 환율 조회 경로와 구분값(`X`)까지는 제공하지만, `USD/KRW`에 대응하는 정확한 `FID_INPUT_ISCD` 예시를 제공하지 않는다. 구현은 KIS 공식 마스터 `frgn_code.mst`와 한국투자증권 공식 환율 화면 기본값을 교차 확인해 `FID_INPUT_ISCD="FX@KRW"`를 확정했고, 이후 구현은 이 상수만 사용한다.

> **Deferred Work — NQ 선물 계약 선택 규칙:**
> 공개 문서는 `SRS_CD` 단건 조회만 문서화하고 있고, `NQ=F` 같은 연속형 심볼 매핑 규칙은 제공하지 않는다. 2차 범위에서 KIS 마스터(`search-contract-detail`/`ffcode.mst`) 기반 프론트월 선택 규칙을 별도로 설계한다.

---

### 2. `src/morning_brief/data/market.py` (내부 함수 교체)

#### 교체 대상 함수 매핑

| 기존 (삭제) | 교체 후 | 변경 내용 |
|---|---|---|
| `_point_from_stooq()` | `_point_from_kis()` | `kis_fetch_close_change_and_volume(ticker)` 직접 호출 |
| `_point_and_volume_from_stooq()` | `_point_and_volume_from_kis()` | 동일 |
| `_safe_stooq_point()` | `_safe_kis_point()` | warning_key `stooq_fallback_` → `kis_fallback_`, `stooq_symbol` 파라미터 제거 |
| `_safe_stooq_point_and_volume()` | `_safe_kis_point_and_volume()` | warning_key `stooq_point_volume_fallback_` → `kis_point_volume_fallback_`, `stooq_symbol` 파라미터 제거 |

> **호출부 시그니처 변경 없음:** 상위 공개 함수(`fetch_us_index_points`, `fetch_tech_stock_points`, `fetch_newsletter_display_data`)의 반환 타입·시그니처는 유지된다.

#### `US_INDEX_TARGETS` 구조 변경

현재 `US_INDEX_TARGETS`는 `(canonical_key, ticker, stooq_symbol)` 3-tuple이다. KIS 마이그레이션 후 stooq_symbol은 불필요하므로 2-tuple로 변경한다.

```python
# 현재 (3-tuple)
US_INDEX_TARGETS = [
    ("spy", "SPY", "spy.us"),
    ("qqq", "QQQ", "qqq.us"),
    ("soxx", "SOXX", "soxx.us"),
]

# 변경 후 (2-tuple)
US_INDEX_TARGETS = [
    ("spy", "SPY"),
    ("qqq", "QQQ"),
    ("soxx", "SOXX"),
]
```

`fetch_us_index_points()`의 이터레이션도 함께 변경:
```python
# 현재
for canonical_key, ticker, stooq_symbol in US_INDEX_TARGETS:
    _safe_stooq_point(
        label=...,
        ticker=ticker,
        canonical_key=canonical_key_for(ticker, stooq_symbol, canonical_key),
        stooq_symbol=stooq_symbol,
    )

# 변경 후
for canonical_key, ticker in US_INDEX_TARGETS:
    _safe_kis_point(
        label=canonical_label_for(canonical_key),
        ticker=ticker,
        canonical_key=canonical_key_for(ticker, canonical_key),
    )
```

#### `market_policy.py` stooq 심볼 레거시 키

`CANONICAL_KEY_BY_SOURCE`의 `"spy.us"`, `"qqq.us"`, `"soxx.us"` 키는 Stooq 심볼용이다. 캐시 호환성을 위해 삭제하지 않고 유지한다. 이 키들이 실제로 생성되지 않을 뿐이므로 기능에 영향 없다.

#### `fetch_us_index_points`, `fetch_tech_stock_points` log message 수정

```python
# 현재 (stooq 레거시)
message="미국 지수 흐름은 Stooq 기준으로 보고 필요하면 yfinance로 보강했어요.",
provider="stooq",

# 변경 후
message="미국 지수 흐름은 KIS 기준으로 보고 필요하면 yfinance로 보강했어요.",
provider="kis",
```

#### `fetch_korea_investor_points()` 교체

```python
# 현재
def fetch_korea_investor_points() -> list[MarketPoint]:
    points = [
        _safe_yfinance_point(label=..., ticker=ticker, ...)
        for canonical_key, ticker, scale in KOREA_INVESTOR_TARGETS
    ]

# 변경 후
def fetch_korea_investor_points() -> list[MarketPoint]:
    points = [
        _safe_kis_usdkrw_point(),
        _safe_yfinance_point(
            label=canonical_label_for("nq_futures"),
            ticker="NQ=F",
            canonical_key=canonical_key_for("NQ=F", "nq_futures"),
            price_scale=1.0,
        ),
    ]
```

```python
def _point_from_kis_usdkrw() -> MarketPoint:
    """KIS fetch_usdkrw_point 결과를 MarketPoint로 변환하는 내부 함수."""
    label = canonical_label_for("usdkrw")
    price, change_pct = kis_fetch_usdkrw_point()
    return _market_point(
        label=label,
        ticker="USDKRW",
        close=price,
        change_pct=change_pct,
        canonical_key="usdkrw",
    )


def _safe_kis_usdkrw_point() -> MarketPoint:
    return _safe_with_fallback(
        warning_key="kis_fallback_usdkrw",
        warning_message="KIS에서 %s (%s) 데이터를 가져오지 못해 yfinance로 이어서 볼게요: %s",
        warning_args=("usdkrw", "KRW=X"),
        primary_fetch=_point_from_kis_usdkrw,
        fallback_fetch=lambda: _safe_yfinance_point(
            label=canonical_label_for("usdkrw"),
            ticker="KRW=X",
            canonical_key=canonical_key_for("KRW=X", "usdkrw"),
            price_scale=1.0,
        ),
    )
```

> **Design Decision — source label 분기를 ticker로 보존:**
> `MarketPoint` 모델에 provider 필드는 없다. 따라서 KIS primary로 만든 `usdkrw` 포인트는 `ticker="USDKRW"`를 사용하고, yfinance fallback은 기존 `ticker="KRW=X"`를 유지해 `_market_source_label()`이 `[출처: KIS]`와 `[출처: yfinance]`를 구분할 수 있게 한다.

#### import 변경

```python
# 삭제
from morning_brief.data.sources.stooq import fetch_close_change_and_volume, to_stooq_symbol

# 추가
from morning_brief.data.sources.kis import (
    fetch_close_change_and_volume as kis_fetch_close_change_and_volume,
    fetch_usdkrw_point as kis_fetch_usdkrw_point,
    is_available as kis_is_available,
)
```

#### `briefing.py` source attribution 교체

```python
def _market_source_label(point: dict) -> str:
    ticker = str(point.get("ticker", "")).strip()
    canonical_key = str(point.get("canonical_key", "")).strip()
    if canonical_key == "usdkrw" and ticker == "USDKRW":
        return "KIS"
    if ticker in {"DX-Y.NYB", "^TNX", "^VIX", "KRW=X", "NQ=F"}:
        return "yfinance"
    ...
```

```python
lines.append(
    f"원/달러 환율은 {usdkrw_price:,.2f}원으로 전일 대비 {usdkrw_change:+.2f}%였습니다"
    f"{_point_suffix(usdkrw)}. [출처: {_market_source_label(usdkrw)}]"
)
```

#### 운영 문서 갱신

- `docs/data-sources.md`: `usdkrw` 1차 소스를 KIS 환율 엔드포인트, 폴백을 yfinance `KRW=X`로 수정
- `docs/data-flow.md`: `korea_watch` 표에서 `usdkrw`를 KIS primary, `nq_futures`를 yfinance primary로 수정

---

### 3. `src/morning_brief/data/sources/provider_runtime.py` (정책 교체)

```python
# 삭제
"stooq": ProviderPolicy(name="stooq", min_interval_seconds=0.35, base_backoff_seconds=1.0),

# 추가
"kis": ProviderPolicy(
    name="kis",
    min_interval_seconds=0.4,      # EGW00201 예방 (테스트 검증값)
    base_backoff_seconds=1.0,
    max_attempts=5,                # EGW00201 retry 최대 5회
    max_backoff_seconds=8.0,       # 1→2→4→8초
    retryable_statuses=frozenset({408, 429, 500, 502, 503, 504}),
),
```

---

### 4. `src/morning_brief/config.py` (필드 추가)

```python
@dataclass(frozen=True)
class Settings:
    ...
    kis_app_key: str      # KIS_APP_KEY 환경변수
    kis_app_secret: str   # KIS_APP_SECRET 환경변수

# load_settings() 내부
kis_app_key=os.getenv("KIS_APP_KEY", "").strip(),
kis_app_secret=os.getenv("KIS_APP_SECRET", "").strip(),
```

---

### 5. `.github/workflows/generate-briefing.yml` (시크릿 주입)

```yaml
env:
  # 기존 유지
  FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
  # 추가
  KIS_APP_KEY:    ${{ secrets.KIS_APP_KEY }}
  KIS_APP_SECRET: ${{ secrets.KIS_APP_SECRET }}
```

---

## Data Models

신규 데이터 모델 없음. `MarketPoint` 변경 없음.

`kis.py` 내부 전용 타입:

```python
# 모듈 내부 전용 (공개 모델 아님)
@dataclass(frozen=True)
class _KisQuoteOutput:
    last:  str   # 현재가 (string)
    base:  str   # 전일 종가
    tvol:  str   # 거래량
    rt_cd: str   # "0" = 성공
```

---

## Correctness Properties

_Requirements 참조번호 기재_

1. **For any** `ticker` in `_EXCD_MAP`에 대해, `fetch_close_change_and_volume(ticker)`가 성공하면 반환값 `(close, change_pct, volume)`은 `close > 0`, `volume >= 0`을 만족해야 한다. _(Req 2.1)_

2. **For any** KIS 응답 `rt_cd != "0"` 또는 `last == ""` 또는 `last == "0"`에 대해, `fetch_close_change_and_volume()`는 `HttpFetchError`를 발생시켜야 한다. _(Req 2.4, 2.5)_

3. **For any** EGW00201 응답에 대해, `fetch_close_change_and_volume()`는 최소 1회 재시도해야 한다. _(Req 4.1)_

4. **For any** `fetch_close_change_and_volume(ticker)` 실패에 대해, `_safe_kis_point(ticker)`의 반환값은 `MarketPoint`이어야 한다 (price=None 허용). _(Req 5.1)_

5. **For any** KIS 미설정(`is_available() == False`)에 대해, `fetch_korea_investor_points()`는 yfinance로 수집한 `list[MarketPoint]`를 반환해야 한다. _(Req 5.5)_

6. **For any** `usdkrw` KIS 실패에 대해, `_safe_kis_usdkrw_point()`는 yfinance fallback으로 `MarketPoint`를 반환해야 한다. _(Req 3.3)_

7. **For any** `canonical_key == "usdkrw"`이고 `ticker == "USDKRW"`인 포인트에 대해, `_market_source_label()`은 `"KIS"`를 반환해야 한다. _(Req 9.3)_

8. **For any** `canonical_key == "usdkrw"`이고 `ticker == "KRW=X"`인 포인트에 대해, `_market_source_label()`은 `"yfinance"`를 반환해야 한다. _(Req 9.4)_

---

## Error Handling

| 상황 | 처리 방식 |
|---|---|
| `KIS_APP_KEY` / `KIS_APP_SECRET` 없음 | `is_available() = False` → 전 항목 즉시 yfinance fallback, INFO 로그 |
| 토큰 발급 실패 (네트워크 / 인증 오류) | `HttpFetchError` → `_safe_kis_point` 일괄 yfinance fallback, WARNING 1회 |
| EGW00201 (HTTP 500 + message) | `_KisRateLimitError` → `execute_with_provider_retry`로 최대 5회 재시도 (1→2→4→8초 backoff) |
| EGW00201 아닌 HTTP 500 | `HttpFetchError(retryable=True)` → 정책 기반 재시도 |
| `rt_cd != "0"` 또는 `last` 무효 | `HttpFetchError` → yfinance fallback |
| KIS + yfinance 모두 실패 | `_resolve_point_from_cache()` → 26시간 이내 캐시 복원, `validation_status="previous_value"` |
| `_EXCD_MAP`에 없는 ticker | `HttpFetchError` 즉시 발생 → yfinance fallback |
| `nq_futures` 수집 시 | 1차 범위에서는 KIS를 거치지 않고 기존 `_safe_yfinance_point("nq_futures", "NQ=F")` 경로를 유지 |

---

## Testing Strategy

### 파일 구조

```
tests/
  test_kis_source.py              # kis.py 단위 테스트 (신설)
  test_stooq.py                   # 삭제
  test_kis.py                     # 탐색용 standalone 스크립트 → tests/ 밖으로 이동 or 삭제
  test_twelvedata.py              # 탐색용 standalone 스크립트 → tests/ 밖으로 이동 or 삭제
  test_market_btc_official_flow.py  # Stooq mock → KIS mock 교체 (lambda signature 포함)
  test_market_reliability.py      # fetch_korea_investor_points 테스트 2개 KIS 기준으로 교체
  test_brief_quality.py           # usdkrw 출처 문구 회귀 검증
  test_briefing_quality.py        # source label 렌더링 검증
  test_preservation_properties.py  # TestStooqFallbackPreservation + TestCanonicalKeyMappingPreservation 교체
```

### `test_kis_source.py` 주요 케이스

```python
# 1. 정상 응답 파싱
def test_fetch_close_change_and_volume_success(monkeypatch):
    # _kis_get을 mock → rt_cd="0", last="150.00", base="148.00", tvol="1000000"
    # 반환값: (150.0, pytest.approx(1.35), 1000000)

# 2. rt_cd != "0" → HttpFetchError
def test_fetch_close_change_and_volume_error_rt_cd(monkeypatch): ...

# 3. last == "" → HttpFetchError
def test_fetch_close_change_and_volume_empty_last(monkeypatch): ...

# 4. EGW00201 → _KisRateLimitError → retry 후 성공
def test_egw00201_retries_and_succeeds(monkeypatch): ...

# 5. EGW00201 5회 후 HttpFetchError
def test_egw00201_exhausts_retries(monkeypatch): ...

# 6. is_available() — 환경변수 있을 때/없을 때
def test_is_available_true(monkeypatch): ...
def test_is_available_false(monkeypatch): ...

# 7. EXCD 매핑 없는 ticker
def test_unknown_ticker_raises(monkeypatch): ...

# 8. fetch_usdkrw_point 정상/실패
def test_fetch_usdkrw_point_success(monkeypatch): ...
def test_fetch_usdkrw_point_failure(monkeypatch): ...
```

### `test_market_btc_official_flow.py` 변경

5개 테스트 모두 동일 패턴:
```python
# 변경 전 (stooq_symbol kwarg 있음)
monkeypatch.setattr(
    "morning_brief.data.market._safe_stooq_point_and_volume",
    lambda label, ticker, stooq_symbol=None: (MarketPoint(...), 10),
)

# 변경 후 (stooq_symbol kwarg 제거)
monkeypatch.setattr(
    "morning_brief.data.market._safe_kis_point_and_volume",
    lambda label, ticker: (MarketPoint(...), 10),
)
```

### `test_market_reliability.py` 변경

아래 두 테스트는 `_safe_yfinance_point` mock으로 `fetch_korea_investor_points()`를 검증한다. 1차 변경 후 이 함수는 `usdkrw`만 `_safe_kis_usdkrw_point()`를 호출하고 `nq_futures`는 기존 yfinance 경로를 유지하므로 mock 대상을 혼합해 검증해야 한다:

```python
# test_fetch_korea_investor_points_uses_yfinance_targets — 삭제 후 아래로 교체
# test_fetch_korea_investor_points_available_for_newsletter — 삭제 후 아래로 교체

def test_fetch_korea_investor_points_uses_mixed_primary(monkeypatch):
    """usdkrw는 KIS, nq_futures는 기존 yfinance를 쓰는지 검증."""
    kis_calls: list[str] = []
    yf_calls: list[str] = []
    def fake_kis_usdkrw_point() -> tuple[float, float]:
        kis_calls.append("usdkrw")
        return (1330.0, 0.2)
    def fake_yfinance_point(*, label, ticker, canonical_key, price_scale=1.0):
        yf_calls.append(canonical_key)
        return MarketPoint(label=label, ticker=ticker, price=20150.0, change_pct=-0.4, canonical_key=canonical_key)
    monkeypatch.setattr("morning_brief.data.market.kis_fetch_usdkrw_point", fake_kis_usdkrw_point)
    monkeypatch.setattr("morning_brief.data.market.kis_is_available", lambda: True)
    monkeypatch.setattr("morning_brief.data.market._safe_yfinance_point", fake_yfinance_point)
    points = fetch_korea_investor_points()
    assert [p.canonical_key for p in points] == ["usdkrw", "nq_futures"]
    assert kis_calls == ["usdkrw"]
    assert yf_calls == ["nq_futures"]
```

### `test_preservation_properties.py` 변경

`TestStooqFallbackPreservation` 클래스의 변경:

```python
# 삭제: test_us_index_targets_have_stooq_symbols
#   → US_INDEX_TARGETS가 2-tuple로 변경됨; .us suffix 체크 불필요

# 변경: test_us_index_targets_have_valid_structure
#   → (canonical_key, ticker, stooq_symbol) 3-tuple → (canonical_key, ticker) 2-tuple

# 변경: test_fetch_us_index_points_uses_safe_stooq_point
assert "_safe_kis_point" in source  # stooq → kis

# 변경: test_btc_etf_uses_safe_stooq_point_and_volume
assert "_safe_kis_point_and_volume" in source  # stooq → kis
```

`TestCanonicalKeyMappingPreservation._EXPECTED_MAPPINGS`의 변경:
```python
# 삭제 (stooq 심볼 — kis에서 생성하지 않음)
"spy.us": "spy",
"qqq.us": "qqq",
"soxx.us": "soxx",
# 유지 (캐시 호환성을 위해 market_policy.py에는 남기지만 테스트에서는 제거)
```

### `test_brief_quality.py`, `test_briefing_quality.py` 변경

```python
# usdkrw가 KIS primary일 때
assert "[출처: KIS]" in briefing

# usdkrw가 yfinance fallback일 때
assert "[출처: yfinance]" in briefing

# nq_futures는 계속 yfinance
assert "나스닥 선물" in briefing and "[출처: yfinance]" in briefing
```

### `fetch_korea_investor_points()` 신규 테스트 (`test_kis_source.py` 내)

```python
# usdkrw KIS 성공 + nq_futures yfinance 유지
def test_korea_investor_kis_success(monkeypatch): ...

# usdkrw KIS 실패 → yfinance fallback
def test_korea_investor_kis_fails_uses_yfinance(monkeypatch): ...

# KIS 미설정(is_available=False) → usdkrw도 yfinance 즉시 사용
def test_korea_investor_kis_unavailable(monkeypatch): ...
```
