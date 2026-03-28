# Requirements Document

## Introduction

현재 브리핑 메일 발송 대상은 GitHub 환경변수 `GMAIL_RECIPIENT`에 수동으로 관리되고 있어, 구독 추가, 구독 해지, 상태 변경이 모두 운영자 수작업에 의존한다. 이 구조는 운영 실수를 유발하기 쉽고, 구독자 관리 기능을 확장하기에도 불편하다.

이를 해결하기 위해 발송 대상의 source of truth를 데이터베이스로 이전하고, 사용자는 공개 프론트에서 구독 신청 및 해지를 수행하며, 프론트는 항상 프로젝트의 자체 API만 호출하도록 한다. 저장소 구현은 우선 Supabase를 사용하되, 애플리케이션 계층은 Supabase에 직접 종속되지 않도록 분리하여 이후 다른 서버/저장소로 이전 가능하게 설계한다.

이번 범위는 단일 newsletter 구독 흐름에 한정하며, double opt-in 기반 구독 등록, 실제 unsubscribe URL/토큰 처리, Cloudflare API 계층, confirmation 메일의 Cloudflare API 직접 발송, newsletter의 수신자별 개별 발송 전환을 포함한다.

## Glossary

**newsletter**: 현재 프로젝트가 발송하는 단일 아침 브리핑 메일
**subscriber**: newsletter 수신 대상 이메일 주체
**subscription status**: 구독 상태. `pending`, `active`, `unsubscribed`, `bounced` 중 하나
**double opt-in**: 사용자가 이메일 입력 후 확인 메일의 링크를 클릭해야 최종 활성화되는 구독 절차
**subscription token**: 구독 확인 또는 해지 처리를 위해 발급되는 일회성 토큰
**subscription API**: 프론트가 호출하는 Cloudflare 기반 API 계층
**subscription repository**: 구독자 저장/조회 구현 추상화 계층. 초기 구현은 Supabase adapter 사용

## Requirements

### Requirement 1: 발송 대상 관리 기준을 환경변수에서 구독 저장소로 전환해야 한다

**User Story:**
As an operator,
I want newsletter recipients to be loaded from a managed subscription repository instead of a GitHub environment variable,
so that recipient changes can be handled without manual secret edits.

#### Acceptance Criteria

1. WHEN 파이프라인이 newsletter 발송 대상을 준비할 때, THE 메일 발송 계층 SHALL `GMAIL_RECIPIENT` 대신 구독 저장소에서 수신 대상을 조회해야 한다.
2. WHEN 수신 대상 조회가 완료될 때, THE 메일 발송 계층 SHALL 상태가 `active`인 구독자에게만 메일을 발송해야 한다.
3. IF `active` 상태 구독자가 한 명도 없을 때, THEN THE 시스템 SHALL 메일 발송을 안전하게 건너뛰고 운영 로그를 남겨야 한다.
4. WHEN 새 구독 저장소 기반 발송이 활성화될 때, THE 시스템 SHALL 정상적인 newsletter 발송을 위해 `GMAIL_RECIPIENT`를 요구하지 않아야 한다.
5. IF 구독 저장소 조회에 실패할 때, THEN THE 시스템 SHALL 환경변수 기반 수신자로 조용히 fallback하지 말고 명시적인 운영 실패로 처리해야 한다.

### Requirement 2: 애플리케이션은 Supabase가 아닌 내부 구독 저장소 추상화에 의존해야 한다

**User Story:**
As a developer,
I want the application to depend on an internal subscription repository interface rather than Supabase directly,
so that the storage backend can be replaced later without rewriting business flow.

#### Acceptance Criteria

1. WHEN 구독 데이터가 조회되거나 변경될 때, THE 애플리케이션 SHALL 내부 구독 저장소 추상화를 통해서만 접근해야 한다.
2. WHEN 초기 구현이 Supabase를 사용할 때, THE 시스템 SHALL Supabase 전용 스키마 및 클라이언트 코드를 adapter 계층에 격리해야 한다.
3. IF 추후 Supabase에서 다른 서버 측 저장소로 이전할 때, THEN THE 애플리케이션 SHALL 비즈니스 계층의 구독 lifecycle semantics를 유지해야 한다.
4. WHEN 프론트엔드가 구독 관련 작업을 수행할 때, THE 프론트엔드 SHALL 프로젝트 자체 API만 호출해야 하며 Supabase에 직접 접근해서는 안 된다.

### Requirement 3: 구독 신청은 double opt-in 절차를 따라야 한다

**User Story:**
As a visitor,
I want to request newsletter subscription with my email and confirm it through a verification email,
so that my address is not subscribed without my consent.

#### Acceptance Criteria

1. WHEN 사용자가 공개 구독 폼에 유효한 이메일을 제출할 때, THE 구독 API SHALL 즉시 발송 대상에 포함하지 않고 pending 상태의 구독 의도를 생성 또는 갱신해야 한다.
2. WHEN pending 구독 의도가 생성될 때, THE Cloudflare API 계층 SHALL 확인 토큰을 발급하고 직접 구독 확인 메일을 보내야 한다.
3. WHEN 사용자가 유효하고 만료되지 않은 확인 링크를 열 때, THE 구독 API SHALL 해당 구독 상태를 `active`로 변경해야 한다.
4. IF 확인 토큰이 유효하지 않거나, 만료되었거나, 이미 사용되었거나, 형식이 잘못되었을 때, THEN THE 구독 API SHALL 활성화를 거부하고 사용자에게 안전한 실패 결과를 반환해야 한다.
5. WHEN 이미 `active`인 이메일이 다시 구독 신청될 때, THE 시스템 SHALL 중복 active 구독 레코드를 만들지 않고 멱등적으로 처리해야 한다.
6. IF `unsubscribed` 상태인 이메일이 다시 구독 신청하고 확인 링크까지 완료할 때, THEN THE 시스템 SHALL 해당 구독을 다시 `active`로 전환할 수 있어야 한다.
7. WHEN confirmation 메일 발송 구현이 선택될 때, THE 시스템 SHALL Cloudflare API 런타임에서 실행 가능한 인증 방식만 사용해야 한다.

### Requirement 4: 실제 구독 해지 URL과 토큰 기반 해지 처리를 제공해야 한다

**User Story:**
As a subscriber,
I want a real unsubscribe link that completes the action safely,
so that I can stop future deliveries without operator intervention.

#### Acceptance Criteria

1. WHEN 시스템이 newsletter 이메일을 렌더링할 때, THE 이메일 SHALL placeholder가 아닌 수신자별 실제 unsubscribe URL을 포함해야 한다.
2. WHEN 사용자가 공개 프론트 도메인의 `/unsubscribe` 경로로 진입할 때, THE 프론트엔드 SHALL 구독 API를 호출해 실제 해지 처리를 수행해야 한다.
3. WHEN 유효한 unsubscribe 토큰이 제출될 때, THE 구독 API SHALL 해당 구독 상태를 `unsubscribed`로 변경해야 한다.
4. IF unsubscribe 토큰이 유효하지 않거나, 만료되었거나, 이미 사용되었거나, 형식이 잘못되었을 때, THEN THE 구독 API SHALL 해지를 거부하고 안전한 실패 결과를 반환해야 한다.
5. WHEN 구독이 `unsubscribed` 상태가 될 때, THE 메일 발송 계층 SHALL 이후 newsletter 발송 대상에서 해당 이메일을 제외해야 한다.
6. WHEN 구독 해지가 성공할 때, THE 시스템 SHALL 상태 변경 시각을 감사 가능한 형태로 보존해야 한다.

### Requirement 5: 구독자는 명시적인 상태 모델을 가져야 한다

**User Story:**
As an operator,
I want each subscriber to carry an explicit delivery status,
so that delivery eligibility and follow-up actions remain manageable.

#### Acceptance Criteria

1. WHEN 구독 레코드가 존재할 때, THE 레코드 SHALL `pending`, `active`, `unsubscribed`, `bounced` 중 하나의 상태를 가져야 한다.
2. WHEN newsletter 발송 대상을 선정할 때, THE 시스템 SHALL `active` 상태만 포함해야 한다.
3. WHEN 사용자가 구독 해지할 때, THE 시스템 SHALL 레코드를 기본적으로 hard delete하지 않고 `unsubscribed` 상태로 보존해야 한다.
4. WHEN 1차 버전이 배포될 때, THE 시스템 SHALL `bounced` 상태를 스키마와 비즈니스 규칙에서 지원해야 하며, 상태 변경은 운영자가 수동으로 관리할 수 있어야 한다.
5. WHEN 구독 상태가 변경될 때, THE 시스템 SHALL 최신 상태 변경 시각과 가능한 경우 상태 변경 사유 범주를 보존해야 한다.

### Requirement 6: 공개 프론트와 실제 처리 API는 분리되어야 한다

**User Story:**
As a product maintainer,
I want public pages and API endpoints to be separated cleanly,
so that user-facing flows remain simple while write operations stay behind the project-controlled backend boundary.

#### Acceptance Criteria

1. WHEN 사용자가 구독 확인 링크를 클릭할 때, THE 사용자용 URL SHALL 공개 프론트 도메인의 `/subscribe/confirm` 경로를 사용해야 한다.
2. WHEN 사용자가 구독 해지 링크를 클릭할 때, THE 사용자용 URL SHALL 공개 프론트 도메인의 `/unsubscribe` 경로를 사용해야 한다.
3. WHEN 공개 페이지가 구독 상태를 읽거나 변경해야 할 때, THE 프론트엔드 SHALL Cloudflare 기반 프로젝트 API 경로 `/api/subscriptions/...` 만 호출해야 한다.
4. WHEN API가 비밀값이나 저장소 인증정보에 접근할 때, THE API 계층 SHALL Cloudflare secrets를 사용해야 하며 브라우저에 해당 비밀값을 노출해서는 안 된다.
5. IF 공개 페이지가 데이터베이스에 직접 접근하지 않는 구조일 때, THEN THE 시스템 SHALL API 호출만으로 전체 구독 흐름을 완료할 수 있어야 한다.
6. WHEN Cloudflare API 계층이 추가될 때, THE 프로젝트 SHALL 로컬 개발 및 배포 검증 절차를 함께 정의해야 한다.

### Requirement 7: 초기 Supabase 스키마는 현재 운영성과 미래 이전 가능성을 함께 지원해야 한다

**User Story:**
As an operator,
I want the initial Supabase schema to support current subscription needs and future migration,
so that today’s implementation is operationally useful without tightly locking the project into one provider.

#### Acceptance Criteria

1. WHEN 초기 저장소 스키마가 설계될 때, THE 스키마 SHALL 구독자 식별, 구독 상태, 구독 확인 토큰, 해지 토큰, 상태 변경 시각을 지원해야 한다.
2. WHEN Supabase가 초기 저장소로 사용될 때, THE 시스템 SHALL 서버 측 신뢰 경계 안에서만 Supabase 자격증명을 사용해야 한다.
3. WHEN 초기 스키마가 정의될 때, THE 스키마 SHALL 다중 상품 선호도 모델이 아니라 단일 newsletter 구독 모델을 표현해야 한다.
4. IF Supabase 구현 전용 필드가 필요할 때, THEN THE repository adapter SHALL 이를 내부적으로 매핑해야 하며 상위 애플리케이션 계약에 누출해서는 안 된다.
5. WHEN 운영 문서가 갱신될 때, THE 프로젝트 SHALL 새로운 비밀값, 데이터 흐름, 구독자 관리 절차를 함께 설명해야 한다.
6. WHEN 구현에 필요한 클라이언트 라이브러리가 추가될 때, THE 프로젝트 SHALL Python 및 TypeScript 런타임 의존성을 명시적으로 갱신해야 한다.

### Requirement 8: 구독 확인 메일은 Cloudflare API가 직접 발송하고 newsletter 메일은 수신자별 개별 발송을 지원해야 한다

**User Story:**
As a maintainer,
I want confirmation emails to be sent directly from the Cloudflare API layer and newsletter emails to support per-recipient delivery,
so that confirmation stays synchronous and unsubscribe links can be individualized safely.

#### Acceptance Criteria

1. WHEN 시스템이 구독 확인 메일을 보낼 때, THE Cloudflare API 계층 SHALL 구독 신청 요청과 같은 처리 경계 안에서 confirmation 메일을 직접 발송해야 한다.
2. IF 구독 확인 메일 발송에 실패할 때, THEN THE 시스템 SHALL 해당 구독을 `active`로 전환해서는 안 된다.
3. WHEN newsletter 메일을 발송할 때, THE 메일 발송 계층 SHALL 수신자별로 개별 메시지를 생성하고 발송해야 한다.
4. WHEN 이메일에 토큰 기반 unsubscribe 링크가 생성될 때, THE 시스템 SHALL 각 링크를 해당 수신자와 intended action에 바인딩해야 한다.
5. WHEN 메일 발송 로그가 기록될 때, THE 시스템 SHALL newsletter 발송과 confirmation 관련 트랜잭션 메일을 구분할 수 있어야 한다.

### Requirement 9: 공개 구독 폼은 최소한의 남용 방지 기준을 충족해야 한다

**User Story:**
As a maintainer,
I want the subscription flow to enforce minimal safety controls,
so that the public form cannot trivially be abused or used to subscribe third-party addresses without consent.

#### Acceptance Criteria

1. WHEN 공개 사용자가 이메일을 제출할 때, THE 시스템 SHALL 저장 전 이메일 형식을 검증해야 한다.
2. WHEN 구독 확인 또는 해지 토큰이 생성될 때, THE 시스템 SHALL 예측 불가능하고 시간 제한이 있는 토큰을 생성해야 한다.
3. WHEN 이미 사용된 토큰이 다시 제출될 때, THE 시스템 SHALL 재사용 요청을 거부해야 한다.
4. WHEN 브라우저가 구독 변경 API를 호출할 때, THE API SHALL 해당 동작에 필요한 최소 요청 데이터만 받아야 한다.
5. IF 제3자가 타인의 이메일을 입력하더라도, THEN THE 시스템 SHALL 확인 링크 클릭 없이는 newsletter 발송을 활성화해서는 안 된다.

### Requirement 10: 새 구독 흐름은 자동화된 테스트로 검증되어야 한다

**User Story:**
As a developer,
I want the new subscription flow to be covered by automated tests,
so that recipient management changes do not break newsletter delivery or user state transitions.

#### Acceptance Criteria

1. WHEN 발송 대상 source가 환경변수에서 저장소로 변경될 때, THE 테스트 스위트 SHALL `active` 상태만 발송 대상으로 선택되는지 검증해야 한다.
2. WHEN 구독 신청이 발생할 때, THE 테스트 스위트 SHALL pending 생성, 확인 메일 생성, 유효 토큰을 통한 `active` 전환을 검증해야 한다.
3. WHEN 구독 해지 흐름이 수행될 때, THE 테스트 스위트 SHALL 유효 토큰으로 `unsubscribed` 상태가 되고 이후 발송에서 제외되는지 검증해야 한다.
4. WHEN 중복 구독 신청 또는 반복 요청이 발생할 때, THE 테스트 스위트 SHALL 기존 레코드에 대해 정의된 멱등 동작이 유지되는지 검증해야 한다.
5. WHEN 저장소 기반 발송 대상 조회가 활성화될 때, THEN THE 시스템 SHALL Gmail 기반 newsletter 발송을 유지하되 수신자별 개별 발송과 unsubscribe 링크 바인딩 규칙을 함께 만족해야 한다.
