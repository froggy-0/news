# KIS Market Data Expansion — Feature Design

## Overview

기존 `kis.py`는 해외 주식·ETF 종가 조회(`HHDFS00000300`)와 USD/KRW 환율 조회(`FHKST03030100`) 두 가지 TR만 사용한다. 이 기능은 KIS TR ID를 카테고리별로 확장하여 해외 주요 지수, 추가 환율, KOSPI/KOSDAQ, 국채금리, 원자재를 수집하는 `kis_market_fetcher.py` 모듈을 신설한다. 기존 `kis.py`는 변경하지 않으며, 새 모듈이 토큰 발급 singleton을 공유하는 방식으로 분리한다.

핵심 전략 세 가지:
1. **기존 `kis.py` 불변** — `fetch_close_change_and_volume` / `fetch_usdkrw_point` 인터페이스는 그대로 유지하고 새 TR은 별도 모듈에서 구현
2. **카테고리별 배치 fetch** — 카테고리(지수·환율·국내지수·금리·원자재)를 단위로 묶어 호출하고, 카테고리 내 항목은 순차 실행하여 KIS rate limit(EGW00201)을 회피
3. **계층적 fallback** — KIS → yfinance(또는 FRED) → skip 순서를 카테고리마다 명시적으로 정의하여 부분 성공을 보장

## Glossary

- **TR ID**: KIS API 거래 구분 코드. 엔드포인트·데이터 종류를 식별
- **EXCD**: KIS 해외 거래소 코드 (`NAS`, `NYS`, `AMS`, `TSE`, `FRA`, `SHS` 등)
- **`_KisRateLimitError`**: KIS HTTP 500 + `EGW00201` 응답 시 발생하는 재시도 가능 오류
- **`_TIMEOUT_SECONDS`**: 단일 KIS HTTP 요청 타임아웃 (현재 15초)
- **배치 fetch**: 동일 카테고리 내 여러 티커를 루프로 순차 조회하는 패턴
- **`validation_status: "missing"`**: fallback까지 모두 실패한 항목의 `MarketPoint` 상태
- **`_info_once`**: 동일 경고를 한 번만 출력하는 기존 패턴 (`_provider_warned` set 활용)
- **직접 렌더링 경로**: `fetch_newsletter_display_data()`를 통해 LLM 프롬프트를 거치지 않고 뉴스레터에 삽입되는 데이터 경로

## Architecture

### 컴포넌트 구조

```
src/morning_brief/data/sources/
├── kis.py                    ← 기존 (변경 없음)
│   ├── _ensure_token()       ← 토큰 singleton (공유 대상)
│   ├── fetch_close_change_and_volume()
│   └── fetch_usdkrw_point()
│
└── kis_market_fetcher.py     ← 신설 (새 TR 전담)
    ├── _ensure_token()       ← kis.py._ensure_token 재사용 (import)
    ├── fetch_global_index_points()   # 해외 주요 지수
    ├── fetch_fx_points()             # 추가 환율 (JPY/EUR/CNY)
    ├── fetch_domestic_index_points() # KOSPI/KOSDAQ
    ├── fetch_bond_yield_points()     # 국채금리 3Y/10Y
    └── fetch_commodity_points()      # 원자재 WTI/Gold/Silver

src/morning_brief/data/
└── market.py                 ← 기존 (진입점 교체·추가)
    ├── fetch_us_index_points()       → KIS SPY/QQQ/SOXX (기존 유지)
    ├── fetch_global_index_points()   → kis_market_fetcher (신규 진입점)
    ├── fetch_fx_points()             → kis_market_fetcher (신규 진입점)
    ├── fetch_domestic_index_points() → kis_market_fetcher (신규 진입점)
    ├── fetch_bond_yield_points()     → kis_market_fetcher (신규 진입점)
    └── fetch_commodity_points()      → kis_market_fetcher (신규 진입점)
```

### KIS TR ID 매핑 테이블

| 카테고리 | TR ID | Path | 비고 |
|---------|-------|------|------|
| 해외 주식·ETF (기존) | `HHDFS00000300` | `/uapi/overseas-price/v1/quotations/price` | `kis.py` 유지 |
| 해외 지수 (신규) | `HHDFS00000300` | `/uapi/overseas-price/v1/quotations/price` | ETF 프록시 티커 사용 |
| 해외 환율 (기존+신규) | `FHKST03030100` | `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice` | `FID_INPUT_ISCD`만 교체 |
| KOSPI/KOSDAQ (신규) | `FHPUP02100000` | `/uapi/domestic-stock/v1/quotations/inquire-index-price` | 국내 지수 전용 |
| 국채금리 (신규) | `FHKST03010100` | `/uapi/domestic-bond/v1/quotations/inquire-bond-price` | 수익률(%) 수집 |
| 원자재 선물 (신규) | `HHDFS00000300` | `/uapi/overseas-price/v1/quotations/price` | 선물 티커(`CL=F` 등) |

### 신규 티커 및 EXCD 확장 (`_EXCD_MAP`)

| 카테고리 | 티커 | EXCD | 비고 |
|---------|------|------|------|
| 해외 지수 (ETF 프록시) | DIA | AMS | DOW Jones |
| 해외 지수 (ETF 프록시) | EWG | AMS | DAX (독일) |
| 해외 지수 (ETF 프록시) | EWJ | AMS | NIKKEI (일본) |
| 원자재 선물 | CL=F | NYS | WTI 원유 |
| 원자재 선물 | GC=F | NYS | Gold |
| 원자재 선물 | SI=F | NYS | Silver |

환율은 `_EXCD_MAP` 대신 `FID_INPUT_ISCD` 파라미터(`FX@JPY`, `FX@EUR`, `FX@CNY`)로 구분한다.

### MarketPoint 필드 매핑

| 카테고리 | `price` | `change_pct` | `change_bps` | `validation_status` |
|---------|---------|--------------|--------------|---------------------|
| 지수·ETF | 종가(USD) | 전일 대비(%) | None | `ok` / `missing` |
| 환율 | 환율(KRW) | 전일 대비(%) | None | `ok` / `missing` |
| KOSPI/KOSDAQ | 지수 레벨 | 전일 대비(%) | None | `ok` / `missing` |
| 국채금리 | 수익률(%) | None | 전일 대비(bp) | `ok` / `missing` |
| 원자재 | 가격(USD) | 전일 대비(%) | None | `ok` / `missing` |

국채금리는 기존 `is_rate_canonical_key()` 판정 로직을 따라 `change_pct = None`, `change_bps`만 설정한다.

## 데이터 흐름

```
[KIS API]                   [kis_market_fetcher.py]          [market.py]
    │                               │                              │
    │  HHDFS00000300 (지수·원자재)  │                              │
    │──────────────────────────────>│  _kis_get()                  │
    │                               │  ↓                           │
    │  FHKST03030100 (환율)         │  _parse_float()              │
    │──────────────────────────────>│  ↓                           │
    │                               │  _market_point()             │
    │  FHPUP02100000 (KOSPI/KOSDAQ) │  ↓                           │
    │──────────────────────────────>│  MarketPoint                 │
    │                               │  ↓                           │
    │  FHKST03010100 (국채금리)     │  (실패 시 fallback 체인)     │
    │──────────────────────────────>│       ↓                      │
    │                               │  yfinance / FRED             │
    │                               │                              │
    │                               │──────── MarketPoint ────────>│
    │                                                              │
    │                                                              ▼
    │                                               build_market_packet()
    │                                                              │
    │                               ┌──────────────────────────────┤
    │                               ▼                              ▼
    │                      LLM prompt (signals)      직접 렌더링
    │                      - 해외 주요 지수           (fetch_newsletter_display_data)
    │                      - KOSPI/KOSDAQ            - 추가 환율 (JPY/EUR/CNY)
    │                      - 국채금리                - 원자재 (WTI/Gold/Silver)
    │                      - 원자재 (이상 신호 시)
```

### LLM 프롬프트 포함/제외 기준

| 데이터 항목 | 경로 | 근거 |
|-----------|------|------|
| 해외 주요 지수 (S&P 500·NASDAQ·DOW·DAX·NIKKEI) | LLM prompt `signals` | 시장 방향성 판단 핵심 — LLM 분석 필요 |
| KOSPI/KOSDAQ | LLM prompt `signals` | 국내 투자자 직접 영향 |
| 국채금리 3Y/10Y | LLM prompt `signals` | 금리 곡선·채권 시그널 |
| 원자재 이상 변동 (±3% 이상) | LLM prompt `signals` | keyword 트리거 조건 충족 시만 포함 |
| 추가 환율 (JPY·EUR·CNY) | 직접 렌더링 | 참고 수치; LLM 분석 불필요 |
| 원자재 정상 변동 | 직접 렌더링 | 참고 수치 |

## 카테고리별 배치 Fetch 전략

### 배치 순서 및 fallback 체인

```python
# kis_market_fetcher.py 구조 (의사코드)

GLOBAL_INDEX_TARGETS = [
    ("spy",   "SPY",  "AMS"),  # S&P 500 프록시 (기존 kis.py 중복 제거 검토)
    ("qqq",   "QQQ",  "NAS"),  # NASDAQ 프록시
    ("dia",   "DIA",  "AMS"),  # DOW
    ("ewg",   "EWG",  "AMS"),  # DAX
    ("ewj",   "EWJ",  "AMS"),  # NIKKEI
]

FX_TARGETS = [
    ("jpykrw", "FX@JPY"),
    ("eurkrw", "FX@EUR"),
    ("cnykrw", "FX@CNY"),
]

DOMESTIC_INDEX_TARGETS = [
    ("kospi",  "0001"),  # KIS 국내 지수 코드
    ("kosdaq", "1001"),
]

BOND_TARGETS = [
    ("kr3y",  "KR3Y"),   # 국채 3년
    ("kr10y", "KR10Y"),  # 국채 10년
]

COMMODITY_TARGETS = [
    ("wti",    "CL=F", "NYS"),
    ("gold",   "GC=F", "NYS"),
    ("silver", "SI=F", "NYS"),
]

# 각 fetch 함수 패턴 (해외 지수 예시)
def fetch_global_index_points() -> list[MarketPoint]:
    points = []
    for canonical_key, ticker, excd in GLOBAL_INDEX_TARGETS:
        point = _safe_with_fallback(
            primary_fetch=lambda: _point_from_kis(ticker, excd),
            fallback_fetch=lambda: _point_from_yfinance(ticker, canonical_key),
        )
        points.append(point)
    return points
```

### Rate Limit 대응

KIS는 초당 거래건수 제한(`EGW00201`)을 가진다. 카테고리 내 순차 실행 + `execute_with_provider_retry` 기존 정책(지수 백오프)으로 처리한다. 카테고리 간 병렬 실행은 하지 않는다.

### 토큰 공유 방식

```python
# kis_market_fetcher.py
from morning_brief.data.sources.kis import _ensure_token, _kis_get, _build_headers

# _ensure_token()을 직접 import하여 동일 singleton 사용
# 별도 토큰 발급 없음
```

## 인메모리 캐시 설계

```python
# TTL 기반 간단한 dict 캐시 (process 내 유효)
_FETCH_CACHE: dict[str, tuple[MarketPoint, float]] = {}  # key → (point, timestamp)

def _cached_fetch(key: str, fetch_fn: Callable[[], MarketPoint]) -> MarketPoint:
    cached = _FETCH_CACHE.get(key)
    if cached and (time.monotonic() - cached[1]) < MARKET_POINT_CACHE_MAX_AGE_HOURS * 3600:
        return cached[0]
    result = fetch_fn()
    _FETCH_CACHE[key] = (result, time.monotonic())
    return result
```

파이프라인 1회 실행 내에서 동일 티커 중복 호출을 방지한다. 캐시 저장 실패는 무시한다.

## 위험 및 대응

| 위험 | 대응 방안 |
|------|-----------|
| KIS 국내 지수 TR 미지원 또는 스펙 변경 | KOSPI/KOSDAQ은 yfinance fallback(^KS11, ^KQ11) 우선 준비 |
| 원자재 선물 티커(`CL=F`)의 EXCD 불일치 | KIS probe(`gw/explorations/kis_probe.py`)로 EXCD 사전 검증 필요 |
| KIS 국채금리 TR 미지원 | FRED DGS3/DGS10 fallback으로 전환 (기존 `_fallback_macro_points` 활용) |
| Rate limit 누적 (카테고리 합산 호출 증가) | 카테고리 내 순차 실행 + 기존 retry 정책 유지. 임계치 초과 시 카테고리 단위 skip |
| 토큰 만료 (장시간 파이프라인 실행) | 401 수신 시 `_TOKEN = None` 초기화 후 재발급 1회 시도 |
| DAX/NIKKEI ETF 프록시 괴리 | 직접 지수 TR 존재 시 우선 사용, 없으면 ETF 프록시 명시적 라벨링 (`"DAX (EWG 기준)"`) |

## Correctness Properties

### Property 1: 기존 `kis.py` 인터페이스 불변

_For any_ `fetch_close_change_and_volume()` 및 `fetch_usdkrw_point()` 호출에서, 기존 반환 타입(`tuple[float, float, int]`, `tuple[float, float]`)과 예외(`HttpFetchError`) 동작이 변경되지 않아야 한다 (SHALL).

**Validates: Requirements 6.4**

### Property 2: 토큰 singleton 공유 보장

_For any_ `kis_market_fetcher.py` 함수 호출에서, 토큰 발급은 `kis.py._ensure_token()`을 통해 모듈-레벨 singleton(`_TOKEN`)을 공유해야 한다. 별도 토큰 발급 로직을 중복 구현하지 않아야 한다 (SHALL).

**Validates: Requirements 6.4**

### Property 3: 부분 성공 보장

_For any_ 카테고리 fetch 실행에서, 단일 항목 실패가 동일 카테고리 내 다른 항목 수집을 중단시키지 않아야 한다 (SHALL). 각 항목은 독립적으로 fallback을 시도한다.

**Validates: Requirements 8.2**

### Property 4: 국채금리 `change_bps` 전용

_For any_ 국채금리 `MarketPoint`에서, `change_pct`는 `None`이어야 하며 전일 대비 변화는 `change_bps`(bp 단위)로만 표현해야 한다 (SHALL). `is_rate_canonical_key()` 판정 결과와 일치해야 한다.

**Validates: Requirements 4.2**

### Property 5: fallback 체인 순서 보장

_For any_ KIS fetch 실패에서, 시스템은 카테고리별 정의된 fallback 순서(KIS → yfinance/FRED → skip)를 순서대로 시도해야 하며 순서를 건너뛰지 않아야 한다 (SHALL).

**Validates: Requirements 8.1, 8.2**
