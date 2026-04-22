# SOVEREIGN BRIEF

암호화폐 시장과 거시경제 데이터를 수집·분석하여, 한국 시간 아침에 읽을 수 있는 시장 브리핑을 자동 생성하고 이메일로 발송하는 프로젝트입니다.

단순한 뉴스 모음이 아니라, 정량 데이터와 감성 분석을 결합해 "오늘 시장을 어떻게 봐야 하는지"를 일관된 형식으로 정리하는 데 목적이 있습니다.

## 프로젝트 구조

이 프로젝트는 세 개의 독립 파이프라인으로 구성됩니다.

1. **브리핑 파이프라인** — 시장 데이터 + 뉴스 수집 → LLM 브리핑 생성 → 이메일 발송
2. **Sentiment Join 파이프라인** — 감성·심리 지표 시계열 조인 → 통계 검정 → Alpha Validation
3. **프론트엔드** — Next.js SSG + Cloudflare Pages 공개 브리핑 사이트

## 수집 데이터

### 시장 데이터

| 데이터 | 소스 | 폴백 |
|---|---|---|
| BTC 현물 가격·거래량 | Binance Spot klines | KIS → yfinance |
| BTC 선물 지표 (펀딩비, 미결제약정, Long/Short Ratio) | Lambda 프록시 → Binance FAPI | Bybit 공개 API → NaN |
| BTC ETF 보유량·순유입 | 공식 발행사 (IBIT, BITB 등) | HTML fallback |
| Fear & Greed Index | alternative.me | — |
| USD/KRW 환율 | KIS 일봉 API | yfinance KRW=X |
| VIX | FRED API | — (optional) |
| 미국 금리·달러·하이일드 스프레드 | FRED API | yfinance |
| 미국 주요 지수·기술주 | KIS API | yfinance |
| 한국 지수 (KOSPI, KOSDAQ) | KIS API | yfinance |

### 뉴스·시그널

| 소스 | 역할 |
|---|---|
| Perplexity Sonar | 토픽별 요약 + citation 기반 뉴스 추출 (1차) |
| Perplexity Search | 키워드 기반 뉴스 검색 |
| Grok 공식 X 시그널 | allowlist 계정의 실시간 시그널 |
| Grok X 키워드 검색 | 시장 반응 시그널 |
| Grok Web Search | 웹 검색 보강 (선택) |
| Gemini Grounding | Perplexity 0건 시 대체 |
| Google News RSS | 레거시 폴백 |
| NewsAPI | 레거시 폴백 |

### 감성 분석

- ProsusAI/finbert 모델로 영문 원본 텍스트에 -1.0~1.0 연속 감성 점수 부여
- 뉴스, X 시그널, 공개 뉴스 카드에 각각 적용
- `FINBERT_ENABLED=false`로 비활성화 가능, ML 의존성 미설치 환경에서도 파이프라인 정상 동작

## 브리핑 파이프라인

```
시장 데이터 수집 → 뉴스·시그널 수집 → FinBERT 감성 분석
→ Sonar 맥락 보강 → 데이터 품질 평가 → OpenAI 브리핑 생성
→ 브리핑 검증·재작성 → 공개 JSON 발행 (R2) → 이메일 발송 (SES)
```

- OpenAI GPT 모델로 한국어 브리핑 생성 (Jinja2 템플릿 기반)
- 브리핑 품질 검증 후 필요 시 자동 재작성 (최대 1~2회)
- Sentiment Join 파이프라인의 하이브리드 지수·통계 검정 결과를 브리핑에 반영

### 이메일 발송

- AWS SES (ap-northeast-2) 경유, sender: `no-reply@sovereignbriefing.com`
- Supabase 구독 저장소에서 active 구독자만 조회하여 개별 발송
- HTML + plain text 이중 포맷
- HMAC-SHA256 기반 구독 해지 토큰 (30일 TTL)

### 공개 산출물

- Cloudflare R2에 JSON 업로드 (index, briefs, news, signals)
- R2 미설정 시 로컬 `outputs/public`에만 저장, 파이프라인 계속 진행
- 공개 뉴스 카드용 한국어 해설·시장 함의 별도 생성 (선택)

## Sentiment Join 파이프라인

브리핑과 독립된 분석용 배치입니다. 감성·심리 지표와 BTC 수익률 간의 통계적 관계를 검증합니다.

```
데이터 수집 (BTC 가격, 감성, FNG, 선물, ETF, VIX, USD/KRW)
→ 날짜 정규화·forward-fill → inner join → 수익률 계산
→ 이상값 필터 (Z-score) → ADF+KPSS 정상성 검정
→ Granger 인과 검정 (63 검정, BH-FDR 보정)
→ VIF + PCA → 하이브리드 지수 (full/core)
→ Lag-1 컬럼 생성 → Alpha Validation
→ Parquet 저장 + R2 업로드
```

### 하이브리드 지수

감성·심리 지표를 PCA로 결합한 0~100 종합 점수입니다.

| 지수 | 입력 feature | VIF gate |
|---|---|---|
| full | 뉴스 감성, FNG, 펀딩비, Long/Short Ratio, ETF 순유입, 거래량 변화, VIX | 적용 (threshold=10) |
| core | 뉴스 감성, FNG, 펀딩비, 거래량 변화 | 미적용 (큐레이션) |

- fng_value_lag1을 부호 앵커로 사용하여 두 지수의 방향성 통일
- 모든 feature는 Lag-1 값을 사용하여 look-ahead bias 방지
- `full`은 항상 저장되지만, ETF history가 `btc_etf_gold`에서 충분히 확보되지 않거나 futures OI/LSR coverage가 낮으면 일부 feature를 제외한 채 `degraded` 상태로 기록됩니다.

### Alpha Validation

하이브리드 지수와 감성 지표가 실제로 BTC 가격 방향을 맞추는지 정량 검증합니다.

| 분석 | 내용 |
|---|---|
| Hit Rate | 5개 predictor의 방향 적중률, Confusion Matrix, Precision/Recall/F1 |
| Correlation | Pearson (정상성 기반 차분) + Spearman, predictor 간 다중공선성 포함 |
| Backtest | 신호 기반 매수/현금 전략 누적 수익률 vs Buy & Hold, Alpha, Sharpe, Max Drawdown |
| Walk-Forward | 120일 train / 30일 test rolling window, out-of-sample 성능 평가 (full + core) |

5개 Predictor: `news_sentiment_mean_lag1`(0), `fng_value_lag1`(50), `vix_lag1`(24, 반전), `full_hybrid_index_score_lag1`(50), `core_hybrid_index_score_lag1`(50)

모든 결과는 Parquet 메타데이터(`sentiment_join_stats`)에 JSON으로 저장됩니다.
`structured_sources`에는 `btc_etf`와 `futures`의 source mode, coverage, quality status가 함께 저장됩니다.

### 실행

```bash
# 기본 180일
make sentiment-join

# 360일 (Granger 검정력 향상, Walk-Forward fold 증가)
SENTIMENT_JOIN_LOOKBACK_DAYS=360 make sentiment-join

# 결과 확인
python scripts/inspect_sentiment_join_parquet.py data/sentiment_join/
```

### 뉴스 감성 백필

```bash
# 과거 뉴스 감성 데이터 수집 (CoinDesk + Alpaca, 최대 460일)
python scripts/backfill_news_sentiment.py --start 2025-01-01 --end 2026-04-18
```

### BTC 선물 OI/LSR 백필

```bash
# 로컬 전용: Coinalyze daily history로 OI/LSR 백필
python scripts/backfill_btc_futures.py --provider coinalyze --start 2025-04-24 --end 2026-04-18
```

- `COINALYZE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 환경변수가 필요합니다.
- Coinalyze OI는 기존 Binance daily 계약과 맞추기 위해 `date + 1일`로 저장합니다.
- ETF history는 `btc_etf_gold`에 의존하며, 최신 스냅샷 fallback은 historical backfill로 취급하지 않습니다.
- futures는 funding / OI / LSR를 분리 평가하며, OI/LSR coverage 미달 시 분석 입력에서 제외됩니다.

## 프론트엔드

- Next.js App Router 기반 SSG
- Cloudflare Pages 배포
- Cloudflare Pages Functions API (구독 관리)
- R2 JSON 소비
- RSS 피드, llms.txt 자동 생성

## 실행 방법

### 환경 설정

```bash
# 로컬 .env에 필수 키 설정: OPENAI_API_KEY, PERPLEXITY_API_KEY, KIS_APP_KEY/SECRET 등
```

### 브리핑 파이프라인

```bash
python scripts/validate_credentials.py  # 인증정보 사전 검증
python -m morning_brief                  # 또는 GitHub Actions workflow_dispatch
```

### 검증

```bash
make fmt        # 포맷
make lint       # 린트
make test       # 테스트
make typecheck  # 타입 체크
make check      # 전체 (위 4개 순차 실행)
```

## GitHub Actions

| 워크플로우 | 트리거 | 내용 |
|---|---|---|
| Generate Sovereign Briefing | workflow_dispatch | 브리핑 생성 → sentiment join → 프론트엔드 배포 |
| Build Sentiment Join | workflow_dispatch | sentiment join 단독 실행 |
| CI | push to main, PR | fmt, lint, test, typecheck |

## 문서

| 문서 | 내용 |
|---|---|
| [docs/data-flow.md](docs/data-flow.md) | 데이터 수집·정제 전체 흐름 |
| [docs/data-sources.md](docs/data-sources.md) | 데이터 소스별 명세 |
| [docs/data-source-reliability.md](docs/data-source-reliability.md) | 소스 신뢰도 기준 |
| [docs/development-standards.md](docs/development-standards.md) | 개발 규칙 |
| [docs/ai-evals.md](docs/ai-evals.md) | AI 품질 점검 기준 |
| [docs/logging-ops.md](docs/logging-ops.md) | 로깅 운영 가이드 |
| [docs/llm-cost-ops.md](docs/llm-cost-ops.md) | LLM 비용 운영 |
| [docs/codex-ops.md](docs/codex-ops.md) | Codex 운영 가이드 |
| [docs/subscriptions-ops.md](docs/subscriptions-ops.md) | 구독 운영 가이드 |
