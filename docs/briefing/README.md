# Sovereign Briefing Docs

Sovereign Briefing은 매일 시장 데이터와 뉴스/시그널을 수집해 한국어 브리핑, public JSON, 이메일을 생성하는 제품 축입니다.

## 코드 기준

| 영역 | 경로 | 역할 |
| --- | --- | --- |
| 실행 진입점 | `main.py` | `once` 또는 `schedule` 모드 실행 |
| 파이프라인 | `src/morning_brief/pipeline.py` | 시장/뉴스/Risk Overlay/브리핑/발행/발송 orchestration |
| 설정 | `src/morning_brief/config.py` | 환경변수 기반 설정 로드 |
| 브리핑 생성 | `src/morning_brief/briefing.py`, `src/morning_brief/prompting.py`, `src/morning_brief/prompts/` | OpenAI 입력 구성과 템플릿 |
| 검수/재작성 | `src/morning_brief/brief_review.py` | 생성 브리핑 validator/rewrite loop |
| 이메일 | `src/morning_brief/emailer.py`, `src/morning_brief/templates/` | SES HTML/text 이메일 렌더링 |
| public JSON | `src/morning_brief/public_site.py`, `src/morning_brief/unified_output.py` | R2/로컬 공개 산출물 생성 |
| 시장 데이터 | `src/morning_brief/data/market.py`, `src/morning_brief/data/sources/` | KIS, FRED, Binance, ETF, 뉴스 공급자 |
| 감성 분석 | `src/morning_brief/data/finbert_sentiment.py` | FinBERT 점수와 confidence |
| 구독 | `src/morning_brief/subscriptions/` | Supabase 구독자 조회 |
| 신호 기록 | `src/morning_brief/signal_logger.py`, `scripts/fill_signal_outcomes.py` | signal_log upsert와 7일 결과 채우기 |

## 실행 흐름

```text
python main.py once
-> load_settings()
-> run_pipeline()
-> market packet
-> news packet
-> risk overlay load
-> data quality assessment
-> OpenAI briefing generation
-> optional validation/rewrite
-> publish public JSON
-> send SES email
-> log signal outcome seed
```

## Sentiment Join 연동

브리핑은 `data/sentiment_join/latest.json` 또는 R2의 `analytics/sentiment/latest.json`에서 Risk Overlay를 읽습니다.

| 산출물 | 생산자 | 소비자 |
| --- | --- | --- |
| `analytics/sentiment/latest.json` | Sentiment Join | 브리핑, 프론트엔드, Arena macro reference |
| `outputs/public/index.json` | 브리핑 파이프라인 | 프론트엔드 archive/home |
| `outputs/public/briefs/YYYY-MM-DD.json` | 브리핑 파이프라인 | 프론트엔드 detail page |
| Supabase `signal_log` | 브리핑 파이프라인 | 이메일 track record, 운영 점검 |

## 실행 명령

```bash
python scripts/validate_credentials.py
python main.py once
python main.py schedule
make sentiment-join
```

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| [../data-flow.md](../data-flow.md) | Sentiment Join과 브리핑 상세 데이터 흐름 |
| [../data-sources.md](../data-sources.md) | 데이터 소스별 primary/fallback/품질 기준 |
| [../subscriptions-ops.md](../subscriptions-ops.md) | 구독 저장소와 이메일 구독/해지 |
| [../llm-cost-ops.md](../llm-cost-ops.md) | LLM 모델/비용 운영 |
| [../ai-evals.md](../ai-evals.md) | 브리핑 품질 점검 기준 |
| [../analysis/sentiment-join/diagnostic-runbook.md](../analysis/sentiment-join/diagnostic-runbook.md) | Sentiment Join 진단 |

## 문서 갱신 기준

- 실행 예시는 `main.py once`를 기준으로 작성합니다.
- 공급자 추가/삭제 시 `docs/data-sources.md`와 이 문서를 함께 갱신합니다.
- public JSON 계약 변경 시 `schema/README.md`, `docs/frontend/README.md`, 프론트 fixture/test를 함께 확인합니다.
- 환경변수는 이름만 적고 값은 적지 않습니다.
