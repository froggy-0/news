# Requirements Document

## Introduction

현재 파이프라인은 전시용 브리핑 JSON과 분석용 감성 수치 데이터를 동일한 R2 객체 계층에서 혼용하고 있다. 이 구조는 분석 파이프라인이 대용량 전시 JSON을 읽게 만들어 성능을 저하시킬 뿐 아니라, 전시 페이로드 변경이 통계 입력 계약에 간접 영향을 주는 구조적 결합을 만든다. 이 요구사항의 목표는 R2 저장소를 `raw/`, `curated/`, `analytics/` 레이어로 분리하고, 분석 엔진이 오직 검증된 최소 수치 데이터만 읽도록 계약을 고정하여 성능, 통계적 무결성, 운영 독립성을 확보하는 것이다.

## Glossary

- **raw 데이터**: 외부 공급자 원본 응답 또는 해당 응답을 손실 없이 재현할 수 있는 수집 경계 payload
- **curated 데이터**: 한국 투자자 전시 및 브리핑 생성에 사용하는 full JSON
- **analytics 데이터**: 통계 분석 전용 최소 수치 JSON
- **schemaVersion**: analytics 데이터 계약의 명시적 버전 식별자
- **_backfill 마커**: analytics JSON이 분석 품질 검증을 거친 적재본임을 나타내는 불리언 플래그
- **분석 엔진**: `fetch_r2_sentiment`를 시작점으로 하는 sentiment join 파이프라인
- **유효 행 수**: 품질 필터와 inner join을 통과한 뒤 실제 통계 검정에 사용할 수 있는 행 수
- **실제 등락 라벨**: `btc_log_return` 부호로부터 파생한 `up`, `down`, `flat` 분류값
- **제외 사유**: 분석 대상에서 특정 날짜를 제거한 원인을 나타내는 표준 사유값

## Requirements

### Requirement 1: R2 저장소 레이어 분리

**카테고리:** 데이터 모델/구조

**User Story:**
As a 데이터 엔지니어,
I want 데이터 목적에 따라 R2 경로를 레이어별로 분리하고 싶다,
so that 저장 경로만으로 데이터 성격과 소비 계약을 명확히 구분할 수 있다.

#### Acceptance Criteria

1. WHEN 파이프라인이 외부 공급자 원본 응답을 저장할 때, THE storage layer SHALL `raw/` 네임스페이스 아래에 적재한다.
2. WHEN 1차 배포가 적용되면, THE storage layer SHALL `btc` 심볼에 대해 먼저 `curated/btc/{YYYY-MM-DD}.json` 및 `analytics/btc/{YYYY-MM-DD}.json` 경로를 지원한다.
3. WHEN 후속 확장이 필요해지면, THE storage layer SHALL 동일 경로 규칙을 다른 심볼에도 확장 가능해야 한다.
4. WHEN 동일 실행 시점에 curated 데이터와 analytics 데이터가 모두 생성되면, THE storage layer SHALL 두 객체를 물리적으로 분리하여 각각 독립 경로에 저장한다.
5. IF 분석 파이프라인이 `analytics/` 외 경로를 입력으로 참조하려고 하면, THEN THE system SHALL 이를 계약 위반으로 간주하고 해당 입력을 사용하지 않는다.

### Requirement 2: Curated 전시 레이어 저장 계약

**카테고리:** 출력/리포트/UI

**User Story:**
As a 브리핑 운영자,
I want 전시용 브리핑 JSON이 curated 레이어에 완전한 형태로 저장되길 원한다,
so that 전시 소비 로직이 분석 계약 변경과 독립적으로 유지될 수 있다.

#### Acceptance Criteria

1. WHEN 매일 브리핑 결과가 생성되면, THE curated writer SHALL 시장 스냅샷, AI 판단문, 뉴스 본문을 포함한 full JSON을 `curated/btc/{YYYY-MM-DD}.json`에 저장한다.
2. WHEN curated JSON이 저장되면, THE curated writer SHALL 기존 전시 소비자가 사용하는 메타 정보와 본문 구조를 유지한다.
3. WHEN analytics 데이터 계약이 변경되더라도, THE curated writer SHALL CONTINUE TO 전시 목적의 full payload를 독립적으로 생성한다.
4. WHEN 레거시 공개 경로가 유지되는 migration 기간에는, THE curated writer SHALL 기존 `briefs/{YYYY-MM-DD}.json` 산출물도 함께 유지할 수 있다.

### Requirement 3: Analytics 최소 데이터 계약

**카테고리:** 데이터 모델/구조

**User Story:**
As a 데이터 분석가,
I want 분석에 필요한 최소 수치만 analytics 레이어에 저장되길 원한다,
so that 분석 파이프라인이 가볍고 안정적인 입력만 사용하도록 만들 수 있다.

#### Acceptance Criteria

1. WHEN curated JSON이 생성되는 동일 실행 시점에, THE analytics writer SHALL 분석 전용 JSON을 `analytics/btc/{YYYY-MM-DD}.json`에 함께 저장한다.
2. WHEN analytics JSON이 저장될 때, THE analytics writer SHALL 다음 필드만 포함한다: `schemaVersion`, `producer`, `generatedAt`, `date`, `symbol`, `newsSentiment.mean`, `newsSentiment.std`, `newsSentiment.count`, `sentimentStatus`, `_backfill`.
3. WHEN analytics JSON이 저장될 때, THE analytics writer SHALL `schemaVersion: "v1"`을 포함한다.
4. WHEN analytics JSON이 저장될 때, THE analytics writer SHALL `producer`와 `generatedAt`을 포함하여 생성 주체와 생성 시각을 식별 가능하게 해야 한다.
5. WHEN analytics JSON이 저장될 때, THE analytics writer SHALL `_backfill: true`를 반드시 포함한다.
6. IF analytics JSON에 전시용 대용량 텍스트 필드 또는 AI 판단문 필드가 포함되면, THEN THE writer SHALL 이를 계약 위반으로 간주한다.
7. WHEN 동일 날짜의 curated JSON과 analytics JSON이 함께 존재하면, THE analytics JSON SHALL curated JSON 없이도 분석 입력으로 단독 사용 가능해야 한다.

### Requirement 4: 저장 원자성 및 멱등성

**카테고리:** 오류 처리/복원

**User Story:**
As a 운영 담당자,
I want 동일 날짜 재실행이 안전하고 partial write가 남지 않길 원한다,
so that 일일 배치 재실행이 데이터 손상 없이 반복 가능해진다.

#### Acceptance Criteria

1. WHEN 동일한 `symbol`과 `date`에 대해 파이프라인이 재실행되면, THE curated and analytics layers SHALL 같은 날짜 경로의 객체를 overwrite 방식으로 멱등적으로 재생성할 수 있어야 한다.
2. WHEN curated 또는 analytics 객체 저장 중 오류가 발생하면, THE storage layer SHALL 부분적으로 깨진 JSON을 최종 경로에 노출하지 않는다.
3. WHEN analytics 객체 저장이 성공하면, THE reader SHALL 해당 날짜를 읽었을 때 완전한 단일 JSON 문서를 받아야 한다.
4. WHEN 동일 날짜를 재생성하면, THE curated and analytics layers SHALL 중복 객체를 추가 생성하지 않고 목표 경로의 최신 유효 버전만 유지한다.
5. WHEN raw payload가 저장되면, THE raw layer SHALL 실행 단위 경로를 사용하여 append-only 증적을 유지한다.
6. WHEN curated 저장은 성공했으나 analytics 저장이 실패하면, THEN THE publish step SHALL 실행을 실패로 기록하고 부분 성공 상태를 정상 완료로 보고하지 않는다.

### Requirement 5: 분석 입력 계약 강화

**카테고리:** 데이터 수집/입력

**User Story:**
As a 분석 엔진 운영자,
I want `fetch_r2_sentiment`가 오직 검증된 analytics 데이터만 읽길 원한다,
so that 운영용 임시 데이터나 미검증 데이터가 통계 분석에 혼입되지 않도록 막을 수 있다.

#### Acceptance Criteria

1. WHEN `fetch_r2_sentiment`가 날짜별 감성 데이터를 조회할 때, THE analysis source reader SHALL `analytics/btc/{YYYY-MM-DD}.json` 경로만 읽는다.
2. WHEN 읽어온 analytics JSON에 `_backfill: true`가 존재하지 않으면, THE analysis source reader SHALL 해당 날짜를 즉시 제외한다.
3. WHEN 읽어온 analytics JSON의 `schemaVersion`이 지원 목록에 없으면, THE analysis source reader SHALL 해당 날짜를 제외하고 버전 불일치 사유를 기록한다.
4. WHEN 읽어온 analytics JSON의 `sentimentStatus` 또는 `newsSentiment` 구조가 계약과 다르면, THE analysis source reader SHALL 해당 날짜를 무효 입력으로 처리한다.
5. WHEN `_backfill: true`와 계약 필드 검증이 모두 통과하면, THE analysis source reader SHALL `news_sentiment_mean`, `news_sentiment_std`, `n_articles`, `sentiment_status`를 분석용 행으로 변환한다.
6. WHEN curated 레이어의 구조가 변경되더라도, THE analysis source reader SHALL CONTINUE TO analytics 계약만 기준으로 동작한다.
7. WHEN dual-write migration 기간이더라도 analysis cutover가 완료된 후에는, THE analysis source reader SHALL legacy `briefs/` 경로를 읽지 않는다.

### Requirement 6: 감성 품질 게이트

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 데이터 과학자,
I want 저품질 감성 관측치를 조인 전에 자동 제거하고 싶다,
so that 통계 검정이 희소 데이터와 불완전 관측치에 오염되지 않게 할 수 있다.

#### Acceptance Criteria

1. WHEN 분석 조인 단계가 시작되면, THE join layer SHALL `newsSentiment.count <= 1`인 날짜를 제거한다.
2. WHEN 분석 조인 단계가 시작되면, THE join layer SHALL `sentimentStatus == "skipped"`인 날짜를 제거한다.
3. WHEN `_backfill: true` 검증에 실패한 날짜가 존재하면, THE join layer SHALL 해당 날짜를 제거한다.
4. WHEN 감성 관측치가 제거되면, THE join layer SHALL 제외 사유를 `missing_backfill_marker`, `insufficient_article_count`, `skipped_sentiment`, `invalid_contract` 중 하나의 표준값으로 기록한다.
5. WHEN 감성 품질 게이트가 완료되면, THE pipeline SHALL 제거 전 행 수, 제거 후 행 수, 제외 사유별 건수를 관측 가능하게 남긴다.

### Requirement 7: 통계 유효성 게이트

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 분석 파이프라인 사용자,
I want 충분한 표본이 확보된 경우에만 Granger 검정을 수행하고 싶다,
so that 검정 결과를 통계적으로 해석 가능한 수준으로 제한할 수 있다.

#### Acceptance Criteria

1. WHEN 감성 품질 게이트와 inner join이 완료되면, THE pipeline SHALL 유효 행 수를 계산한다.
2. WHEN inner join 이후 유효 행 수가 180일 이상이면, THE statistical test runner SHALL Granger 인과성 검정을 수행한다.
3. IF inner join 이후 유효 행 수가 180일 미만이면, THEN THE statistical test runner SHALL Granger 인과성 검정을 건너뛰고 `insufficient_rows_for_granger` 사유를 기록한다.
4. WHEN Granger 검정이 수행되면, THE runner SHALL 검정 기준 행 수와 실제 사용 행 수를 함께 기록한다.
5. WHEN ADF 또는 기타 진단 검정이 수행되더라도, THE 180일 기준 SHALL 오직 Granger 실행 게이트에 적용된다.

### Requirement 8: 분석 변환 레이어 계약

**카테고리:** 비즈니스 로직/분류/판단

**User Story:**
As a 데이터 분석가,
I want 감성 점수와 실제 가격 반응이 직접 비교 가능한 형태로 정규화되길 원한다,
so that 후속 통계 분석과 리포트가 일관된 기준을 사용하게 할 수 있다.

#### Acceptance Criteria

1. WHEN 분석용 BTC 가격 시계열을 생성할 때, THE transform layer SHALL BTC 종가를 `btc_log_return`으로 변환한다.
2. WHEN `btc_log_return > 0`이면, THE transform layer SHALL 실제 등락 라벨을 `"up"`으로 설정한다.
3. WHEN `btc_log_return < 0`이면, THE transform layer SHALL 실제 등락 라벨을 `"down"`으로 설정한다.
4. WHEN `btc_log_return == 0`이면, THE transform layer SHALL 실제 등락 라벨을 `"flat"`으로 설정한다.
5. WHEN 선행 설명 변수 `funding_rate`, `open_interest_usd`, `btc_long_short_ratio`, `etf_net_inflow_usd`가 결합되면, THE join layer SHALL 모든 선행 지표를 Lag-1 기준으로 계산한다.
6. WHEN 최종 master dataset이 저장되면, THE output dataset SHALL `news_sentiment_mean`, `btc_log_return`, 실제 등락 라벨을 동일 행 기준으로 함께 기록해야 한다.

### Requirement 9: 성능 및 운영 독립성

**카테고리:** 성능/확장성

**User Story:**
As a 운영 담당자,
I want 분석 파이프라인이 curated full JSON 대신 analytics minimal JSON만 읽길 원한다,
so that 네트워크 비용과 파싱 비용을 줄이고 전시 로직 변경 영향을 최소화할 수 있다.

#### Acceptance Criteria

1. WHEN sentiment join 파이프라인이 R2 입력을 읽을 때, THE pipeline SHALL curated full JSON 대신 analytics minimal JSON만 조회한다.
2. WHEN 동일 날짜 기준으로 curated와 analytics 객체 크기를 비교하면, THE analytics 객체 SHALL curated 객체보다 유의하게 작아야 하며 대용량 텍스트 본문을 포함하지 않는다.
3. WHEN curated 레이어에 새로운 전시 필드가 추가되더라도, THE analysis pipeline SHALL CONTINUE TO analytics 계약만 읽고 동일한 수치 입력 구조를 유지한다.
4. WHEN analytics 입력 조회가 수행되면, THE pipeline SHALL 날짜당 1개 최소 JSON 객체만 읽도록 유지한다.
5. WHEN dual-write migration 기간이 시작되면, THE system SHALL legacy `briefs/` 경로와 `curated/` 경로를 병행 유지할 수 있으나 analytics reader 전환 이후의 분석 입력은 `analytics/`만 사용해야 한다.

### Requirement 10: 관측성 및 검증 출력

**카테고리:** 출력/리포트/UI

**User Story:**
As a 운영 담당자,
I want 데이터 제외, 계약 검증, 통계 게이트 결과가 관측 가능하게 남길 원한다,
so that 배치 품질 저하와 계약 위반을 빠르게 탐지할 수 있다.

#### Acceptance Criteria

1. WHEN analytics 계약 검증이 수행되면, THE pipeline SHALL 성공 건수와 실패 건수를 기록한다.
2. WHEN 감성 품질 게이트가 수행되면, THE pipeline SHALL 제외 사유별 건수를 구조화 로그 또는 동등한 메타데이터로 남긴다.
3. WHEN Granger 검정이 실행되거나 스킵되면, THE pipeline SHALL 실행 여부와 기준 충족 여부를 기록한다.
4. WHEN 최종 `master_sentiment_join.parquet`가 저장되면, THE output metadata SHALL 유효 행 수와 Granger 실행 여부를 포함해야 한다.
5. WHEN 계약 검증 실패가 발생하면, THE pipeline SHALL 실패 날짜 목록 또는 대표 샘플 사유를 운영자가 추적 가능한 형태로 남겨야 한다.

### Requirement 11: 테스트 및 회귀 방지

**카테고리:** 테스트/검증

**User Story:**
As a 개발팀,
I want 저장소 분리와 분석 계약 강화를 자동 테스트로 보호하고 싶다,
so that 운영 로직 변경이 분석 결과를 조용히 깨뜨리지 못하게 할 수 있다.

#### Acceptance Criteria

1. WHEN curated writer가 실행되면, THE test suite SHALL curated 경로 저장과 analytics 경로 저장이 동시에 일어나는지 검증해야 한다.
2. WHEN `fetch_r2_sentiment`가 실행되면, THE test suite SHALL `analytics/` 외 경로를 읽지 않는 것을 검증해야 한다.
3. WHEN `_backfill: true`가 없거나 `count <= 1`이거나 `sentimentStatus == "skipped"`인 입력이 주어지면, THE test suite SHALL 해당 날짜가 분석 대상에서 제외됨을 검증해야 한다.
4. WHEN inner join 이후 유효 행 수가 179행인 입력이 주어지면, THE test suite SHALL Granger 검정이 실행되지 않음을 검증해야 한다.
5. WHEN inner join 이후 유효 행 수가 180행인 입력이 주어지면, THE test suite SHALL Granger 검정이 실행됨을 검증해야 한다.
6. WHEN 최종 master dataset이 생성되면, THE test suite SHALL `news_sentiment_mean`, `btc_log_return`, 실제 등락 라벨, Lag-1 컬럼이 함께 존재함을 검증해야 한다.
