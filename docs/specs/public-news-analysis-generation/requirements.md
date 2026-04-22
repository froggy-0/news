# Requirements Document

## Introduction

현재 공개 뉴스 카드의 `뉴스 해설(summaryKo)`와 `시장 함의(interpretation)`는 기사형 뉴스 선택이 정상이어도 충분히 채워지지 않는다. 그 결과 프론트의 `AI 뉴스 분석` 섹션은 기사 제목은 보이지만, 실제로 읽을 해설 문장이 비거나 placeholder로 남는 경우가 생긴다. 이번 작업의 목적은 공개 기사형 뉴스가 최종 선택된 뒤, 카드에 바로 사용할 수 있는 한국어 해설과 시장 함의를 생성하는 단계를 추가하여 공개 뉴스 품질을 안정적으로 끌어올리는 것이다.

## Glossary

**공개 기사형 뉴스**: `featuredNews/allNews`에 들어가는 기사형 뉴스 항목. X 핸들 기반 항목은 제외한다.  
**뉴스 해설**: 기사 내용을 한국어로 짧게 설명하는 `summaryKo` 필드  
**시장 함의**: 해당 기사가 시장이나 자산 가격 해석에 어떤 의미를 가지는지 설명하는 `interpretation` 필드  
**공개 뉴스 선택**: 공개 사이트에 노출할 기사형 뉴스를 고르는 단계  
**해설 생성 단계**: 공개 뉴스 선택 이후, 기사별 `summaryKo`와 `interpretation`을 생성하는 새 후처리 단계  
**placeholder 텍스트**: `"해당 없음"`, `"없음"`, `"n/a"` 등 실제 설명으로 볼 수 없는 값  
**공개 JSON 계약**: 프론트가 소비하는 `featuredNews`, `allNews`, `summaryKo`, `interpretation` 등 기존 필드 구조

## Requirements

### Requirement 1: 공개 기사형 뉴스 전용 해설 생성 단계 추가

**User Story:**  
As a 공개 브리프 독자,  
I want 기사형 뉴스 카드에 읽을 수 있는 한국어 해설과 시장 함의가 채워지길 원한다,  
so that 기사 제목만 보는 것이 아니라 왜 중요한지 바로 이해할 수 있다.

#### Acceptance Criteria

1. WHEN 공개 기사형 뉴스 선택이 완료될 때, THE pipeline SHALL 공개 기사형 뉴스 항목에 대해 별도의 해설 생성 단계를 실행한다.
2. WHEN 해설 생성 단계가 실행될 때, THE pipeline SHALL `featuredNews/allNews` 후보로 살아남은 기사형 뉴스만 대상으로 사용한다.
3. IF 공개 기사형 뉴스 후보가 `0`건인 경우, THEN THE pipeline SHALL 해설 생성을 건너뛰고 빈 공개 뉴스 묶음을 유지한다.
4. WHEN `featuredXSignals/allXSignals`가 생성될 때, THEN THE system SHALL CONTINUE TO 기존 X 시그널 경로를 그대로 유지한다.

### Requirement 2: 생성 입력 범위와 근거 제한

**User Story:**  
As a 유지보수자,  
I want 해설 생성이 현재 파이프라인이 이미 가진 기사 메타데이터에 기반하길 원한다,  
so that 1차 구현 범위를 통제하고 추가 크롤링 의존성을 만들지 않을 수 있다.

#### Acceptance Criteria

1. WHEN 기사 해설 생성 입력이 준비될 때, THE pipeline SHALL 기사별 `title`, `url`, `source`, `topic`, `summary/snippet`, `why_it_matters`, `published_at`, `citations` 범위 안의 데이터만 사용한다.
2. WHEN v1 해설 생성이 실행될 때, THE pipeline SHALL 추가 기사 본문 크롤링이나 별도 웹 fetch를 필수 조건으로 두지 않는다.
3. IF 기사 항목에 `title` 또는 `url`이 없는 경우, THEN THE pipeline SHALL 해당 항목을 해설 생성 대상에서 제외한다.
4. WHEN 해설이 생성될 때, THEN THE generated output SHALL 현재 기사 입력에 근거한 내용만 포함해야 한다.

### Requirement 3: 뉴스 해설(summaryKo) 생성 품질

**User Story:**  
As a 공개 브리프 독자,  
I want 각 뉴스 카드에 짧고 읽기 쉬운 한국어 기사 해설이 들어가길 원한다,  
so that 기사 핵심을 카드 안에서 빠르게 이해할 수 있다.

#### Acceptance Criteria

1. WHEN 기사 해설이 생성될 때, THE pipeline SHALL 각 기사에 대해 비어 있지 않은 한국어 `summaryKo`를 생성한다.
2. WHEN `summaryKo`가 생성될 때, THE generated text SHALL `1~2문장` 범위여야 한다.
3. WHEN `summaryKo`가 생성될 때, THE generated text SHALL `240자 이하`를 목표로 유지해야 한다.
4. IF 생성 결과가 placeholder 텍스트이거나 의미 없는 반복 문구인 경우, THEN THE pipeline SHALL 해당 결과를 유효한 해설로 간주하지 않는다.

### Requirement 4: 시장 함의(interpretation) 생성 품질

**User Story:**  
As a 공개 브리프 독자,  
I want 각 뉴스 카드에 해당 기사의 시장 함의가 별도로 들어가길 원한다,  
so that 기사 내용과 시장 의미를 구분해서 읽을 수 있다.

#### Acceptance Criteria

1. WHEN 시장 함의가 생성될 때, THE pipeline SHALL 각 기사에 대해 비어 있지 않은 한국어 `interpretation`을 생성한다.
2. WHEN `interpretation`이 생성될 때, THE generated text SHALL `1문장`으로 유지되어야 한다.
3. WHEN `interpretation`이 생성될 때, THE generated text SHALL `120자 이하`를 목표로 유지해야 한다.
4. IF 생성 결과가 기사 요약을 그대로 반복하거나 placeholder 텍스트인 경우, THEN THE pipeline SHALL 해당 결과를 유효한 시장 함의로 간주하지 않는다.

### Requirement 5: 비근거 추론 및 placeholder 차단

**User Story:**  
As a 제품 오너,  
I want 공개 뉴스 해설이 실제 기사 근거에 기반하고 placeholder 없이 출력되길 원한다,  
so that 공개 카드 품질과 신뢰도를 유지할 수 있다.

#### Acceptance Criteria

1. WHEN 해설 생성이 실행될 때, THE pipeline SHALL 입력 기사에 없는 수치, 기업명, 인과 관계를 임의로 추가하지 않는다.
2. IF 입력 기사 정보만으로 근거 있는 한국어 해설을 만들 수 없는 경우, THEN THE pipeline SHALL 해당 기사를 공개 뉴스 결과에서 제외하거나 축소된 결과 집합으로 유지한다.
3. WHEN 공개 JSON이 직렬화될 때, THE pipeline SHALL `"해당 없음"`, `"없음"`, `"n/a"` 등 placeholder 값을 `summaryKo` 또는 `interpretation`으로 내보내지 않는다.
4. WHEN 공개 프론트가 뉴스를 렌더링할 때, THEN THE public payload SHALL CONTINUE TO placeholder 대신 실제 해설이 있는 기사만 노출하도록 지원한다.

### Requirement 6: 공개 JSON 계약 유지

**User Story:**  
As a 프론트엔드 개발자,  
I want 기존 공개 뉴스 JSON 구조가 유지되면서 내용 품질만 좋아지길 원한다,  
so that 프론트 계약을 깨지 않고 카드 품질을 개선할 수 있다.

#### Acceptance Criteria

1. WHEN 공개 브리프 JSON이 생성될 때, THE pipeline SHALL 기존 `featuredNews`와 `allNews` 필드 구조를 유지한다.
2. WHEN 해설 생성이 성공할 때, THE pipeline SHALL 기존 `summaryKo`와 `interpretation` 필드를 의미 있는 한국어 값으로 채운다.
3. WHEN 공개 뉴스가 직렬화될 때, THE pipeline SHALL 기존 `title`, `rawTitle`, `source`, `sourceTier`, `url`, `publishedAt`, `category`, `urgency`, `tags` 필드를 계속 유지한다.
4. IF 공개 뉴스 개수가 줄어드는 경우, THEN THE pipeline SHALL 필드 구조를 바꾸지 않고 축소된 기사 개수만 반환한다.

### Requirement 7: 축소 허용과 fallback 경계 유지

**User Story:**  
As a 제품 오너,  
I want 기사형 뉴스 해설 품질이 부족할 때는 개수를 줄이더라도 품질을 우선하길 원한다,  
so that X성 항목이나 placeholder로 슬롯을 억지로 채우지 않게 할 수 있다.

#### Acceptance Criteria

1. WHEN 기사형 뉴스 해설 생성 후 유효한 기사 수가 기존 목표 개수보다 적을 때, THE pipeline SHALL 축소된 기사 개수를 그대로 유지한다.
2. WHEN 공개 뉴스 개수가 부족할 때, THE pipeline SHALL X 기반 항목을 `featuredNews/allNews`에 다시 섞어 넣지 않는다.
3. WHEN 공개 뉴스 개수가 부족할 때, THE pipeline SHALL 기사형 뉴스 품질을 우선하고 빈 슬롯을 허용한다.
4. WHEN `featuredXSignals/allXSignals`가 생성될 때, THEN THE system SHALL CONTINUE TO X 기반 항목을 해당 섹션에서 정상 노출한다.

### Requirement 8: 기존 이메일 및 연구 경로 보존

**User Story:**  
As a 유지보수자,  
I want 공개 뉴스 해설 생성 기능이 공개 사이트 경로에 국한되길 원한다,  
so that 이메일 본문, 연구 백필, 기존 뉴스 수집 경로 회귀를 막을 수 있다.

#### Acceptance Criteria

1. WHEN 공개 뉴스 해설 생성 기능이 추가될 때, THE pipeline SHALL 공개 사이트용 뉴스 직렬화 경로에 우선 적용된다.
2. WHEN 이메일용 뉴스 선택과 렌더링이 실행될 때, THEN THE system SHALL CONTINUE TO 기존 이메일 경로를 유지한다.
3. WHEN `research_backfill` 또는 일반 publish filter가 실행될 때, THEN THE system SHALL CONTINUE TO 기존 selection 규칙을 유지한다.
4. IF 향후 이메일 경로에도 같은 생성 기능을 확장하지 않는 한, THEN THE current email path SHALL NOT depend on the new public-news analysis stage.

### Requirement 9: 생성 비용 및 범위 제한

**User Story:**  
As a 운영자,  
I want 공개 뉴스 해설 생성이 제한된 수의 기사에만 적용되길 원한다,  
so that 비용과 지연 시간을 통제할 수 있다.

#### Acceptance Criteria

1. WHEN 공개 뉴스 해설 생성이 실행될 때, THE pipeline SHALL 최대 `PUBLIC_ALL_NEWS_ITEMS(현재 12건)` 이내의 기사형 뉴스에만 적용한다.
2. WHEN `featuredNews`가 생성될 때, THE pipeline SHALL `PUBLIC_FEATURED_NEWS_ITEMS(현재 5건)` 범위 안에서 우선 품질 있는 기사 해설을 제공한다.
3. IF 선택된 공개 기사형 뉴스 수가 12건보다 적은 경우, THEN THE pipeline SHALL 존재하는 기사 수만큼만 해설을 생성한다.
4. WHEN 해설 생성 범위가 계산될 때, THE pipeline SHALL 비기사형 항목이나 공개 뉴스 후보에서 탈락한 항목까지 확장하지 않는다.

### Requirement 10: 관측 가능성 및 검증

**User Story:**  
As a 운영자,  
I want 기사 해설 생성 결과를 로그와 테스트로 확인할 수 있길 원한다,  
so that 품질 저하나 provider 실패를 빠르게 파악할 수 있다.

#### Acceptance Criteria

1. WHEN 공개 뉴스 해설 생성이 실행될 때, THE pipeline SHALL 생성 대상 수, 성공 수, 제외 수, 실패 수를 관측 가능한 이벤트로 기록한다.
2. IF provider 호출이 실패하거나 부분 실패하는 경우, THEN THE pipeline SHALL 실패 원인을 기록하고 전체 파이프라인을 치명적으로 중단하지 않는다.
3. WHEN 테스트가 추가될 때, THE codebase SHALL 기사 해설 정상 생성, placeholder 차단, 축소 유지, X 경계 유지 케이스를 포함한다.
4. WHEN `UnifiedOutput -> build_public_brief()` 경로가 실행될 때, THE system SHALL CONTINUE TO 생성된 기사 해설이 최종 공개 JSON에 반영되도록 보장한다.
