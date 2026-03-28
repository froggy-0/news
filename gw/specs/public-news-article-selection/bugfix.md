# Bugfix Document

## Bug Description

공개 프론트의 `featuredNews/allNews`가 기사형 뉴스보다 X 기반 항목을 우선 포함할 수 있고, 이때 `summaryKo`와 `interpretation`이 `"해당 없음"` 같은 placeholder로 남아 뉴스 카드의 `뉴스 해설`과 `시장 함의`가 비어 보인다.

### Reproduction Steps

1. `/Users/giwon/code/news/output/briefs_2026-03-28.json` 또는 동일 구조의 공개 브리프 JSON을 확인한다.
2. `featuredNews` 항목의 `source`, `url`, `summaryKo`, `interpretation` 값을 본다.
3. 프론트의 `AI 뉴스 분석` 섹션에서 뉴스 카드의 `뉴스 해설`과 `시장 함의`를 확인한다.

### Current Behavior

- WHEN public brief JSON이 생성될 때, THE public site pipeline SHALL `x_news` 또는 `source`가 `@handle` 형식인 항목을 `featuredNews/allNews`에 포함할 수 있다.
- WHEN 해당 항목의 `summaryKo` 또는 `interpretation`가 `"해당 없음"` 같은 placeholder로 들어올 때, THE public site pipeline SHALL 이를 유효 해설 텍스트로 유지한다.
- WHEN 프론트가 뉴스 카드를 렌더링할 때, THEN THE system SHALL placeholder 텍스트를 그대로 `뉴스 해설`과 `시장 함의`에 노출한다.

### Expected Behavior

- WHEN public news selection이 실행될 때, THE pipeline SHALL 기사형 뉴스 항목을 `featuredNews/allNews`에서 우선 선택한다.
- WHEN `x_news` 또는 `source`가 `@handle` 형식인 항목이 후보에 포함될 때, THEN THE pipeline SHALL 이를 기본적으로 `featuredNews/allNews`에서 제외하거나 기사형 뉴스보다 더 엄격하게 필터링한다.
- WHEN `summaryKo` 또는 `interpretation`가 `"해당 없음"` 또는 동등한 placeholder일 때, THE public site pipeline SHALL 이를 유효한 뉴스 해설로 간주하지 않는다.
- IF 기사형 뉴스 수가 부족한 경우, THEN THE pipeline SHALL X 기반 항목으로 `featuredNews` 슬롯을 채우지 않는다.
- IF 기사형 뉴스 수가 부족한 경우, THEN THE pipeline SHALL 기사형 뉴스만 남긴 축소된 `featuredNews/allNews`를 생성할 수 있다.
- IF 기사형 뉴스 수가 부족한 경우, THEN THE pipeline SHALL CONTINUE TO `featuredXSignals/allXSignals`에서 X 시그널을 별도 섹션으로 제공한다.

### Unchanged Behavior

- WHEN 기사형 뉴스가 정상적으로 `summary`와 `why_it_matters`를 포함할 때, THEN the system SHALL CONTINUE TO 이를 `featuredNews/allNews`로 직렬화하고 프론트 뉴스 카드에서 해설로 표시한다.
- WHEN `featuredXSignals/allXSignals`가 생성될 때, THEN the system SHALL CONTINUE TO 현재처럼 `content`와 `impact`를 포함한 X 시그널 payload를 제공한다.
- WHEN public brief가 생성될 때, THEN the system SHALL CONTINUE TO 기존 `featuredNews`, `allNews`, `featuredXSignals`, `allXSignals` 계약 필드 구조를 유지한다.
