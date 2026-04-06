# Implementation Plan

## P0 — 해외 주요 지수 + KOSPI/KOSDAQ

- [ ] 1. KIS probe로 신규 TR 및 EXCD 사전 검증
  - `gw/explorations/kis_probe.py`를 활용하여 DIA·EWG·EWJ EXCD 코드 실제 응답 확인
  - KOSPI/KOSDAQ TR ID(`FHPUP02100000`) 응답 필드 확인 및 파싱 전략 결정
  - 국내 지수 TR 응답이 없거나 미지원 시 yfinance 전용 경로 확정
  - 원자재 선물 티커(`CL=F`, `GC=F`, `SI=F`) EXCD 코드 검증
  - _Requirements: 1.3, 3.1, 5.1_
  - **예상 소요**: 2h
  - **의존성**: 없음 (KIS 자격증명 필요)

- [ ] 2. `kis_market_fetcher.py` 모듈 골격 구현
  - `src/morning_brief/data/sources/kis_market_fetcher.py` 파일 생성
  - `kis.py`의 `_ensure_token`, `_kis_get`, `_build_headers`, `_parse_float`, `_parse_int` import
  - `_GLOBAL_INDEX_TARGETS`, `_FX_TARGETS`, `_DOMESTIC_INDEX_TARGETS`, `_BOND_TARGETS`, `_COMMODITY_TARGETS` 상수 정의
  - `_EXCD_MAP` 신규 항목(DIA·EWG·EWJ·CL=F·GC=F·SI=F) 추가 — `kis.py._EXCD_MAP`에 직접 추가하거나 fetcher 내 별도 dict 결정
  - TTL 기반 인메모리 캐시 (`_FETCH_CACHE`) 구현
  - _Requirements: 6.4, 7.1, 7.2, 7.3, 7.4_
  - **예상 소요**: 2h
  - **의존성**: Task 1 (EXCD 코드 확정)

- [ ] 3. 해외 주요 지수 fetch 구현 (`fetch_global_index_points`)
  - `fetch_global_index_points() -> list[MarketPoint]` 구현
  - S&P 500(SPY), NASDAQ(QQQ), DOW(DIA), DAX(EWG), NIKKEI(EWJ) 순차 조회
  - 기존 `_safe_with_fallback` 패턴으로 KIS → yfinance fallback 연결
  - `market.py`에 `fetch_global_index_points()` 진입점 추가
  - `_info_once` 패턴으로 `is_available()` False 시 경고 1회 출력
  - _Requirements: 1.1, 1.2, 1.3, 8.1, 8.2, 8.4_
  - **예상 소요**: 3h
  - **의존성**: Task 2

- [ ] 4. KOSPI/KOSDAQ fetch 구현 (`fetch_domestic_index_points`)
  - `fetch_domestic_index_points() -> list[MarketPoint]` 구현
  - Task 1에서 확인한 TR ID·응답 필드로 파싱 로직 구현
  - `change_pct`만 설정, `change_bps = None` 적용
  - KIS → yfinance(`^KS11`, `^KQ11`) fallback 연결
  - `market.py`에 `fetch_domestic_index_points()` 진입점 추가
  - `build_market_packet()`의 LLM prompt `signals` 섹션에 포함
  - _Requirements: 3.1, 3.2, 3.3, 8.1, 10.1_
  - **예상 소요**: 3h
  - **의존성**: Task 1, Task 2

- [ ] 5. P0 테스트 작성

  - [ ] 5.1 `fetch_global_index_points` 단위 테스트
    - KIS 정상 응답 시 SPY·QQQ·DIA·EWG·EWJ MarketPoint 반환 확인
    - KIS 실패 시 yfinance fallback 호출 확인
    - 모든 fallback 실패 시 `validation_status: "missing"` 반환 확인
    - 단일 항목 실패가 나머지 항목 수집을 중단하지 않는지 확인 (Property 3)
    - _Requirements: 1.1, 1.2, 8.2_

  - [ ] 5.2 `fetch_domestic_index_points` 단위 테스트
    - KIS 정상 응답 시 KOSPI·KOSDAQ MarketPoint 반환 확인
    - `change_pct` 존재, `change_bps = None` 확인 (Property 4와 대칭)
    - yfinance fallback 동작 확인
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 5.3 캐시 동작 테스트
    - 동일 티커 2회 호출 시 KIS API가 1회만 호출되는지 확인
    - TTL 만료 후 재호출 시 KIS API가 다시 호출되는지 확인
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 5.4 기존 `kis.py` 인터페이스 불변 테스트
    - `fetch_close_change_and_volume()` 반환 타입이 변경되지 않았는지 확인
    - `fetch_usdkrw_point()` 반환 타입이 변경되지 않았는지 확인
    - _Requirements: 6.4 / Property 1_

  - **예상 소요**: 3h
  - **의존성**: Task 3, Task 4

---

## P1 — 원자재(WTI·Gold) + 추가 환율(JPY·EUR·CNY)

- [ ] 6. 원자재 fetch 구현 (`fetch_commodity_points`)
  - `fetch_commodity_points() -> list[tuple[MarketPoint, int]]` 구현 (거래량 포함)
  - WTI(`CL=F`), Gold(`GC=F`), Silver(`SI=F`) 순차 조회
  - Task 1 검증 결과 기반 EXCD 적용
  - KIS → yfinance fallback 연결
  - `market.py`에 `fetch_commodity_points()` 진입점 추가
  - 정상 변동(±3% 미만) → `fetch_newsletter_display_data` 직접 렌더링 경로
  - 이상 변동(±3% 이상) → keyword 트리거로 LLM prompt `signals` 조건부 포함
  - _Requirements: 5.1, 5.2, 5.3, 10.2_
  - **예상 소요**: 3h
  - **의존성**: Task 1, Task 2

- [ ] 7. 추가 환율 fetch 구현 (`fetch_fx_points`)
  - `fetch_fx_points() -> list[MarketPoint]` 구현
  - `fetch_usdkrw_point()` 내부의 `FHKST03030100` TR 재사용 — `FID_INPUT_ISCD` 파라미터만 교체
  - JPY/KRW(`FX@JPY`), EUR/KRW(`FX@EUR`), CNY/KRW(`FX@CNY`) 순차 조회
  - KIS → yfinance(`JPYKRW=X`, `EURKRW=X`, `CNYKRW=X`) fallback 연결
  - `fetch_newsletter_display_data` 직접 렌더링 경로에 추가 (LLM prompt 제외)
  - _Requirements: 2.1, 2.2, 2.3, 10.2_
  - **예상 소요**: 2h
  - **의존성**: Task 2

- [ ] 8. P1 테스트 작성

  - [ ] 8.1 `fetch_commodity_points` 단위 테스트
    - KIS 정상 응답 시 WTI·Gold·Silver 가격 및 거래량 반환 확인
    - yfinance fallback 동작 확인
    - 이상 변동 조건(±3%) 시 keyword 트리거 포함 여부 확인
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 8.2 `fetch_fx_points` 단위 테스트
    - JPY·EUR·CNY MarketPoint 반환 확인
    - `FID_INPUT_ISCD` 파라미터가 각 통화별로 올바르게 교체되는지 확인
    - KIS 실패 시 yfinance fallback 호출 확인
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 8.3 LLM prompt 비포함 확인 테스트
    - JPY·EUR·CNY·원자재(정상 변동) 항목이 `build_market_packet()` `signals` 섹션에 포함되지 않는지 확인
    - `fetch_newsletter_display_data()` 결과에는 포함되는지 확인
    - _Requirements: 10.2_

  - **예상 소요**: 2h
  - **의존성**: Task 6, Task 7

---

## P2 — 국내 국채금리 (3Y·10Y)

- [ ] 9. 국채금리 fetch 구현 (`fetch_bond_yield_points`)
  - `fetch_bond_yield_points() -> list[MarketPoint]` 구현
  - KIS 채권 시세 TR(`FHKST03010100`) 응답 파싱
  - 수익률(%)을 `price`에, 전일 대비 변화를 `change_bps`에 매핑. `change_pct = None`
  - KIS → FRED(`DGS3`, `DGS10`) fallback 연결 — `_fallback_macro_points` 기존 패턴 활용
  - FRED도 실패 시 해당 항목 skip (`validation_status: "missing"`)
  - `market.py`에 `fetch_bond_yield_points()` 진입점 추가
  - `build_market_packet()` LLM prompt `signals`에 포함
  - _Requirements: 4.1, 4.2, 4.3, 10.1_
  - **예상 소요**: 3h
  - **의존성**: Task 1 (KIS 채권 TR 지원 여부 확인), Task 2

- [ ] 10. P2 테스트 작성

  - [ ] 10.1 `fetch_bond_yield_points` 단위 테스트
    - KIS 정상 응답 시 3Y·10Y `MarketPoint` 반환 확인
    - `change_pct = None`, `change_bps` 설정 확인 (Property 4)
    - KIS 실패 시 FRED fallback 호출 확인
    - FRED도 실패 시 `validation_status: "missing"` 반환 확인
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 10.2 `is_rate_canonical_key()` 연동 테스트
    - 국채금리 canonical key(`kr3y`, `kr10y`)가 `is_rate_canonical_key()` 판정에서 `True`를 반환하는지 확인
    - `MarketPoint._point_changes()` 내 bp 계산 경로가 올바르게 호출되는지 확인
    - _Requirements: 4.2_

  - **예상 소요**: 2h
  - **의존성**: Task 9

---

## 통합 검증

- [ ] 11. 전체 파이프라인 통합 테스트
  - `make check` 전체 통과 확인 (`fmt` → `lint` → `test` → `typecheck`)
  - KIS 자격증명 없는 환경에서 모든 카테고리가 fallback으로 정상 동작하는지 확인
  - `fetch_newsletter_display_data()` 결과에 신규 항목 포함 여부 확인
  - Rate limit 시뮬레이션: `EGW00201` mock 시 retry 후 fallback 전환 확인
  - _Requirements: 6.1, 8.1, 8.2, 8.3, 8.4_
  - **예상 소요**: 2h
  - **의존성**: Task 5, Task 8, Task 10

- [ ] 12. 성능 검증
  - 단일 fetch 2초 미만 기준 확인 (정상 KIS 응답 기준)
  - 전체 시장 데이터 수집 단계 타임아웃 기준 내 완료 확인
  - _Requirements: 9.1, 9.2_
  - **예상 소요**: 1h
  - **의존성**: Task 11
