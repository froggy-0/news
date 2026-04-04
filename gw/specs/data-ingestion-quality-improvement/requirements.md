# Requirements Document

## Introduction

현재 데이터 수집 파이프라인은 정형(시장 지표), 반정형(뉴스 패킷), 비정형(X 시그널/텍스트) 세 유형의 데이터를 처리하지만, 유형 간 경계에서 타입 안정성이 깨지고, 품질 지표가 유형을 구분하지 않으며, 공급자 식별 상수가 중복 정의되어 있다. 이 작업은 데이터 엔지니어링 관점에서 수집·분류·품질 평가 레이어를 강화해 파이프라인의 신뢰성과 유지보수성을 높인다. 구현 로직(LLM 브리핑 생성, 이메일 발송, 프론트엔드)은 범위 밖이다.

## Glossary

- **Provider**: 데이터를 공급하는 외부 서비스 (예: `perplexity_search`, `grok_x_keyword`). 현재 문자열 리터럴로 식별됨
- **canonical_key**: 시장 지표를 유일하게 식별하는 정규화된 키 (예: `btc_usd`, `us10y`)
- **NewsItem**: 뉴스 단건을 표현하는 dataclass. 파이프라인 내부 표준 타입
- **뉴스 패킷(news packet)**: `NewsItem` 목록을 `list[dict]`로 직렬화한 중간 표현. 현재 타입 정보가 소실됨
- **XSignal**: Grok X 키워드 검색에서 수집한 소셜 시그널 dataclass
- **zero_ratio**: 시장 포인트 중 가격이 0이거나 누락된 비율. 현재 전체 포인트를 단일 배열로 계산
- **staleness**: 캐시에 저장된 데이터가 실제 수집 시각 기준으로 허용 시간을 초과한 상태
- **meaningless interpretation**: `why_it_matters` / `summary` 필드가 "없음", "N/A" 등 내용이 없는 것으로 판정되는 문자열

---

## Requirements

### Requirement 1: Provider 식별 상수 단일 출처화

**카테고리:** 데이터 모델

**User Story:**
As a 파이프라인 유지보수 엔지니어,
I want 모든 provider 식별자를 단일 모듈에서 관리하고,
so that provider 이름 변경 또는 추가 시 한 곳만 수정해도 시스템 전체에 반영되어 오탈자로 인한 silent bug를 방지할 수 있다.

**현재 문제:**
`PERPLEXITY_PROVIDER = "perplexity_search"` 등 동일 상수가 `data_quality.py:11-16`와 `news_selection.py:21-26`에 각각 중복 정의되어 있다. 향후 값이 달라질 경우 런타임에서야 불일치를 감지한다.

#### Acceptance Criteria

1. WHEN 파이프라인이 provider 이름을 참조할 때, THE 모든 모듈 SHALL `morning_brief.data.providers` 단일 모듈의 상수(또는 `Literal` type alias / `StrEnum`)만 임포트한다
2. WHEN 기존 `data_quality.py`, `news_selection.py`, `news_packet.py`가 provider 상수를 사용할 때, THE 해당 모듈 SHALL 직접 문자열 리터럴을 정의하지 않고 `providers` 모듈을 참조한다
3. IF 새로운 provider가 추가될 때, THEN THE `providers` 모듈 SHALL 해당 상수를 추가하는 단일 변경으로 파이프라인 전체에 반영된다
4. WHEN 테스트가 실행될 때, THE 테스트 SHALL `providers` 모듈의 상수 값이 각 소스 파일에서 사용되는 값과 동일함을 검증한다

---

### Requirement 2: 뉴스 패킷 스키마 명시 및 타입 경계 보존

**카테고리:** 데이터 모델

**User Story:**
As a 파이프라인 개발자,
I want 뉴스 패킷의 필드 구조를 명시된 타입으로 정의하고,
so that `NewsItem → dict` 변환 이후에도 필드 접근이 타입 안전하게 유지되어 필드명 변경 시 런타임 오류 대신 정적 분석이 경고를 잡아낸다.

**현재 문제:**
`news_items_to_packet()`이 `NewsItem` → `dict` 변환 후 `data_quality.py`에서 `item.get("age_hours")`, `item.get("domain")` 등 raw dict 접근이 발생한다. `NewsItem` 필드명 변경 시 `data_quality.py`는 silently `None`을 반환한다.

#### Acceptance Criteria

1. WHEN `news_items_to_packet`이 반환할 때, THE 반환 타입 SHALL `TypedDict` 또는 이에 준하는 명시된 스키마로 정의된다
2. WHEN `data_quality.py`가 뉴스 패킷 필드에 접근할 때, THE 접근 키 SHALL 스키마 정의의 필드명과 일치해야 하며 mypy가 오류를 검출한다
3. WHEN `NewsItem`의 필드가 변경될 때, THE `news_items_to_packet` 변환 로직 SHALL 컴파일 타임(mypy strict)에서 타입 불일치를 노출한다
4. WHEN 기존 파이프라인이 패킷을 소비하는 모든 위치(briefing, emailer, public_site 등)는, THE 변경 후에도 CONTINUE TO 동일한 dict 키 접근 패턴을 사용할 수 있다 (하위 호환 유지)

---

### Requirement 3: 시장 포인트 캐시 TTL 및 staleness 경고

**카테고리:** 오류 처리

**User Story:**
As a 파이프라인 운영자,
I want 시장 포인트 캐시가 수집 시각을 함께 기록하고 설정된 TTL을 초과 시 경고를 남기도록 하고,
so that live fetch 실패로 stale 캐시가 사용될 때 이를 인지하고 브리핑 데이터 신뢰도를 판단할 수 있다.

**현재 문제:**
`_load_market_point_cache`는 파일 mtime을 확인하지 않아 며칠 전 캐시가 조용히 재사용된다. BTC ETF에만 `BTC_ETF_CACHE_MAX_AGE_HOURS = 48` TTL이 존재하고 `MarketPoint` 캐시에는 없다.

#### Acceptance Criteria

1. WHEN 시장 포인트 캐시 파일이 저장될 때, THE 파일 SHALL 최상위에 `"cached_at": "<ISO 8601 UTC>"` 필드를 포함한다
2. WHEN 캐시를 로드할 때 `cached_at`이 설정 임계값(기본 `MARKET_POINT_CACHE_MAX_AGE_HOURS = 26`)을 초과하면, THE 시스템 SHALL `WARNING` 수준 구조화 로그(`event="cache.stale"`)를 남기고 캐시를 사용한다 (중단하지 않음)
3. WHEN `cached_at` 필드가 없는 기존 캐시 파일을 로드할 때, THE 시스템 SHALL `staleness` 판정 없이 기존 방식대로 로드한다 (하위 호환)
4. IF live fetch가 성공하면, THEN THE 시스템 SHALL staleness 경고 없이 CONTINUE TO 정상 동작한다
5. WHEN `MARKET_POINT_CACHE_MAX_AGE_HOURS` 설정값이 존재할 때, THE `Settings` 클래스 SHALL 해당 값을 환경변수(`MARKET_POINT_CACHE_MAX_AGE_HOURS`)로 오버라이드할 수 있다

---

### Requirement 4: 시장 데이터 품질 지표 카테고리별 분리

**카테고리:** 비즈니스 로직

**User Story:**
As a 파이프라인 운영자,
I want 시장 데이터 품질 지표를 카테고리(macro, indices, tech, bitcoin)별로 분리해서 확인하고,
so that 특정 소스 장애 시 어느 카테고리가 문제인지 즉시 파악하고 브리핑 품질을 정확히 평가할 수 있다.

**현재 문제:**
`_zero_ratio`가 `macro + us_indices + tech_stocks + btc`를 단일 배열로 평탄화해 계산한다. 기술주 10개의 zero가 거시지표 3개보다 비율에 더 큰 영향을 미쳐 "어느 소스가 죽었는지" 알 수 없다.

#### Acceptance Criteria

1. WHEN `assess_data_quality`가 호출될 때, THE 반환값 SHALL `"zero_ratio_by_category": {"macro": float, "indices": float, "tech": float, "bitcoin": float}` 필드를 포함한다
2. WHEN 전체 `zero_ratio`가 계산될 때, THE 시스템 SHALL 카테고리별 zero_ratio의 **최댓값**을 사용한다 (가중 평균은 macro 전멸을 희석하므로 채택하지 않음)
3. WHEN `"critical"` 상태 판정 시, THE 시스템 SHALL 기존 임계값(`zero_ratio >= 0.8` 또는 `news_count < MIN_NEWS_ITEMS`)을 유지한다 (하위 호환)
4. WHEN 기존 `"zero_price_ratio"` 필드를 소비하는 코드가 있을 때, THE 해당 필드 SHALL 기존과 동일하게 반환된다 (하위 호환, 단 계산 방식은 최댓값 방식으로 변경)
5. WHEN `bitcoin` 카테고리 zero_ratio가 계산될 때, THE 시스템 SHALL `build_market_packet` 경로에서 `etf_points`가 항상 `[]`임을 인지하고 spot 단일 포인트만을 기준으로 판정한다

---

### Requirement 5: 뉴스 아이템 제목 기반 보조 dedup

**카테고리:** 비즈니스 로직

**User Story:**
As a 구독자,
I want 동일 사건을 여러 언론사가 거의 동일한 제목으로 보도했을 때 한 건만 보이고,
so that 브리핑에서 같은 내용이 반복되는 경험을 줄이고 더 다양한 뉴스를 받아볼 수 있다.

**현재 문제:**
`_dedup_and_rank`는 `normalized_url`만 dedup 키로 사용한다. Reuters, AP, Bloomberg이 동일 사건을 각자 URL로 보도하면 3건이 모두 통과된다.

#### Acceptance Criteria

1. WHEN `_dedup_and_rank`가 실행될 때, THE 시스템 SHALL URL이 다르더라도 제목 앞 40자(`title[:40]`)를 정규화한 보조 키가 동일한 경우 중복으로 판정하고 더 높은 점수의 아이템을 유지한다
2. WHEN 보조 dedup 키가 충돌할 때, THE 시스템 SHALL `_item_score`가 더 높은 아이템을 유지하고 낮은 것을 버린다
3. WHEN 제목 앞 40자가 비어있거나 None인 아이템은, THE 시스템 SHALL URL 기반 dedup만 적용하고 보조 dedup에서 제외한다
4. WHEN 기존 URL dedup이 동작하던 케이스에서, THE 시스템 SHALL CONTINUE TO URL 기반 dedup을 우선 적용한다

---

### Requirement 6: XSignal 중복 제거

**카테고리:** 비즈니스 로직

**User Story:**
As a 구독자,
I want 같은 사건에 대해 여러 X 계정이 거의 동일한 헤드라인으로 올린 시그널 중 하나만 보이고,
so that X 시그널 섹션이 다양한 관점을 제공하며 동일 내용 반복을 피한다.

**현재 문제:**
`XSignal`에는 URL이 없어 `_dedup_and_rank` 로직이 적용되지 않는다. 동일 이벤트에 대한 여러 계정의 시그널이 모두 통과된다.

#### Acceptance Criteria

1. WHEN `_cap_signals_by_topic`이 실행되기 전, THE 시스템 SHALL `source_handle + headline[:30]` 복합 키로 중복 XSignal을 제거하고 `posted_at`이 더 최신인 것을 유지한다
2. IF `posted_at`이 동일하거나 None이면, THEN THE 시스템 SHALL 먼저 수집된 아이템을 유지한다
3. WHEN dedup 후 제거된 건수가 1건 이상이면, THE 시스템 SHALL `DEBUG` 수준 구조화 로그(`event="dedup.applied"`, `provider="x_signal"`, `removed_count=N`)를 남긴다
4. WHEN XSignal 목록이 비어있을 때, THE 시스템 SHALL 오류 없이 빈 목록을 반환한다

---

### Requirement 7: 다국어 meaningless interpretation 탐지 확장

**카테고리:** 비즈니스 로직

**User Story:**
As a 파이프라인 품질 관리자,
I want `why_it_matters` / `summary` 필드의 무의미한 응답을 한국어와 영어 모두에서 탐지하고,
so that 공급자가 영어로 빈 응답을 돌려줄 때도 해당 아이템이 퍼블리시 목록에서 걸러진다.

**현재 문제:**
`_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS`가 "없음", "해당없음" 등 한국어 패턴만 포함한다. "N/A", "None", "No information available" 등 영어 응답은 탐지하지 못한다.

#### Acceptance Criteria

1. WHEN `_has_meaningful_public_interpretation`이 호출될 때, THE 시스템 SHALL 아래 영어 패턴도 무의미로 판정한다: `"n/a"`, `"na"`, `"none"`, `"no information"`, `"no comment"`, `"not available"`, `"unknown"`, `"–"`, `"-"`
2. WHEN interpretation 텍스트가 30자 미만이고 위 패턴 목록 중 하나와 정규화 후 일치할 때, THE 시스템 SHALL 해당 아이템을 `"placeholder_public_interpretation"` 사유로 드롭한다
3. WHEN 유효한 영어 interpretation(예: "The Fed raised rates...")이 있을 때, THE 시스템 SHALL CONTINUE TO 해당 아이템을 통과시킨다
4. WHEN 패턴 목록이 변경될 때, THE 해당 패턴 목록 SHALL `news_selection.py`의 단일 상수(`_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS`)에서만 관리된다

---

### Requirement 8: 도메인 점수 및 티어 외부 설정 분리

**카테고리:** 설정/환경

**User Story:**
As a 파이프라인 운영자,
I want 도메인 점수와 티어 정의를 코드 외부(YAML/JSON)에서 관리하고,
so that 새로운 신뢰 출처 추가 또는 점수 조정을 코드 변경 없이 설정 파일 수정만으로 적용할 수 있다.

**현재 문제:**
`news_policy.py`의 `PREFERRED_DOMAINS`, `DOMAIN_SCORES`, `SOURCE_TIERS`가 코드에 하드코딩되어 있어 변경 시 코드 리뷰와 배포가 필요하다. 점수의 근거도 기록되지 않는다.

#### Acceptance Criteria

1. WHEN `news_policy` 모듈이 임포트될 때, THE 시스템 SHALL 프로젝트 루트 기준 `config/domain_policy.yaml`을 자동으로 로드해 모듈 레벨 상수(`DOMAIN_SCORES`, `SOURCE_TIERS`, `PREFERRED_DOMAINS`)를 초기화한다 (스케줄러 재시작 없이 YAML 변경 반영 불가 — 의도된 동작)
2. WHEN `config/domain_policy.yaml`이 존재하지 않을 때, THE 시스템 SHALL 기존 하드코딩 값을 폴백으로 사용하고 `WARNING` 로그를 남긴다
3. WHEN 설정 파일에 `score_rationale` 필드가 있을 때, THE 시스템 SHALL 해당 필드를 로드 시 무시하되 오류를 발생시키지 않는다 (문서화 용도 허용)
4. WHEN 설정 파일의 스키마가 유효하지 않을 때(필수 필드 누락, 점수가 음수 등), THE 시스템 SHALL `WARNING` 로그를 남기고 하드코딩 fallback으로 계속 실행한다 (프로덕션에서 YAML 손상으로 인한 파이프라인 전체 중단 방지)
5. WHEN 테스트가 실행될 때, THE 테스트 SHALL 기존 하드코딩 값과 동일한 설정 파일을 로드했을 때 동일한 결과를 반환함을 검증한다
6. WHEN `PyYAML`이 `requirements.txt`에 없을 때, THE 시스템 SHALL 빌드 단계에서 의존성 오류를 발생시킨다 — `PyYAML`을 `requirements.txt`에 명시적으로 추가한다

---

## 우선순위 및 구현 순서

| 우선순위 | Requirement | 이유 |
|---------|-------------|------|
| P0 | R1 (Provider 상수 단일화) | silent bug 위험, 후속 작업 전제 조건 |
| P0 | R2 (뉴스 패킷 타입 경계) | mypy strict 위반, 필드 변경 시 회귀 위험 |
| P1 | R3 (시장 캐시 TTL) | stale 데이터 운영 노출 방지 |
| P1 | R4 (카테고리별 zero_ratio) | 장애 진단 가시성 |
| P2 | R5 (뉴스 제목 dedup) | 브리핑 품질 직접 영향 |
| P2 | R6 (XSignal dedup) | 브리핑 품질, 구현 범위 작음 |
| P2 | R7 (다국어 interpretation 탐지) | 공급자 응답 언어 다양성 대응 |
| P3 | R8 (도메인 정책 외부화) | 운영 편의, 긴급도 낮음 |
