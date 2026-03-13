# AGENTS.md

상세 기준은 `docs/development-standards.md`를 따릅니다. 이 파일에는 Codex가 항상 지켜야 할 실행 규칙만 둡니다.

## Always
- 관련 코드, 테스트, 문서를 먼저 읽고 수정 범위를 최소화합니다.
- 검색은 `rg`, 검증은 `make fmt`, `make lint`, `make test`, 최종 확인은 `make check`를 우선 사용합니다.
- 동작, 설정, 운영 절차가 바뀌면 `README.md` 또는 관련 문서를 함께 갱신합니다.
- Python 변경은 가능한 한 타입 힌트를 유지하고, 새 외부 계약은 테스트로 고정합니다.

## Data Pipeline
- `src/morning_brief/data/` 변경은 외부 계약 변경으로 취급합니다. fallback, retry, ranking, parser를 건드리면 회귀 테스트를 함께 수정합니다.
- 공급자별 요청 간격, 재시도, circuit breaker 규칙은 `provider_runtime`과 관련 어댑터에만 둡니다.
- 수집기는 전체 실패보다 부분 성공을 우선하고, 로그만 보고 원인을 좁힐 수 있어야 합니다.

## Safety
- `.env`, `credentials.json`, `token.json`은 읽거나 수정하지 않습니다.
- 생성 산출물과 비밀값을 커밋하지 않습니다.
- 무관한 대규모 리포맷이나 구조 변경을 끼워 넣지 않습니다.

## Commit
- 커밋 제목은 `type(scope): 한국어 요약` 형식을 사용합니다.
- 커밋 본문에는 `배경`, `변경`, `검증`을 짧게 남깁니다.

