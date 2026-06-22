# SOVEREIGNWON Frontend

`frontend/`는 SOVEREIGNWON 공개 웹사이트입니다. Next.js App Router 기반 SSG로 빌드되고, Cloudflare Pages에 `out/` 정적 산출물과 Pages Functions API를 배포합니다.

## 역할

- 최신 Sovereign Briefing 홈 화면
- 브리핑 아카이브와 상세 페이지
- Sentiment Join/Risk Overlay 기반 분석 화면
- 뉴스/시그널 피드
- 이메일 구독, 구독 확인, 해지 흐름
- `rss.xml`, `llms.txt` 정적 asset 생성

프론트엔드는 데이터를 다시 계산하지 않습니다. 공개 R2 JSON과 `schema/` 계약에 맞춰 렌더링합니다.

## 주요 경로

| 경로 | 역할 |
| --- | --- |
| `app/` | Next.js route |
| `components/brief/` | 브리핑 본문, Risk Overlay, Sovereign index |
| `components/analysis/` | 분석 대시보드 |
| `components/news/`, `components/signals/` | 뉴스와 X signal |
| `components/layout/` | 공통 레이아웃, 구독 UI |
| `functions/api/subscriptions/` | Cloudflare Pages Functions 구독 API |
| `lib/` | 데이터 로더, formatter, subscription helper |
| `scripts/generate-static-assets.ts` | RSS/llms.txt 등 정적 asset 생성 |
| `tests/` | Node test |

## 데이터 소스

| 모드 | 설정 | 용도 |
| --- | --- | --- |
| R2 public JSON | `NEXT_PUBLIC_R2_BASE_URL` | 기본 운영/개발 |
| fixture | `BRIEF_DATA_SOURCE=fixture` | 디자인/테스트용 고정 데이터 |
| output | `BRIEF_DATA_SOURCE=output` | 로컬 `../outputs` 산출물 확인 |

`NEXT_PUBLIC_R2_BASE_URL`이 canonical입니다. 기존 `R2_BASE_URL`은 legacy alias로만 취급합니다.

## 실행

```bash
npm ci
NEXT_PUBLIC_R2_BASE_URL="https://..." npm run dev
npm run dev:fixture
npm run dev:output
```

## 검증

```bash
npm run lint
npm test
NEXT_PUBLIC_R2_BASE_URL="https://..." npm run build
```

## 배포

```bash
NEXT_PUBLIC_R2_BASE_URL="https://..." \
CLOUDFLARE_API_TOKEN="..." \
CLOUDFLARE_ACCOUNT_ID="..." \
CLOUDFLARE_PAGES_PROJECT_NAME="..." \
npm run deploy:preview

NEXT_PUBLIC_R2_BASE_URL="https://..." \
CLOUDFLARE_API_TOKEN="..." \
CLOUDFLARE_ACCOUNT_ID="..." \
CLOUDFLARE_PAGES_PROJECT_NAME="..." \
npm run deploy:production
```

위 예시는 환경변수 이름만 보여줍니다. 실제 secret 값은 문서나 로그에 남기지 않습니다.

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| `../docs/frontend/README.md` | 프론트엔드 문서 입구 |
| `../schema/README.md` | public JSON 계약 매핑 |
| `../docs/subscriptions-ops.md` | 구독 운영 |
| `../docs/infrastructure/README.md` | Cloudflare Pages/GitHub Actions 운영 |
