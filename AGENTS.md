# AGENTS.md

이 저장소의 상세 기준은 `docs/development-standards.md`를 따릅니다. 이 파일에는 Codex가 항상 먼저 따라야 하는 짧은 실행 규칙만 둡니다.

- 기본 검증 순서는 `make fmt`, `make lint`, `make test`, `make typecheck`, `make check`입니다. 반복 작업 중에는 가장 좁은 범위의 명령부터 실행합니다.
- 변경 범위는 최소화합니다. 무관한 리팩터, 대규모 리포맷, 생성 산출물 갱신을 끼워 넣지 않습니다.
- `src/morning_brief/data/` 변경은 외부 공급자 계약 변경으로 취급합니다. fallback, retry, ranking, parser, provider policy를 건드리면 관련 pytest를 함께 수정합니다.
- 동작, 설정, 운영 절차가 바뀌면 `README.md` 또는 가장 가까운 문서를 같은 커밋에서 갱신합니다.
- `.env*`, `credentials.json`, `token.json`은 읽거나 수정하지 않습니다. 비밀값과 생성 산출물은 커밋하지 않습니다.
