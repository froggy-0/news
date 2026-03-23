# LLM 비용 절감 운영 체크리스트

## 목적

`Morning Market Brief`의 LLM 비용이 다시 급증할 때, 어디부터 확인하고 어떤 순서로 줄여야 하는지 운영자가 빠르게 판단할 수 있게 하는 문서다.

## 왜 이 네 가지가 우선인가

1. 검수 정합성
   - 생성 포맷과 검수 포맷이 다르면 `brief_review -> rewrite -> re-review` 루프가 거의 고정비가 된다.
   - 가장 먼저 `brief_review_failed`, `brief_review_retry`, `brief_review_response_incomplete`를 본다.

2. prompt slimming
   - 같은 컨텍스트를 `packet_json`, `news_focus_json`, `sonar_context`로 여러 번 보내면 cached input 이점을 잃고 입력 토큰이 급증한다.
   - 생성 프롬프트는 실제로 쓰는 뉴스/시그널/요약만 남겨야 한다.

3. early publish gate
   - public에서 못 쓸 기사를 뒤에서 버리면, Perplexity, OpenAI web backfill, public translation 비용을 전부 낭비한다.
   - `candidate는 많지만 kept=0`이면 gate가 늦은 구조다.

4. public translation 축소
   - 홈과 상세에 모두 쓰지 않는 raw 필드까지 번역하면 공개 번역이 새 고정비가 된다.
   - 기본은 `headline`, `summaryLead/support`, `featuredNews`, `featuredXSignals`, `topicSummaries`만 번역한다.

## 운영 목표치

- OpenAI requests `<= 7`
- OpenAI input tokens `<= 90,000`
- OpenAI cost `<= $0.035`
- total cost `<= $0.055`

기준선:

- 안정 run `23390939438`
  - total `$0.053885`
  - openai `$0.028997`
- 비용 급증 run `23439961352`
  - total `$0.074114`
  - openai `$0.047275`

## 먼저 볼 곳

1. GitHub Actions 최신 `Morning Market Brief` run
2. `outputs/observability/pipeline-run-*.json`
3. 같은 파일의 `summary.provider_usage_by_phase`
4. `summary.provider_usage_line`

핵심 phase:

- `brief_generation`
- `brief_review`
- `brief_rewrite`
- `web_backfill`
- `public_translation`

## 증상별 체크 순서

### 1. OpenAI requests가 갑자기 늘었다

- `provider_usage_by_phase.openai`에서 어떤 phase가 늘었는지 본다
- `brief_review`와 `brief_rewrite`가 크면:
  - `/Users/giwon/code/news/src/morning_brief/prompts/brief_validator_input.j2`
  - `/Users/giwon/code/news/src/morning_brief/prompts/brief_validator_instructions.j2`
  를 확인한다
- `public_translation`이 크면:
  - `/Users/giwon/code/news/src/morning_brief/public_site.py`
  의 featured-only translation 조건이 깨졌는지 본다
- `web_backfill`이 크면:
  - `/Users/giwon/code/news/src/morning_brief/pipeline.py`
  - `/Users/giwon/code/news/src/morning_brief/research_backfill.py`
  의 skip 조건이 유지되는지 본다

### 2. input tokens가 90,000을 넘는다

- 생성 phase input이 큰지 먼저 본다
- 아래 파일에서 중복 payload가 다시 들어갔는지 확인한다
  - `/Users/giwon/code/news/src/morning_brief/prompting.py`
  - `/Users/giwon/code/news/src/morning_brief/prompts/brief_input.j2`

### 3. public 뉴스가 0건인데 비용은 높다

- `public_publish_news_candidates`
- `public_publish_news_selection`
- `web_backfill_result`
이벤트를 같이 본다

의미:

- `candidate_count`는 많은데 `kept_count=0`
  - early publish gate가 늦거나 source 품질이 낮다
- `reason=source_only_fallback`
  - citation 기반 후보를 살렸다는 뜻
- `reason=source_only_filtered` 또는 `parsed_items_filtered`
  - web backfill 결과가 publish 기준을 못 통과한 것이다

### 4. public translation이 비싸지만 화면 품질 개선이 없다

- `translationStatus`
- `featuredNews`
- `featuredXSignals`
를 본다

원칙:

- `featured`가 비어 있으면 해당 타입 번역 요청은 없어야 한다
- `allNews`, `allXSignals` raw 필드는 번역하지 않는다

## 관련 핵심 파일

- `/Users/giwon/code/news/src/morning_brief/prompting.py`
- `/Users/giwon/code/news/src/morning_brief/prompts/brief_input.j2`
- `/Users/giwon/code/news/src/morning_brief/prompts/brief_validator_input.j2`
- `/Users/giwon/code/news/src/morning_brief/prompts/brief_validator_instructions.j2`
- `/Users/giwon/code/news/src/morning_brief/brief_review.py`
- `/Users/giwon/code/news/src/morning_brief/data/news.py`
- `/Users/giwon/code/news/src/morning_brief/data/news_selection.py`
- `/Users/giwon/code/news/src/morning_brief/research_backfill.py`
- `/Users/giwon/code/news/src/morning_brief/public_site.py`
- `/Users/giwon/code/news/src/morning_brief/observability.py`

## 회귀 검증 명령

```bash
cd /Users/giwon/code/news
.venv/bin/pytest -q tests/test_llm_cost_baselines.py tests/test_prompting.py tests/test_brief_review.py tests/test_news_quality.py tests/test_public_site.py tests/test_research_backfill.py tests/test_pipeline_observability.py
.venv/bin/ruff check src/morning_brief/prompting.py src/morning_brief/brief_review.py src/morning_brief/data/news.py src/morning_brief/data/news_selection.py src/morning_brief/research_backfill.py src/morning_brief/public_site.py src/morning_brief/observability.py tests/test_llm_cost_baselines.py tests/test_prompting.py tests/test_brief_review.py tests/test_news_quality.py tests/test_public_site.py tests/test_research_backfill.py tests/test_pipeline_observability.py
```
