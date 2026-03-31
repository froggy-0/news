# Requirements Document

## Introduction

프론트엔드 "AI 뉴스 분석" 섹션의 뉴스 카드에 `summaryKo`(뉴스 해설)와 `interpretation`(시장 함의)가 자주 비거나 불충분하게 채워진다. 원인은 두 가지다. 첫째, `public_news_analysis_instructions.j2` 프롬프트가 지나치게 보수적으로 설계되어 입력 데이터가 얇으면 바로 빈 문자열을 반환하며, 토픽(ai_bigtech·macro·bitcoin·us_equity)별 분석 지침이 없다. 둘째, Grok X 키워드 검색이 4개 그룹(매크로+증시, 크립토+ETF, AI 빅테크, BTC ETF)을 별도로 실행하여 중복 커버리지가 발생하고 Grok API 호출량이 과도하다. 이번 작업에서는 프롬프트 품질을 끌어올리고 Grok 검색 그룹을 통합·감소시켜 "AI 뉴스 분석" 섹션 데이터 충족률을 개선하고 API 비용을 줄인다.

## Glossary

**AI 뉴스 분석 섹션**: 프론트엔드 홈 페이지에 표시되는 `NewsFeedClient` 컴포넌트. 뉴스 카드별 `뉴스 해설(summaryKo)`과 `시장 함의(interpretation)`를 보여줌
**뉴스 해설(summaryKo)**: 기사 핵심을 한국어 1~2문장으로 정리한 필드 (240자 이하)
**시장 함의(interpretation)**: 기사가 시장·자산에 갖는 의미를 한국어 1문장으로 정리한 필드 (120자 이하)
**토픽별 분석 지침**: 기사 `topic`(`"macro"`, `"ai_bigtech"`, `"bitcoin"`, `"us_equity"`) 값에 따라 다르게 적용하는 해설 초점 규칙. `PublicNewsAnalysisInput.topic` 필드 기준이며 프론트엔드 `category` 값과는 다름
**Grok X 키워드 그룹**: `grok_x_keyword.py`의 `MACRO_EQUITY_GROUP`, `CRYPTO_ETF_GROUP`, `AI_BIGTECH_GROUP`, `BTC_ETF_GROUP` 4개 검색 그룹
**그룹 통합**: 중복 커버리지가 있는 두 그룹을 하나로 합치는 작업 (CRYPTO_ETF + BTC_ETF → BITCOIN_CRYPTO)
**max_items**: 각 Grok 그룹 검색에서 반환받는 최대 시그널 수
**세계 지식 보완**: 프롬프트에서 입력 데이터가 얇을 때 LLM의 배경 지식을 활용해 분석을 보강하는 허용 규칙

---

## Requirements

### Requirement 1: public_news_analysis 프롬프트 품질 개선

**User Story:**
As a 공개 브리프 독자,
I want "AI 뉴스 분석" 섹션의 모든 뉴스 카드에 읽을 수 있는 한국어 해설과 시장 함의가 채워지길 원한다,
so that 기사 제목만 보는 것이 아니라 기사가 왜 중요한지 카드 안에서 바로 이해할 수 있다.

#### Acceptance Criteria

1. WHEN 기사 해설 생성 프롬프트가 실행될 때, THE prompt SHALL 입력 데이터가 얇더라도 LLM의 배경 지식을 활용해 해설을 보강할 수 있도록 허용한다. 단, 입력에 없는 구체적 수치·날짜·기업명을 새로 지어내는 것은 금지한다.
2. WHEN 기사 해설 생성 프롬프트가 실행될 때, THE prompt SHALL 기사 `topic`(`"macro"`, `"ai_bigtech"`, `"bitcoin"`, `"us_equity"`) 값에 따라 해설의 초점이 달라지도록 토픽별 분석 지침을 포함한다.
3. WHEN `topic`이 `"ai_bigtech"`인 기사 해설이 생성될 때, THE generated text SHALL AI 인프라, 반도체 공급망, 모델 발표, 설비투자 등 AI/빅테크 맥락의 함의를 우선 반영한다.
4. WHEN `topic`이 `"macro"`인 기사 해설이 생성될 때, THE generated text SHALL 연준 정책, 금리 기대, 인플레이션, 성장 전망과의 연결을 우선 반영한다.
5. WHEN `topic`이 `"bitcoin"`인 기사 해설이 생성될 때, THE generated text SHALL ETF 자금 흐름, 규제 동향, 기관 수요와의 연결을 우선 반영한다.
6. WHEN `topic`이 `"us_equity"`인 기사 해설이 생성될 때, THE generated text SHALL 섹터 영향, 지수 영향, 투자 심리와의 연결을 우선 반영한다.
7. WHEN 기사 해설 생성 결과가 반환될 때, THE generated text SHALL 빈 문자열이 아니라 의미 있는 한국어 문장이어야 하며, 입력 데이터만으로 충분하지 않아도 기사 제목·출처·토픽을 최소 근거로 삼아 세계 지식을 활용해 내용을 생성한다.
8. IF 기사 입력에 `title`과 `topic` 이상의 정보가 없는 경우, THEN THE prompt SHALL 빈 문자열 대신 제목과 토픽을 근거로 최소 1문장 해설을 생성하는 것을 허용한다.

---

### Requirement 2: public_news_analysis reasoning 수준 상향

**User Story:**
As a 운영자,
I want 뉴스 해설 생성 LLM 호출의 추론 수준이 적절히 설정되길 원한다,
so that 얇은 입력에도 문맥을 살린 해설이 생성되고 빈 응답 발생률을 낮출 수 있다.

#### Acceptance Criteria

1. WHEN `enrich_public_news_packet()`이 LLM을 호출할 때, THE call SHALL `reasoning={"effort": "low"}`를 사용한다 (현재 `"minimal"`에서 `"low"`로만 변경).
2. WHEN reasoning 수준이 변경될 때, THE pipeline SHALL 기존 `max_output_tokens` 공식(`min(3200, max(900, 320 × batch_size))`)을 변경하지 않는다. reasoning 토큰은 출력 토큰과 별도이므로 조정 불필요.
3. WHEN reasoning 수준 설정이 변경될 때, THE pipeline SHALL 기존 `Settings`의 `openai_public_news_analysis_model` 경로를 그대로 사용하고 별도 환경변수를 추가하지 않는다.

---

### Requirement 3: Grok X 키워드 그룹 통합 (CRYPTO_ETF + BTC_ETF → BITCOIN_CRYPTO)

**User Story:**
As a 운영자,
I want Grok X 키워드 검색 그룹 수를 줄여 API 호출과 비용을 낮추길 원한다,
so that 중복 커버리지를 제거하면서 시장 시그널의 다양성은 유지할 수 있다.

#### Acceptance Criteria

1. WHEN Grok X 키워드 검색이 실행될 때, THE pipeline SHALL `CRYPTO_ETF_GROUP`과 `BTC_ETF_GROUP` 두 그룹을 하나의 `BITCOIN_CRYPTO_GROUP`으로 통합하여 실행한다.
2. WHEN `BITCOIN_CRYPTO_GROUP` 프롬프트가 구성될 때, THE prompt SHALL 비트코인 ETF 자금 흐름, BTC 가격 동향, 크립토 규제, 기관 수요를 모두 커버하도록 두 기존 프롬프트의 핵심 포커스를 병합한다.
3. WHEN 그룹 통합 후 파이프라인이 실행될 때, THE pipeline SHALL Grok X 키워드 검색 그룹 수가 4개에서 3개(MACRO_EQUITY, AI_BIGTECH, BITCOIN_CRYPTO)로 줄어들고 API 호출도 그에 맞게 감소한다.
4. WHEN `grok_x_keyword.py`에서 `BITCOIN_CRYPTO_GROUP` 핸들을 구성할 때, THE pipeline SHALL `grouped_verified_x_handles()`의 `"crypto_and_etf"`와 `"btc_etf_primary"` 두 그룹 핸들을 코드 내에서 union하여 사용한다. registry JSON 및 `grok_official_signals.py`는 변경하지 않는다.
5. WHEN `GROUP_TOPIC_MAP`이 업데이트될 때, THE pipeline SHALL `BITCOIN_CRYPTO_GROUP`의 `topic`이 `"bitcoin"`으로 매핑되도록 유지한다.
6. IF 통합 그룹 실행 중 오류가 발생하면, THEN THE pipeline SHALL 기존 4-그룹 방식과 동일한 per-group 에러 처리(continue + log)를 적용한다.

---

### Requirement 4: Grok X 키워드 그룹당 max_items 감소

**User Story:**
As a 운영자,
I want 각 Grok X 키워드 그룹에서 반환받는 시그널 수를 줄여 API 토큰 소비를 낮추길 원한다,
so that 관련성 낮은 시그널 처리 비용 없이 핵심 시그널만 파이프라인에 유입시킬 수 있다.

#### Acceptance Criteria

1. WHEN Grok X 키워드 검색의 기본 설정이 적용될 때, THE pipeline SHALL `grok_x_search_max_items`의 기본값을 `6`에서 `4`로 줄인다.
2. WHEN `config.py`에서 `grok_x_search_max_items`가 정의될 때, THE config SHALL 허용 범위를 `min=1, max=8`로 조정한다 (현재 `max=10`에서 감소).
3. WHEN 그룹 통합(Req 3)과 max_items 감소(Req 4)가 동시에 적용될 때, THE pipeline SHALL X 키워드 시그널 총 수가 최대 `3 groups × 4 items = 12`로 줄어든다 (현재 최대 `4 × 6 = 24`에서 50% 감소).
4. WHEN `grok_x_search_max_items`가 환경변수로 오버라이드될 때, THE pipeline SHALL 새 기본값(4)과 상한(8)을 기준으로 검증한다.

---

### Requirement 5: grok_official_signals max_items 감소

**User Story:**
As a 운영자,
I want 공식 X 핸들 시그널 수도 적절히 줄여 전체 Grok 호출 비용을 낮추길 원한다,
so that 핵심 공식 시그널만 유지하면서 토큰 소비를 통제할 수 있다.

#### Acceptance Criteria

1. WHEN grok_official_signals의 기본 설정이 적용될 때, THE pipeline SHALL `official_x_max_items`의 기본값을 `4`에서 `3`으로 줄인다.
2. WHEN `config.py`에서 `official_x_max_items`가 정의될 때, THE config SHALL 허용 범위를 `min=1, max=5`로 조정한다 (현재 `max=6`에서 감소).
3. WHEN 변경 후 파이프라인이 실행될 때, THE pipeline SHALL grok_official 총 시그널 수가 최대 `3 groups × 3 items = 9`로 줄어든다 (현재 최대 `3 × 4 = 12`에서 25% 감소).

---

### Requirement 6: 기존 파이프라인 계약 유지

**User Story:**
As a 유지보수자,
I want 프롬프트 개선과 Grok 그룹 통합이 기존 파이프라인 인터페이스를 깨지 않길 원한다,
so that 이메일 발송, 공개 JSON 직렬화, 관측 가능성 경로에 회귀가 없도록 할 수 있다.

#### Acceptance Criteria

1. WHEN Grok X 키워드 그룹이 통합될 때, THE pipeline SHALL `fetch_x_keyword_signals()`의 반환 타입(`tuple[list[XSignal], list[NewsItem], dict[str, list[str]]]`)을 변경하지 않는다.
2. WHEN 그룹 수가 변경될 때, THE pipeline SHALL `GROUP_TOPIC_MAP`과 `GROUP_PROMPTS` 딕셔너리 구조를 그대로 유지하되 항목 수만 줄인다.
3. WHEN `public_news_analysis_instructions.j2`가 수정될 때, THE pipeline SHALL `enrich_public_news_packet()`의 입출력 인터페이스(`PublicNewsAnalysisInput`, `PublicNewsAnalysisOutput`, JSON schema)를 변경하지 않는다.
4. WHEN 기존 `summaryKo`와 `interpretation` 필드 검증 로직이 실행될 때, THEN THE system SHALL CONTINUE TO placeholder 필터링, 한국어 검증, 글자수 제한 로직을 유지한다.
5. WHEN 이메일 발송 경로와 research backfill 경로가 실행될 때, THEN THE system SHALL CONTINUE TO 이 변경에 영향받지 않고 기존대로 동작한다.

---

### Requirement 7: 관측 가능성 및 테스트 보완

**User Story:**
As a 운영자,
I want 프롬프트 개선과 그룹 통합 결과를 테스트와 로그로 확인할 수 있길 원한다,
so that 품질 변화를 수치로 추적하고 회귀를 빠르게 감지할 수 있다.

#### Acceptance Criteria

1. WHEN `grok_x_keyword` 테스트가 실행될 때, THE test SHALL `BITCOIN_CRYPTO_GROUP` 단독 그룹 시그널 수집 및 `GROUP_TOPIC_MAP` 매핑 정확성을 검증한다.
2. WHEN `public_news_analysis` 테스트가 실행될 때, THE test SHALL 얇은 입력(title + topic만 있는 항목)에서도 비어 있지 않은 해설이 생성되는 케이스를 검증한다.
3. WHEN 전체 테스트 스위트가 실행될 때, THE codebase SHALL `make check` 기준 lint + type + test를 모두 통과한다.
