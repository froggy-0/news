# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Sovereign Brief** — AI 기반 한국어 시장/기술 브리핑 서비스. 매일 오전 8시(KST) 파이프라인이 실행되어 시장 데이터·뉴스를 수집하고 LLM으로 브리핑을 생성한 뒤 이메일(AWS SES)로 발송하고 프론트엔드(Cloudflare Pages)에 게시합니다.

## Commands

### Python Backend

```bash
make fmt          # Ruff 포매팅 + 자동 수정
make lint         # Ruff 포맷/린트 검사
make typecheck    # mypy strict 타입 검사
make test         # pytest 전체 실행
make check        # lint + test + typecheck 통합 검사
make sentiment-join # 감성-시계열 결합 분석용 Parquet 생성

# 단일 테스트 실행
pytest tests/test_brief_review.py -v
pytest tests/test_pipeline_quality.py::test_name -v

# 파이프라인 직접 실행
python main.py once               # 브리핑 1회 실행
python main.py once --print-brief # 실행 후 결과 출력
python main.py schedule           # 매일 08:00 KST 스케줄 실행

# 분석 배치 직접 실행
./scripts/build_sentiment_join.py
SENTIMENT_JOIN_LOOKBACK_DAYS=90 make sentiment-join
FUTURES_LAMBDA_ARN=arn:aws:lambda:ap-northeast-2:...:function:binance-futures-fetcher make sentiment-join

# Lambda 수동 배포 (선물 데이터 프록시)
bash lambda/binance_futures/deploy.sh
```

### Frontend

```bash
cd frontend

npm run dev              # 개발 서버 (R2 데이터 소스)
npm run dev:fixture      # 개발 서버 (fixture 데이터)
npm run dev:output       # 개발 서버 (로컬 output JSON)

npm run build            # 정적 빌드
npm run build:fixture    # fixture 데이터로 빌드
npm run lint             # TypeScript 타입 검사
npm test                 # Node test runner
npm run qa:playwright    # Playwright QA 캡처

npm run deploy:preview      # Cloudflare preview 배포
npm run deploy:production   # Cloudflare production 배포
```

## Architecture

### Backend Pipeline (8단계)

`main.py` → `src/morning_brief/pipeline.py`의 `run_pipeline()` 진입점.

| 단계 | 모듈 | 역할 |
|------|------|------|
| 1. Market Data | `data/market.py` | FRED(거시), KIS(지수·환율), yfinance(주식 fallback), CoinGecko(BTC), ETF 공식 사이트 |
| 2. Keywords | `data/market.py` | VIX 스파이크·금리·지수·BTC 변동 감지 → 검색 토픽 생성 |
| 3. News | `data/news.py` | Grok X 신호 → Perplexity Sonar → Grok 키워드 검색 → fallback(Gemini/RSS) |
| 3.5. Sentiment | `data/finbert_sentiment.py` | ProsusAI/finbert로 뉴스·X시그널 영문 원본에 감성 점수(-1~1) 부여. `FINBERT_ENABLED=false`로 비활성화 가능. 선택적 의존성(`requirements-ml.txt`) |
| 4. Context | `data/sources/` | 상위 12개 뉴스 Perplexity 교차 분석 |
| 5. Quality | `data/data_quality.py` | ok / degraded / critical 품질 판정 |
| 6. Backfill | `data/sources/` | 뉴스 부족 시 OpenAI web_search 보완 |
| 7. Generate | `briefing.py` + `brief_review.py` | Jinja2 → GPT-4 → 검증 → 재작성(최대 1회) |
| 8. Publish | `emailer.py`, `public_site.py` | AWS SES 발송 + R2 JSON/HTML 업로드 |

**핵심 모듈:**
- `src/morning_brief/pipeline.py` — 전체 오케스트레이션
- `src/morning_brief/config.py` — 환경변수 + 기본값
- `src/morning_brief/observability.py` — 구조화 로깅
- `src/morning_brief/templates/` — Jinja2 이메일/마크다운 템플릿
- `src/morning_brief/prompts/` — LLM 프롬프트
- `src/morning_brief/data/finbert_sentiment.py` — FinBERT 감성 분석 (선택적)

### Sentiment Join Analysis Pipeline

기존 브리핑 발송 파이프라인과 분리된 분석용 배치입니다.

- 진입점: `scripts/build_sentiment_join.py`
- Make 타겟: `make sentiment-join`
- 구현 위치: `src/morning_brief/analysis/sentiment_join/`
- 출력물: `data/sentiment_join/master_{YYYYMMDD}.parquet`
- 주요 환경변수:
  - `SENTIMENT_JOIN_LOOKBACK_DAYS`
  - `SENTIMENT_JOIN_OUTPUT_DIR`
  - `SENTIMENT_JOIN_R2_MAX_CONCURRENCY`
  - `SENTIMENT_JOIN_RETAIN_DAYS`
  - `FUTURES_LAMBDA_ARN` — ap-northeast-2 Lambda ARN (설정 시 Binance fapi 직접 호출 건너뜀)
- 선물 데이터 fallback 체인: Lambda(ap-northeast-2) → Bybit 공개 API → NaN 프레임
- Lambda 인프라: `lambda/binance_futures/` (ARM64, Python 3.11, stdlib만 사용, 수동 배포)
- 분석 의존성: `requirements-analysis.txt` (`pandera`, `pyarrow`, `pandas`, `numpy`)

### Frontend

Next.js 15 App Router + SSG(`output: 'export'`), Cloudflare Pages 배포.

- `frontend/app/` — 페이지 라우팅 (archive, subscribe, unsubscribe, privacy)
- `frontend/components/` — 도메인별 React 컴포넌트 (brief, market, news, bitcoin, signals 등)
- `frontend/functions/api/subscriptions/` — Cloudflare Pages Functions (구독 API)
- `frontend/lib/` — 유틸리티 (subscriptions, mail)
- `schema/brief.types.ts` — 백엔드↔프론트엔드 공유 데이터 계약

### Data Sources

- **시장**: FRED, KIS, yfinance, CoinGecko, BlackRock/Bitwise 공식 ETF 페이지
- **뉴스**: Perplexity (Sonar/Search), Grok (X API + 웹 검색), Gemini Grounding, RSS/NewsAPI
- **LLM**: OpenAI GPT-4 (브리핑 생성·검증)
- **NLP**: ProsusAI/finbert (뉴스·시그널 감성 점수, 선택적 — `requirements-ml.txt`)
- **DB**: Supabase PostgreSQL (구독자 관리)

## Development Rules

`AGENTS.md`와 `docs/development-standards.md`에 상세 기준이 있습니다. 핵심 규칙:

1. **검증 순서**: `make fmt` → `make lint` → `make test` → `make typecheck` → `make check`
2. **변경 범위 최소화**: 무관한 리팩터·리포맷을 섞지 않습니다.
3. **`src/morning_brief/data/` 변경** = 외부 공급자 계약 변경으로 취급 → fallback, retry, ranking, parser, provider policy를 건드리면 관련 pytest를 함께 수정합니다.
4. **동작·설정 변경 시** `README.md` 또는 가장 가까운 문서를 같은 커밋에서 갱신합니다.
5. **커밋 형식**: `type(scope): 한국어 요약` (type: feat/fix/refactor/perf/test/docs/ci/chore)

## Key Constraints

- Python 3.11 호환성 유지 (CI 기준)
- `.env*`, `credentials.json`, `token.json`은 읽거나 수정하지 않습니다.
- 경고 로그는 운영 신호여야 합니다 — 잡음 로그를 추가하지 않습니다.
- `404`는 재시도하지 않고, `429/5xx/timeout` 중심으로만 재시도합니다. `451`(지역 제한)도 재시도하지 않습니다.
- `FUTURES_LAMBDA_ARN` 설정 시 Binance fapi 직접 호출을 건너뜁니다 — GitHub Actions(US IP)에서 451 차단 우회 목적입니다.
- 집계 로직은 부분 성공을 허용해 한 소스 실패가 전체를 망가뜨리지 않도록 설계합니다.
