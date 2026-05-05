# SOVEREIGN BRIEF

암호화폐 시장과 거시경제 데이터를 수집·분석하여 한국 시간 아침에 읽을 수 있는 시장 브리핑을 자동 생성하고 이메일로 발송하는 프로젝트입니다.

단순한 뉴스 모음이 아니라, 정량 데이터와 감성 분석을 결합해 "오늘 시장을 어떻게 봐야 하는지"를 일관된 형식으로 정리하는 데 목적이 있습니다.

## 프로젝트 구조

이 프로젝트는 세 개의 독립 파이프라인으로 구성됩니다.

1. **Sentiment Join 파이프라인** — 감성·심리 지표 시계열 조인 → 통계 검정 → Risk Overlay 산출 → R2 업로드
2. **브리핑 파이프라인** — Risk Overlay 수신 → 시장 데이터 + 뉴스 수집 → LLM 브리핑 생성 → 이메일 발송 → 신호 기록
3. **프론트엔드** — Next.js SSG + Cloudflare Pages 공개 브리핑 사이트

> **실행 순서 중요**: Sentiment Join이 먼저 실행되고, 그 결과(latest.json)를 브리핑 파이프라인이 읽어 Risk Overlay를 이메일에 포함합니다.

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

## Sentiment Join 파이프라인

브리핑과 독립된 분석용 배치입니다. 매일 브리핑 파이프라인보다 **먼저** 실행됩니다.

```
데이터 수집 (BTC 가격, 감성, FNG, 선물, ETF, VIX, USD/KRW)
→ 날짜 정규화·forward-fill → inner join → 수익률 계산
→ 이상값 필터 (Z-score) → ADF+KPSS 정상성 검정
→ Granger 인과 검정 (63 검정, BH-FDR 보정)
→ VIF + PCA → 하이브리드 지수 (full/core)
→ vol_regime_v2 overlay gate 평가 (21일 이상 누적 기준)
→ Risk Overlay Score 산출 (3계층)
→ Parquet 저장 + latest.json R2 업로드
```

### Risk Overlay Score

Sentiment Join이 산출하는 3계층 시장 구조 분석입니다. 브리핑 이메일의 "BTC 신호 신뢰도" 섹션에 표시됩니다.

| 계층 | 항상 표시 | 내용 |
|---|---|---|
| Layer 1: RegimeState | ✅ | BullQuiet / BullHeated / BearPanic / Choppy / Transitional |
| Layer 2: VolEnvironment | ✅ | 변동성 레벨(High/Mid/Low) + 방향(rising/falling/stable) |
| Layer 3: SignalConfidence | 조건부 | HIGH / MEDIUM / None (신호 없는 날 null) |

**RegimeState 분류 기준**:

| 상태 | 조건 |
|---|---|
| BearPanic | VIX ≥ 90일 q80 AND FNG ≤ 20 |
| BullHeated | funding_zscore ≥ 1.5 AND (FNG ≥ 80 OR OI 과열) |
| BullQuiet | VIX < 90일 q40 AND rv < 45일 q45 AND 20 < FNG < 80 |
| Transitional | 위 세 조건 외, 방향성 있음 |
| Choppy | 방향성 판단 불가 |

**SignalConfidence**는 `vol_regime_v2` overlay gate가 `promote` 상태일 때만 HIGH 도달 가능합니다.

### 하이브리드 지수

감성·심리 지표를 PCA로 결합한 0~100 종합 점수입니다.

| 지수 | 입력 feature | VIF gate |
|---|---|---|
| full | 뉴스 감성, FNG, 펀딩비, Long/Short Ratio, ETF 순유입, 거래량 변화, VIX | 적용 (threshold=10) |
| core | 뉴스 감성, FNG, 펀딩비, 거래량 변화 | 미적용 (큐레이션) |

### Alpha Validation

하이브리드 지수와 감성 지표가 실제로 BTC 가격 방향을 맞추는지 정량 검증합니다.

| 분석 | 내용 |
|---|---|
| Hit Rate | 5개 predictor의 방향 적중률, Confusion Matrix, Precision/Recall/F1 |
| Correlation | Pearson (정상성 기반 차분) + Spearman |
| Backtest | 신호 기반 매수/현금 전략 누적 수익률 vs Buy & Hold |
| Walk-Forward | 120일 train / 30일 test rolling window |

### 실행

```bash
# 기본 180일
make sentiment-join

# 360일 (Granger 검정력 향상, Walk-Forward fold 증가)
SENTIMENT_JOIN_LOOKBACK_DAYS=360 make sentiment-join

# 결과 확인
python scripts/inspect_sentiment_join_parquet.py data/sentiment_join/
```

## 브리핑 파이프라인

```
[R2에서 latest.json 다운로드] → Risk Overlay 로드
→ 시장 데이터 수집 → 뉴스·시그널 수집 → FinBERT 감성 분석
→ Sonar 맥락 보강 → 데이터 품질 평가 → OpenAI 브리핑 생성
→ 브리핑 검증·재작성 → 공개 JSON 발행 (R2) → 이메일 발송 (SES)
→ Supabase signal_log 기록 → 7일 전 신호 결과 채우기
```

- OpenAI GPT 모델로 한국어 브리핑 생성 (Jinja2 템플릿 기반)
- 이메일에 Risk Overlay 블록 포함 (regime + vol + 신호 신뢰도 + 트랙레코드)
- Sentiment Join 파이프라인의 하이브리드 지수·통계 검정 결과를 브리핑에 반영

### 신호 트랙레코드

매일 신호를 Supabase `signal_log` 테이블에 기록하고, 7일 후 BTC 수익률로 적중 여부를 자동 평가합니다.

```sql
-- signal_log 테이블 스키마
create table signal_log (
  id             bigserial primary key,
  signal_date    date not null unique,
  regime_state   text not null,       -- BullQuiet/BullHeated/BearPanic/Choppy/Transitional
  vol_level      text not null,       -- High/Mid/Low
  vol_trend      text,                -- rising/falling/stable
  overlay_decision text not null,     -- promote/research_only
  confidence     text,                -- HIGH/MEDIUM/null
  reasons        jsonb,               -- ["vol_regime_v2_promoted", ...]
  btc_price_open numeric,             -- 발송 시점 BTC 가격
  btc_price_7d   numeric,             -- 7일 후 가격 (자동 채워짐)
  ret_7d         numeric,             -- (price_7d / price_open) - 1
  hit            boolean,             -- 신호 방향 적중 여부
  created_at     timestamptz default now()
);
```

### 이메일 발송

- AWS SES (ap-northeast-2) 경유, sender: `no-reply@sovereignbriefing.com`
- Supabase 구독 저장소에서 active 구독자만 조회하여 개별 발송
- HTML + plain text 이중 포맷
- HMAC-SHA256 기반 구독 해지 토큰 (30일 TTL)

### 공개 산출물

- Cloudflare R2에 JSON 업로드 (index, briefs, news, signals)
- R2 미설정 시 로컬 `outputs/public`에만 저장, 파이프라인 계속 진행
- 공개 뉴스 카드용 한국어 해설·시장 함의 별도 생성 (선택)

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
# Supabase: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (신호 기록용, 선택)
# FRED_API_KEY (VIX 수집용, 선택)
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

매일 22:40 UTC (한국시간 07:40) 자동 실행됩니다.

| 워크플로우 | 트리거 | 내용 |
|---|---|---|
| **Generate Sovereign Briefing** | schedule (매일) + workflow_dispatch | ① Sentiment Join → ② 브리핑 생성·발송 → ③ 신호 결과 채우기 → ④ 프론트엔드 배포 |
| CI | push to main, PR | fmt, lint, test, typecheck |

**실행 순서 (동일 워크플로우 내 job 의존성)**:

```
run-sentiment-join  →  run-brief  →  deploy-frontend
                          ↓
                   fill-signal-outcomes (run-brief 성공 시)
```

`run-brief`는 실행 전에 R2에서 `analytics/sentiment/latest.json`을 내려받아 Risk Overlay를 로드합니다. `run-sentiment-join`이 실패하거나 생략되어도 이전 R2 artifact가 있으면 파이프라인은 계속 진행합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/data-flow.md](docs/data-flow.md) | 데이터 수집·정제 전체 흐름 + Risk Overlay 상세 |
| [docs/data-sources.md](docs/data-sources.md) | 데이터 소스별 명세 |
| [docs/development-standards.md](docs/development-standards.md) | 개발 규칙 |
| [docs/ai-evals.md](docs/ai-evals.md) | AI 품질 점검 기준 |
| [docs/logging-ops.md](docs/logging-ops.md) | 로깅 운영 가이드 |
| [docs/llm-cost-ops.md](docs/llm-cost-ops.md) | LLM 비용 운영 |
| [docs/codex-ops.md](docs/codex-ops.md) | Codex 운영 가이드 |
| [docs/subscriptions-ops.md](docs/subscriptions-ops.md) | 구독 운영 가이드 |
| [docs/analysis/sentiment-join/signal-pipeline-status-20260503.md](docs/analysis/sentiment-join/signal-pipeline-status-20260503.md) | vol_regime_v2 현황 |
