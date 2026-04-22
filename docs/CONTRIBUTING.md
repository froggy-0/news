# Contributing

이 저장소는 작은 변경을 빠르게 검증하는 흐름을 기준으로 운영합니다. 상세 원칙은 `docs/development-standards.md`를 참고하세요.

## 빠른 시작

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
git config commit.template .gitmessage.txt
```

## 기본 작업 흐름

1. 관련 코드, 테스트, 문서를 먼저 읽습니다.
2. 변경은 가능한 한 하나의 책임으로 묶습니다.
3. 동작을 바꾸면 테스트와 문서를 함께 갱신합니다.
4. 최종 제출 전 `make check`를 실행합니다.

## 브랜치와 커밋

- 브랜치 이름은 `codex/<topic>` 또는 목적이 드러나는 짧은 이름을 사용합니다.
- 커밋 제목 형식은 `type(scope): 한국어 요약`입니다.
- 권장 `type`: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `ci`, `chore`

예시:

```text
fix(news): Perplexity fallback 기준을 분리한다
refactor(market): ETF 일봉 호출을 단일 응답으로 통합한다
docs(dev): 에이전트 작업 규칙과 검증 절차를 정리한다
```

## 검증 명령

```bash
make fmt
make lint
make test
make check
```

## 리뷰 기준

- 동작이 더 정확해졌는지
- 폴백과 로그가 더 일관적인지
- 테스트가 회귀를 막는 수준인지
- README와 운영 문서가 최신 상태인지

