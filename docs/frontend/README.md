# Frontend Docs

공개 프론트엔드는 `frontend/`의 Next.js App Router 정적 사이트입니다. R2 public JSON을 읽어 홈, 아카이브, 상세 브리핑, 분석 대시보드, 구독/해지 화면을 렌더링합니다.

## 코드 기준

| 영역 | 경로 | 역할 |
| --- | --- | --- |
| 앱 라우트 | `frontend/app/` | home, archive, analysis, subscribe, unsubscribe, privacy |
| 브리핑 컴포넌트 | `frontend/components/brief/` | 본문, Risk Overlay, Sovereign index, 판단 블록 |
| 분석 컴포넌트 | `frontend/components/analysis/` | 분석 대시보드와 signal field |
| 뉴스/시그널 | `frontend/components/news/`, `frontend/components/signals/` | public JSON 뉴스와 X signal 표시 |
| 구독 UI | `frontend/components/layout/SubscriptionForm.tsx` | 구독 폼과 상태 UI |
| Pages Functions | `frontend/functions/api/subscriptions/` | 구독 확인/해지 API |
| 데이터 로더 | `frontend/lib/` | R2/fixture/output 데이터 로드와 정규화 |
| 정적 산출물 생성 | `frontend/scripts/generate-static-assets.ts` | RSS, llms.txt 등 build-time asset |
| 타입 계약 | `schema/brief.types.ts`, `schema/analysis.types.ts` | 프론트가 기대하는 JSON 구조 |

## 데이터 원칙

- 프론트엔드는 시장 데이터나 신호를 다시 계산하지 않습니다.
- 기본 데이터 소스는 `NEXT_PUBLIC_R2_BASE_URL`의 public JSON입니다.
- fixture는 디자인/테스트용이며, 실서비스 기준 데이터가 아닙니다.
- 구독 mutation은 Cloudflare Pages Functions에서 처리하고, 브라우저가 Supabase service role key를 직접 다루지 않습니다.

## 실행 명령

```bash
cd frontend
npm ci
NEXT_PUBLIC_R2_BASE_URL="https://..." npm run dev
NEXT_PUBLIC_R2_BASE_URL="https://..." npm run build
npm run lint
npm test
```

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| `frontend/README.md` | 프론트엔드 로컬 실행/배포 상세 |
| `frontend/DESIGN.md` | 시각 설계 노트 |
| `schema/README.md` | public JSON 계약 매핑 |
| [../specs/public-brief-frontend/design.md](../specs/public-brief-frontend/design.md) | public brief frontend 설계 |
| [../specs/frontend-ssg-redesign-migration/design.md](../specs/frontend-ssg-redesign-migration/design.md) | SSG redesign migration |
| [../ux/conversion-ux-plan.md](../ux/conversion-ux-plan.md) | 구독/전환 UX 계획 |
