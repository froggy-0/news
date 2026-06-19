# Documentation Map

이 디렉터리는 저장소에서 공유할 문서를 모읍니다.

## Active

| Directory | Purpose |
| --- | --- |
| [arena/](arena/) | BTC Signal Arena 운영, 아키텍처, 백테스트, 제품 문서 |

현재 Arena 작업을 이어갈 때는 먼저 [arena/overview/next-session-handoff.md](arena/overview/next-session-handoff.md)를 읽고, 이어서 [arena/overview/current-state.md](arena/overview/current-state.md)를 읽는다.

## Legacy / Reference

| Directory | Purpose |
| --- | --- |
| `specs/` | 기존 기능 요구사항, 설계, 작업 체크리스트 |
| `reports/` | 제출용 또는 공유용 완성 보고서와 코드 기반 보고서 초안 |
| `research/` | 리서치 노트, 질문서, 탐색 정리 |
| `analysis/` | 특정 실행 결과, 장애/품질 분석, 사후 리뷰 |
| `teaching/` | 발표/교육용 산출물 |
| `ux/` | UX 개선 계획 |

## Hygiene

- 개인 도구 설정, 일회성 실행 로그, 로컬 에이전트 설정은 저장소 문서로 보지 않고 `.gitignore`에 둔다.
- `.DS_Store` 같은 OS 부산물은 보관하지 않는다.
- secret 값이 들어갈 수 있는 `.env`, 터미널 캡처, 인증 출력은 문서화하지 않는다.
