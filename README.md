# SOVEREIGN BRIEF

한국 시간 아침에 미국 기술주와 비트코인 시장을 빠르게 파악할 수 있도록, 여러 시장 데이터와 뉴스 흐름을 한 번 더 정리해 이메일 브리핑으로 전달하는 프로젝트입니다.

이 프로젝트의 목적은 단순한 뉴스 모음이 아니라, 한국 투자자 입장에서 "오늘 시장을 어떻게 봐야 하는지"를 짧고 일관된 형식으로 정리하는 데 있습니다.

## 무엇을 다루는가

이 브리핑은 아래 네 가지 축을 함께 다룹니다.

### 시장 데이터

- 미국 금리와 변동성
- 하이일드 스프레드
- 달러 흐름
- 미국 주요 지수
- 기술주 주요 종목
- 비트코인 현물 가격
- 미국 현물 비트코인 ETF 보유 현황

### 한국 투자자 참고 지표

- 원/달러 환율
- 나스닥 선물
- 미국 시장 흐름이 한국 개장에 줄 수 있는 영향

### 뉴스와 시그널

- 거시경제 관련 뉴스
- 미국 증시와 기술주 관련 뉴스
- AI·빅테크 관련 뉴스
- 비트코인 및 ETF 관련 뉴스
- 공식 X 계정에서 나온 실시간 시그널

### 브리핑 출력

- 오늘의 판단
- 주요 뉴스
- 종목별 흐름
- 거시 지표 요약
- 출처와 데이터 처리 메모

## 어떻게 수집하고 정리하는가

브리핑은 아래 흐름으로 만들어집니다.

1. 시장 데이터를 먼저 모읍니다.
금리, 달러, 지수, 기술주, 비트코인, ETF 관련 데이터를 수집하고 이상값이나 결측값을 점검합니다.

- 미국 현물 BTC ETF 보유량은 공식 issuer source를 우선 사용하고, Bronze/Silver/Gold 계층으로 raw payload, 정규화 필드, daily primary snapshot을 분리 저장합니다.
- 공식 structured source가 없으면 HTML fallback으로 내리고, aggregator 데이터는 reference-only로만 분리 기록합니다.

2. 뉴스와 시그널을 모읍니다.
Perplexity 검색 결과를 중심으로 뉴스를 수집하고, 공식 X 시그널도 함께 확인합니다.

2.5. 뉴스와 시그널에 감성 점수를 매깁니다.
ProsusAI/finbert 모델로 영문 원본 텍스트에 -1.0~1.0 범위의 연속 감성 점수를 부여합니다. 이 점수는 시계열 통계 분석의 입력으로 활용됩니다. `FINBERT_ENABLED=false`로 비활성화할 수 있으며, `transformers`/`torch`가 미설치된 환경에서도 파이프라인은 정상 동작합니다.

- sentiment join 산출물은 Binance 선물 지표 Lag-1 컬럼, ADF/Granger 검정 요약, VIF/PCA 기반 `hybrid_index`를 포함하고 Parquet schema metadata의 `sentiment_join_stats`에 진단 요약을 함께 저장합니다.
- 선물 데이터(펀딩비·미결제약정·Long/Short Ratio)는 ap-northeast-2 Lambda 프록시 → Bybit 공개 API → NaN 순서로 폴백합니다. GitHub Actions(US IP)에서 `fapi.binance.com`이 지역 제한(HTTP 451)으로 차단되기 때문입니다.
- `make sentiment-join`으로 직접 실행하며 `FUTURES_LAMBDA_ARN`, `SENTIMENT_JOIN_LOOKBACK_DAYS` 등 환경변수로 동작을 제어합니다.

3. 맥락을 보강합니다.
Perplexity Sonar 요약을 통해 개별 기사보다 큰 흐름을 함께 보고, 필요할 때는 web search 기반 보강 경로로 부족한 부분을 메웁니다.

4. 품질을 다시 거릅니다.
중복 기사, 품질이 낮은 제목, 비정상적인 수치, 빠진 값, 출처가 좁은 뉴스 묶음을 다시 걸러냅니다.

5. 한국어 브리핑으로 정리합니다.
수집된 데이터와 뉴스, 시그널을 바탕으로 아침에 읽기 쉬운 형태의 브리핑을 만들고 이메일로 발송합니다.

## 이 프로젝트가 특히 신경 쓰는 점

- 숫자를 그대로 믿지 않고 한 번 더 점검합니다.
- 추정 성격이 강한 수치는 줄이고, 원본 레벨값 중심으로 정리합니다.
- 뉴스는 많이 모으는 것보다, 읽을 가치가 있는 항목만 남기는 데 초점을 둡니다.
- 공식 X 시그널과 일반 뉴스, 구조화된 ETF 정보처럼 성격이 다른 데이터를 섞어 보되, 역할은 분리합니다.
- 공개 사이트의 기사형 뉴스 카드는 선택된 기사만 대상으로 한국어 해설과 시장 함의를 별도로 생성합니다.
- 브리핑 구조가 무너지거나 데이터가 부족하면 그 사실도 함께 남깁니다.
- 어떤 공급자가 어떤 역할로 사용됐는지 실행 로그를 남깁니다.

## 결과물

실행이 끝나면 아래 결과물이 만들어집니다.

- Markdown 브리핑 파일
- 이메일 본문(HTML / plain text)
- 실행 요약 로그
- 뉴스 수집 감사 로그

## 메일 구독 운영

- Python 파이프라인은 Supabase 구독 저장소에서 `active` 구독자만 읽어 recipient별 개별 발송합니다.
- newsletter 발송은 GitHub Actions OIDC role과 AWS SES `ap-northeast-2`를 사용하고 sender는 `no-reply@sovereignbriefing.com`입니다.
- GitHub Actions `Generate Sovereign Briefing` workflow는 현재 `workflow_dispatch`로만 수동 실행합니다.
- newsletter SES 발송이 실패하면 run은 `degraded`로 기록하고 공개 산출물과 후속 frontend deploy는 계속 진행합니다.
- 구독 신청, 확인 메일, 구독 해지는 Cloudflare Pages Functions API가 처리하며 confirmation 메일도 같은 SES sender/region을 사용합니다.
- 로컬 개발에서는 실제 SES 발송 smoke test를 지원하지 않고, route 초기화와 테스트 기반 비발송 검증만 수행합니다.
- 필요한 secret와 migration 절차는 `docs/subscriptions-ops.md`에 정리합니다.

## 공개 산출물 R2 업로드

- 공개 JSON 업로드는 선택적 단계입니다. R2가 미설정이거나 업로드 인증이 실패하면 로컬 `outputs/public` 산출물은 계속 생성하고 파이프라인은 이어서 진행합니다.
- canonical R2 키는 `R2_PUBLIC_BUCKET`, `R2_S3_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `NEXT_PUBLIC_R2_BASE_URL`입니다.
- `R2_S3_ENDPOINT`는 bucket/path/query가 붙지 않은 account-level S3 endpoint 형식이어야 합니다. 예: `https://<account-id>.r2.cloudflarestorage.com`
- 기존 `R2_BUCKET_NAME`, `R2_ENDPOINT_URL`, `R2_BASE_URL`도 alias로 읽지만, 새 설정은 canonical 키로 맞춥니다.

## FinBERT 감성 분석

- `FINBERT_ENABLED` 환경변수로 켜고 끌 수 있습니다 (기본값 `true`).
- ML 의존성(`transformers`, `torch`)은 `requirements-ml.txt`에 별도 관리하며, `requirements.txt`에 포함하지 않습니다.
- 뉴스와 X 시그널의 영문 원본에 대해 ProsusAI/finbert 모델로 감성 점수(`sentimentScore`)와 확신도(`sentimentConfidence`)를 산출합니다.
- 결과는 최종 JSON의 각 뉴스·시그널 항목과 `meta` 섹션의 집계 지표(`newsSentiment`, `signalSentiment`, `sentimentByCategory`)에 포함됩니다.
- 모델 버전은 `FINBERT_MODEL_REVISION`으로 commit hash를 고정하여 시계열 연속성을 보장합니다.
- 임계값(`FINBERT_BULLISH_THRESHOLD`, `FINBERT_BEARISH_THRESHOLD`)으로 라벨 매핑 기준을 조정할 수 있습니다.

## 공개 뉴스 카드 해설 생성

- 공개 뉴스 카드용 해설 생성은 `OPENAI_PUBLIC_NEWS_ANALYSIS_ENABLED`로 켜고 끌 수 있습니다.
- 모델은 `OPENAI_PUBLIC_NEWS_ANALYSIS_MODEL`로 별도 지정할 수 있고, 비우면 공개 번역 모델 또는 기본 OpenAI 모델을 순서대로 사용합니다.
- 이 단계는 공개 기사형 뉴스에만 적용되며, 이메일 뉴스 경로나 X 시그널 경로에는 영향을 주지 않습니다.

## 누구를 위한 프로젝트인가

이 프로젝트는 아래 같은 사용자에게 맞춰져 있습니다.

- 한국 시간 아침에 미국 장 상황을 빠르게 파악하고 싶은 투자자
- 기술주와 비트코인을 함께 보는 사용자
- 숫자와 뉴스, 둘 다 놓치고 싶지 않은 사용자
- 사람이 일일이 정리하지 않아도 읽을 수 있는 브리핑을 원하는 사용자

## 자세한 문서

README에는 프로젝트의 목적과 흐름만 남기고, 상세 기준은 별도 문서로 분리했습니다.

## 검증 원칙

- 로컬 pre-commit 훅은 빠른 Python 포맷/린트만 맡습니다.
- PR CI는 Python과 frontend를 모두 정식 품질 게이트로 검증합니다.
- 배포 워크플로우는 테스트를 중복 실행하지 않고 build와 deploy에 집중합니다.
- 커밋 가능 여부가 로컬 `.venv` 존재 여부에 묶이지 않도록 유지합니다.

자주 쓰는 검증 명령:

- `make fmt`
- `make lint`
- `make test`
- `make typecheck`
- `make check`
- `cd frontend && npm run lint`
- `cd frontend && npm test`
- `cd frontend && npm run build:fixture`

- 개발 기준: [docs/development-standards.md](docs/development-standards.md)
- 품질 점검 기준: [docs/ai-evals.md](docs/ai-evals.md)
- 데이터 소스 및 품질 기준: [docs/data-sources.md](docs/data-sources.md)
- 데이터 수집·정제 흐름: [docs/data-flow.md](docs/data-flow.md)
- LLM 비용 운영: [docs/llm-cost-ops.md](docs/llm-cost-ops.md)
- 로깅 운영 가이드: [docs/logging-ops.md](docs/logging-ops.md)
- Codex 운영 가이드: [docs/codex-ops.md](docs/codex-ops.md)
- 구독 운영 가이드: [docs/subscriptions-ops.md](docs/subscriptions-ops.md)
