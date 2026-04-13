# Implementation Plan: Analytics Storage Contract V2

## Overview

구현은 `btc` 기준 dual-write 추가부터 시작해 analytics reader cutover, 조인/통계 게이트 강화, raw capture 보강, 회귀 테스트 확장 순서로 진행한다. 각 단계는 기존 `briefs/` 공개 경로와 ETF Supabase 저장을 깨뜨리지 않도록 호환성을 유지한 채 점진적으로 전환한다.

## Tasks

- [ ] 1. 저장 경로/계약 모듈 추가
  - [ ] 1.1 `src/morning_brief/data/storage/news_data_paths.py`를 추가해 `curated/btc/{date}.json`, `analytics/btc/{date}.json`, raw capture key 생성 규칙을 구현한다
    - publish path와 raw append-only path 정책을 분리한다
    - _Requirements: 1.2, 1.4, 4.1, 4.5_
  - [ ] 1.2 `src/morning_brief/data/storage/analytics_contract.py`를 추가해 analytics payload 빌드/검증 로직을 구현한다
    - `schemaVersion`, `producer`, `generatedAt`, `date`, `symbol`, `sentimentStatus`, `newsSentiment`, `_backfill`만 허용한다
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.3, 5.4_
  - [ ] 1.3 `tests/data/test_news_data_paths.py`와 `tests/data/test_analytics_contract.py`를 추가해 path 정책과 analytics 계약 검증을 테스트한다
    - Property 1: 동일 날짜 재실행에서도 publish path는 동일하고 raw path는 run_id에 따라 달라야 한다
    - Property 2: analytics payload는 허용 필드 외 키를 포함하지 않아야 한다
    - **Validates: Requirements 1.2, 3.2, 4.1, 4.5**

- [ ] 2. Curated/analytics writer 추가 및 publish 단계 dual-write 연결
  - [ ] 2.1 `src/morning_brief/data/storage/news_data_writer.py`를 추가해 low-level writer, curated writer, analytics writer, raw capture writer를 구현한다
    - analytics 저장 실패는 publish 실패로 승격할 수 있게 인터페이스를 설계한다
    - _Requirements: 2.1, 2.2, 3.1, 4.2, 4.6_
  - [ ] 2.2 `src/morning_brief/public_site.py`를 수정해 `build_public_brief()` 결과를 `curated/btc/{date}.json`와 `analytics/btc/{date}.json`에 dual-write 하도록 연결한다
    - migration 기간 동안 기존 `briefs/{date}.json` 저장은 유지한다
    - _Requirements: 2.1, 2.4, 3.1, 4.1, 4.4, 9.5_
  - [ ] 2.3 `tests/test_public_site.py`에 curated/analytics dual-write, legacy `briefs/` 유지, analytics 실패 시 publish 실패를 검증하는 테스트를 추가한다
    - Property 3: 같은 full payload에서 파생된 curated와 analytics는 같은 날짜와 같은 집계 기준을 가져야 한다
    - **Validates: Requirements 2.1, 2.4, 3.1, 4.6, 9.5**

- [ ] 3. Checkpoint - 저장 계층 기본 검증
  - [ ] 3.1 `pytest -q tests/data/test_news_data_paths.py tests/data/test_analytics_contract.py tests/test_public_site.py`가 통과하는지 확인한다
    - 실패 시 path 정책, dual-write, 계약 필드 누출 여부를 먼저 점검한다
    - _Requirements: 1.2, 2.1, 3.2, 4.6_

- [ ] 4. 분석 reader를 analytics 계약으로 전환
  - [ ] 4.1 `src/morning_brief/analysis/sentiment_join/sources/r2_sentiment.py`를 수정해 `analytics/btc/{date}.json`만 읽도록 바꾼다
    - legacy `briefs/` 의존을 제거한다
    - _Requirements: 5.1, 5.6, 5.7, 9.1_
  - [ ] 4.2 analytics payload 검증 결과를 reader output에 반영한다
    - `sentiment_status`, `is_backfill_valid`, `ingest_validation_reason`를 함께 반환한다
    - `_backfill` 누락, schema mismatch, 구조 불일치를 구분한다
    - _Requirements: 5.2, 5.3, 5.4, 10.1, 10.5_
  - [ ] 4.3 `tests/analysis/test_sentiment_join/test_r2_sentiment.py`를 수정해 analytics-only read, `_backfill` gate, schema version mismatch, invalid contract exclusion을 검증한다
    - Property 4: 지원되지 않는 계약 버전은 항상 유효 감성 관측치로 승격되지 않아야 한다
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.7**

- [ ] 5. 조인 품질 게이트와 실제 등락 라벨 추가
  - [ ] 5.1 `src/morning_brief/analysis/sentiment_join/join.py`를 수정해 `count <= 1`, `sentimentStatus == "skipped"`, invalid backfill 입력을 조인 전에 제거한다
    - exclusion reason을 집계 가능한 형태로 남긴다
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [ ] 5.2 같은 모듈 또는 인접 transform 단계에 `btc_direction_label` 생성 로직을 추가한다
    - `btc_log_return` 부호 기준으로 `up`, `down`, `flat`을 부여한다
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6_
  - [ ] 5.3 `tests/analysis/test_sentiment_join/test_join.py`를 수정해 품질 게이트 제거 조건, exclusion reason, `btc_direction_label`, Lag-1 유지 여부를 검증한다
    - Property 5: `btc_direction_label`은 모든 행에서 `btc_log_return` 부호와 일치해야 한다
    - **Validates: Requirements 6.1, 6.2, 6.4, 8.2, 8.3, 8.4, 8.5**

- [ ] 6. 통계 유효성 게이트를 180행 기준으로 분리
  - [ ] 6.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py`를 수정해 ADF와 Granger 최소 표본 기준을 분리한다
    - ADF는 기존 기준을 유지하고, Granger만 180행 게이트를 적용한다
    - _Requirements: 7.2, 7.3, 7.5_
  - [ ] 6.2 `src/morning_brief/analysis/sentiment_join/pipeline.py`를 수정해 Granger eligibility 행 수와 skip reason을 metadata/log에 남긴다
    - outlier filter 이후 유효 행 수와 통계 실행 여부를 함께 기록한다
    - _Requirements: 7.1, 7.4, 10.3, 10.4_
  - [ ] 6.3 `tests/analysis/test_sentiment_join/test_statistical_tests.py`와 `tests/analysis/test_sentiment_join/test_pipeline.py`를 수정해 179행 skip, 180행 실행, metadata 기록을 검증한다
    - Property 6: Granger는 180행 미만에서 어떤 lag에도 결과를 생성하지 않아야 한다
    - **Validates: Requirements 7.2, 7.3, 7.4, 10.4**

- [ ] 7. Checkpoint - analytics reader cutover 검증
  - [ ] 7.1 `pytest -q tests/analysis/test_sentiment_join/test_r2_sentiment.py tests/analysis/test_sentiment_join/test_join.py tests/analysis/test_sentiment_join/test_statistical_tests.py tests/analysis/test_sentiment_join/test_pipeline.py`가 통과하는지 확인한다
    - 실패 시 analytics-only read, exclusion reason, 180행 gate 중 어디가 깨졌는지 먼저 분리 진단한다
    - _Requirements: 5.1, 6.4, 7.3, 10.4_

- [ ] 8. raw capture를 현재 캡처 가능한 수집 경계에 연결
  - [ ] 8.1 `src/morning_brief/pipeline.py`에 raw capture hook을 추가해 `build_market_packet()`와 `build_news_packet()` 경계 payload를 저장한다
    - source 함수 내부 모든 HTTP body 저장은 1차 범위에서 제외한다
    - _Requirements: 1.1, 4.5_
  - [ ] 8.2 `src/morning_brief/data/news.py`와 필요한 시장 수집 경계에서 provider/topic/run_id 기준 raw capture 입력값을 정리한다
    - 최소한 pipeline 시장 경계, pipeline 뉴스 경계, provider별 주요 뉴스 수집 결과를 분류 가능하게 한다
    - _Requirements: 1.1, 1.4_
  - [ ] 8.3 `tests/test_pipeline_storage_layering.py`를 추가해 raw append-only, curated/analytics overwrite, dual-write 일관성을 검증한다
    - Property 7: 같은 날짜 재실행 시 curated/analytics key는 같고 raw key는 달라야 한다
    - **Validates: Requirements 1.1, 4.1, 4.4, 4.5**

- [ ] 9. 관측성/운영 로그 보강
  - [ ] 9.1 analytics 계약 검증 성공/실패 건수, 실패 날짜 샘플, exclusion reason 집계를 구조화 로그와 parquet metadata에 연결한다
    - _Requirements: 10.1, 10.2, 10.4, 10.5_
  - [ ] 9.2 `src/morning_brief/analysis/sentiment_join/pipeline.py`의 metadata 생성 로직을 확장해 유효 행 수, Granger 실행 여부, skip reason을 포함한다
    - _Requirements: 7.4, 10.3, 10.4_
  - [ ] 9.3 관련 테스트를 보강해 운영자가 계약 실패와 Granger skip 이유를 추적할 수 있는지 검증한다
    - **Validates: Requirements 10.1, 10.2, 10.5**

- [ ] 10. 마이그레이션 정리 및 회귀 방지
  - [ ] 10.1 dual-write migration 조건과 reader cutover 완료 조건을 문서에 반영한다
    - 필요 시 `README.md` 또는 가장 가까운 운영 문서를 갱신한다
    - _Requirements: 2.4, 5.7, 9.5_
  - [ ] 10.2 기존 ETF bronze/silver/gold/reference 저장이 영향받지 않는 회귀 테스트를 추가하거나 기존 테스트를 보강한다
    - _Requirements: 1.1, 11.1_
  - [ ] 10.3 저장 계층, analytics reader, 조인 품질 게이트, 통계 게이트를 아우르는 최종 통합 테스트를 실행한다
    - `make test` 전에 가장 좁은 범위 pytest부터 확인한다
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**

- [ ] 11. Checkpoint - 최종 검증
  - [ ] 11.1 아래 검증 순서를 통과한다
    - `pytest -q tests/data/test_news_data_paths.py tests/data/test_analytics_contract.py tests/test_public_site.py tests/test_pipeline_storage_layering.py tests/analysis/test_sentiment_join/test_r2_sentiment.py tests/analysis/test_sentiment_join/test_join.py tests/analysis/test_sentiment_join/test_statistical_tests.py tests/analysis/test_sentiment_join/test_pipeline.py`
    - 필요 시 `make test`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
