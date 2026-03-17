# 구현 계획: X 레지스트리 확장

## 개요

`official_signal_registry.json`에 9개 신규 엔티티를 추가하고, `MAX_X_HANDLES_PER_GROUP` 상수를 10에서 12로 변경한다. 기존 테스트를 확장하고 Hypothesis 속성 기반 테스트를 추가하여 데이터 무결성을 검증한다.

## Tasks

- [x] 1. 레지스트리 JSON에 신규 엔티티 추가 및 상수 변경
  - [x] 1.1 `official_signal_registry.json`에 ai_bigtech_primary 그룹 4개 엔티티 추가
    - Google (entity_id: `google`, x_handle: `Google`, ticker: `GOOGL`, x_search_priority: 2)
    - Amazon (entity_id: `amazon`, x_handle: `AmazonNews`, ticker: `AMZN`, x_search_priority: 2)
    - Tesla (entity_id: `tesla`, x_handle: `Tesla`, ticker: `TSLA`, x_search_priority: 2)
    - Broadcom (entity_id: `broadcom`, x_handle: `Broadcom`, ticker: `AVGO`, x_search_priority: 2)
    - 모든 엔티티는 `OfficialSignalEntity` 스키마의 15개 필드를 포함해야 함
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.1, 5.3, 5.4_

  - [x] 1.2 `official_signal_registry.json`에 crypto_and_etf 그룹 3개 엔티티 추가
    - VanEck (entity_id: `vaneck`, x_handle: `vaneck_us`, ticker: `HODL`, x_search_priority: 2)
    - Franklin Templeton (entity_id: `franklin_templeton`, x_handle: `FTI_US`, ticker: `EZBC`, x_search_priority: 2)
    - Invesco (entity_id: `invesco`, x_handle: `InvescoUS`, ticker: `BTCO`, x_search_priority: 2)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.1, 5.3, 5.4_

  - [x] 1.3 `official_signal_registry.json`에 macro_and_equity 그룹 2개 엔티티 추가
    - White House (entity_id: `white_house`, x_handle: `WhiteHouse`, category: `macro_regulator`, x_search_priority: 1)
    - POTUS (entity_id: `potus`, x_handle: `POTUS`, category: `macro_regulator`, x_search_priority: 1)
    - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.3, 5.4_

  - [x] 1.4 `official_signal_registry.py`에서 `MAX_X_HANDLES_PER_GROUP`를 10에서 12로 변경
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 2. 체크포인트 - 데이터 변경 검증
  - `registry_validation_errors()`가 빈 리스트를 반환하는지 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. 단위 테스트 추가
  - [x] 3.1 `tests/test_official_signal_registry.py`에 신규 엔티티 존재 확인 테스트 추가
    - 9개 신규 entity_id가 모두 레지스트리에 존재하는지 확인
    - 각 신규 엔티티의 `x_verified=true`, `enabled=true`, 올바른 `x_search_group` 및 `x_search_priority` 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 3.2, 5.2, 5.3, 5.4_

  - [x] 3.2 `tests/test_official_signal_registry.py`에 그룹별 핸들 수 및 상수 확인 테스트 추가
    - `grouped_verified_x_handles()`에서 `ai_bigtech_primary` 핸들 수 = 9, `crypto_and_etf` = 10, `macro_and_equity` = 11 확인
    - `MAX_X_HANDLES_PER_GROUP` 값이 12인지 확인
    - _Requirements: 1.5, 2.4, 3.3, 4.1, 4.3_

  - [x] 3.3 `tests/test_official_signal_registry.py`에 기존 핸들 보존 확인 테스트 추가
    - 기존 25개 엔티티의 핸들이 모두 그대로 포함되는지 확인
    - _Requirements: 6.1, 6.2_

  - [ ]* 3.4 `tests/test_official_signal_registry.py`에 그룹 한도 초과 테스트 업데이트
    - 기존 `test_registry_validation_errors_when_group_exceeds_limit` 테스트가 새 상수(12)에 맞게 동작하는지 확인
    - 13개 엔티티로 한도 초과 시 오류가 발생하는지 확인
    - _Requirements: 4.2_

- [ ] 4. 속성 기반 테스트 추가 (Hypothesis)
  - [ ]* 4.1 Property 1: 레지스트리 엔티티 스키마 완전성 테스트 작성
    - **Property 1: 레지스트리 엔티티 스키마 완전성**
    - Hypothesis로 랜덤 엔티티를 생성하여 레지스트리에 추가한 후, 모든 엔티티가 15개 필수 필드를 포함하는지 검증
    - `@settings(max_examples=100)` 이상으로 설정
    - **Validates: Requirements 5.1**

  - [ ]* 4.2 Property 2: entity_id 고유성 테스트 작성
    - **Property 2: entity_id 고유성**
    - Hypothesis로 랜덤 entity_id를 가진 엔티티들을 생성하여 레지스트리에 추가한 후, 모든 entity_id가 고유한지 검증
    - `@settings(max_examples=100)` 이상으로 설정
    - **Validates: Requirements 5.2**

  - [ ]* 4.3 Property 3: JSON 라운드트립 테스트 작성
    - **Property 3: JSON 라운드트립**
    - Hypothesis로 랜덤 엔티티 데이터로 레지스트리 JSON을 구성한 후, `json.loads(json.dumps(data))`가 원본과 동일한지 검증
    - `@settings(max_examples=100)` 이상으로 설정
    - **Validates: Requirements 6.3**

- [x] 5. 최종 체크포인트 - 전체 검증
  - `make check` 실행하여 모든 테스트, 린트, 타입 체크 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택 사항이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 추적 가능성을 위해 특정 요구사항을 참조함
- 체크포인트를 통해 점진적 검증 수행
- 속성 테스트는 보편적 정확성 속성을 검증하고, 단위 테스트는 구체적 예시와 엣지 케이스를 검증함
