# Newsletter Subscription Ops

newsletter 발송 대상은 Supabase `subscriptions` 테이블의 `active` 상태에서만 읽고, 메일 전송은 AWS SES를 사용합니다.

## 런타임 구성

### Python 파이프라인

필수 환경변수:

- `AWS_REGION=ap-northeast-2`
- `SES_SENDER=no-reply@sovereignbriefing.com`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_APP_BASE_URL`
- `SUBSCRIPTION_TOKEN_SECRET`

설명:

- Python 파이프라인은 `active` 구독자를 Supabase에서 읽어 recipient별 개별 발송합니다.
- Python 파이프라인의 newsletter 발송은 GitHub Actions에서 OIDC로 `arn:aws:iam::254849613915:role/kr-pr-ses-news-v1a`를 Assume한 뒤 SES `ap-northeast-2` 리전으로 보냅니다.
- sender는 `no-reply@sovereignbriefing.com`로 고정합니다.
- newsletter SES 발송이 일부 recipient에서 실패하면 run은 `degraded`로 기록하고 `email_send_failed` 이벤트를 남긴 뒤 공개 산출물과 후속 frontend deploy는 계속 진행합니다.
- newsletter key는 `morning-brief`, unsubscribe path는 `/unsubscribe`로 현재 코드에 고정돼 있습니다.
- unsubscribe 링크는 `PUBLIC_APP_BASE_URL`과 `SUBSCRIPTION_TOKEN_SECRET`으로 서명된 만료 토큰 URL을 만듭니다.
- 고정 recipient 환경변수나 OAuth 토큰 파일 없이 운영합니다.

### Cloudflare Pages Functions

필수 secrets:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_APP_BASE_URL`
- `SUBSCRIPTION_TOKEN_SECRET`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION=ap-northeast-2`
- `SES_SENDER=no-reply@sovereignbriefing.com`
  - legacy alias: `CONFIRMATION_SES_SENDER`

설명:

- 공개 페이지는 `/subscribe/confirm`, `/unsubscribe`를 사용합니다.
- 실제 처리는 `/api/subscriptions/request`, `/api/subscriptions/confirm`, `/api/subscriptions/unsubscribe` Functions가 담당합니다.
- confirmation 메일은 Cloudflare Functions가 AWS SES API로 직접 보냅니다.
- sender는 `no-reply@sovereignbriefing.com`, 리전은 `ap-northeast-2`로 고정합니다.

## 로컬 검증

frontend fixture build:

```bash
cd frontend
npm run build:fixture
```

주의:

- 로컬 개발에서는 실제 SES 발송 smoke test를 지원하지 않습니다.
- 로컬은 route 초기화와 입력/응답 계약 확인까지만 수행합니다.

Pages Functions 개발 서버:

```bash
cd frontend
npx wrangler@4 pages dev out \
  --binding SUPABASE_URL=https://example.supabase.co \
  --binding SUPABASE_SERVICE_ROLE_KEY=service-role-key \
  --binding PUBLIC_APP_BASE_URL=https://brief.example.com \
  --binding SUBSCRIPTION_TOKEN_SECRET=token-secret
```

주의:

- 실제 민감값은 `--binding` 대신 Cloudflare dashboard 또는 Wrangler secrets를 사용합니다.
- 로컬 명령은 라우팅과 Functions 초기화 확인용입니다.

## 배포 전 체크

1. Supabase migration을 적용합니다.
2. SES `ap-northeast-2` 리전에서 `no-reply@sovereignbriefing.com` 또는 해당 도메인 identity가 verified 상태인지 확인합니다.
3. Cloudflare Pages 프로젝트에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `SES_SENDER`를 secret로 등록합니다.
   - 기존 `CONFIRMATION_SES_SENDER`도 alias로 동작합니다.
4. GitHub Actions에서 OIDC role `arn:aws:iam::254849613915:role/kr-pr-ses-news-v1a`를 Assume할 수 있는지 확인합니다.
5. preview 환경에서 `/api/subscriptions/request`와 `/unsubscribe`를 수동 확인합니다.
6. Python 파이프라인 실행 환경에도 Supabase 관련 환경변수를 등록합니다.

## 운영 검증 절차

### GitHub Actions newsletter 발송

1. workflow가 `aws-actions/configure-aws-credentials`로 role을 Assume하는지 확인합니다.
2. 필요 시 workflow 안에서 `aws sts get-caller-identity`로 현재 caller를 확인합니다.
3. workflow 실행 후 `app-events-<run_id>.jsonl`에 `email_send_failed` 이벤트가 없는지 확인합니다.
4. SES 발송과 실제 수신 mailbox 도착 여부를 확인합니다.

### Cloudflare preview confirmation 발송

1. preview 환경에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `SES_SENDER`가 모두 등록됐는지 확인합니다.
   - 기존 `CONFIRMATION_SES_SENDER`만 있어도 동작하지만 새 설정은 `SES_SENDER`로 맞춥니다.
2. `/api/subscriptions/request`를 호출해 confirmation 메일이 도착하는지 확인합니다.
3. confirmation 링크를 열어 `subscriptions.status`가 `active`로 바뀌는지 확인합니다.

## 선택적 MCP 개발 연결

- Supabase MCP는 개발용 보조 도구입니다.
- 런타임은 MCP 없이도 동작해야 하며, Cloudflare Functions와 Python 파이프라인은 직접 `SUPABASE_URL`과 `SUPABASE_SERVICE_ROLE_KEY`만 사용합니다.
- 가능하면 production 대신 dev project 또는 branch database를 연결합니다.

## 수동 점검 체크리스트

1. 공개 홈에서 이메일을 넣고 구독 신청 메시지가 보이는지 확인합니다.
2. SES confirmation 메일이 `no-reply@sovereignbriefing.com` 발신자로 도착하고 `/subscribe/confirm` 링크가 열리는지 확인합니다.
3. 확인 후 Supabase `subscriptions.status`가 `active`로 바뀌는지 확인합니다.
4. Python 파이프라인 발송 시 `active` 구독자만 recipient별로 전송되고 sender가 `no-reply@sovereignbriefing.com`인지 확인합니다.
5. 메일 본문마다 recipient별 unsubscribe 링크가 포함되는지 확인합니다.
6. `/unsubscribe`에서 preview 상태 확인 후 실제 해지가 동작하는지 확인합니다.
7. 해지 후 해당 이메일이 다음 발송 대상에서 제외되는지 확인합니다.

## bounced 상태 운영

1차에서는 `bounced`를 운영자가 수동으로 바꿉니다.

예시 SQL:

```sql
update public.subscriptions
set
  status = 'bounced',
  status_reason = 'manual_bounce_review',
  bounced_at = now()
where newsletter = 'morning-brief'
  and email_normalized = lower('user@example.com');
```
