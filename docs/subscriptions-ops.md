# Newsletter Subscription Ops

newsletter 구독은 더 이상 `GMAIL_RECIPIENT`를 source of truth로 사용하지 않습니다. 발송 대상은 Supabase `subscriptions` 테이블의 `active` 상태에서만 읽습니다.

## 런타임 구성

### Python 파이프라인

필수 환경변수:

- `GMAIL_SENDER`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_APP_BASE_URL`
- `SUBSCRIPTION_NEWSLETTER_KEY`
- `SUBSCRIPTION_UNSUBSCRIBE_PATH`
- `SUBSCRIPTION_TOKEN_SECRET`

설명:

- Python 파이프라인은 `active` 구독자를 Supabase에서 읽어 recipient별 개별 발송합니다.
- unsubscribe 링크는 `PUBLIC_APP_BASE_URL`과 `SUBSCRIPTION_TOKEN_SECRET`으로 서명된 만료 토큰 URL을 만듭니다.
- `GMAIL_RECIPIENT`는 더 이상 정상 경로에서 사용하지 않습니다.

### Cloudflare Pages Functions

필수 secrets:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_APP_BASE_URL`
- `SUBSCRIPTION_NEWSLETTER_KEY`
- `SUBSCRIPTION_TOKEN_SECRET`
- `CONFIRMATION_GMAIL_CLIENT_ID`
- `CONFIRMATION_GMAIL_CLIENT_SECRET`
- `CONFIRMATION_GMAIL_REFRESH_TOKEN`
- `CONFIRMATION_GMAIL_SENDER`

설명:

- 공개 페이지는 `/subscribe/confirm`, `/unsubscribe`를 사용합니다.
- 실제 처리는 `/api/subscriptions/request`, `/api/subscriptions/confirm`, `/api/subscriptions/unsubscribe` Functions가 담당합니다.
- confirmation 메일은 Cloudflare Functions가 Gmail API를 직접 호출해 보냅니다.

## 로컬 검증

frontend fixture build:

```bash
cd frontend
npm run build:fixture
```

Pages Functions 개발 서버:

```bash
cd frontend
npx wrangler@4 pages dev out \
  --binding SUPABASE_URL=https://example.supabase.co \
  --binding SUPABASE_SERVICE_ROLE_KEY=service-role-key \
  --binding PUBLIC_APP_BASE_URL=https://brief.example.com \
  --binding SUBSCRIPTION_NEWSLETTER_KEY=morning-brief \
  --binding SUBSCRIPTION_TOKEN_SECRET=token-secret \
  --binding CONFIRMATION_GMAIL_CLIENT_ID=client-id \
  --binding CONFIRMATION_GMAIL_CLIENT_SECRET=client-secret \
  --binding CONFIRMATION_GMAIL_REFRESH_TOKEN=refresh-token \
  --binding CONFIRMATION_GMAIL_SENDER=brief@example.com
```

주의:

- 실제 민감값은 `--binding` 대신 Cloudflare dashboard 또는 Wrangler secrets를 사용합니다.
- 로컬 명령은 라우팅과 Functions 초기화 확인용입니다.

## 배포 전 체크

1. Supabase migration을 적용합니다.
2. Cloudflare Pages 프로젝트에 위 secrets를 등록합니다.
3. preview 환경에서 `/api/subscriptions/request`와 `/unsubscribe`를 수동 확인합니다.
4. Python 파이프라인 실행 환경에도 Supabase 관련 환경변수를 등록합니다.

## 선택적 MCP 개발 연결

- Supabase MCP는 개발용 보조 도구입니다.
- 런타임은 MCP 없이도 동작해야 하며, Cloudflare Functions와 Python 파이프라인은 직접 `SUPABASE_URL`과 `SUPABASE_SERVICE_ROLE_KEY`만 사용합니다.
- 가능하면 production 대신 dev project 또는 branch database를 연결합니다.

## 수동 점검 체크리스트

1. 공개 홈에서 이메일을 넣고 구독 신청 메시지가 보이는지 확인합니다.
2. confirmation 메일이 도착하고 `/subscribe/confirm` 링크가 열리는지 확인합니다.
3. 확인 후 Supabase `subscriptions.status`가 `active`로 바뀌는지 확인합니다.
4. Python 파이프라인 발송 시 `active` 구독자만 recipient별로 전송되는지 확인합니다.
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
