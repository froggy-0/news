# SOVEREIGNWON

SOVEREIGNWON은 시장 데이터, 뉴스, 감성 분석, 리스크 오버레이, 공개 웹 UI, 그리고 BTC Signal Arena를 하나의 운용 체계로 묶는 프로젝트입니다.

현재 저장소는 과거 `SOVEREIGN BRIEF` 중심 설명에서 출발했지만, 실제 코드베이스는 크게 두 축으로 운영됩니다.

1. **Sovereign Briefing**: 한국 시간 아침에 읽을 수 있는 시장 브리핑을 생성하고, R2/이메일/공개 프론트엔드로 배포합니다.
2. **BTC Signal Arena**: BTC 현물 long/flat 전략을 연구, 백테스트, shadow/live 운영하기 위한 아레나입니다.

브리핑은 정보 전달 제품이고, 아레나는 의사결정·검증 엔진입니다. 둘은 `analytics/sentiment/latest.json`과 Risk Overlay를 통해 연결됩니다.

## 목적

- 단순 뉴스 모음이 아니라, 정량 데이터와 신뢰 가능한 뉴스/시그널을 결합해 오늘의 시장 판단을 일관된 형식으로 제공합니다.
- 감성·심리·파생·거시 데이터를 장기 시계열로 조인해 브리핑에 들어갈 Risk Overlay와 공개 분석 지표를 만듭니다.
- BTC Signal Arena에서 4H spot long/flat 전략의 신호, 실행 게이트, 리스크 트리거, 백테스트 패리티를 검증합니다.
- 공개 사용자는 `frontend/`의 Next.js SSG 사이트에서 브리핑, 아카이브, 분석 대시보드, 구독 흐름을 봅니다.

## 현재 코드베이스 지도

| 영역 | 경로 | 역할 |
| --- | --- | --- |
| 브리핑 파이프라인 | `main.py`, `src/morning_brief/` | 시장/뉴스 수집, FinBERT, OpenAI 브리핑 생성, 검수, R2 발행, SES 이메일 |
| Sentiment Join | `src/morning_brief/analysis/sentiment_join/`, `scripts/build_sentiment_join.py` | 감성·심리·거시·파생 데이터 조인, 통계 검정, 하이브리드 지수, Risk Overlay 산출 |
| BTC Signal Arena | `src/arena/` | EC2 상시 프로세스, 4H 스케줄러, 스트림, 실시간 리스크, 백테스트, 데이터레이크 기록 |
| 공개 프론트엔드 | `frontend/` | Next.js App Router SSG, Cloudflare Pages, Pages Functions 구독 API |
| 계약 스키마 | `schema/` | 프론트엔드가 읽는 public brief/analysis JSON 타입 계약 |
| 운영 스크립트 | `scripts/` | backfill, 검증, 리플레이, R2 모니터링, 진단 스크립트 |
| Lambda | `lambda/binance_futures/` | Binance futures 프록시 |
| 인프라 | `deploy/`, `supabase/`, `.github/workflows/` | EC2 배포 스크립트, DB migration, CI/배치/배포 워크플로우 |
| 문서 | `docs/` | 제품·운영·아키텍처·분석·스펙·문서 인벤토리 |

## 실행 흐름

### 1. Sentiment Join

브리핑보다 먼저 실행되는 분석 배치입니다.

```text
BTC 가격, R2 감성, FNG, 선물, ETF, VIX, USD/KRW 수집
-> 날짜 정규화/forward-fill
-> 통계 검정과 PCA 기반 하이브리드 지수
-> vol_regime_v2 overlay gate
-> Risk Overlay
-> Parquet + latest.json 저장/R2 업로드
```

실행:

```bash
make sentiment-join
SENTIMENT_JOIN_LOOKBACK_DAYS=540 make sentiment-join
```

### 2. Sovereign Briefing

`main.py once`가 현재 실제 실행 진입점입니다.

```text
R2 latest.json 로드
-> 시장 데이터/뉴스/X 시그널 수집
-> FinBERT 감성 분석
-> 데이터 품질 평가와 선택적 웹 검색 보강
-> OpenAI 브리핑 생성/검수/재작성
-> public JSON 발행
-> SES 이메일 발송
-> Supabase signal_log 기록
```

실행:

```bash
python scripts/validate_credentials.py
python main.py once
```

### 3. Frontend

`frontend/`는 R2 public JSON을 읽는 정적 사이트입니다. 데이터 계산은 하지 않고, `schema/brief.types.ts`와 `schema/analysis.types.ts` 계약에 맞춰 렌더링합니다.

```bash
cd frontend
npm ci
NEXT_PUBLIC_R2_BASE_URL="https://..." npm run build
```

### 4. BTC Signal Arena

`src/arena/server.py`가 EC2 상시 프로세스 진입점입니다.

```bash
PYTHONPATH=src python -m arena.server
PYTHONPATH=src python -m arena.walk_forward --symbol BTCUSDT --interval 4h
PYTHONPATH=src python scripts/verify_arena_data_lake.py
```

현재 운영 원칙은 spot long/flat입니다. raw `short` 신호는 신규 숏 포지션이 아니라 long 청산 또는 no-trade 판단 재료로만 취급합니다.

## GitHub Actions

| Workflow | 파일 | 역할 |
| --- | --- | --- |
| Generate Sovereign Briefing | `.github/workflows/morning-brief.yml` | 매일 22:40 UTC 실행. Sentiment Join -> Brief -> Frontend deploy 순서 |
| Build Sentiment Time Join | `.github/workflows/sentiment-join.yml` | 수동 Sentiment Join 재실행 |
| Deploy Frontend to Production | `.github/workflows/frontend-pages.yml` | 수동 Cloudflare Pages production 배포 |
| Replay Realtime Risk Gate | `.github/workflows/replay-risk-gate.yml` | 월 1회 arena realtime risk gate 리플레이 검증 |
| Repository Checks | `.github/workflows/ci.yml` | Python format/lint/test/typecheck |

## 문서 입구

| 문서 | 내용 |
| --- | --- |
| `docs/README.md` | 전체 문서 지도 |
| `docs/briefing/README.md` | 브리핑, Sentiment Join, 이메일, public JSON 흐름 |
| `docs/arena/README.md` | BTC Signal Arena 운영/연구/제품 문서 |
| `docs/frontend/README.md` | 공개 프론트엔드와 schema 계약 |
| `docs/infrastructure/README.md` | GitHub Actions, Lambda, Terraform, Supabase, Cloudflare 운영 경로 |
| `docs/reference/codebase-map.md` | 실제 코드 경로 기준 상세 맵 |
| `docs/reference/markdown-inventory.md` | 저장소 Markdown 문서 인벤토리 |
| `docs/reference/docs-rubric.md` | 문서 정합성 점검 루브릭 |

## 개발 검증

```bash
make lint
make test
make typecheck
make check

cd frontend
npm run lint
npm test
npm run build
```

`.env`와 `.env.*` 파일은 문서화하거나 출력하지 않습니다. 필요한 설정 이름만 문서에 적고, 값은 환경변수나 GitHub Actions secrets/vars에서 관리합니다.
