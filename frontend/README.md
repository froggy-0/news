# Morning Brief Frontend

이 디렉토리는 SOVEREIGN BRIEF 공개 프론트엔드입니다.

## 현재 목표

- Next.js App Router 기반 SSG
- `npm run build` 시 `out/` 정적 산출물 생성
- `frontend/functions/` 기반 Cloudflare Pages Functions API 제공
- Cloudflare R2 JSON 읽기
- Cloudflare Pages 배포
- 한국어 중심 시장 브리핑 페이지

## 산출물

- Cloudflare Pages에는 `out/` 디렉토리만 올리면 됩니다.
- Functions를 함께 배포할 때는 `frontend/` 디렉토리에서 Wrangler를 실행해야 합니다.
- `rss.xml`, `llms.txt`도 build 시 `public/`에 생성된 뒤 함께 export 됩니다.

## 로컬 배포

- 로컬에서 프론트만 다시 배포할 때는 `npm run deploy:preview` 또는 `npm run deploy:production` 을 사용합니다.
- 배포 전에 현재 공개 JSON이 R2에 올라가 있어야 합니다.

필수 환경변수:
- `NEXT_PUBLIC_R2_BASE_URL`

`NEXT_PUBLIC_R2_BASE_URL`를 canonical로 사용합니다. 기존 `R2_BASE_URL`은 legacy alias로만 읽습니다.
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_PAGES_PROJECT_NAME`

선택 환경변수:
- `DEPLOY_BRANCH`
  - preview 배포 branch alias를 강제로 지정할 때만 사용합니다.

예시:
- preview 배포
  - `NEXT_PUBLIC_R2_BASE_URL='https://pub-...r2.dev' CLOUDFLARE_API_TOKEN='...' CLOUDFLARE_ACCOUNT_ID='...' CLOUDFLARE_PAGES_PROJECT_NAME='news-amo' npm run deploy:preview`
- production 배포
  - `NEXT_PUBLIC_R2_BASE_URL='https://pub-...r2.dev' CLOUDFLARE_API_TOKEN='...' CLOUDFLARE_ACCOUNT_ID='...' CLOUDFLARE_PAGES_PROJECT_NAME='news-amo' npm run deploy:production`

## 개발 기본 원칙

- 프론트는 데이터를 다시 계산하지 않습니다.
- 계약 기준은 `../schema/brief.types.ts` 입니다.
- 기본 동작은 공개 R2 JSON 기준입니다. `NEXT_PUBLIC_R2_BASE_URL` 없이 앱을 빌드하거나 실행하지 않습니다.
- fixture 는 테스트/디자인 확인용으로만 남기며, `BRIEF_DATA_SOURCE=fixture` 를 명시했을 때만 사용합니다.
- 실제 생성 JSON을 로컬에서 직접 확인할 때는 `BRIEF_DATA_SOURCE=output` 으로 `../output/briefs_YYYY-MM-DD.json` 파일을 읽습니다.
- 구독/확인/해지 흐름은 `functions/api/subscriptions/*` 에서 처리하며, 브라우저는 Supabase에 직접 접근하지 않습니다.
- 예시:
  - 실데이터 개발: `NEXT_PUBLIC_R2_BASE_URL='https://pub-...r2.dev' npm run dev`
  - fixture 개발: `npm run dev:fixture`
  - output 개발: `npm run dev:output`
  - fixture build: `npm run build:fixture`
  - output build: `npm run build:output`

## 구독 기능 운영

- confirmation 메일과 subscription mutation은 Cloudflare Pages Functions가 처리합니다.
- Python 파이프라인은 Supabase `subscriptions` 테이블의 `active` 구독자만 읽습니다.
- 상세 secret 목록과 로컬 검증 경로는 `../docs/subscriptions-ops.md`를 따릅니다.
