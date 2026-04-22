# Implementation Plan: BTC ETF Collection Redesign

## Overview

ETF 공식 수집 경로를 구조화 데이터 우선, aggregator reference-only, Bronze/Silver/Gold 계층 분리 기준으로 먼저 재정렬한 뒤 Sentiment Join 분석 파이프라인 확장을 연결한다. 구현 순서는 수집 모델/파서 기반 정리 → 저장/집계와 관측성 → 선물 지표·통계 검정·하이브리드 지수 → 통합 회귀 테스트 순으로 진행한다.

## Tasks

- [ ] 1. ETF 스냅샷 모델과 캐시 직렬화 기반을 재정비한다
  - [ ] 1.1 `src/morning_brief/models.py`의 `BitcoinEtfIssuerSnapshot`과 관련 호출부를 표준 스냅샷 인터페이스에 맞게 확장한다
    - `BitcoinEtfIssuerSnapshot`은 Gold 전용 DTO로 고정하고, Silver 표준 레코드는 별도 `SilverNormalizedFieldRecord`로 분리 구현한다.
    - Gold 모델은 `as_of_date`, `collected_at`, `source_type`, `quality_status`를 유지하고, `source_file_url`과 field-level 원문 필드는 Silver 모델에만 둔다.
    - `src/morning_brief/data/market.py`의 요약 로직이 `critical`/reference-only 스냅샷을 primary 합산에 포함하지 않도록 호출 경계를 명시한다.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 8.1, 8.4, 14.1_
  - [ ] 1.2 `src/morning_brief/data/sources/btc_etf_official.py`의 캐시 저장/로드와 품질 상태 계산을 schema-version aware 방식으로 정리한다
    - 구버전 `as_of` 캐시 마이그레이션, ISO 날짜 왕복, `quality_status` 계산, anomaly 승격 로직을 한 경로로 모은다.
    - Runtime Cache는 fetch 재사용과 전일 비교 전용으로 남기고 영구 저장소 책임은 분리한다.
    - _Requirements: 2.5, 3.4, 8.1, 8.2, 8.3, 9.1, 9.2, 14.2_
  - [ ] 1.3 모델/캐시/품질 상태 회귀 테스트를 보강한다
    - 테스트 파일: `tests/test_btc_etf_official.py`
    - `as_of -> as_of_date` 마이그레이션, ISO 직렬화 왕복, `official_html -> degraded`, invalid numeric field -> `critical` 승격을 고정한다.
    - _Requirements: 2.5, 8.1, 8.2, 8.3, 9.1, 9.2_

- [ ] 2. 공식 소스 우선 정책과 issuer별 선택 매트릭스를 공용 로직으로 정리한다
  - [ ] 2.1 `src/morning_brief/data/sources/btc_etf_official.py`에 issuer별 source selection helper를 도입한다
    - 공식 구조화 데이터와 HTML fallback을 분리하고, JSON/CSV 세부 우선순위는 ticker별 매트릭스로 관리한다.
    - PDF는 명시적으로 배제하고, 비공식 내부 API와 커뮤니티 경로는 primary 저장 대상에서 제외한다.
    - _Requirements: 1.1, 1.2, 1.3, 4.1, 5.1, 6.1, 7.1_
  - [ ] 2.2 공식 도메인 검증과 source metadata 부여를 강제한다
    - `domain_utils`와 연동해 issuer whitelist 밖 URL은 즉시 실패시키고, 성공 레코드에는 `source_url`, `source_type`, `source_format`, `parse_method`, `source_file_url`을 채운다.
    - _Requirements: 1.4, 2.1, 2.4, 10.1_
  - [ ] 2.3 소스 선택/도메인 검증 테스트를 추가한다
    - 테스트 파일: `tests/test_btc_etf_official.py`
    - ticker별 우선순위, PDF 배제, 비공식 URL 차단, structured source가 있을 때 HTML로 대체되지 않는 성질을 검증한다.
    - _Requirements: 1.1, 1.2, 1.4, 4.1, 5.1, 6.1, 7.1_

- [ ] 3. IBIT와 BITB 파서를 구조화 데이터 우선 기준으로 개편한다
  - [ ] 3.1 IBIT 파서에 CSV/JSON 우선 경로와 파생값 계산을 추가한다
    - `parse_ibit_snapshot`와 관련 fetch 경로에서 CSV 다운로드, 페이지 구조화 JSON, HTML fallback 순으로 시도한다.
    - `basket_bitcoin_amount / 40_000` 기반 `bitcoin_per_share`, `total_btc` 계산을 표준 스냅샷에 맞게 유지한다.
    - _Requirements: 4.1, 4.2, 4.3, 8.1, 8.2_
  - [ ] 3.2 BITB 파서를 공식 다운로드 + `__NEXT_DATA__` + HTML fallback 순으로 정리한다
    - 공식 다운로드가 있으면 1순위로 사용하고, 없을 때만 `__NEXT_DATA__`를 사용하도록 파싱 경계를 분리한다.
    - 구조화 payload에서 추출한 필드가 충분할 때만 `quality_status="ok"`를 부여한다.
    - _Requirements: 5.1, 5.2, 5.3, 8.1, 8.2_
  - [ ] 3.3 IBIT/BITB 회귀 테스트를 보강한다
    - 테스트 파일: `tests/test_btc_etf_official.py`
    - IBIT의 파생값 계산, BITB의 structured payload 우선 사용, structured source 부족 시 HTML fallback 강등을 고정한다.
    - _Requirements: 4.2, 4.3, 5.2, 5.3_

- [ ] 4. Grayscale/FBTC 수집과 reference-only 경계를 구현한다
  - [ ] 4.1 Grayscale 공용 파서에 구조화 다운로드 우선 경로와 레이블 수정 로직을 추가한다
    - `_parse_grayscale_snapshot`, `parse_gbtc_snapshot`, `parse_btc_mini_snapshot`에서 구조화 다운로드(XLSX 포함) → HTML fallback 순으로 정리한다.
    - `TOTAL BITCOIN IN FUND` 레이블, 429 처리, 필드 매핑을 공용화한다.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.3_
  - [ ] 4.2 FBTC 파서와 reference-only 처리 경계를 구현한다
    - `digital.fidelity.com` 경로에 대해 JSON/CSV 우선, HTML fallback, `total_btc` 부재 시 degraded/critical 분기, `estimated_total_btc` 분리 저장 규칙을 추가한다.
    - 공식 원천 수집 실패 시 primary snapshot을 만들지 않고 reference-only 상태로만 남긴다.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 10.4_
  - [ ] 4.3 Grayscale/FBTC 회귀 테스트를 추가한다
    - 테스트 파일: `tests/test_btc_etf_official.py`, `tests/test_market_btc_official_flow.py`
    - 잘못된 Grayscale 레이블 거부, structured file -> HTML fallback, FBTC HTML failure -> primary 미생성, reference-only 분기를 검증한다.
    - _Requirements: 6.4, 6.5, 7.3, 7.4, 10.4_

- [ ] 5. Checkpoint - ETF 파서 기반 테스트 통과 확인
  - [ ] 5.1 `pytest tests/test_btc_etf_official.py tests/test_market_btc_official_flow.py -q` 실행 결과를 기록한다
    - issuer별 source selection, 품질 상태, reference-only 경계가 기대대로 고정됐는지 확인한다.
    - _Requirements: 1.1, 4.1, 5.1, 6.5, 7.3, 10.4_

- [ ] 6. Bronze/Silver/Gold 저장 계층과 schema versioning을 도입한다
  - [ ] 6.1 ETF raw/normalized/primary 저장용 인터페이스와 스키마를 추가한다
    - `src/morning_brief/data/` 하위에 Bronze Storage, Silver Repository, Gold Repository 책임을 나누는 모듈을 도입한다.
    - Bronze에는 raw payload + checksum + fetch metadata, Silver에는 표준 필드 레코드, Gold에는 `ticker + as_of_date` 단일 primary snapshot을 저장한다.
    - _Requirements: 3.1, 3.2, 3.3, 14.2, 14.5_
  - [ ] 6.2 Silver/Gold 집계 우선순위와 멱등 upsert 규칙을 구현한다
    - 동일 입력 checksum 재처리는 no-op 또는 upsert로 처리하고, Gold는 issuer별 우선순위로 단일 primary를 선택한다.
    - reference-only 레코드는 primary 테이블과 분리한다.
    - _Requirements: 3.3, 10.1, 10.3, 14.3, 14.4_
  - [ ] 6.3 저장 계층 단위 테스트와 fixture를 추가한다
    - 테스트 파일: `tests/test_market_btc_official_flow.py` 또는 신규 `tests/test_btc_etf_storage.py`
    - Bronze 원문 없을 때 Silver/Gold skip, 동일 checksum 재처리 멱등성, reference-only 분리 저장을 검증한다.
    - _Requirements: 3.5, 10.1, 10.3, 14.3, 14.4_

- [ ] 7. 시장 브리핑 통합 경로와 aggregator 분리를 마무리한다
  - [ ] 7.1 `src/morning_brief/data/market.py`에서 Gold primary snapshot만 소비하도록 통합 경로를 조정한다
    - total BTC/AUM 집계에서 `critical` 또는 aggregator/source-less 데이터를 제외하고, reference-only 상태를 브리핑 note/로그로만 전달한다.
    - _Requirements: 2.2, 8.4, 10.2, 10.4_
  - [ ] 7.2 실행 추적성과 구조화 로그를 추가한다
    - `run_id`, `etf.run_summary`, `etf.collection_quality`, `etf.reference_only_snapshot`를 Bronze/Silver/Gold와 observer 이벤트에 공통 반영한다.
    - _Requirements: 8.5, 10.4, 14.1, 14.6_
  - [ ] 7.3 시장 통합 회귀 테스트를 추가한다
    - 테스트 파일: `tests/test_market_btc_official_flow.py`
    - Gold primary만 브리핑 집계에 반영되는지, aggregator-only 상태에서 합계가 오염되지 않는지 검증한다.
    - _Requirements: 10.2, 10.4, 14.6_

- [ ] 8. Checkpoint - ETF 저장/통합 경로 검증
  - [ ] 8.1 ETF 수집 관련 테스트 묶음과 좁은 범위 검증 명령을 실행한다
    - `pytest tests/test_btc_etf_official.py tests/test_market_btc_official_flow.py -q`
    - 필요 시 저장 계층 테스트를 함께 실행해 Bronze/Silver/Gold 및 reference-only 경계가 유지되는지 확인한다.
    - _Requirements: 3.3, 10.1, 10.2, 14.3, 14.4_

- [ ] 9. Binance 선물 지표와 Lag-1 조인을 완성한다
  - [ ] 9.1 `src/morning_brief/analysis/sentiment_join/sources/futures.py`를 Requirement 기준으로 정리한다
    - Binance funding/OI 공식 API를 primary로 사용하고, 실패 시 aggregator fallback은 source_type 태깅과 NaN 채움 정책을 유지한다.
    - 일별 funding은 8시간 3건 합산, OI는 `sumOpenInterestValue` 기준으로 집계한다.
    - _Requirements: 11.1, 11.2, 11.4, 11.5_
  - [ ] 9.2 `src/morning_brief/analysis/sentiment_join/join.py`에 Lag-1 파생 컬럼 조인을 고정한다
    - `funding_rate_lag1`, `oi_change_pct_lag1` 생성과 누락 시 NaN 유지 규칙을 merge 경로에 통합한다.
    - _Requirements: 11.3, 11.4_
  - [ ] 9.3 선물 지표/조인 테스트를 추가한다
    - 테스트 파일: 신규 `tests/analysis/test_sentiment_join/test_futures.py`, 기존 `tests/analysis/test_sentiment_join/test_join.py`
    - funding 합산 방식, OI 추출, Lag-1 방향, 소스 실패 시 NaN 채움을 검증한다.
    - _Requirements: 11.2, 11.3, 11.4_

- [ ] 10. ADF·Granger 통계 검정 모듈을 파이프라인에 연결한다
  - [ ] 10.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py`에서 ADF/Granger 실행과 예외 격리를 구현한다
    - `btc_log_return`만 분석 대상에 사용하고, 행 수 부족 또는 개별 검정 예외는 warning 로그로만 처리한다.
    - 유의미한 결과는 구조화 로그와 Parquet schema metadata의 `sentiment_join_stats` JSON 요약에 포함한다.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6, 12.7_
  - [ ] 10.2 통계 검정 테스트를 추가한다
    - 테스트 파일: 신규 `tests/analysis/test_sentiment_join/test_statistical_tests.py`
    - insufficient rows skip, predictor/target 순서, significant result logging, `sentiment_join_stats` 메타데이터 직렬화, 예외 격리 동작을 검증한다.
    - _Requirements: 12.3, 12.4, 12.6, 12.7_

- [ ] 11. VIF/PCA 하이브리드 지수와 스키마 확장을 마무리한다
  - [ ] 11.1 `src/morning_brief/analysis/sentiment_join/hybrid_index.py`와 `validate.py`를 Requirement 기준으로 정리한다
    - 후보 변수 존재 여부 필터링, VIF 반복 제거, 설명분산 80% 기준 PCA, `hybrid_index` 추가, 변수 부족 시 NaN 채움 규칙을 구현한다.
    - `validate.py`, `storage.py`, `pipeline.py`가 신규 컬럼과 메타데이터를 일관되게 처리하도록 연결한다.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_
  - [ ] 11.2 하이브리드 지수/검증 스키마 테스트를 추가한다
    - 테스트 파일: 신규 `tests/analysis/test_sentiment_join/test_hybrid_index.py`, 기존 `tests/analysis/test_sentiment_join/test_validate.py`, `tests/analysis/test_sentiment_join/test_pipeline.py`
    - VIF 제거 수렴, feature 부족/row 부족 시 NaN, strict schema 유지, pipeline output에 `hybrid_index`와 메타데이터가 반영되는지 검증한다.
    - _Requirements: 13.2, 13.4, 13.6, 13.7_

- [ ] 12. Checkpoint - Sentiment Join 확장 검증
  - [ ] 12.1 Sentiment Join 관련 테스트를 집중 실행한다
    - `pytest tests/analysis/test_sentiment_join -q`
    - 선물 지표, 통계 검정, 하이브리드 지수, schema validation이 기존 조인 파이프라인과 함께 안정적으로 동작하는지 확인한다.
    - _Requirements: 11.4, 12.7, 13.7_

- [ ] 13. 의존성/문서/최종 검증 경로를 정리한다
  - [ ] 13.1 분석 배치 전용 의존성과 운영 문서를 갱신한다
    - `requirements-analysis.txt`에 `statsmodels`, `scikit-learn`을 추가하고 필요 시 구조화 다운로드 파싱용 의존성을 문서화한다.
    - 저장 계층, reference-only 정책, 실행 검증 순서를 `README.md` 또는 가장 가까운 운영 문서에 반영한다.
    - _Requirements: 6.1, 11.5, 12.5, 13.5_
  - [ ] 13.2 최종 회귀 검증 명령을 수행하고 결과를 정리한다
    - 권장 순서: `make fmt` → `make lint` → `make test` → `make typecheck`
    - 대규모 검증 전에 좁은 범위 pytest가 모두 통과하는지 확인하고, 실패 시 원인 분석을 남긴다.
    - _Requirements: 14.6_
