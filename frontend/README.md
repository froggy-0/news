# Morning Brief Frontend

이 디렉토리는 SOVEREIGN BRIEF 공개 프론트엔드입니다.

## 현재 목표

- Next.js App Router 기반 SSG
- `npm run build` 시 `out/` 정적 산출물 생성
- Cloudflare R2 JSON 읽기
- Cloudflare Pages 배포
- 한국어 중심 시장 브리핑 페이지

## 산출물

- Cloudflare Pages에는 `out/` 디렉토리만 올리면 됩니다.
- `rss.xml`, `llms.txt`도 build 시 `public/`에 생성된 뒤 함께 export 됩니다.

## 개발 기본 원칙

- 프론트는 데이터를 다시 계산하지 않습니다.
- 계약 기준은 `../schema/brief.types.ts` 입니다.
- 기본 동작은 공개 R2 JSON 기준입니다. `NEXT_PUBLIC_R2_BASE_URL` 없이 앱을 빌드하거나 실행하지 않습니다.
- fixture 는 테스트/디자인 확인용으로만 남기며, `BRIEF_DATA_SOURCE=fixture` 를 명시했을 때만 사용합니다.
- 예시:
  - 실데이터 개발: `NEXT_PUBLIC_R2_BASE_URL='https://pub-...r2.dev' npm run dev`
  - fixture 개발: `npm run dev:fixture`
