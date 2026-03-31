# Requirements Document

## Introduction

현재 `src/morning_brief/prompts` 아래 템플릿들은 대부분 사용되고 있지만, 실제 프롬프트 자산 관리 방식은 공용 Jinja 렌더, Sonar 직접 로딩, 코드 상수 하드코딩으로 나뉘어 있다. 이 구조는 운영자가 프롬프트 원천을 한 번에 파악하기 어렵고, 핵심 계약이 여러 파일에 중복되어 변경 시 드리프트 위험이 크다. 이번 작업의 목적은 프롬프트 자산의 관리 체계를 일관되게 정리하되, 기존 브리프 생성·검수·재작성·웹검색·Sonar·공개 뉴스 해설 동작은 유지하는 것이다.

## Glossary

**공용 프롬프트 렌더 경로**: `src/morning_brief/prompting.py`를 통해 Jinja 템플릿을 렌더링하는 표준 경로

**프롬프트 거버넌스**: 프롬프트 자산의 위치, 버전, 렌더링 방식, 추적 가능성을 일관되게 관리하는 규칙

**브리프 핵심 계약**: 브리프 섹션 구조, 숫자 사용 규칙, 한국어 문체, 뉴스 해설 규칙처럼 생성·검수·재작성이 함께 따라야 하는 공통 규칙

**직접 로딩 프롬프트**: 공용 렌더 경로를 거치지 않고 파일을 직접 읽거나 문자열 치환으로 조합하는 프롬프트

**하드코딩 프롬프트**: 코드 상수 문자열로 소스 파일 내부에 정의된 프롬프트

## Requirements

### Requirement 1: 프롬프트 자산 인벤토리와 사용 경로를 일관되게 관리한다

**User Story:**  
As a 유지보수 담당자,  
I want 모든 프롬프트 자산의 실제 사용 경로를 한눈에 추적하고 싶다,  
so that 미사용 템플릿, 동적 로딩, 하드코딩 프롬프트를 혼동하지 않고 안전하게 변경할 수 있다.

#### Acceptance Criteria

1. WHEN 유지보수 담당자가 프롬프트 자산을 점검할 때, THE prompt system SHALL 각 프롬프트 파일 또는 프롬프트 상수가 어떤 런타임 경로에서 사용되는지 식별 가능하게 제공한다.
2. WHEN `src/morning_brief/prompts` 아래 템플릿이 존재할 때, THE prompt system SHALL 해당 템플릿이 정적 참조인지 동적 참조인지 구분 가능한 구조를 제공한다.
3. IF 특정 프롬프트가 동적 이름 조합 또는 직접 로딩으로 사용되는 경우, THEN THE prompt system SHALL 그 사용 관계를 운영자가 놓치지 않도록 명시적인 매핑 지점을 유지한다.
4. WHEN 프롬프트 자산을 검토할 때, THEN THE system SHALL 실제 사용되는 프롬프트와 사용되지 않는 프롬프트를 구분할 수 있어야 한다.

### Requirement 2: Sonar 프롬프트를 공용 렌더 거버넌스 안으로 통합한다

**User Story:**  
As a 프롬프트 운영자,  
I want Sonar 프롬프트도 다른 프롬프트와 같은 렌더 정책을 따르길 원한다,  
so that 버전 관리, 추적, 변경 검증을 같은 방식으로 수행할 수 있다.

#### Acceptance Criteria

1. WHEN Sonar 토픽 요약 또는 Sonar 맥락 분석 프롬프트가 렌더링될 때, THE prompt system SHALL 공용 프롬프트 렌더 경로와 호환되는 방식으로 처리한다.
2. WHEN Sonar 프롬프트가 렌더링될 때, THE prompt system SHALL `prompt_template_version` 기반 추적과 동일한 거버넌스 규칙을 적용할 수 있어야 한다.
3. IF Sonar 프롬프트에 동적 변수(`time_range`, 기사 목록 등)가 필요한 경우, THEN THE prompt system SHALL 문자열 직접 치환이 아니라 표준 템플릿 컨텍스트 방식으로 이를 주입할 수 있어야 한다.
4. WHEN Sonar 관련 템플릿을 검토할 때, THE prompt system SHALL 토픽 템플릿과 컨텍스트 템플릿의 사용 경로가 정적 분석과 운영 문맥에서 모두 이해 가능해야 한다.
5. WHEN 기존 Sonar 요약 기능이 실행될 때, THEN THE system SHALL 현재 지원 토픽(`macro`, `us_equity`, `ai_bigtech`, `bitcoin`) 동작을 계속 유지해야 한다.
6. WHEN Sonar 프롬프트가 OpenAI 또는 Perplexity 호출 직전 조합될 때, THE prompt system SHALL 시스템 지시와 사용자 입력을 현재 호출부가 계속 사용할 수 있는 구조로 분리해서 제공해야 한다.

### Requirement 3: 브리프 핵심 계약의 원천을 단일화한다

**User Story:**  
As a 프롬프트 설계자,  
I want 생성·검수·재작성 프롬프트가 같은 핵심 계약을 공유하길 원한다,  
so that 섹션 구조나 숫자 규칙을 바꿀 때 결과가 서로 어긋나지 않게 할 수 있다.

#### Acceptance Criteria

1. WHEN 브리프 섹션 구조, BTC 절대값 규칙, 뉴스 한국어 의역 규칙, 쉬운 한국어 문체 규칙이 정의될 때, THE prompt system SHALL 해당 핵심 계약의 단일 원천을 유지해야 한다.
2. WHEN 생성 프롬프트, 검수 프롬프트, 재작성 프롬프트가 같은 계약을 필요로 할 때, THE prompt system SHALL 중복 복사보다 공유 가능한 구조를 우선 사용해야 한다.
3. IF 공통 계약과 각 단계별 전용 규칙이 함께 필요한 경우, THEN THE prompt system SHALL 공통 계약과 단계 전용 지시를 구분해서 관리해야 한다.
4. WHEN 핵심 계약이 변경될 때, THE prompt system SHALL 생성·검수·재작성 경로 간 규칙 불일치가 발생하지 않도록 유지해야 한다.
5. WHEN 브리프 검수 또는 재작성이 수행될 때, THEN THE system SHALL 현재 생성 브리프가 따르는 핵심 섹션 구조와 숫자 규칙을 계속 검증할 수 있어야 한다.
6. WHEN 브리프 생성, 검수, 재작성 프롬프트를 정리할 때, THE prompt system SHALL 현재 코드가 기대하는 출력 구조와 검수 JSON 필드(`pass`, `structure_pass`, `issues`, `rewrite_needed`, `rewrite_guidance`)를 계속 유지해야 한다.

### Requirement 4: 과도하게 분리된 입력 템플릿을 정리한다

**User Story:**  
As a 프롬프트 유지보수 담당자,  
I want 입력 템플릿이 실제 역할이 있을 때만 분리되길 원한다,  
so that 관리 포인트만 늘어나는 형식적 템플릿을 줄일 수 있다.

#### Acceptance Criteria

1. WHEN 입력 템플릿이 별도 파일로 존재할 때, THE prompt system SHALL 해당 파일이 입력 포장, 역할 설명, 컨텍스트 구조화 중 최소 하나의 실질적 역할을 가져야 한다.
2. IF 입력 템플릿이 단순 변수 출력만 수행하는 pass-through 구조인 경우, THEN THE prompt system SHALL 이를 호출부 통합 또는 의미 있는 입력 구조로 정리해야 한다.
3. WHEN 프롬프트 파일을 분리 유지하기로 결정할 때, THE prompt system SHALL 왜 별도 파일이 필요한지 코드와 문서 구조에서 이해 가능해야 한다.

### Requirement 5: 하드코딩 프롬프트와 템플릿 기반 프롬프트의 관리 정책을 명확히 한다

**User Story:**  
As a 운영자,  
I want 어떤 프롬프트가 템플릿 파일에 있어야 하고 어떤 프롬프트가 코드 상수로 남아도 되는지 기준이 명확하길 원한다,  
so that 새 프롬프트를 추가할 때 구조가 다시 제각각으로 퍼지지 않게 할 수 있다.

#### Acceptance Criteria

1. WHEN 새로운 장문 프롬프트가 추가되거나 기존 장문 프롬프트를 수정할 때, THE prompt system SHALL 템플릿 파일 기반 관리와 코드 상수 기반 관리 중 허용 기준을 명확히 가져야 한다.
2. WHEN 기존 하드코딩 프롬프트를 검토할 때, THE prompt system SHALL 중앙 템플릿 정책에 맞춰 이전할 대상과 예외로 남길 대상을 구분할 수 있어야 한다.
3. IF 특정 프롬프트가 캐싱, 성능, SDK 제약 때문에 코드 상수로 유지되어야 하는 경우, THEN THE prompt system SHALL 그 예외 사유를 코드 구조에서 이해 가능하게 유지해야 한다.
4. WHEN 운영자가 `src/morning_brief/prompts`를 볼 때, THEN THE system SHALL 이것이 전체 프롬프트 자산의 전부인지 일부인지 오해하지 않도록 일관된 관리 정책을 제공해야 한다.
5. WHEN 코드 상수 프롬프트를 예외로 유지할 때, THE prompt system SHALL 해당 예외를 파일 인접 코드 또는 운영 문서에서 식별 가능하게 설명해야 한다.

### Requirement 6: 기존 프롬프트 동작과 출력 계약을 보존한다

**User Story:**  
As a 제품 운영자,  
I want 프롬프트 관리 구조를 정리해도 실제 브리프 생성 기능은 깨지지 않길 원한다,  
so that 구조 개선이 사용자 결과 품질이나 파이프라인 안정성을 해치지 않게 할 수 있다.

#### Acceptance Criteria

1. WHEN 프롬프트 자산 구조가 정리된 후에도, THE system SHALL 브리프 생성, 브리프 검수, 브리프 재작성, 웹 검색 백필, 공개 뉴스 해설, Sonar 요약, Sonar 맥락 분석 동작을 계속 지원해야 한다.
2. WHEN 동일한 입력 데이터와 동일한 모델 설정이 주어질 때, THE system SHALL 구조 정리 전후에 각 프롬프트 경로의 출력 계약을 유지해야 한다.
3. IF 프롬프트 자산 위치나 렌더 경로가 변경되는 경우, THEN THE system SHALL 호출부에서 런타임 오류 없이 새 구조를 사용할 수 있어야 한다.
4. WHEN 구조 정리 후 검증을 수행할 때, THE verification plan SHALL 최소한 프롬프트 렌더 경로별 테스트 또는 회귀 검증을 포함해야 한다.
5. WHEN prompt template versioning이 사용되는 경로를 정리할 때, THEN THE system SHALL 기존 버전 추적 의미를 유지해야 한다.
6. WHEN 공개 뉴스 해설과 웹 검색 백필 프롬프트를 정리할 때, THE system SHALL 현재 코드가 기대하는 JSON schema 기반 응답 계약을 유지해야 한다.
