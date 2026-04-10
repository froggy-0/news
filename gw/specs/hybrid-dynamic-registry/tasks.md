# Implementation Plan

- [ ] 1. 기존 레지스트리 구조 분석 및 Base Layer 인터페이스 정의
  - `official_signal_registry.json` 파일 구조 분석 (그룹 목록, 핸들 형식, 메타데이터)
  - 기존 채널 데이터 수집 로직에서 레지스트리를 로드하는 진입점 파악
  - Runtime Merge 함수 인터페이스 정의 (`official_signal_registry.json` + `dynamic_signal_registry.json` 병합)
  - Base Layer 로드 함수 인터페이스 정의
  - _Requirements: 1.1, 1.2, 3.3, 3.4_

- [ ] 2. Grok API 클라이언트 모듈 구현
  - xai_sdk v1.10.0 이상으로 업그레이드 (`requirements.txt` / `pyproject.toml` 업데이트)
  - `grok-4-1-fast-non-reasoning` 모델 호출 함수 작성
  - xai_sdk gRPC 방식으로 클라이언트 초기화:
    `Client(api_key=api_key, metadata=(("x-grok-conv-id", "registry-update-daily-2026"),))`
  - `response_format: {"type": "json_object"}` Structured Outputs 설정
  - API 호출 실패 시 예외를 상위로 전파 (Base Layer fallback 트리거용)
  - _Requirements: 2.2, 5.1, 5.2_

- [ ] 3. System Prompt 및 User Prompt 작성
  - System Prompt 작성 (역할 정의, 그룹 목록, JSON 출력 형식 명세, Few-shot 예시)
    - 캐싱을 위해 내용을 고정 유지, 날짜·동적 정보 미포함
    - `x_verified: true` 인증 계정만 추천하도록 필수 조건 명시
    - 신뢰도 계층(기관/기업 공식 > 미디어 공식 > 전문가) 및 `trust_score`·`rationale` 출력 명시
  - User Prompt 템플릿 작성 (날짜 등 최소 동적 정보만 포함)
  - messages 배열 구성 함수 작성 (System Prompt → User Prompt 순서 고정)
  - messages 수정·삭제·재정렬 금지 로직 검증
  - `DynamicSignalEntity` TypedDict 정의 (6개 필드):
    ```python
    class DynamicSignalEntity(TypedDict):
        handle: str            # X 핸들 (@제외)
        x_search_group: str    # 소속 그룹 상수값 (예: "crypto_and_etf")
        x_search_priority: int # 항상 0으로 고정
        trust_score: int       # Grok 신뢰성 점수 (1~5)
        rationale: str         # Grok 추천 근거 문자열
        x_verified: bool       # 항상 True로 고정
    ```
  - _Requirements: 2.5, 2.6, 2.7, 4.2, 5.2, 5.3, 5.4_

- [ ] 4. x_search Tool 호출 전략 구현 (그룹당 순차 API 호출)
  - xai_sdk `x_search` 도구의 `allowed_x_handles`는 tool 등록 시 고정되므로, 그룹당 별도 API 요청으로 순차 실행하는 함수 작성 (`grok_official_signals.py` 패턴 참조)
  - 그룹당 핸들 수 상한 `_GROK_MAX_HANDLES = 10` 적용. `allowed_x_handles` 단독 사용 (max 10)
  - `from:handle1 OR from:handle2 ...` OR 쿼리 방식 사용 금지 (xAI 미지원)
  - 하루 1회 실행 제한 (N그룹 = N회 API 호출, 중복 실행 방지)
  - _Requirements: 4.1_

- [ ] 5. Grok 응답 파싱 및 검증 모듈 구현
  - JSON 응답 파싱 함수 작성 (그룹별 핸들 목록 추출)
  - `trust_score` (정수 1~5), `rationale` (문자열) 필드 파싱 및 스키마 검증
  - `trust_score < 3` 항목 제외 필터 구현
  - `x_verified: true` 이중 확인 — `list_verified_x_entities()` 통과 가능 여부 검증
  - 파싱 실패 시 빈 결과 반환 (Base Layer fallback 안전 보장)
  - 핸들 형식 검증 (`@` 제거 등 정규화)
  - _Requirements: 1.2, 2.5, 2.6, 2.7, 6.1, 8.1_

- [ ] 6. Dynamic Registry 저장 로직 구현
  - Base에 없는 신규 핸들만 Dynamic Layer로 추가하는 함수 작성
  - 그룹당 상한 `_GROK_MAX_HANDLES = 10` 적용. Dynamic(priority=0) 우선 정렬 후 슬라이스하며, Base 하위 priority 항목 탈락 허용 (Requirements 3.5)
  - Dynamic 엔티티 `x_search_priority = 0` 고정 설정 코드 구현
  - `x_verified: true`가 아닌 핸들은 저장 금지 (`dynamic_verified` 별도 필드 추가 금지)
  - 검증 통과한 결과를 `dynamic_signal_registry.json`에 자동 저장 (수동 승인 없음)
  - _Requirements: 1.3, 3.1, 3.2, 3.3, 8.1_

- [ ] 7. 일 단위 업데이트 스케줄러 구현
  - 매일 새벽 실행 스케줄러 설정 (cron 또는 기존 스케줄러 활용)
  - 하루 1회 단일 Grok API 호출 제한 보장 (중복 실행 방지)
  - Grok API 장애 시 Base Layer fallback 처리 및 로깅
  - 업데이트 성공/실패 로그 기록 (`cached_input_tokens` 포함)
  - _Requirements: 2.1, 2.4, 6.1, 6.2_

- [ ] 8. 기존 채널 데이터 수집 로직 연결 (Runtime Merge)
  - 기존 수집 로직의 레지스트리 로드를 런타임에 `official_signal_registry.json` + `dynamic_signal_registry.json` 두 파일을 병합하는 방식으로 변경. 별도 merged 파일 생성 없음
  - `dynamic_signal_registry.json` 파일 없을 경우 `official_signal_registry.json`만 사용 (fallback)
  - `load_official_signal_registry.cache_clear()` 호출로 캐시 무효화 처리
  - 기존 수집 로직 내부(sort, slice 등)는 변경하지 않음
  - _Requirements: 3.4, 1.2_

- [ ] 9. 커버리지 개선 검증
  - AI/bigtech 그룹 외 다양한 그룹의 핸들 추천 품질 검토
  - 그룹당 핸들 수가 `_GROK_MAX_HANDLES = 10` 상한 내에서 올바르게 적용됐는지 확인
  - `x_verified: true` 계정만 Dynamic Layer에 포함됐는지 확인
  - _Requirements: 8.1, 8.2_

- [ ] 10. 테스트 작성

  - [ ] 10.1 Merge 로직 단위 테스트
    - Base 핸들이 항상 포함되는지 테스트 (Property 1)
    - Grok 추천 신규 핸들만 추가되는지 테스트
    - 그룹당 상한 10개(`_GROK_MAX_HANDLES = 10`) 적용되는지 테스트 (Property 5)
    - Dynamic+Base 합계 초과 시 Base 하위 priority 항목 탈락 허용 확인 (Property 5, Requirements 3.5)
    - _Requirements: 1.3, 3.1, 3.2_

  - [ ] 10.2 x_verified 필터 이중 검증 테스트
    - Grok 프롬프트 단계에서 비인증 계정이 추천 제외되는지 확인 (Property 6)
    - `list_verified_x_entities()` 필터 통과 여부 확인 (Property 6)
    - `x_verified: false` 핸들이 `dynamic_signal_registry.json`에 저장되지 않는지 확인
    - _Requirements: 2.5, 8.1_

  - [ ] 10.3 Prompt Caching 구조 단위 테스트
    - messages[0]이 항상 고정 System Prompt인지 확인 (Property 4)
    - gRPC metadata `x-grok-conv-id` 값이 항상 고정값으로 설정되는지 확인 (Property 3)
    - User Prompt에 날짜 외 동적 정보가 없는지 확인
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 10.4 Fallback 동작 통합 테스트
    - Grok API 호출 실패 시 Base Layer만으로 수집 로직이 동작하는지 확인 (Property 2)
    - 파싱 오류 시에도 Base Layer 정상 사용 확인
    - _Requirements: 1.2, 6.1_

  - [ ] 10.5 기존 수집 로직 보존 테스트
    - Runtime Merge 적용 후 기존 채널 데이터 수집 결과가 동일한지 확인 (Property 8)
    - `dynamic_signal_registry.json` 파일 없을 시 Base Layer fallback 확인 (Property 8)
    - OR 쿼리(`from:handle OR ...`) 코드가 어디에도 존재하지 않는지 확인
    - _Requirements: 3.4, 1.2_

  - [ ] 10.6 신뢰성 스키마 파싱 테스트
    - `trust_score`, `rationale` 필드가 JSON 응답에 존재하고 올바른 타입인지 확인 (Property 9)
    - `trust_score < 3` 항목이 Dynamic Registry에서 제외되는지 확인 (Property 9)
    - 스키마 필드 누락 시 해당 핸들이 저장되지 않는지 확인
    - _Requirements: 2.6, 2.7_

  - [ ] 10.7 x_search_priority 정렬 검증 테스트
    - Dynamic 엔티티의 `x_search_priority`가 `0`으로 설정됐는지 확인 (Property 7)
    - `sorted(key=x_search_priority ASC)[:12]` 정렬 결과에서 Dynamic 엔티티가 Base 엔티티보다 앞에 오는지 확인 (Property 7)
    - _Requirements: 3.1_

- [ ] 11. 운영 문서 작성
  - Fully Automated Dynamic Registry 아키텍처 및 운영 가이드 문서화
  - 자동 갱신 실행 로그 확인 방법 안내
  - Cached Input Tokens 비용 모니터링 방법 안내 (`cached_input_tokens` 로그 필드)
  - `dynamic_signal_registry.json` 갱신 실패 시 Base Layer fallback 확인 방법 안내
  - _Requirements: 7.1_
