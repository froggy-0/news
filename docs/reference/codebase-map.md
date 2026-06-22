# Codebase Map

이 문서는 실제 코드 경로를 기준으로 SOVEREIGNWON 저장소를 설명합니다.

## 제품 축

| 축 | 목적 | Primary code |
| --- | --- | --- |
| Sovereign Briefing | 매일 브리핑 생성, public JSON 발행, 이메일 발송 | `main.py`, `src/morning_brief/` |
| Sentiment Join | 감성/심리/시장 데이터를 조인해 Risk Overlay와 분석 artifact 생성 | `src/morning_brief/analysis/sentiment_join/`, `scripts/build_sentiment_join.py` |
| BTC Signal Arena | BTC spot long/flat 신호 연구, shadow/live 운영, 데이터레이크 기록 | `src/arena/` |
| Public Frontend | 브리핑/분석/구독 UI 제공 | `frontend/`, `schema/` |

## `src/morning_brief`

| 경로 | 설명 |
| --- | --- |
| `pipeline.py` | 브리핑 전체 orchestration |
| `config.py` | 환경변수 기반 설정 |
| `briefing.py`, `prompting.py`, `prompts/` | LLM 입력/출력 생성 |
| `brief_review.py` | validation/rewrite loop |
| `brief_formatting.py`, `unified_output.py` | 브리핑 구조화와 출력 정규화 |
| `emailer.py`, `templates/` | SES 이메일 렌더링/발송 |
| `public_site.py` | public JSON 생성/R2 업로드 |
| `data/market.py`, `data/news.py`, `data/sources/` | 시장/뉴스 공급자와 fallback |
| `data/finbert_sentiment.py` | FinBERT 감성 분석 |
| `analysis/sentiment_join/` | 통계 분석, 하이브리드 지수, Risk Overlay |
| `subscriptions/` | 구독 저장소 abstraction |
| `signal_logger.py` | Supabase signal_log 기록/조회 |
| `observability.py`, `logging_utils.py` | 관측/로깅 |

## `src/arena`

| 경로 | 설명 |
| --- | --- |
| `server.py` | EC2 상시 프로세스 진입점 |
| `scheduler.py`, `stream.py`, `realtime_market.py` | 4H/stream/realtime collector |
| `positions.py`, `allocator.py`, `execution_rules.py` | 포지션 원장, allocation, 실행 규칙 |
| `algorithms.py`, `sleeves.py`, `regime.py`, `spot_policy.py` | 전략/레짐/spot semantics |
| `risk.py`, `realtime_risk.py`, `execution_gate.py` | 리스크와 execution gate |
| `data_lake.py`, `feature_registry.py` | Supabase data lake 기록 |
| `backtest.py`, `walk_forward.py`, `backtest_validation.py`, `backtest_report.py` | 백테스트/워크포워드/검증 |
| `frequency.py`, `tca_shadow.py`, `roster_diagnostics.py` | 빈도 연구, TCA shadow, 진단 |

## `frontend`

| 경로 | 설명 |
| --- | --- |
| `app/` | Next.js App Router 페이지 |
| `components/brief/` | 브리핑 본문, Risk Overlay, index panel |
| `components/analysis/` | 분석 대시보드 |
| `components/news/`, `components/signals/` | 뉴스와 X signal 렌더링 |
| `components/layout/` | 헤더/푸터/구독 폼 |
| `functions/api/subscriptions/` | Cloudflare Pages Functions 구독 API |
| `lib/` | R2/fixture/output loader, formatter, subscription helpers |
| `scripts/` | build/deploy/static asset 생성 |
| `tests/` | Node test |

## `scripts`

| 경로 | 설명 |
| --- | --- |
| `build_sentiment_join.py` | Sentiment Join 실행 |
| `validate_credentials.py` | 브리핑 실행 전 인증 설정 점검 |
| `fill_signal_outcomes.py` | 7일 후 신호 성과 채우기 |
| `validate_latest_artifact.py` | public/latest artifact 검증 |
| `monitor_r2.py` | R2 상태 모니터링 |
| `analysis/` | Arena/research 리플레이와 진단 |
| `backfill*.py`, `backfill/` | 뉴스/ETF/futures/stablecoin/backfill 도구 |
| `diagnostics/`, `exploratory/` | 진단과 탐색용 도구 |

## 외부 시스템 경계

| 시스템 | 코드 경계 | 실패 처리 원칙 |
| --- | --- | --- |
| OpenAI | `src/morning_brief/openai_utils.py`, `briefing.py`, `brief_review.py` | validation/rewrite 설정과 fallback |
| Perplexity/Grok/Gemini/News APIs | `src/morning_brief/data/sources/` | 공급자별 독립 실패 허용, 품질 평가 후 fallback |
| KIS/FRED/Binance/CoinGecko/yfinance | `src/morning_brief/data/market.py`, `analysis/sentiment_join/sources/` | primary/fallback/cache |
| R2 | `public_site.py`, sentiment join storage | 미설정 시 로컬 출력 또는 다운로드 skip |
| Supabase | subscriptions, signal_log, arena ledger | 미설정 시 브리핑 기록/구독 일부 skip, Arena는 운영 필수 |
| AWS SES/Lambda | `emailer.py`, `lambda/binance_futures/` | GitHub Actions/OIDC와 환경변수로 연결 |

## 문서 갱신 체크

- 새 코드 영역이 생기면 이 문서와 `docs/reference/markdown-inventory.md`를 갱신합니다.
- 실행 명령이 바뀌면 루트 `README.md`와 영역별 README를 함께 수정합니다.
- public JSON 계약이 바뀌면 `schema/README.md`, `docs/frontend/README.md`, frontend tests/fixtures를 함께 확인합니다.
