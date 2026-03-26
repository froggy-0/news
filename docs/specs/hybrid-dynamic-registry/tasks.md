# Implementation Plan

- [ ] 1. 기존 레지스트리 구조 분석 및 Base Layer 인터페이스 정의
  - `official_signal_registry.json` 파일 구조 분석 (그룹 목록, 핸들 형식, 메타데이터)
  - 기존 채널 데이터 수집 로직에서 레지스트리를 로드하는 진입점 파악
  - Merged Registry 파일 경로 및 파일명 컨벤션 결정
  - Base Layer 로드 함수 인터페이스 정의
  - _Requirements: 1.1, 1.2, 3.3, 3.4_

- [ ] 2. Grok API 클라이언트 모듈 구현
  - `grok-4.1-fast` 모델 호출 함수 작성
  - `response_format: {"type": "json_object"}` Structured Outputs 설정
  - `x-grok-conv-id: registry-update-daily-2026` HTTP 헤더 고정 설정
  - Responses API 사용 시 `prompt_cache_key` 필드 추가
  - API 호출 실패 시 예외를 상위로 전파 (Base Layer fallback 트리거용)
  - _Requirements: 2.2, 5.1, 5.2_

- [ ] 3. System Prompt 및 User Prompt 작성
  - System Prompt 작성 (역할 정의, 그룹 목록, JSON 출력 형식 명세, Few-shot 예시)
    - 캐싱을 위해 내용을 고정 유지, 날짜·동적 정보 미포함
  - User Prompt 템플릿 작성 (날짜 등 최소 동적 정보만 포함)
  - messages 배열 구성 함수 작성 (System Prompt → User Prompt 순서 고정)
  - messages 수정·삭제·재정렬 금지 로직 검증
  - _Requirements: 5.3, 5.4, 5.5_

- [ ] 4. X Search Tool 호출 전략 구현 (쿼리 방식 분기)
  - 그룹별 핸들 수에 따른 쿼리 방식 분기 함수 작성
    - ≤10개: `allowed_x_handles` 파라미터 사용
    - >10개: `from:handle1 OR from:handle2 ...` OR 쿼리 사용
  - `allowed_x_handles`와 OR 쿼리 mutually exclusive 보장 로직 추가
  - Parallel Tool Calling 활용하여 모든 그룹을 단일 API 요청에서 처리
  - _Requirements: 2.3, 2.4, 4.1, 4.2, 4.3_

- [ ] 5. Grok 응답 파싱 및 검증 모듈 구현
  - JSON 응답 파싱 함수 작성 (그룹별 핸들 목록 추출)
  - 파싱 실패 시 빈 결과 반환 (Base Layer fallback 안전 보장)
  - 핸들 형식 검증 (`@` 제거 등 정규화)
  - _Requirements: 1.2, 6.1_

- [ ] 6. Merge 로직 구현
  - Base Layer 핸들 우선 포함 함수 작성
  - Dynamic Layer 신규 핸들 추가 함수 작성 (Base에 없는 것만)
  - 그룹당 25~30개 상한 적용 함수 작성
    - Base가 상한 초과 시 Base 전체 유지 (상한은 신규 추가에만 적용)
  - Merged Registry 파일 저장 함수 작성
  - _Requirements: 1.3, 3.1, 3.2, 3.3_

- [ ] 7. 일 단위 업데이트 스케줄러 구현
  - 매일 새벽 실행 스케줄러 설정 (cron 또는 기존 스케줄러 활용)
  - 하루 1회 단일 Grok API 호출 제한 보장 (중복 실행 방지)
  - Grok API 장애 시 Base Layer fallback 처리 및 로깅
  - 업데이트 성공/실패 로그 기록
  - _Requirements: 2.1, 2.4, 6.1, 6.2_

- [ ] 8. 기존 채널 데이터 수집 로직 연결 (최소 변경)
  - 기존 수집 로직의 레지스트리 로드 경로를 Merged Registry 파일 경로로 변경
  - Merged Registry 파일이 없을 경우 Base Layer 직접 사용 (fallback)
  - 기존 수집 로직 내부는 변경하지 않음
  - _Requirements: 3.4, 1.2_

- [ ] 9. 커버리지 개선 검증
  - Apple 공식 계정, TSMC proxy(`@mingchikuo` 등)이 Dynamic Layer에 포함되는지 확인
  - AI/bigtech 그룹 외 다양한 그룹의 핸들 추천 품질 검토
  - 그룹당 핸들 수가 기존 10개에서 25~30개로 확대됐는지 확인
  - _Requirements: 8.1, 8.2_

- [ ] 10. 테스트 작성

  - [ ] 10.1 Merge 로직 단위 테스트
    - Base 핸들이 항상 포함되는지 테스트 (Property 1)
    - Grok 추천 신규 핸들만 추가되는지 테스트
    - 그룹당 상한 25~30개 적용되는지 테스트 (Property 5)
    - Base가 상한 초과 시 Base 전체 유지되는지 테스트
    - _Requirements: 1.3, 3.1, 3.2_

  - [ ] 10.2 쿼리 방식 분기 단위 테스트
    - ≤10개 그룹에서 `allowed_x_handles` 사용 확인 (Property 6)
    - >10개 그룹에서 OR 쿼리 사용 확인 (Property 6)
    - `allowed_x_handles`와 OR 쿼리 동시 미사용 확인 (mutually exclusive)
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 10.3 Prompt Caching 구조 단위 테스트
    - messages[0]이 항상 고정 System Prompt인지 확인 (Property 4)
    - x-grok-conv-id 헤더가 항상 고정값으로 설정되는지 확인 (Property 3)
    - User Prompt에 날짜 외 동적 정보가 없는지 확인
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 10.4 Fallback 동작 통합 테스트
    - Grok API 호출 실패 시 Base Layer만으로 수집 로직이 동작하는지 확인 (Property 2)
    - 파싱 오류 시에도 Base Layer 정상 사용 확인
    - _Requirements: 1.2, 6.1_

  - [ ] 10.5 기존 수집 로직 보존 테스트
    - Merged Registry 파일 사용 후 기존 채널 데이터 수집 결과가 동일한지 확인 (Property 7)
    - Merged Registry 파일 없을 시 Base Layer fallback 확인
    - _Requirements: 3.4, 1.2_

- [ ] 11. 운영 문서 작성
  - Hybrid Dynamic Registry 아키텍처 및 운영 가이드 문서화
  - Human-in-the-loop 검토 주기 적용 방법 안내
  - 비용 모니터링 방법 (Cached Input Tokens 확인 등) 안내
  - _Requirements: 7.1, 7.2_
