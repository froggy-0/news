# Documentation Rubric

문서 변경 후 아래 기준으로 자체 검증합니다.

| 기준 | 확인 질문 | 판정 |
| --- | --- | --- |
| 제품 범위 | 루트 README가 브리핑만 설명하지 않고 SOVEREIGNWON, 브리핑, Arena, 프론트엔드를 모두 설명하는가 | 필수 |
| 코드 정합성 | 실행 명령, 진입점, workflow 이름이 실제 파일과 맞는가 | 필수 |
| 경로 명확성 | 각 문서가 어느 디렉터리에 속해야 하는지 `docs/README.md`에서 찾을 수 있는가 | 필수 |
| 누락 방지 | 프로젝트 Markdown 목록을 `reference/markdown-inventory.md`에서 찾을 수 있는가 | 필수 |
| 보안 | `.env`, secret 값, 인증 출력이 문서에 포함되지 않았는가 | 필수 |
| 중복 최소화 | 루트 README는 전체 지도, 상세 절차는 하위 문서로 분리됐는가 | 권장 |
| 오래된 표현 | `python -m morning_brief`처럼 현재 코드와 맞지 않는 예시가 제거됐는가 | 필수 |
| 변경 가능성 | 실시간 수치/외부 상태를 확정값처럼 적지 않았는가 | 권장 |

## 이번 정리 결과

| 항목 | 결과 |
| --- | --- |
| 루트 README | SOVEREIGNWON 전체 개요로 재작성 |
| 브리핑 문서 | `docs/briefing/README.md` 신설 |
| 프론트엔드 문서 | `docs/frontend/README.md` 신설 |
| 인프라 문서 | `docs/infrastructure/README.md` 신설 |
| 코드베이스 맵 | `docs/reference/codebase-map.md` 신설 |
| Markdown 인벤토리 | `docs/reference/markdown-inventory.md` 생성 |
