# 구현 계획: LLM 비용 절감 및 중복 컨텍스트 제거

## 개요

최근 `Morning Market Brief` 실행에서 LLM 비용이 유의미하게 증가했다. 최신 성공 run `23439961352`(2026-03-23 22:33 KST 시작)는 총 `$0.074114`였고, 이 중 OpenAI 비용이 `$0.047275`였다. 비교 기준인 run `23390939438`(2026-03-22 08:14 KST 시작)은 총 `$0.053885`, OpenAI `$0.028997`였다. 즉 총비용은 약 37.5%, OpenAI 비용은 약 63.0% 증가했다.

실코드와 run artifact를 보면 원인은 모델 품질 저하가 아니라 **큰 입력을 여러 단계에서 반복 전송하는 구조**다.

- 생성 프롬프트가 `packet_json + news_focus_json + sonar_context`를 중복으로 넣음
- 검수 프롬프트가 아직 `3개 레이어 / LAYER 2 / LAYER 3`를 검사해서 현재 `Section 0~6` 구조와 불일치함
- 공개용 뉴스 품질 gate가 너무 늦게 걸려, Perplexity/OpenAI backfill/공개 번역 비용을 다 쓴 뒤 결과를 버림
- 공개 JSON 번역이 `featured`뿐 아니라 `all` 수준까지 번역해서 새 고정비가 됨
- phase별 usage 로그가 없어 어떤 단계가 실제로 비싼지 매번 artifact를 열어야 함

이 계획의 목표는 **이메일 품질과 공개 JSON 품질을 유지하면서, 중복 컨텍스트와 불필요한 OpenAI 호출을 줄이는 것**이다.

추가 원칙:

- 단순히 “수집한 뒤 덜 보내는 것”으로는 부족하다.
- `email`, `public_home`, `public_detail` 각각이 실제로 쓰는 데이터만 수집·보강·번역해야 한다.
- 사용하지 않는 섹션은 **수집 → backfill → 번역** 모든 단계에서 가능한 한 일찍 건너뛴다.

## 공식 Docs 기준

아래 원칙은 OpenAI 공식 문서를 기준으로 한다.

- Prompt caching: 반복되는 prefix를 최대한 고정하고, 큰 컨텍스트 중복을 줄여 cached input 비율을 높인다.  
  [Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching)
- Cost optimization: 더 작은 모델, 더 짧은 입력, 중복 제거가 우선이다.  
  [Cost Optimization](https://platform.openai.com/docs/guides/cost-optimization)
- Model selection: 좁은 번역/검수/구조화 작업은 generation과 분리해 더 작은 모델을 고려한다.  
  [Models](https://platform.openai.com/docs/models)
- Structured outputs: 검수/번역처럼 출력 형식이 좁은 작업은 JSON schema를 유지하고, 입력을 더 작게 줄여 재시도 비용을 낮춘다.  
  [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- Batch API: 실시간성이 낮은 후행 번역은 비동기 배치 후보로 분리할 수 있다.  
  [Batch API](https://platform.openai.com/docs/api-reference/batch)

## 현재 기준선

### 실행 기준선

- run `23390939438` (2026-03-22 08:14 KST)
  - total: `$0.053885`
  - openai: `requests=4 input=57385 output=8348 cached=9088 reasoning=832 cost=0.028997`
  - perplexity: `requests=9 input=1026 output=3116 cost=0.004142`
- run `23439961352` (2026-03-23 22:33 KST)
  - total: `$0.074114`
  - openai: `requests=9 input=112777 output=11585 cached=18176 reasoning=448 cost=0.047275`
  - perplexity: `requests=9 input=10654 output=3923 cost=0.014577`

### 코드 기준선

- 생성 프롬프트 중복 컨텍스트: `/Users/giwon/code/news/src/morning_brief/prompting.py:112`, `/Users/giwon/code/news/src/morning_brief/prompts/brief_input.j2:4`
- 검수 프롬프트 구조 불일치: `/Users/giwon/code/news/src/morning_brief/prompts/brief_validator_input.j2:11`
- 검수/재작성 루프: `/Users/giwon/code/news/src/morning_brief/brief_review.py:173`, `/Users/giwon/code/news/src/morning_brief/brief_review.py:274`
- 공개 번역 범위: `/Users/giwon/code/news/src/morning_brief/public_site.py:982`, `/Users/giwon/code/news/src/morning_brief/public_site.py:1056`
- 공개 품질 gate: `/Users/giwon/code/news/src/morning_brief/data/news_selection.py:54`
- OpenAI web backfill fallback: `/Users/giwon/code/news/src/morning_brief/research_backfill.py:392`

### 확인된 증상

- 최신 run에서 public 뉴스는 `candidate_count=12`, `kept_count=0`, `non_preferred_domain=12`
- 최신 run에서 OpenAI web backfill은 `source_only_fallback`으로 `11건` 후보를 추가
- 최신 run에서 브리프 검수는 현재 포맷과 맞지 않는 검사 기준으로 `brief_review_failed`를 반복 기록
- 공개 번역은 generation과 같은 `settings.openai_model`을 사용

## Tasks

- [ ] 0. 소비자별 데이터 계약과 수집 budget을 먼저 고정
  - [ ] 0.1 consumer matrix 문서화
    - `email`, `public_home`, `public_detail` 3개 소비자별로 실제 사용 필드를 표로 정리
    - 각 소비자별로 아래를 명시
      - required fields
      - optional fields
      - max item count
      - allowed providers
      - skip conditions
    - 예시:
      - `email`: 뉴스 5건, X 시그널 요약, market packet 전체, 상세 본문 필요
      - `public_home`: `summaryLead/support`, `topicSummaries`, `featuredNews`, `featuredXSignals`만 필요
      - `public_detail`: `allNews`, `allXSignals`, `body`, 일부 market card만 필요
    - 산출 위치:
      - `/Users/giwon/code/news/.kiro/specs/llm-cost-reduction-plan/tasks.md` 또는 가장 가까운 설계 문서에 표 추가
    - _목표: “누가 어떤 데이터를 실제로 쓰는지”를 먼저 고정_

  - [ ] 0.2 consumer별 collection budget 정의
    - consumer matrix를 바탕으로 수집 단계 최대 개수를 고정
    - 최소 정의:
      - `email_news_max=5`
      - `public_featured_news_max=5`
      - `public_all_news_max=12`
      - `email_x_max`
      - `public_featured_x_max=5`
      - `public_all_x_max=12`
    - 이 budget은 후단 slice가 아니라 upstream merge/rank/backfill 조건에도 반영
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/data/news.py`, `/Users/giwon/code/news/src/morning_brief/pipeline.py`_

  - [ ] 0.3 section skip policy 정의
    - 아래처럼 “실제로 안 쓰는 섹션”이면 후속 비용을 쓰지 않는 정책을 명시
      - `public_home`에서 market ticker/ETF snapshot을 안 쓰면 해당 public augmentation 생략
      - `featuredNews=[]` 확정이면 뉴스 번역 생략
      - `featuredXSignals=[]` 확정이면 X 번역 생략
      - 특정 소비자에서 필요 없는 market sub-block은 prompt/backfill 입력에서 제거
    - _목표: 수집 후 버리기 대신, 필요 없는 가지는 일찍 차단_

- [x] 1. 기준선 검증 테스트와 비용 관측 테스트를 먼저 추가
  - [x] 1.1 최근 비용 증가를 재현하는 baseline fixture 추가
    - run `23390939438`, `23439961352`의 observability 요약을 테스트 fixture로 저장
    - 기준선 비교용 최소 필드만 포함: provider별 requests/input/output/cached/cost_usd
    - fixture는 민감정보 없이 숫자와 이벤트명만 포함
    - _목표: 이후 최적화가 실제 절감으로 이어졌는지 자동 비교 가능하게 만들기_

  - [x] 1.2 phase별 usage 집계 테스트 작성
    - 새 observability helper가 `brief_generation`, `brief_review`, `brief_rewrite`, `public_translation`, `web_backfill` 별 usage를 기록하는지 검증
    - provider 총합과 phase 합계가 모순되지 않는지 확인
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/observability.py`, 관련 테스트 파일 추가_

  - [x] 1.3 현재 검수 프롬프트 구조 불일치 존재 테스트 작성
    - `brief_input.j2`는 `Section 0~6`를 요구하지만 `brief_validator_input.j2`는 `3개 레이어 / LAYER 2 / LAYER 3`를 검사하고 있음을 명시적으로 검증
    - 수정 전에는 이 테스트가 FAIL해야 함
    - _목표: 비용 증가의 직접 원인 중 하나를 테스트로 고정_

- [ ] 2. 검수 프롬프트를 현재 Section 0~6 구조에 맞게 정합성 수정
  - [x] 2.1 `brief_validator_input.j2`를 Section 기반으로 전면 교체
    - `3개 레이어`, `LAYER 2`, `LAYER 3` 표현 제거
    - 생성 프롬프트와 동일하게 `Section 0`, `Section 1`, `Section 2`, `Section 3`, `Section 4-1`, `4-2`, `4-3`, `5-1`, `5-2`, `5-3`, `6` 기준으로 검사 포인트 재정의
    - `news item` 검사는 현재 공개/메일 구조와 맞는 필수 요소만 남김
    - _핵심 목표: false positive 검수 감소_

  - [x] 2.2 `brief_validator_instructions.j2`의 rewrite 기준 축소
    - 단순 문체 차이나 섹션명 표현 차이로 rewrite가 걸리지 않게 기준 정리
    - rewrite_needed는 구조 손상, 심각한 수치 충돌, 섹션 누락에만 반응하도록 제한
    - _목표: 쓸데없는 재작성 방지_

  - [x] 2.3 검수/재작성 회귀 테스트 추가
    - 현재 valid한 `Section 0~6` 브리프가 rewrite 없이 pass하는 예시 테스트 추가
    - 실제 rewrite가 필요한 손상된 브리프는 여전히 rewrite로 가는지 확인
    - _검증 대상: `/Users/giwon/code/news/tests/test_briefing_quality.py`, `/Users/giwon/code/news/tests/test_brief_review.py`_

  - [ ] 2.4 비용 절감 확인용 run-level acceptance 정의
    - 이 단계 완료 후 기대치:
      - OpenAI requests가 동일 데이터 기준 `9 -> 7 이하`
      - `brief_review_failed` 이벤트 현저히 감소
    - 실제 수치는 다음 run artifact로 검증

- [ ] 3. 생성 프롬프트 payload에서 중복 컨텍스트 제거
  - [x] 3.1 `_build_news_focus()` payload 축소
    - `topic_summaries`, `x_market_signals`, `sonar_context` 중 중복되는 필드를 제거
    - `packet_json`에 이미 들어 있는 데이터는 `news_focus_json`에서 다시 보내지 않도록 정리
    - `top_items`는 브리프 생성에 필요한 최소 필드만 유지
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/prompting.py:60`_

  - [x] 3.2 `brief_input.j2`에서 중복 설명 제거
    - `<market_data_json>`와 `<news_focus_json>` 역할을 구분해서 한 번만 설명
    - `sonar_context`는 `news_focus_json` 안에 포함되면 별도 bullet로 다시 설명하지 않음
    - 프롬프트 지침은 유지하되 맥락 설명 텍스트를 압축
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/prompts/brief_input.j2:4`_

  - [x] 3.3 prompt cache 효율 회귀 테스트 추가
    - 같은 instructions/static prefix에서 cache key가 안정적으로 유지되는지 확인
    - payload 축소 후에도 기존 출력 계약이 깨지지 않는지 테스트
    - _검증 대상: `/Users/giwon/code/news/tests/test_prompting.py`_

  - [ ] 3.4 입력 토큰 절감 acceptance 정의
    - 동일한 fixture 기준으로 generation input token 목표:
      - `packet + news_focus` 직렬화 길이 최소 20% 감소
      - 실제 OpenAI input token 총량 `112,777 -> 90,000 이하` 목표

- [ ] 4. publish 품질 gate를 앞당겨 불필요한 검색/백필/번역 비용 제거
  - [x] 4.1 publish early filter 함수 추가
    - `filter_publish_news()`와 같은 기준을 **candidate merge 직후**에도 적용할 수 있는 helper 추가
    - blocked domain, non-preferred domain, placeholder title, file-like title, duplicate interpretation을 초기에 제거
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/data/news_selection.py:54`_

  - [x] 4.2 public용 뉴스 풀과 이메일용 뉴스 풀 분리
    - 이메일용은 기존 흐름 유지
    - public용은 조기 필터를 통과한 후보만 유지
    - public에서 `kept_count=0`이면 backfill과 번역 입력 후보도 그 기준을 따르도록 연결
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/data/news.py`_

  - [x] 4.3 OpenAI web backfill trigger 강화
    - preferred domain 기준으로 public/email 모두 부족할 때만 web backfill 수행
    - `source_only_fallback` 결과가 public gate를 통과할 가능성이 낮으면 merge하지 않음
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/research_backfill.py:392`_

  - [x] 4.4 consumer-aware backfill 분기 추가
    - `public_home`와 `public_detail`에서 실제로 필요 없는 후보라면 backfill 자체를 건너뜀
    - 예:
      - `public_home`가 이미 `featuredNews` 조건을 채웠으면 추가 기사 backfill 금지
      - `public_detail` 기준 minimum도 못 채우는 domain set이면 source-only fallback merge 금지
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/research_backfill.py`, `/Users/giwon/code/news/src/morning_brief/data/news.py`_

  - [x] 4.5 회귀 테스트 추가
    - non-preferred domain만 있는 날에는 public 뉴스가 비는 대신, web backfill이 과도하게 호출되지 않는지 검증
    - email은 여전히 기존 max_news_items 흐름을 유지하는지 확인
    - _검증 대상: `tests/test_news_quality.py`, `tests/test_research_backfill.py`_

  - [ ] 4.6 비용 절감 acceptance 정의
    - 최신 문제 케이스 기준:
      - public `candidate_count=12 kept_count=0`이면 OpenAI web backfill 호출 수 또는 extra item 수가 줄어야 함
      - Perplexity cost가 동일한 날 `0.014577 -> 0.010 이하` 수준으로 감소하는지 다음 run에서 확인

- [ ] 5. 공개 번역 범위와 모델 사용을 축소
  - [x] 5.1 공개 번역 대상을 `featured` 우선으로 축소
    - 번역 대상 기본값:
      - `headline`
      - `summaryLead`
      - `summarySupport`
      - `featuredNews`
      - `featuredXSignals`
      - `topicSummaries.summary`
    - `allNews`, `allXSignals`는 기본적으로 raw 유지 또는 선택적 번역 플래그로 분리
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/public_site.py:1056`_

  - [x] 5.2 번역 전용 모델 설정 분리
    - `Settings`에 `openai_public_translation_model` 추가
    - 비어 있으면 기존 `openai_model` fallback
    - 운영 시 generation보다 더 작은/싼 모델을 선택할 수 있게 함
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/config.py:13`_

  - [x] 5.3 번역 호출 조건 강화
    - `featured`가 비었으면 해당 타입 번역 요청 자체를 생략
    - 이미 한국어인 필드, 숫자/티커/URL만 포함된 필드는 기존처럼 pass-through 유지
    - translation batch 구성 전 pending 수가 너무 적거나 raw-only면 건너뛰는 조건 추가
    - consumer matrix상 해당 소비자에서 쓰지 않는 필드는 번역 대상 후보에서 제외

  - [x] 5.4 번역 회귀 테스트 추가
    - `translationStatus`가 `ok/partial/failed`로 정확히 내려오는지 유지
    - 축소 이후에도 홈에 필요한 한국어 필드가 여전히 채워지는지 확인
    - 사용하지 않는 `allNews`/`allXSignals` raw 필드가 번역 요청에 들어가지 않는지 확인
    - _검증 대상: `/Users/giwon/code/news/tests/test_public_site.py`_

  - [ ] 5.5 비용 절감 acceptance 정의
    - OpenAI requests에서 public translation 배치 수 감소
    - OpenAI cost 목표:
      - `0.047275 -> 0.035 이하`
      - translation 관련 호출 수 최소 30% 절감

- [x] 6. phase별 observability를 추가해 원인 추적을 즉시 가능하게 만듦
  - [x] 6.1 provider usage 기록 API에 `phase` 개념 추가
    - `record_provider_usage(provider, ..., phase=...)` 또는 동등한 구조 추가
    - 기존 집계와 하위 호환 유지
    - _검증 대상 파일: `/Users/giwon/code/news/src/morning_brief/observability.py`_

  - [x] 6.2 OpenAI 호출 지점에 phase 태깅 추가
    - generation: `/Users/giwon/code/news/src/morning_brief/briefing.py`
    - review/rewrite: `/Users/giwon/code/news/src/morning_brief/brief_review.py`
    - web backfill: `/Users/giwon/code/news/src/morning_brief/research_backfill.py`
    - public translation: `/Users/giwon/code/news/src/morning_brief/public_site.py`

  - [x] 6.3 run summary에 phase breakdown 포함
    - run.log와 observability JSON에서 바로 볼 수 있게 phase별 request/input/output/cost 집계 추가
    - 다음 비용 이슈 발생 시 artifact 한 번으로 원인 파악 가능해야 함

  - [x] 6.4 observability 회귀 테스트 추가
    - provider 총합과 phase 총합이 일치하는지 검증
    - phase가 누락돼도 기존 총합 계산이 깨지지 않는지 확인

- [x] 7. 문서와 운영 체크리스트 업데이트
  - [x] 7.1 비용 절감 전략 문서화
    - 왜 검수 정합성, prompt slimming, early gate, translation 축소가 우선인지 정리
    - 운영자가 run cost가 다시 튀면 어디를 볼지 체크리스트 추가
    - 위치: `/Users/giwon/code/news/docs/` 하위 가장 가까운 운영 문서 또는 신규 문서

  - [x] 7.2 운영 지표 업데이트
    - 성공 기준:
      - OpenAI requests `<= 7`
      - OpenAI input tokens `<= 90,000`
      - OpenAI cost `<= $0.035`
      - total cost `<= $0.055`
    - 이 값은 2026-03-23 기준선과 최근 안정 run 사이를 절충한 목표치다

- [ ] 8. 최종 검증
  - [x] 8.1 좁은 범위 테스트
    - `pytest -q tests/test_prompting.py tests/test_brief_review.py tests/test_briefing_quality.py tests/test_public_site.py tests/test_news_quality.py tests/test_research_backfill.py`
  - [ ] 8.2 코드 품질 검증
    - `make fmt`
    - `make lint`
    - `make test`
    - `make typecheck`
  - [ ] 8.3 실 run 검증
    - `main`에서 `Morning Market Brief` 1회 실행
    - 최신 run artifact에서 phase별 usage와 총 cost 비교
    - 목표치 미달이면 어느 phase가 남았는지 관측성으로 바로 확인

## 작업 순서 제안

1. 태스크 1: 기준선 테스트와 phase logging 뼈대 추가
2. 태스크 2: 검수 프롬프트 정합성 수정
3. 태스크 3: 생성 프롬프트 payload slimming
4. 태스크 4: publish early gate + backfill trigger 강화
5. 태스크 5: public translation 축소 및 모델 분리
6. 태스크 6: observability phase breakdown 마감
7. 태스크 7~8: 문서화와 최종 run 검증

선행 조건:

- 태스크 0이 끝나기 전에는 태스크 4와 5를 구현하지 않는다.
- 이유: consumer matrix와 collection budget이 없으면 “후단에서만 줄이는 구현”으로 다시 회귀할 가능성이 크다.

## 완료 판단 기준

아래를 모두 만족해야 완료로 본다.

- 최신 `main` run에서 OpenAI 요청 수와 입력 토큰이 기준선 대비 감소
- `brief_review_failed`가 false positive로 반복되지 않음
- public 뉴스가 0건인 날에도 Perplexity/OpenAI backfill 비용이 과도하게 증가하지 않음
- public 번역이 홈에 필요한 핵심 필드만 처리하고, 상세용 raw까지 무조건 번역하지 않음
- observability JSON만 열어도 어느 phase가 비용을 썼는지 즉시 알 수 있음
- consumer별로 실제 쓰지 않는 데이터가 upstream 수집/backfill/번역 단계에서 제외됨

## 루브릭

이 문서는 아래 조건을 만족해야 한다.

- [ ] 작업자가 **코드베이스를 처음 봐도** 손댈 파일과 순서를 알 수 있다
- [ ] 각 태스크에 **왜 이 작업을 하는지**가 적혀 있다
- [ ] 각 태스크에 **구체 파일 경로**가 있다
- [ ] 테스트와 acceptance가 있어 완료 여부를 판단할 수 있다
- [ ] 비용 절감 목표가 숫자로 적혀 있다
- [ ] 이메일 품질/공개 JSON 품질을 해치지 않는 보존 조건이 있다
- [ ] run artifact와 observability를 이용한 실제 검증 단계가 있다
