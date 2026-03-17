# Data Source Reliability Fix — Bugfix Design

## Overview

매일 아침 시장 브리핑 파이프라인에서 3개 데이터 소스가 구조적으로 실패하고 있다. DXY(달러 인덱스)는 yfinance `DX-Y.NYB` 티커가 "possibly delisted"로 10/10 실패하고, Perplexity BTC ETF structured query는 10/10 빈 배열을 반환하며, GBTC는 Grayscale의 HTTP 429 차단으로 수집 불가하다.

수정 전략은 세 가지다:
1. DXY의 yfinance 티커를 `DX-Y.NYB`에서 `DX=F`(ICE Dollar Index Futures)로 교체 — `MACRO_FALLBACK_TARGETS` 내 티커만 변경하는 최소 수정 (Stooq는 선물 심볼의 CSV 다운로드를 지원하지 않아 사용 불가)
2. BTC ETF 보유량 수집에서 Perplexity structured query를 제거하고 direct fetch(IBIT+BITB)를 primary 경로로 승격
3. GBTC 수집 시도를 제거하고 IBIT+BITB 2종 운영을 공식화

## Glossary

- **Bug_Condition (C)**: DXY 수집 시 yfinance `DX-Y.NYB` 사용, BTC ETF 수집 시 Perplexity structured query 호출, GBTC direct fetch 시도 — 이 세 경로가 구조적으로 실패하는 조건
- **Property (P)**: DXY가 yfinance `DX=F` 티커로 안정 수집되고, BTC ETF가 direct fetch로 즉시 수집되며, 불필요한 API 호출이 제거되는 상태
- **Preservation**: 기존 거시 지표(us10y, us2y, us3m, vix), 미국 지수(SPY, QQQ, SOXX), 빅테크 10종, BTC ETF 가격·거래량, 캐시 구조, Perplexity Sonar의 다른 용도가 변경 없이 유지되는 것
- **`fetch_macro_points()`**: `market.py`의 거시 지표 수집 함수. FRED 우선 → `MACRO_FALLBACK_TARGETS` yfinance fallback
- **`MACRO_FALLBACK_TARGETS`**: `market.py`의 yfinance 전용 거시 지표 목록. `(canonical_key, ticker, price_scale)` 튜플 리스트
- **`fetch_official_btc_etf_snapshots()`**: `btc_etf_official.py`의 BTC ETF 보유량 수집 함수. Perplexity structured query → direct fetch fallback
- **`_safe_stooq_point()`**: `market.py`의 Stooq 우선 → yfinance fallback 패턴 함수
- **`CANONICAL_KEY_BY_SOURCE`**: `market_policy.py`의 소스 티커 → canonical key 매핑 딕셔너리

## Bug Details

### Bug Condition

버그는 세 가지 독립적인 데이터 수집 경로에서 발생한다:

1. **DXY**: `fetch_macro_points()`가 `MACRO_FALLBACK_TARGETS`를 통해 yfinance `DX-Y.NYB`를 호출하면 "possibly delisted" 오류로 항상 실패. yfinance `DX=F` 같은 유효한 대안 티커가 적용되지 않은 상태.
2. **BTC ETF Perplexity**: `fetch_official_btc_etf_snapshots()`가 `_request_reference_snapshots()`를 먼저 호출하면 항상 `{"snapshots": []}` 반환. 이후 direct fetch fallback이 성공하지만 불필요한 API 비용과 지연 발생.
3. **GBTC**: Grayscale이 HTTP 429로 scraping 차단. 이미 direct fetch 대상에서 제외되어 있으나, Perplexity structured query에서 GBTC를 요청하는 코드와 주석이 남아 있음.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type DataCollectionRequest
  OUTPUT: boolean

  CASE input.type OF
    "macro_dxy":
      RETURN input.ticker == "DX-Y.NYB"
             AND input.source == "yfinance"

    "btc_etf_perplexity":
      RETURN input.method == "perplexity_structured_query"
             AND input.target IN ["IBIT", "BITB", "GBTC"]

    "btc_etf_gbtc":
      RETURN input.ticker == "GBTC"
             AND input.method == "direct_fetch"
             AND httpStatus(input.url) == 429
  END CASE
END FUNCTION
```

### Examples

- DXY 수집: `_safe_yfinance_point("달러 인덱스", "DX-Y.NYB", "dxy")` → "possibly delisted" 오류 → `validation_status=missing` → 브리핑에서 DXY 완전 누락
- BTC ETF Perplexity: `_request_reference_snapshots(api_key)` → `{"snapshots": []}` → direct fetch fallback 발동 → IBIT+BITB 성공하지만 ~3초 지연 + Perplexity API 비용 낭비
- GBTC direct fetch: `get_text_with_retry(GBTC_URL)` → HTTP 429 → GBTC 데이터 수집 불가
- 정상 케이스 (SPY): `_safe_stooq_point("S&P500", "SPY", stooq_symbol="spy.us")` → Stooq 성공 → `validation_status=ok`

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- us10y, us2y, us3m, vix 거시 지표의 FRED 우선 → yfinance fallback 경로
- SPY, QQQ, SOXX 미국 지수의 Stooq 우선 → yfinance fallback 경로
- 빅테크 10종의 Stooq 우선 → yfinance fallback 경로
- BTC ETF 가격·거래량의 `_safe_stooq_point_and_volume()` 경로
- BTC ETF 보유량 캐시 구조 (`btc-etf-snapshots-YYYYMMDD`, 로드/저장/TTL)
- Perplexity Sonar의 토픽 요약, 뉴스 수집, 맥락 분석 용도
- `build_market_packet()` 반환 packet 구조
- DXY validation bounds `(95.0, 115.0)`
- 기존 테스트 전체 통과

**Scope:**
DXY 수집 경로 변경과 BTC ETF Perplexity structured query 제거 외의 모든 데이터 수집 경로는 이번 수정에 영향받지 않아야 한다.

## Hypothesized Root Cause

### Problem 1: DXY 수집 실패

1. **yfinance 티커 비활성화**: `DX-Y.NYB`(ICE Dollar Index)가 yfinance에서 "possibly delisted"로 표시됨. Yahoo Finance가 해당 심볼의 데이터 제공을 중단한 것으로 추정.
2. **yfinance 전용 경로 내 티커 미교체**: `MACRO_FALLBACK_TARGETS`는 yfinance 전용 경로로, 티커만 교체하면 되지만 `DX-Y.NYB`가 그대로 유지되어 있음.
3. **대안 티커 미적용**: yfinance `DX=F`(ICE Dollar Index Futures)는 ICE DXY와 거의 동일한 값을 제공하지만 현재 코드에서 사용하지 않음.

**Root Cause**: `DX-Y.NYB` 티커 비활성화가 근본 원인. `MACRO_FALLBACK_TARGETS` 내 티커를 `DX=F`로 교체하면 해결됨.

### Problem 2: Perplexity BTC ETF structured query 실패

1. **Perplexity 구조화 응답 한계**: Perplexity Sonar의 `json_schema` response format이 BTC ETF 보유량 같은 실시간 수치 데이터를 안정적으로 반환하지 못함.
2. **도메인 필터 제약**: `search_domain_filter`가 `ishares.com`, `bitbetf.com`, `etfs.grayscale.com`으로 제한되어 있어 Perplexity가 해당 도메인에서 구조화 데이터를 추출하지 못할 수 있음.
3. **Direct fetch가 이미 100% 성공**: IBIT+BITB direct fetch가 10/10 성공하므로 Perplexity 경로는 불필요한 중복.

**Root Cause**: Perplexity Sonar가 issuer 도메인의 동적 금융 데이터를 구조화 JSON으로 안정 추출하지 못하는 구조적 한계.

### Problem 3: GBTC 수집 차단

1. **Grayscale 429 차단**: Grayscale이 `etfs.grayscale.com`에 대한 자동화 scraping을 HTTP 429로 차단.
2. **브리핑 프롬프트 비요구**: 브리핑 프롬프트(`brief_instructions.j2`, `brief_input.j2`)에서 GBTC 보유량을 명시적으로 요구하지 않음. `official_etf_snapshots` 필드에 IBIT+BITB만 있어도 브리핑 생성에 충분.

**Root Cause**: Grayscale의 anti-scraping 정책. GBTC 데이터는 현재 아키텍처에서 수집 불가하며, 브리핑에 필수가 아님.

## Correctness Properties

Property 1: Bug Condition - DXY yfinance `DX=F` 수집

_For any_ 파이프라인 실행에서 DXY를 수집할 때, 수정된 `fetch_macro_points()` 함수는 yfinance `DX=F` 티커로 DXY 값을 수집해야 한다 (SHALL). 더 이상 `DX-Y.NYB` 티커를 사용하지 않아야 한다.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition - BTC ETF Direct Fetch Primary

_For any_ 파이프라인 실행에서 BTC ETF 보유량을 수집할 때, 수정된 `fetch_official_btc_etf_snapshots()` 함수는 Perplexity structured query를 호출하지 않고 direct fetch(IBIT+BITB)를 primary 경로로 즉시 사용해야 한다 (SHALL).

**Validates: Requirements 2.3, 2.4, 2.5**

Property 3: Preservation - 기존 거시 지표 경로 유지

_For any_ DXY 외의 거시 지표(us10y, us2y, us3m, vix) 수집에서, 수정된 코드는 기존 `MACRO_FALLBACK_TARGETS` + FRED 우선 → yfinance fallback 경로와 동일한 결과를 생성해야 한다 (SHALL).

**Validates: Requirements 3.1, 3.7**

Property 4: Preservation - 기존 Stooq/yfinance 패턴 유지

_For any_ 미국 지수(SPY, QQQ, SOXX), 빅테크 10종, BTC ETF 가격·거래량 수집에서, 수정된 코드는 기존 Stooq 우선 → yfinance fallback 패턴과 동일한 결과를 생성해야 한다 (SHALL).

**Validates: Requirements 3.2, 3.3**

Property 5: Preservation - Perplexity Sonar 다른 용도 무영향

_For any_ Perplexity Sonar의 토픽 요약, 뉴스 수집, 맥락 분석 호출에서, 수정된 코드는 해당 기능에 어떤 영향도 주지 않아야 한다 (SHALL).

**Validates: Requirements 2.4, 3.5**

Property 6: Preservation - 캐시 구조 및 packet 구조 유지

_For any_ `build_market_packet()` 호출에서, 수정된 코드는 기존 packet 구조(`macro`, `korea_watch`, `us_indices`, `tech_stocks`, `bitcoin` 등)와 캐시 로드/저장/TTL 로직을 그대로 유지해야 한다 (SHALL).

**Validates: Requirements 3.4, 3.6, 3.8**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `src/morning_brief/data/market.py`

**Change 1: `MACRO_FALLBACK_TARGETS`에서 DXY 티커를 `DX-Y.NYB`에서 `DX=F`로 교체**
- `MACRO_FALLBACK_TARGETS` 리스트에서 `("dxy", "DX-Y.NYB", 1.0)` 튜플의 티커를 `DX=F`로 변경
- DXY는 기존 yfinance 전용 경로를 그대로 사용하되 티커만 교체

**Change 2: `fetch_macro_points()` 내 DXY 주석 업데이트**
- 기존 "ICE DXY is sourced only from Yahoo Finance's DX-Y.NYB path" 주석을 `DX=F` 티커 사용 설명으로 교체

---

**File**: `src/morning_brief/data/market_policy.py`

**Change 3: `CANONICAL_KEY_BY_SOURCE`에 새 DXY 티커 매핑 추가**
- `"DX=F": "dxy"` 추가 (yfinance 티커)
- 기존 `"DX-Y.NYB": "dxy"` 매핑은 유지 (하위 호환성, 캐시에 이전 티커가 남아있을 수 있음)

---

**File**: `src/morning_brief/data/sources/btc_etf_official.py`

**Change 4: `fetch_official_btc_etf_snapshots()`에서 Perplexity structured query 제거**
- `_request_reference_snapshots()` 호출을 제거하고 `_fetch_direct_reference_snapshots()`를 primary 경로로 직접 호출
- `api_key` 파라미터는 시그니처에 유지하되 (호출부 변경 최소화), Perplexity 호출에 사용하지 않음

**Change 5: GBTC 관련 주석 업데이트**
- `_fetch_direct_reference_snapshots()` 내 GBTC 주석을 "Perplexity structured query 경로에서만 수집" → "IBIT+BITB 2종으로 운영" 으로 업데이트
- `BTC_ETF_REFERENCE_DOMAINS`에서 `etfs.grayscale.com` 제거 여부는 선택적 (Perplexity query 자체가 제거되므로 실질적 영향 없음)

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 counterexample을 확인하고, 수정 후 코드에서 fix가 올바르게 작동하며 기존 동작이 보존되는지 검증한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 버그를 재현하여 root cause 분석을 확인 또는 반박한다.

**Test Plan**: 각 실패 경로를 단위 테스트로 시뮬레이션하여 실패 패턴을 관찰한다.

**Test Cases**:
1. **DXY yfinance 실패 테스트**: `_safe_yfinance_point("달러 인덱스", "DX-Y.NYB", "dxy")`를 호출하여 "possibly delisted" 또는 빈 데이터 반환을 확인 (수정 전 코드에서 실패)
2. **DXY 티커 확인 테스트**: DXY 티커가 비활성화된 `DX-Y.NYB`임을 확인 (수정 전 코드에서 실패)
3. **Perplexity structured query 빈 배열 테스트**: `_request_reference_snapshots(api_key)`가 빈 리스트를 반환함을 확인 (수정 전 코드에서 실패)
4. **GBTC 429 차단 테스트**: `get_text_with_retry(GBTC_URL)`이 HTTP 429를 반환함을 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- DXY: yfinance가 `DX-Y.NYB`에 대해 빈 DataFrame 또는 "possibly delisted" 예외 반환
- BTC ETF: Perplexity가 유효한 JSON을 반환하지만 `snapshots` 배열이 비어 있음
- GBTC: HTTP 429 응답으로 `HttpFetchError` 발생

### Fix Checking

**Goal**: 버그 조건에 해당하는 모든 입력에 대해 수정된 함수가 올바른 동작을 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  CASE input.type OF
    "macro_dxy":
      result := fetch_macro_points_fixed(fred_api_key)
      dxy_point := findByCanonicalKey(result, "dxy")
      ASSERT dxy_point IS NOT NULL
      ASSERT dxy_point.ticker == "DX=F"
      ASSERT dxy_point.validation_status != "missing"

    "btc_etf_perplexity":
      result := fetch_official_btc_etf_snapshots_fixed()
      ASSERT perplexityStructuredQueryNotCalled()
      ASSERT result contains IBIT AND BITB snapshots

    "btc_etf_gbtc":
      result := fetch_official_btc_etf_snapshots_fixed()
      ASSERT gbtcDirectFetchNotAttempted()
      ASSERT result contains only IBIT AND BITB
  END CASE
END FOR
```

### Preservation Checking

**Goal**: 버그 조건에 해당하지 않는 모든 입력에 대해 수정된 함수가 기존 함수와 동일한 결과를 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT fetch_macro_points_original(input) \ {dxy} == fetch_macro_points_fixed(input) \ {dxy}
  ASSERT fetch_us_index_points_original() == fetch_us_index_points_fixed()
  ASSERT fetch_tech_stock_points_original() == fetch_tech_stock_points_fixed()
  ASSERT perplexity_sonar_topic_summary_unchanged()
  ASSERT cache_structure_unchanged()
  ASSERT packet_structure_unchanged()
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- 다양한 FRED 응답 조합에서 DXY 외 지표가 동일하게 처리되는지 자동 검증
- 캐시 로드/저장 경로가 변경되지 않았는지 다양한 시나리오에서 확인
- 수동 테스트로 놓칠 수 있는 edge case를 자동 탐지

**Test Plan**: 수정 전 코드에서 DXY 외 지표, BTC ETF 가격·거래량, Perplexity Sonar 토픽 요약의 동작을 관찰한 후, 수정 후 동일한 동작이 보존되는지 property-based test로 검증한다.

**Test Cases**:
1. **거시 지표 보존 테스트**: us10y, us2y, us3m, vix가 수정 전후 동일한 FRED → yfinance fallback 경로로 수집되는지 확인
2. **미국 지수 보존 테스트**: SPY, QQQ, SOXX가 수정 전후 동일한 Stooq → yfinance fallback 경로로 수집되는지 확인
3. **BTC ETF 가격 보존 테스트**: IBIT, FBTC, ARKB, BITB, GBTC 가격·거래량이 `_safe_stooq_point_and_volume()` 경로로 동일하게 수집되는지 확인
4. **Perplexity Sonar 무영향 테스트**: 토픽 요약, 뉴스 수집, 맥락 분석 코드가 변경되지 않았는지 확인

### Unit Tests

- DXY가 `DX=F` 티커로 yfinance에서 수집되는지 테스트
- `fetch_official_btc_etf_snapshots()`가 `_request_reference_snapshots()`를 호출하지 않고 direct fetch를 바로 사용하는지 테스트
- `MACRO_FALLBACK_TARGETS`에 DXY가 `DX=F` 티커로 포함되는지 테스트
- `CANONICAL_KEY_BY_SOURCE`에 `DX=F` → `dxy` 매핑이 존재하는지 테스트

### Property-Based Tests

- 랜덤 FRED 응답 조합을 생성하여 DXY 외 거시 지표가 수정 전후 동일하게 처리되는지 검증
- 랜덤 Stooq/yfinance 응답 조합을 생성하여 미국 지수·빅테크 수집이 보존되는지 검증 (DXY는 yfinance `DX=F` 티커 교체만 해당)
- 랜덤 BTC ETF direct fetch 응답을 생성하여 IBIT+BITB 스냅샷이 올바르게 파싱되는지 검증

### Integration Tests

- `fetch_macro_points()` 전체 흐름에서 DXY가 yfinance `DX=F`로 수집되고 validation bounds `(95.0, 115.0)` 내에 있는지 확인
- `fetch_official_btc_etf_snapshots()`가 Perplexity 없이 IBIT+BITB를 반환하는지 확인
- `build_market_packet()` 전체 흐름에서 packet 구조가 보존되고 DXY가 포함되는지 확인
