# Specs Docs

`docs/specs/`는 기능 요구사항, 설계, 작업 체크리스트를 보관합니다.

## 규칙

- 기능 단위 디렉터리에는 가능하면 `requirements.md`, `design.md`, `tasks.md`를 둡니다.
- 완료된 스펙이라도 코드 계약이나 운영 문서로 승격할 내용은 `docs/briefing/`, `docs/frontend/`, `docs/infrastructure/`, `docs/arena/`로 옮겨 요약 링크를 남깁니다.
- 과거 작업 기록은 삭제하지 않고, 현재 상태와 다를 수 있음을 문서 안에서 명시합니다.

## 주요 현재 스펙 축

| 주제 | 예시 경로 |
| --- | --- |
| public frontend | `public-brief-frontend/`, `frontend-ssg-redesign-migration/` |
| 데이터 수집/품질 | `data-ingestion-quality-improvement/`, `public-news-feed-quality/` |
| Sentiment Join | `sentiment-time-join/`, `sentiment-join-advanced-features/`, `analytics-storage-contract-v2/` |
| 공급자/인프라 | `binance-integration/`, `aws-ses-mail-migration/`, `stooq-to-kis-migration/` |
| 이메일/프롬프트 | `mail-template-brand-alignment/`, `prompt-governance-unification/` |
