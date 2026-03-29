# Requirements Document

## Introduction

현재 저장소의 메일 발송은 Gmail OAuth와 refresh token, `token.json`/`credentials.json`에 의존하고 있습니다. 이를 AWS SES 기반으로 전환해 GitHub Actions 뉴스레터 경로는 OIDC로 `arn:aws:iam::254849613915:role/kr-pr-ses-news-v1a` 역할을 Assume하고, Cloudflare Pages Functions 확인 메일 경로는 암호화된 AWS secret를 사용하도록 재구성해야 합니다. 운영 리전은 서울(`ap-northeast-2`)로 고정하고, 뉴스레터와 확인 메일 모두 SES verified sender `no-reply@sovereignbriefing.com`를 사용합니다. 범위는 뉴스레터 본 발송과 구독 확인 메일 발송 경로를 SES 기준으로 재정의하는 것이며, 메일 콘텐츠 구조와 구독자 해석 규칙은 유지하고 Gmail 전용 비밀값과 파일 의존은 제거합니다.

## Glossary

**Newsletter Mail**: Python 파이프라인이 active 구독자에게 개별 발송하는 브리핑 메일

**Confirmation Mail**: 구독 신청 직후 보내는 확인 링크 메일

**SES Transport**: Amazon SES를 통해 raw email 또는 API 방식으로 메일을 전송하는 계층

**OIDC Role**: GitHub Actions가 `AssumeRoleWithWebIdentity`로 획득하는 AWS IAM Role

**Verified Identity**: SES에서 발신자로 검증된 이메일 주소 또는 도메인

**Mail Intent**: `newsletter`, `confirm_subscription` 같은 메일 목적 분류

**Seoul Region**: 본 전환에서 SES 발송 리전으로 고정하는 AWS 리전 `ap-northeast-2`

## Requirements

### Requirement 1: 뉴스레터 발송 경로의 SES 전환

**User Story:**
As an operator,
I want the scheduled newsletter pipeline to send through AWS SES instead of Gmail,
so that CI 발송 경로가 Gmail OAuth 파일과 장기 토큰 없이 동작할 수 있다.

#### Acceptance Criteria

1. WHEN the pipeline runs with `SEND_EMAIL=true`, THE newsletter mail transport SHALL send each active recipient email through Amazon SES instead of Gmail API.
2. WHEN newsletter mail is sent, THE system SHALL CONTINUE TO resolve recipients from the Supabase subscription repository and send one message per recipient.
3. WHEN newsletter mail is rendered, THE system SHALL CONTINUE TO include the existing unsubscribe URL and current HTML/plain-text body structure.
4. WHEN newsletter mail is sent, THE system SHALL use `no-reply@sovereignbriefing.com` as the SES sender identity in `ap-northeast-2`.
5. IF no active recipients exist, THEN THE pipeline SHALL skip delivery without calling SES.
6. IF one or more recipient deliveries fail, THEN THE pipeline SHALL surface a failure that identifies the failed recipient count and preserve per-recipient error logging.

### Requirement 2: GitHub Actions OIDC 기반 AWS 인증

**User Story:**
As an operator,
I want GitHub Actions to assume the AWS role `arn:aws:iam::254849613915:role/kr-pr-ses-news-v1a` via OIDC,
so that static AWS access keys are not stored in GitHub secrets.

#### Acceptance Criteria

1. WHEN the `morning-brief` workflow sends newsletter mail, THE workflow SHALL request `id-token: write` permission and assume `arn:aws:iam::254849613915:role/kr-pr-ses-news-v1a`.
2. WHEN the workflow authenticates to AWS, THE workflow SHALL NOT require `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` secrets.
3. WHEN the workflow is configured for SES delivery, THE workflow SHALL NOT restore or depend on Gmail OAuth files such as `credentials.json` or `token.json`.
4. IF the AWS role assumption fails, THEN THE workflow SHALL fail before attempting SES delivery.
5. WHEN AWS credentials are obtained through OIDC, THE workflow SHALL use `ap-northeast-2` consistently for all newsletter delivery calls.

### Requirement 3: 구독 확인 메일의 SES 전환

**User Story:**
As a subscriber,
I want subscription confirmation mail to be sent through AWS SES,
so that the public subscription flow uses the same provider family and removes Gmail refresh token dependency.

#### Acceptance Criteria

1. WHEN a user requests a subscription, THE confirmation mail transport SHALL send the confirmation email through Amazon SES instead of Gmail API.
2. WHEN confirmation mail is sent, THE system SHALL CONTINUE TO use the existing confirmation URL, subject, text body, and HTML body generation.
3. WHEN confirmation mail is sent, THE system SHALL use `no-reply@sovereignbriefing.com` as the SES sender identity in `ap-northeast-2`.
4. WHEN the frontend subscription API is configured for SES delivery, THE Cloudflare Pages Functions runtime SHALL use encrypted secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `CONFIRMATION_SES_SENDER` for SES authentication and sender configuration.
5. WHEN the frontend subscription API is configured for SES delivery, THE runtime SHALL NOT require `CONFIRMATION_GMAIL_CLIENT_ID`, `CONFIRMATION_GMAIL_CLIENT_SECRET`, or `CONFIRMATION_GMAIL_REFRESH_TOKEN`.
6. IF confirmation mail delivery fails, THEN THE request subscription flow SHALL preserve the current failure propagation behavior and SHALL NOT activate the subscription.
7. WHEN confirmation mail delivery succeeds, THE request subscription flow SHALL CONTINUE TO return the current pending response contract.

### Requirement 4: 설정 및 비밀값 정리

**User Story:**
As an operator,
I want mail-related configuration to reflect SES and OIDC usage clearly,
so that runtime setup is understandable and Gmail-specific secrets can be retired safely.

#### Acceptance Criteria

1. WHEN mail transport is configured, THE system SHALL use SES-specific environment variables for sender identity, region, and any required transport mode instead of Gmail OAuth-specific variables.
2. WHEN the migration is complete, THE newsletter path and the confirmation path SHALL both use `no-reply@sovereignbriefing.com` as the sender identity.
3. WHEN the migration is complete, THE newsletter path and the confirmation path SHALL both use `ap-northeast-2` as the SES region.
4. WHEN GitHub Actions sends newsletter mail, THE configuration SHALL use OIDC-based AWS authentication with the configured IAM role.
5. WHEN Cloudflare Pages Functions send confirmation mail, THE configuration SHALL use encrypted AWS credential secrets and SHALL NOT place AWS credential values in plain-text bindings.
6. WHEN local development runs this system, THE configuration SHALL NOT require actual SES delivery credentials and SHALL treat local execution as non-delivery verification only.
7. WHEN the migration is complete, THE operational documentation SHALL describe the required SES identities, AWS role, region, and runtime-specific secret setup.
8. IF legacy Gmail variables remain temporarily for rollout safety, THEN THE documentation SHALL mark them as deprecated and define the removal condition explicitly.

### Requirement 5: 관측성, 로깅, 검증

**User Story:**
As an operator,
I want the SES migration to preserve delivery visibility and regression coverage,
so that provider migration does not reduce diagnosability or break current mail behavior silently.

#### Acceptance Criteria

1. WHEN newsletter or confirmation mail is sent through SES, THE structured logs SHALL record the provider as `ses` and preserve the current mail intent and recipient-level visibility.
2. WHEN provider-specific errors occur, THE system SHALL log enough structured context to distinguish authentication failure, identity configuration failure, and per-recipient send failure.
3. WHEN the migration changes mail transport behavior, THEN automated tests SHALL cover newsletter sending, confirmation mail sending, and configuration loading for SES paths.
4. WHEN the migration is validated, THEN documentation SHALL include executable verification steps for GitHub Actions OIDC role assumption and SES delivery smoke testing.
