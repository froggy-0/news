# Morning Market Brief (US Tech + BTC)

매일 오전 08:00(KST) 기준으로 미국 기술주 + 비트코인 중심 `Morning Market Brief`를 생성하고 이메일로 발송하는 단일 Python 프로젝트입니다.

## 핵심 기능
- 시장 데이터 수집: 금리/달러/VIX, 미국 지수, 빅테크 10종, BTC + ETF
  - 거시: FRED API 우선, 실패 시 yfinance 폴백
  - 공급자별 요청 간격 제어, 영구 실패 비재시도, quota 감지 시 회로 차단 적용
  - Alpha Vantage는 ETF 가격/거래량을 동일 응답에서 함께 읽어 불필요한 중복 호출 제거
  - 공식 BTC ETF 발행사 페이지는 issuer별 부분 성공을 허용해 한 곳 실패가 전체 스냅샷을 무너뜨리지 않도록 구성
- 뉴스 수집: `Perplexity Search API`를 토픽별 메인 리서치 레이어로 사용하고, 결과가 약할 때만 legacy 뉴스 경로로 보강
  - Reuters/Bloomberg/WSJ/FT/CNBC/CoinDesk 도메인 우선
  - Perplexity 품질 평가는 Perplexity 항목 기준으로만 계산하고, Grok 공식 X citation 부족이 legacy fallback을 과도하게 켜지 않도록 분리
- 브리핑 생성: OpenAI API 기반 한국어 해석형 리포트(실패 시 템플릿 폴백)
  - Jinja 템플릿 기반 프롬프트 관리 (`src/morning_brief/prompts`)
  - OpenAI `prompt_cache_key` 기반 프롬프트 캐싱 최적화
- 이메일 발송: Gmail API
- 자동 실행: 로컬 스케줄러 또는 GitHub Actions

## 프로젝트 구조
- `main.py`: 실행 엔트리포인트
- `src/morning_brief/config.py`: 환경설정 로더
- `src/morning_brief/data/market.py`: 시장 데이터 수집 (재시도 포함)
- `src/morning_brief/data/news.py`: 뉴스 수집 (우선소스 + 백필)
- `src/morning_brief/data/sources/`: FRED/GDELT/Stooq/CoinGecko/Perplexity/Grok/공식 ETF/공급자 정책 어댑터
- `src/morning_brief/briefing.py`: 브리핑 생성
- `src/morning_brief/prompting.py`: Jinja 프롬프트 렌더링/캐시 키 생성
- `src/morning_brief/prompts/*.j2`: 프롬프트 템플릿
- `src/morning_brief/emailer.py`: Gmail 발송
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
```

## 2) 환경변수
```bash
cp .env.example .env
```

주요 항목:
- `CACHE_DIR` (기본 `.cache`, ETF 공식 스냅샷 캐시 저장 경로)
- `OPENAI_API_KEY`
- `OPENAI_BRIEF_VALIDATION_ENABLED` (기본 `true`, 브리핑 최종 검수 사용)
- `OPENAI_BRIEF_VALIDATION_MODEL` (기본 `gpt-5-mini`)
- `OPENAI_BRIEF_MAX_REWRITES` (기본 `1`, 검수 실패 시 자동 재작성 횟수)
- `OPENAI_REASONING_EFFORT` (기본 `low`)
- `OPENAI_MAX_OUTPUT_TOKENS` (기본 `1700`)
- `OPENAI_PROMPT_CACHE_KEY` (고정 프롬프트 캐시 네임스페이스)
- `OPENAI_WEB_SEARCH_ENABLED` (기본 `true`, 뉴스 품질 저하 시 OpenAI web search 검증 사용)
- `OPENAI_WEB_SEARCH_MODEL` (기본 `gpt-5-mini`)
- `OPENAI_WEB_SEARCH_MAX_RESULTS` (기본 `3`)
- `PROMPT_TEMPLATE_DIR` (기본 `src/morning_brief/prompts`)
- `PROMPT_TEMPLATE_VERSION` (프롬프트 변경 시 버전 증가 권장)
- `FRED_API_KEY` (권장, 매크로 공식 소스)
- `ALPHA_VANTAGE_API_KEY` (선택 권장, 미국 주식/ETF 일봉 API 소스)
- `PERPLEXITY_API_KEY` (Perplexity Search API 키)
- `GROK_API_KEY` (검증된 공식 X 시그널 조회용)
- `GROK_MODEL` (기본 `grok-4.20-beta-latest-non-reasoning`)
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
- 이메일 제목: `미국 기술주·비트코인 시장 브리핑 (YYYY-MM-DD)`
- 데이터 커버리지 저하 시 제목 아래 `[데이터 품질 알림]` 자동 표시
- 이메일 본문: HTML + plain text fallback 동시 전송
- 비트코인 ETF 공식 보유량/순유입: 발행사 공식 페이지 스냅샷을 캐시와 비교해 계산
- 검증된 공식 X 시그널: allowlist에 등록된 공식 계정만 Grok `x_search`로 확인해 뉴스와 함께 반영

## 6) 수집 신뢰성 운영 원칙
- 공급자별로 요청 간격과 재시도 규칙이 다르게 적용됩니다. `404` 같은 영구 실패는 바로 중단하고, `429/5xx/timeout` 중심으로만 다시 시도합니다.
- Alpha Vantage가 quota 또는 burst 제한을 반환하면 그 실행에서는 이후 Alpha Vantage 요청을 중단하고 Stooq/yfinance로 일관되게 넘깁니다.
- 공식 BTC ETF 수집은 `IBIT`, `BITB`, `GBTC`를 issuer별로 독립 처리합니다. 한 발행사 페이지가 깨져도 나머지 스냅샷은 유지합니다.
- Perplexity legacy fallback은 Perplexity 기사 자체의 개수/신선도/도메인/근거 링크 기준으로 판단합니다. 공식 X 항목의 citation 부족은 별도 취급합니다.
- 파이프라인 종료 시 공급자별 요청/성공/실패/재시도/skip 요약 로그를 남깁니다.

## 7) 테스트
```bash
pytest -q
```

## 8) 프롬프트 엔지니어링 참고
- OpenAI Prompt Engineering: <https://platform.openai.com/docs/guides/prompt-engineering>
- OpenAI Prompt Caching: <https://platform.openai.com/docs/guides/prompt-caching>
- OpenAI Responses API: <https://platform.openai.com/docs/api-reference/responses/create>
- Anthropic Prompt Engineering Overview: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview>
- Anthropic Prompt Caching: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching>

## 9) GitHub Actions 운영
워크플로우는 `.github/workflows/morning-brief.yml`에 포함되어 있습니다.

스케줄:
- `57 22 * * *` (UTC) = 매일 07:57 KST

필수 GitHub Secrets:
- `OPENAI_API_KEY`
- `FRED_API_KEY`
- `GMAIL_SENDER`
- `GMAIL_RECIPIENT`
- `GMAIL_CREDENTIALS_JSON_B64`
- `GMAIL_TOKEN_JSON_B64`

선택 GitHub Secrets:
- `ALPHA_VANTAGE_API_KEY`
- `PERPLEXITY_API_KEY`
- `GROK_API_KEY`
- `NEWSAPI_KEY`

선택 GitHub Variables:
- `OPENAI_MODEL` (기본 `gpt-5-mini`)
- `OPENAI_BRIEF_VALIDATION_ENABLED` (기본 `true`)
- `OPENAI_BRIEF_VALIDATION_MODEL` (기본 `gpt-5-mini`)
- `OPENAI_BRIEF_MAX_REWRITES` (기본 `1`)
- `OPENAI_REASONING_EFFORT` (기본 `low`)
- `OPENAI_MAX_OUTPUT_TOKENS` (기본 `1700`)
- `OPENAI_PROMPT_CACHE_KEY` (기본 `morning-market-brief`)
- `PROMPT_TEMPLATE_VERSION` (기본 `market_brief_v3`)
- `OPENAI_WEB_SEARCH_ENABLED` (기본 `true`)
- `OPENAI_WEB_SEARCH_MODEL` (기본 `gpt-5-mini`)
- `OPENAI_WEB_SEARCH_MAX_RESULTS` (기본 `3`)
- `RESEARCH_PROVIDER` (기본 `perplexity`)
- `ENABLE_LEGACY_NEWS_FALLBACK` (기본 `true`)
- `GROK_MODEL` (기본 `grok-4.20-beta-latest-non-reasoning`)
- `ENABLE_OFFICIAL_X_SIGNALS` (기본 `true`)
- `OFFICIAL_X_LOOKBACK_HOURS` (기본 `48`)
- `OFFICIAL_X_MAX_ITEMS` (기본 `4`)

워크플로우는 `.cache/btc_etf/official_snapshots.json`을 GitHub Actions 캐시로 복원/저장합니다.
이 파일을 기준으로 다음 실행에서 비트코인 ETF 공식 보유량의 전일 대비 순유입/순유출을 계산합니다.
뉴스 품질이 낮을 때는 OpenAI `web_search`를 사용해 Reuters/Bloomberg/WSJ/FT/CNBC/CoinDesk 등 허용 도메인 안에서만 검증용 백필을 시도합니다.
브리핑 본문은 생성 후 한 번 더 OpenAI 검수를 거치고, 일반인이 이해하기 어려운 표현이나 숫자-해석 불일치가 있으면 최대 1회 자동으로 다시 다듬습니다.

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

## 10) 최초 점검 실행
Secrets/Variables 등록이 끝났다면 바로 실행 가능합니다.

- GitHub: Actions -> `Morning Market Brief` -> `Run workflow` (수동 실행)
- 로컬 1회 점검:
```bash
SEND_EMAIL=false python3 main.py once --print-brief
```
