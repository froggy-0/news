# Implementation Plan

- [x] 1. 버그 조건 탐색 테스트 작성 (수정 전 코드에서 실행)
  - **Property 1: Bug Condition** - DXY yfinance 전용 경로 및 Perplexity BTC ETF structured query 실패 확인
  - **CRITICAL**: 이 테스트는 수정 전 코드에서 반드시 FAIL해야 한다 — 실패가 버그 존재를 증명한다
  - **DO NOT** 테스트 실패 시 테스트나 코드를 수정하지 말 것
  - **NOTE**: 이 테스트는 기대 동작을 인코딩한다 — 수정 후 PASS하면 버그가 해결된 것이다
  - **GOAL**: 버그 존재를 증명하는 counterexample을 도출
  - **Scoped PBT Approach**: 결정적 버그이므로 구체적 실패 케이스로 범위를 한정
  - 테스트 1a: `MACRO_FALLBACK_TARGETS`에 `("dxy", "DX-Y.NYB", 1.0)`이 포함되어 있고, DXY 티커가 비활성화된 `DX-Y.NYB`이고 유효한 `DX=F`가 아님을 확인
  - 테스트 1b: `fetch_official_btc_etf_snapshots()`가 `_request_reference_snapshots()`를 먼저 호출하는 구조임을 확인
  - 테스트 1c: `CANONICAL_KEY_BY_SOURCE`에 `DX=F` → `dxy` 매핑이 없음을 확인
  - 수정 전 코드에서 실행
  - **EXPECTED OUTCOME**: 테스트 FAIL (버그 존재 확인)
  - counterexample 문서화: DXY가 yfinance 전용 경로만 사용, Perplexity가 primary 경로
  - 테스트 작성·실행·실패 문서화 완료 시 태스크 완료 처리
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. 보존 속성 테스트 작성 (수정 전 코드에서 실행)
  - **Property 2: Preservation** - 기존 거시 지표·미국 지수·BTC ETF 가격·Perplexity Sonar 동작 보존
  - **IMPORTANT**: observation-first 방법론을 따를 것
  - 관찰: 수정 전 코드에서 `MACRO_FALLBACK_TARGETS`에 us10y(`^TNX`), us3m(`^IRX`), vix(`^VIX`)가 포함됨을 확인
  - 관찰: 수정 전 코드에서 `US_INDEX_TARGETS`에 SPY, QQQ, SOXX가 Stooq 우선 패턴으로 수집됨을 확인
  - 관찰: 수정 전 코드에서 `BTC_ETF_TICKERS`가 `_safe_stooq_point_and_volume()` 경로를 사용함을 확인
  - 관찰: 수정 전 코드에서 Perplexity Sonar의 토픽 요약·뉴스 수집·맥락 분석 코드가 `btc_etf_official.py` 외부에 있음을 확인
  - 관찰: 수정 전 코드에서 `build_market_packet()` 반환 packet 구조가 `macro`, `korea_watch`, `us_indices`, `tech_stocks`, `bitcoin` 키를 포함함을 확인
  - 관찰: 수정 전 코드에서 DXY validation bounds가 `(95.0, 115.0)`임을 확인
  - Property-based test: DXY 외 모든 거시 지표가 동일한 FRED → yfinance fallback 경로를 유지하는지 검증
  - Property-based test: 미국 지수·빅테크·BTC ETF 가격이 동일한 Stooq → yfinance fallback 패턴을 유지하는지 검증
  - Property-based test: 캐시 구조 및 packet 구조가 변경되지 않았는지 검증
  - 수정 전 코드에서 실행
  - **EXPECTED OUTCOME**: 테스트 PASS (보존할 기준 동작 확인)
  - 테스트 작성·실행·통과 확인 시 태스크 완료 처리
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. 데이터 소스 신뢰성 수정 구현

  - [x] 3.1 `MACRO_FALLBACK_TARGETS`에서 DXY 티커를 `DX-Y.NYB`에서 `DX=F`로 교체 (`market.py`)
    - `MACRO_FALLBACK_TARGETS`에서 `("dxy", "DX-Y.NYB", 1.0)`을 `("dxy", "DX=F", 1.0)`으로 교체
    - 기존 "ICE DXY is sourced only from Yahoo Finance's DX-Y.NYB path" 주석을 `DX=F` 티커 사용 설명으로 교체
    - _Bug_Condition: isBugCondition(input) where input.ticker == "DX-Y.NYB" AND input.source == "yfinance"_
    - _Expected_Behavior: DXY가 yfinance `DX=F` 티커로 안정 수집_
    - _Preservation: us10y, us3m, vix의 MACRO_FALLBACK_TARGETS + FRED 경로 유지_
    - _Requirements: 2.1, 2.2, 3.1, 3.7_

  - [x] 3.2 `CANONICAL_KEY_BY_SOURCE`에 새 DXY 티커 매핑 추가 (`market_policy.py`)
    - `"DX=F": "dxy"` 추가
    - 기존 `"DX-Y.NYB": "dxy"` 매핑은 하위 호환성을 위해 유지
    - _Bug_Condition: CANONICAL_KEY_BY_SOURCE에 DX=F 매핑 부재_
    - _Expected_Behavior: 새 티커가 canonical key `dxy`로 정상 매핑_
    - _Preservation: 기존 매핑 전체 유지_
    - _Requirements: 2.2_

  - [x] 3.3 BTC ETF 보유량 수집에서 Perplexity structured query 제거 (`btc_etf_official.py`)
    - `fetch_official_btc_etf_snapshots()`에서 `_request_reference_snapshots()` 호출 제거
    - `_fetch_direct_reference_snapshots()`를 primary 경로로 직접 호출
    - `api_key` 파라미터는 시그니처에 유지 (호출부 변경 최소화)
    - GBTC 관련 주석을 "IBIT+BITB 2종 운영"으로 업데이트
    - _Bug_Condition: isBugCondition(input) where input.method == "perplexity_structured_query"_
    - _Expected_Behavior: Perplexity 호출 없이 direct fetch(IBIT+BITB)를 즉시 사용_
    - _Preservation: Perplexity Sonar의 다른 용도(토픽 요약, 뉴스 수집, 맥락 분석) 무영향_
    - _Requirements: 2.3, 2.4, 2.5, 3.5_

  - [x] 3.4 버그 조건 탐색 테스트가 이제 통과하는지 확인
    - **Property 1: Expected Behavior** - DXY yfinance `DX=F` 수집 및 BTC ETF Direct Fetch Primary
    - **IMPORTANT**: 태스크 1에서 작성한 동일한 테스트를 재실행 — 새 테스트를 작성하지 말 것
    - 태스크 1의 테스트가 기대 동작을 인코딩하고 있음
    - 이 테스트가 통과하면 기대 동작이 충족된 것
    - 태스크 1의 버그 조건 탐색 테스트 재실행
    - **EXPECTED OUTCOME**: 테스트 PASS (버그 수정 확인)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.5 보존 테스트가 여전히 통과하는지 확인
    - **Property 2: Preservation** - 기존 동작 보존 확인
    - **IMPORTANT**: 태스크 2에서 작성한 동일한 테스트를 재실행 — 새 테스트를 작성하지 말 것
    - 태스크 2의 보존 속성 테스트 재실행
    - **EXPECTED OUTCOME**: 테스트 PASS (회귀 없음 확인)
    - 수정 후 모든 보존 테스트가 통과하는지 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 4. 문서 업데이트
  - `docs/data-source-reliability.md` 또는 관련 문서에 DXY 수집 경로 변경 사항 반영
  - BTC ETF 보유량 수집 경로 변경 (Perplexity → direct fetch primary) 반영
  - IBIT+BITB 2종 운영 공식화 반영
  - 커밋 형식: `docs(data-source): DXY DX=F 티커 교체 및 BTC ETF direct fetch 승격 문서화`
  - _Requirements: 2.1, 2.3, 2.5_

- [x] 5. 최종 검증 — 전체 테스트 통과 확인
  - `make check` 실행 (ruff format + ruff check + pytest)
  - 모든 기존 테스트가 수정 없이 통과하는지 확인
  - 새로 작성한 버그 조건 테스트 및 보존 테스트 모두 통과 확인
  - 문제 발생 시 사용자에게 확인 요청
  - _Requirements: 3.8_
