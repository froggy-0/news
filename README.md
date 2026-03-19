# Morning Market Brief (US Tech + BTC) test

매일 오전 08:00(KST) 기준으로 미국 기술주 + 비트코인 중심 `Morning Market Brief`를 생성하고 이메일로 발송하는 단일 Python 프로젝트입니다.

## 핵심 기능
- 시장 데이터 수집: 금리/달러/VIX, 미국 지수, 빅테크 10종, BTC + ETF
  - 거시: FRED API 우선, 실패 시 yfinance 폴백
  - 공급자별 요청 간격 제어, 공통 지수 백오프 + jitter, 영구 실패 비재시도, quota 감지 시 회로 차단 적용
  - 미국 지수/기술주/BTC ETF 가격·거래량은 Stooq 우선, 실패 시 yfinance 폴백으로 고정
  - BTC ETF 보유량/순유입은 Perplexity가 공식 issuer 도메인만 참조해 구조화한 스냅샷을 캐시와 비교해 계산
- 뉴스 수집: `Perplexity Search API`를 토픽별 메인 리서치 레이어로 사용하고, 결과가 약할 때만 legacy 뉴스 경로로 보강
  - Reuters/Bloomberg/WSJ/FT/CNBC/CoinDesk 도메인 우선
  - Perplexity 품질 평가는 Perplexity 항목 기준으로만 계산하고, Grok 공식 X citation 부족이 legacy fallback을 과도하게 켜지 않도록 분리
- 브리핑 생성: OpenAI API 기반 한국어 해석형 리포트(실패 시 생성 중단, 메일 발송 스킵)
  - Jinja 템플릿 기반 프롬프트 관리 (`src/morning_brief/prompts`)
  - OpenAI `prompt_cache_key` 기반 프롬프트 캐싱 최적화
- 관측성: 단계별 duration, provider usage, 이상값 감지 결과, Perplexity audit log를 JSON으로 저장
- 이메일 발송: Gmail API
- 자동 실행: 로컬 스케줄러 또는 GitHub Actions

## 프로젝트 구조
- `main.py`: 실행 엔트리포인트
- `AGENTS.md`: Codex 작업 규칙 요약
- `.codex/config.toml`: 이 저장소 전용 Codex 설정과 multi-agent 역할 등록
- `.agents/skills/`: 저장소 전용 Codex skills
- `agents/*.toml`: subagent 역할별 Codex 설정
- `CONTRIBUTING.md`: 기여/커밋/검증 가이드
- `docs/development-standards.md`: 개발 표준과 리뷰 루브릭
- `src/morning_brief/config.py`: 환경설정 로더
- `src/morning_brief/data/market.py`: 시장 데이터 수집 (재시도 포함)
- `src/morning_brief/data/news.py`: 뉴스 수집 오케스트레이션 (Perplexity + 공식 X + legacy fallback)
- `src/morning_brief/data/news_selection.py`: 뉴스 정규화/랭킹/중복 제거 헬퍼
- `src/morning_brief/data/sources/`: FRED/Stooq/CoinGecko/Perplexity/Grok/BTC ETF 참조/공급자 정책 어댑터
- `src/morning_brief/briefing.py`: 브리핑 생성
- `src/morning_brief/prompting.py`: Jinja 프롬프트 렌더링/캐시 키 생성
- `src/morning_brief/prompts/*.j2`: 프롬프트 템플릿
- `src/morning_brief/emailer.py`: 브리핑 HTML 렌더링 + Gmail 발송
- `src/morning_brief/observability.py`: 구조화 실행 로그 / audit 파일 기록
- `src/morning_brief/pipeline.py`: 전체 파이프라인
- `src/morning_brief/scheduler.py`: 일일 스케줄러
- `.github/workflows/morning-brief.yml`: GitHub Actions 일일 실행
- `tests/`: 핵심 수집/품질 로직 테스트

## 1) 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

개발/테스트 의존성까지 설치:
```bash
pip install -r requirements-dev.txt
git config commit.template .gitmessage.txt
```

## 2) 환경변수
```bash
cp .env.example .env
```

주요 항목:
- `LOG_LEVEL` (기본 `INFO`, `DEBUG`로 변경 시 데이터 소스 선택 경로·캐시 히트 등 상세 로그 출력)
- `CACHE_DIR` (기본 `.cache`, ETF 공식 스냅샷 캐시 저장 경로)
- `OPENAI_API_KEY`
- `OPENAI_BRIEF_VALIDATION_ENABLED` (기본 `true`, 브리핑 최종 검수 사용)
- `OPENAI_BRIEF_VALIDATION_MODEL` (기본 `gpt-5-mini-2025-08-07`)
- `OPENAI_BRIEF_MAX_REWRITES` (기본 `1`, 검수 실패 시 자동 재작성 횟수)
- `OPENAI_REASONING_EFFORT` (기본 `low`)
- `OPENAI_MAX_OUTPUT_TOKENS` (기본 `50000`)
- `OPENAI_PROMPT_CACHE_KEY` (고정 프롬프트 캐시 네임스페이스)
- `PROMPT_TEMPLATE_DIR` (기본 `src/morning_brief/prompts`)
- `PROMPT_TEMPLATE_VERSION` (프롬프트 변경 시 버전 증가 권장)
- `FRED_API_KEY` (권장, 매크로 공식 소스)
- `PERPLEXITY_API_KEY` (Perplexity Search API 키)
- `PERPLEXITY_USE_SONAR_SUMMARY` (기본 `true`, Sonar Chat Completions 요약/맥락 보강 활성화. 실제 뉴스 본문은 Perplexity Search를 우선 사용)
- `PERPLEXITY_SONAR_MODEL` (기본 `sonar`)
- `PERPLEXITY_SONAR_MAX_TOKENS` (기본 `1500`, 토픽당 최대 출력)
- `GROK_API_KEY` (검증된 공식 X 시그널 조회용)
- `GROK_MODEL` (기본 `grok-4-1-fast-non-reasoning`)
- `GROK_X_KEYWORD_SEARCH_ENABLED` (기본 `true`, 키워드 기반 X Search)
- `GROK_WEB_SEARCH_ENABLED` (기본 `false`, Web Search 뉴스 수집)
- `GROK_X_SEARCH_MAX_ITEMS` (기본 `6`, X Search 최대 결과)
- `GROK_WEB_SEARCH_MAX_ITEMS` (기본 `8`, Web Search 최대 결과)
- `GEMINI_API_KEY` (Gemini Flash fallback용)
- `GEMINI_MODEL` (기본 `gemini-2.0-flash`)
- `RESEARCH_PROVIDER` (기본 `perplexity`, 토픽별 Search API를 먼저 조회)
- `ENABLE_LEGACY_NEWS_FALLBACK` (기본 `true`, 품질 비교 기간에는 켜두는 것을 권장)
- `ENABLE_OFFICIAL_X_SIGNALS` (기본 `true`, 검증된 공식 X 계정만 조회)
- `OFFICIAL_X_LOOKBACK_HOURS` (기본 `48`, 공식 X 조회 범위)
- `OFFICIAL_X_MAX_ITEMS` (기본 `4`, 공식 X 시그널 최대 반영 수)
- `GMAIL_SENDER`
- `GMAIL_RECIPIENT` (`user1@example.com,user2@example.com` 형식으로 다중 수신자 가능)
- `GMAIL_CREDENTIALS_FILE` (기본 `credentials.json`)
- `GMAIL_TOKEN_FILE` (기본 `token.json`)
- `GMAIL_OAUTH_INTERACTIVE` (로컬 OAuth 로그인 필요 시 `true`)

참고:
- `OPENAI_WEB_SEARCH_*` 환경변수는 뉴스 품질 미달 시 OpenAI web_search 백필에 사용됩니다.

## 3) Gmail API 준비 (최초 1회)
1. Google Cloud Console에서 Gmail API 활성화
2. OAuth Client ID(Desktop App) 생성
3. `credentials.json` 다운로드
4. 아래 명령으로 `token.json` 생성
```bash
.venv/bin/python generate_gmail_token.py
```
5. 브라우저 인증 완료 후 `token.json` 생성 확인

참고:
- 로컬에서는 `token.json`이 없으면 인증을 통해 자동 생성됩니다.
- GitHub Actions에서는 브라우저 인증이 불가능하므로, 로컬에서 만든 `token.json`을 Secret으로 등록해야 합니다.
- `GMAIL_RECIPIENT`는 콤마(`,`) 기준으로 여러 이메일 주소를 지정할 수 있습니다.

## 4) 실행
즉시 1회 실행:
```bash
python3 main.py once
```

브리핑 본문을 stdout으로 출력:
```bash
python3 main.py once --print-brief
```

로컬 스케줄 실행(매일 08:00 KST):
```bash
python3 main.py schedule
```

## 5) 출력
- 파일 저장: `outputs/brief_YYYYMMDD_HHMM.md`
- 관측성 로그: `outputs/observability/pipeline-run-YYYYMMDDTHHMMSSZ.json`
- Perplexity 감사 로그: `outputs/observability/perplexity-audit-YYYYMMDDTHHMMSSZ.json`
- 이메일 제목: `미국 기술주·비트코인 시장 브리핑 (YYYY-MM-DD)`
- 데이터 커버리지 저하 시 제목 아래 `[데이터 품질 알림]` 자동 표시
- OpenAI 생성 실패 시 브리핑 파일과 메일 발송은 건너뛰고 관측성 요약만 남깁니다.
- 구조 검증에 실패해 안전 기본 브리핑으로 대체되면 observability 요약 상태는 `brief_fallback`으로 기록됩니다.
- 이메일 본문: HTML + plain text fallback 동시 전송
- 비트코인 ETF 공식 보유량/순유입: Perplexity가 공식 issuer 도메인을 바탕으로 정리한 참조 스냅샷을 캐시와 비교해 계산
- 검증된 공식 X 시그널: allowlist에 등록된 공식 계정만 Grok `x_search`로 확인해 뉴스와 함께 반영

## 6) 수집 신뢰성 운영 원칙
- LLM provider 역할은 고정합니다.
  - Perplexity: 뉴스 수집, 출처 URL 추적, BTC ETF structured response, Sonar 맥락 보강
    - 실제 뉴스 아이템은 Perplexity Search가 1순위이고, Sonar citations는 Search 결과가 비었을 때만 보조로 사용
  - Grok: 공식 X 실시간 시그널 + 키워드 기반 시장 반응 수집
  - OpenAI: 브리핑 생성과 검수(fallback)만 담당
  - OpenAI: 브리핑 생성과 검수 담당
  - Gemini: Perplexity 0건 시 Google Search grounding fallback
- 공급자별로 요청 간격과 재시도 규칙이 다르게 적용됩니다. `404` 같은 영구 실패는 바로 중단하고, `429/5xx/timeout` 중심으로만 다시 시도합니다.
- HTTP 요청뿐 아니라 Perplexity/Grok SDK 호출과 yfinance 폴백도 공통 `provider_runtime` 계층의 지수 백오프와 provider별 간격 제어를 따릅니다.
- Alpha Vantage free tier는 구조적 quota 한계 때문에 비활성화했고, 시장 가격 수집은 Stooq/yfinance 경로로 고정했습니다.
- BTC ETF 참조 수집은 `IBIT`, `BITB`, `GBTC`를 대상으로 Perplexity structured query를 사용하되 공식 issuer 도메인만 허용합니다.
- GDELT는 제거했고, legacy 뉴스 fallback은 RSS와 NewsAPI만 사용합니다.
- Perplexity legacy fallback은 Perplexity 기사 자체의 개수/신선도/도메인/근거 링크 기준으로 판단합니다. 공식 X 항목의 citation 부족은 별도 취급합니다.
- 파이프라인 종료 시 공급자별 요청/성공/실패/재시도/skip 요약 로그를 남깁니다.
- 이상값 검증은 canonical key 기준으로 수행하고, 생략/전일 대체 결과를 브리핑 footer note와 관측성 로그에 함께 남깁니다.

## 7) 테스트
```bash
pytest -q
```

## 8) 개발 워크플로우

권장 명령:

```bash
make fmt
make lint
make test
make typecheck
make check
make validate-pre-commit
```

주요 개발 규칙:
- 커밋 제목 형식은 `type(scope): 한국어 요약`
- 상세 기준은 `docs/development-standards.md`
- 변경 유형별 회귀 기준은 `docs/ai-evals.md`
- Codex용 단축 규칙은 `AGENTS.md`
- Python 변경은 `ruff format`, `ruff check`, `pytest`를 모두 통과해야 완료로 봅니다.

### Codex 프로젝트 설정
- 루트 `AGENTS.md`: 저장소 전체 공통 규칙
- 하위 `src/morning_brief/data/AGENTS.md`: 데이터 수집 계층 전용 규칙
- `.codex/config.toml`: 이 저장소에서 `multi_agent`, runtime metrics, project instruction fallback을 켭니다.
- `.agents/skills/`: 반복 작업용 repo skill을 자동 발견합니다.
- `agents/*.toml`: `explorer`, `pipeline_investigator`, `docs_researcher` 역할별 기본 설정입니다.

참고:
- Codex 공식 규칙 파일명은 `AGENTS.md`입니다.
- 이 저장소는 fallback 파일명으로 `agent.md`, `.agents.md`도 인식하도록 `.codex/config.toml`에 등록했습니다.
- project-scoped `.codex/config.toml`은 Codex가 이 저장소를 trusted project로 인식할 때만 로드됩니다.

## 9) 프롬프트 엔지니어링 참고
- OpenAI Prompt Engineering: <https://platform.openai.com/docs/guides/prompt-engineering>
- OpenAI Prompt Caching: <https://platform.openai.com/docs/guides/prompt-caching>
- OpenAI Responses API: <https://platform.openai.com/docs/api-reference/responses/create>

## 10) GitHub Actions 운영
워크플로우는 `.github/workflows/morning-brief.yml`에 포함되어 있습니다.

스케줄:
- `0 23 * * *` (UTC) = 매일 08:00 KST

필수 GitHub Secrets:
- `OPENAI_API_KEY`
- `FRED_API_KEY`
- `GMAIL_SENDER`
- `GMAIL_RECIPIENT`
- `GMAIL_CREDENTIALS_JSON_B64`
- `GMAIL_TOKEN_JSON_B64`

선택 GitHub Secrets:
- `PERPLEXITY_API_KEY`
- `GROK_API_KEY`
- `NEWSAPI_KEY`
- `GEMINI_API_KEY`

선택 GitHub Variables:
- `OPENAI_MODEL` (기본 `gpt-5-mini-2025-08-07`)
- `OPENAI_BRIEF_VALIDATION_ENABLED` (기본 `true`)
- `OPENAI_BRIEF_VALIDATION_MODEL` (기본 `gpt-5-mini-2025-08-07`)
- `OPENAI_BRIEF_MAX_REWRITES` (기본 `1`)
- `OPENAI_REASONING_EFFORT` (기본 `low`)
- `OPENAI_MAX_OUTPUT_TOKENS` (기본 `50000`)
- `OPENAI_PROMPT_CACHE_KEY` (기본 `morning-market-brief`)
- `PROMPT_TEMPLATE_VERSION` (기본 `market_brief_v4`)
- `RESEARCH_PROVIDER` (기본 `perplexity`)
- `ENABLE_LEGACY_NEWS_FALLBACK` (기본 `true`)
- `GROK_MODEL` (기본 `grok-4-1-fast-non-reasoning`)
- `ENABLE_OFFICIAL_X_SIGNALS` (기본 `true`)
- `OFFICIAL_X_LOOKBACK_HOURS` (기본 `48`)
- `OFFICIAL_X_MAX_ITEMS` (기본 `4`)

워크플로우는 날짜 단위 key로 아래 캐시를 복원/저장합니다.
- BTC ETF 참조 스냅샷: `btc-etf-snapshots-YYYYMMDD`
- 마지막 성공 시장 지표: `market-snapshot-YYYYMMDD`
- pip 의존성: `pip-{requirements 해시}`

각 캐시는 날짜 prefix restore-keys를 사용하고, miss가 나도 파이프라인은 계속 실행됩니다. 캐시 상태는 `outputs/observability` 요약 로그에 함께 기록됩니다.
브리핑 본문은 생성 후 한 번 더 OpenAI 검수를 거치고, 일반인이 이해하기 어려운 표현이나 숫자-해석 불일치가 있으면 최대 1회 자동으로 다시 다듬습니다.
품질 게이트는 `python -m ruff format --check .`, `python -m ruff check .`, `python -m pytest -q` 순서로 실행됩니다.

### base64 생성 예시 (macOS)
```bash
base64 -i credentials.json | tr -d '\n' | pbcopy
base64 -i token.json | tr -d '\n' | pbcopy
```
복사된 값을 각각 `GMAIL_CREDENTIALS_JSON_B64`, `GMAIL_TOKEN_JSON_B64`에 넣으면 됩니다.

`pbcopy` 동작 참고:
- `pbcopy`는 터미널 출력이 없는 것이 정상입니다. (클립보드로만 복사)
- 확인 명령: `pbpaste | wc -c`
- 줄바꿈 제거 출력 시 끝에 보이는 `%`는 zsh 프롬프트이며 base64 값이 아닙니다.

## 11) 최초 점검 실행
Secrets/Variables 등록이 끝났다면 바로 실행 가능합니다.

- GitHub: Actions -> `Morning Market Brief` -> `Run workflow` (수동 실행)
- 로컬 1회 점검:
```bash
SEND_EMAIL=false python3 main.py once --print-brief
```
