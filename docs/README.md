# SOVEREIGNWON Documentation

이 디렉터리는 SOVEREIGNWON 저장소의 제품, 코드, 운영, 분석, 스펙 문서를 모읍니다.

문서의 기준은 실제 코드베이스입니다. 새 문서를 만들 때는 먼저 아래 소유 영역 중 하나에 배치하고, 오래된 실행 경로나 코드와 맞지 않는 설명을 남기지 않습니다.

## 빠른 진입점

| 영역 | 문서 | 먼저 읽을 상황 |
| --- | --- | --- |
| 전체 지도 | [reference/codebase-map.md](reference/codebase-map.md) | 어떤 코드가 어떤 제품/파이프라인에 속하는지 확인 |
| 브리핑 | [briefing/README.md](briefing/README.md) | 브리핑, Sentiment Join, 이메일, public JSON 흐름 확인 |
| Arena | [arena/README.md](arena/README.md) | BTC Signal Arena 운영/연구/제품 맥락 확인 |
| Frontend | [frontend/README.md](frontend/README.md) | 공개 사이트, Pages Functions, schema 계약 확인 |
| Infrastructure | [infrastructure/README.md](infrastructure/README.md) | GitHub Actions, Lambda, deploy, Supabase 운영 경로 확인 |
| 문서 인벤토리 | [reference/markdown-inventory.md](reference/markdown-inventory.md) | Markdown 파일이 어디에 있고 어떤 성격인지 확인 |
| 문서 루브릭 | [reference/docs-rubric.md](reference/docs-rubric.md) | 문서 변경 후 자체 검증 |

## 디렉터리 규칙

| 디렉터리 | 역할 |
| --- | --- |
| `briefing/` | Sovereign Briefing, Sentiment Join, 이메일, public JSON, 데이터 소스 운영 |
| `arena/` | BTC Signal Arena의 운영, 아키텍처, 연구, 제품 문서 |
| `frontend/` | 공개 Next.js/Cloudflare Pages 사이트와 JSON 계약 |
| `infrastructure/` | 배포, 워크플로우, Lambda, Supabase, R2 운영 경로 |
| `reference/` | 코드베이스 맵, Markdown 인벤토리, 문서 정합성 루브릭 |
| `analysis/` | 특정 실행 결과, 장애/품질 분석, 사후 리뷰 |
| `reports/` | 제출용/공유용 완성 보고서와 코드 기반 보고서 초안 |
| `research/` | 리서치 노트, 질문서, 탐색 정리 |
| `specs/` | 요구사항, 설계, 작업 체크리스트 |
| `teaching/` | 발표/교육용 산출물 |
| `ux/` | UX 개선 계획 |

## 운영 중인 핵심 문서

| 문서 | 내용 |
| --- | --- |
| [data-flow.md](data-flow.md) | Sentiment Join -> 브리핑 -> 프론트엔드 배포 데이터 흐름 |
| [data-sources.md](data-sources.md) | 시장/뉴스/감성/Supabase 데이터 소스와 품질 기준 |
| [logging-ops.md](logging-ops.md) | 로깅 운영 가이드 |
| [llm-cost-ops.md](llm-cost-ops.md) | LLM 비용 운영 |
| [ai-evals.md](ai-evals.md) | AI 품질 점검 기준 |
| [subscriptions-ops.md](subscriptions-ops.md) | 구독 운영 가이드 |
| [codex-ops.md](codex-ops.md) | 에이전트/Codex 운영 가이드 |
| [development-standards.md](development-standards.md) | 개발 규칙 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 기여/검증/커밋 가이드 |

## 문서 정리 원칙

- 루트 `README.md`는 제품 전체 소개와 진입점만 유지합니다.
- 세부 운영 절차는 `docs/` 아래의 영역별 문서로 이동합니다.
- Arena 관련 문서는 `docs/arena/` 아래에 둡니다.
- 브리핑/Sentiment Join 관련 문서는 `docs/briefing/`, `docs/data-flow.md`, `docs/data-sources.md`, `docs/analysis/sentiment-join/` 중 성격에 맞게 둡니다.
- 프론트엔드 구현/계약 문서는 `docs/frontend/`, `frontend/README.md`, `schema/README.md`를 함께 갱신합니다.
- `.env`, `.env.*`, 터미널 secret 출력, 인증 토큰 값은 문서화하지 않습니다.
- 도구 설정, 캐시, 가상환경, node_modules의 Markdown은 프로젝트 문서 인벤토리 대상에서 제외합니다.
