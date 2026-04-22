# Requirements Document

## Introduction

현재 BTC 현물 ETF 수집 구조(`src/morning_brief/data/sources/btc_etf_official.py`)는 IBIT·BITB 2종만 대상으로 하며, 공식 원천 데이터와 집계 사이트 데이터를 동일 레이어로 처리할 위험이 있다. 또한 수집 포맷 우선순위(JSON/CSV > HTML) 없이 HTML 텍스트 스크래핑에만 의존하고 있고, `BitcoinEtfIssuerSnapshot` 모델에 `as_of_date`/`collected_at` 분리·`source_type`·품질 상태가 없어 데이터 신뢰도 추적이 불가하다. 기존 `sentiment_join` 분석 파이프라인(`src/morning_brief/analysis/sentiment_join/`)은 FinBERT 뉴스 감성·FnG·BTC 수익률을 결합하지만, 선물 시장 지표(펀딩비·미결제약정)가 없고 정상성 검정(ADF)·인과성 검정(Granger)·다중공선성 진단(VIF/PCA)이 구현되어 있지 않아 예측력 검증이 불가하다. 이 요구사항은 PDF를 완전히 배제하고 JSON/CSV 우선 수집 정책을 확립하며, 수집 대상을 IBIT·BITB·GBTC·BTC 4종(1차), FBTC 후순위(2차)로 확장하고, Bronze/Silver/Gold 저장 계층·표준 컬럼 스키마 도입과 함께 분석 파이프라인에 선물 지표·통계 검정·하이브리드 지수를 추가하는 범위를 다룬다.

---

## Glossary

**source of truth (원천)**: 각 ETF 운용사가 공식으로 공개하는 페이지/파일. iShares, Bitwise, Grayscale, Franklin Templeton, Fidelity 공식 도메인에서 직접 수집한 데이터.

**집계 사이트**: Coinglass, Farside 등 여러 운용사 데이터를 취합해 제공하는 2차 사이트. 교차검증·모니터링 전용으로만 사용하며 원천값 컬럼에 혼입 금지.

**as_of_date**: 운용사가 공개한 데이터의 기준 날짜 (예: "as of 04/10/2025"). 실제 수집 시점과 다를 수 있다. Python `date` 타입으로 저장하며 JSON 직렬화 시 ISO 8601 문자열(`YYYY-MM-DD`)로 변환한다.

**collected_at**: 파이프라인이 실제로 원천 페이지를 fetch한 UTC 타임스탬프.

**source_type**: 수집 경로 유형. `"official_json"` / `"official_csv"` / `"official_html"` / `"aggregator"`. 집계 사이트(Coinglass, Farside 등) 데이터는 반드시 `"aggregator"`로 태깅한다.

**source_format**: 원문 포맷. `"json"` / `"csv"` / `"html"`.

**parse_method**: 파싱 방법. `"structured_json"` / `"csv_download"` / `"html_label"`.

**collection_status (= quality_status)**: 단일 수집 실행의 품질 상태. `"ok"` / `"degraded"` / `"critical"` 3단계.

**핵심 필드**: `total_btc`, `aum_usd`, `shares_outstanding` — 이 3개 중 2개 이상 미수집 시 `critical`.

**Bronze layer**: 공식 원문(raw HTML, raw CSV, raw JSON) 전체를 메타데이터와 함께 저장하는 계층. Supabase Storage 대상.

**Silver layer**: Bronze 원문을 표준 컬럼 스키마로 정규화한 계층. Supabase Postgres 대상.

**Gold layer**: Silver 데이터를 `as_of_date` 기준으로 집계한 분석/브리핑용 일별 테이블. Supabase Postgres 대상.

**Runtime Cache**: fetch 재사용·rate limit 완화를 위한 로컬 임시 저장. 기존 `.cache/btc_etf/` 유지. Bronze/Silver/Gold와 역할 분리. 이상치 검증(Req 9)에서 전일 값 비교 시 Runtime Cache를 단기 참조 소스로 사용할 수 있다.

**run_id**: 단일 수집/정규화/집계 실행을 식별하는 고유 ID. Bronze·Silver·Gold 전 계층과 구조화 로그에 동일하게 전파해 재처리와 장애 추적에 사용한다.

**schema_version**: 표준 컬럼 스키마 및 Gold 집계 규칙 버전. 재파싱·역마이그레이션·하위 호환 판단 기준으로 사용한다.

**펀딩비 (Funding Rate)**: 무기한 선물 계약에서 롱/숏 포지션 보유자 간 주기적으로 정산되는 비용. 레버리지 과열 상태를 나타내는 선행 지표. Binance는 8시간 주기로 3회 정산하므로 일별 `funding_rate`는 **8h 주기 값 3개의 합산**으로 산출한다.

**미결제약정 (Open Interest, OI)**: 만료되지 않은 선물 계약의 총 수량. 시장 참여자의 포지션 규모를 나타냄. 일별 값은 해당 일 종가 기준 `sumOpenInterestValue`(USD)를 사용한다.

**ADF Test (Augmented Dickey-Fuller)**: 시계열 데이터의 단위근(unit root) 존재 여부를 검정하는 정상성 검정. BTC 가격은 비정상 시계열이므로 로그 수익률 변환 후 검정을 통과한 데이터만 분석에 사용.

**로그 수익률 (Log Return)**: `ln(P_t / P_{t-1})`. 기존 `transform.py:compute_returns()`에서 `close_log_return` 컬럼으로 이미 계산됨.

**Granger Causality Test**: "변수 A의 과거 값이 변수 B의 미래 값을 예측하는 데 유의미한가"를 검정. p-value < 0.05 수준에서 뉴스 감성의 BTC 수익률 선행 여부를 검증.

**VIF (Variance Inflation Factor)**: 다중공선성 진단 지표. VIF ≥ 10이면 해당 변수를 PCA 입력에서 제거한다. 제거는 **VIF가 가장 높은 변수 1개씩 순차 제거 → 재계산** 반복 방식으로 수행한다.

**PCA (Principal Component Analysis)**: 상관관계가 높은 변수들(뉴스 감성·FnG 등)을 직교하는 주성분으로 변환해 다중공선성을 해소하고 가중치를 자동 산출하는 차원 축소 기법.

**하이브리드 지수**: 뉴스 감성(비정형)·ETF 유입량(자금)·FnG(심리)·선물 펀딩비(레버리지)를 PCA로 통합한 복합 신호 지수. PCA 첫 번째 주성분(`hybrid_index`)으로 표현한다.

**etf_net_inflow_usd**: ETF 일별 순유입 금액(USD). 현재 sentiment_join 파이프라인에는 미구현 상태이며, 향후 ETF 공식 수집 데이터와 연계 시 PCA 후보 변수로 편입 예정이다. 해당 컬럼이 DataFrame에 없는 경우 PCA 입력 후보에서 자동으로 제외한다.

**funding_rate_lag1**: 전일 일별 펀딩비 합산값. 당일 수익률과의 미래 오염을 방지하기 위해 Lag-1 처리(`shift(1)`)를 적용한 파생 컬럼.

**oi_change_pct_lag1**: 전일 미결제약정 변화율(%). `open_interest_usd.pct_change().shift(1)`로 산출한 파생 컬럼.

---

## Requirements

### Requirement 1: 수집 포맷 우선순위 정책 — PDF 배제, JSON/CSV 우선

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 파이프라인 개발자,
I want 수집 포맷 우선순위가 공식 구조화 데이터(JSON/CSV) → 공식 HTML 순서로 명확히 고정되길,
so that HTML 구조 변경에 취약한 스크래핑 의존을 줄이고 포맷별 신뢰도를 일관되게 관리할 수 있다.

#### Acceptance Criteria

1. WHEN ETF 수집이 실행될 때, THE 수집기 SHALL 아래 우선순위 원칙을 따른다:
   - 1순위: 공식 구조화 데이터 (`source_type="official_json"` 또는 `"official_csv"`)
   - 2순위: 공식 HTML 라벨 기반 파싱 (`source_type="official_html"`)
   - JSON과 CSV 사이의 세부 우선순위는 issuer별 포맷 우선순위 매트릭스(Req 4~7)를 따른다.
2. WHEN PDF 파싱이 시도될 때, THE 시스템 SHALL 해당 시도를 거부하고 다음 우선순위 소스로 넘어간다.
3. WHEN 비공식 내부 API endpoint나 서드파티 커뮤니티 데이터가 사용될 때, THE 시스템 SHALL 해당 데이터를 원천값 컬럼에 저장하지 않는다.
4. WHEN 공식 issuer 도메인 외부의 URL에서 데이터가 수집될 때, THE 시스템 SHALL `ValueError`를 발생시키고 수집을 중단한다.

---

### Requirement 2: 데이터 모델 — 표준 컬럼 스키마 도입

**카테고리:** 데이터 모델/구조

**User Story:**
As a 데이터 파이프라인 개발자,
I want 모든 ETF 종목에 공통으로 적용되는 표준 컬럼 스키마를 사용하길,
so that 종목이 추가될 때마다 새 모델 클래스 없이 동일 스키마로 적재할 수 있다.

#### Acceptance Criteria

1. WHEN ETF 수집 레코드가 생성될 때, THE Silver/Gold 계층 SHALL 아래 표준 컬럼을 포함한다:
   - Silver 계층 식별: `ticker`, `issuer`, `run_id`
   - Silver 계층 필드 값: `field_name`, `field_value`, `value_type`, `unit`
   - Silver 계층 시점: `as_of_date`, `collected_at`
   - Silver 계층 소스: `source_url`, `source_type`, `source_format`, `parse_method`
   - Silver 계층 품질: `quality_status`, `raw_label`, `raw_text`
2. WHEN 분석/브리핑용 정규화 컬럼이 필요할 때, THE Gold 계층 SHALL 아래 컬럼을 제공한다:
   - `aum_usd`, `shares_outstanding`, `total_btc`, `bitcoin_per_share`, `nav_per_share`, `market_price`, `premium_discount_pct`, `daily_volume`, `sponsor_fee`
3. WHEN 데이터 모델이 구현될 때, THE 시스템 SHALL Silver 정규화 레코드 모델과 Gold 일별 스냅샷 모델을 분리한다:
   - Silver 계층 SHALL `SilverNormalizedFieldRecord`와 같은 field-level 모델을 사용한다.
   - 기존 `BitcoinEtfIssuerSnapshot`은 Gold 일별 집계 DTO로 유지하거나 동등한 `GoldDailySnapshot`으로 대체하되, Silver 표준 레코드 역할을 겸하지 않는다.
   - Gold 모델은 `as_of: str` 대신 `as_of_date: date`를 사용하고 `source_type`, `quality_status`, `collected_at` 필드를 포함한다.
4. WHEN Silver 레코드의 `source_type`이 `"official_json"` 또는 `"official_csv"`일 때, THE 레코드 SHALL `source_file_url: str`을 함께 포함한다.
5. WHEN `as_of_date`를 JSON으로 직렬화할 때, THE 시스템 SHALL ISO 8601 문자열(`YYYY-MM-DD`)로 변환하고, 역직렬화 시 `date.fromisoformat()`으로 복원한다. 구버전 캐시에 `as_of: str`이 남아 있는 경우 자동 마이그레이션을 수행한다.

---

### Requirement 3: Bronze/Silver/Gold 저장 계층 분리

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 파이프라인 개발자,
I want 원문 저장(Bronze) → 정규화(Silver) → 분석용 집계(Gold)를 명확히 분리하길,
so that 파싱 로직 변경 시 원문을 재파싱할 수 있고 Runtime Cache와 영구 저장소를 혼용하지 않는다.

#### Acceptance Criteria

1. WHEN Bronze 수집이 실행될 때, THE Bronze 계층 SHALL raw HTML/CSV/JSON 원문 전체, `source_url`, `fetch_timestamp_utc`, `http_status`, `ticker`를 Supabase Storage에 저장한다.
2. WHEN Silver 정규화가 실행될 때, THE Silver 계층 SHALL Bronze 원문을 입력으로 받아 표준 컬럼 스키마로 변환하고 `raw_label`, `raw_text`, `parse_method`를 함께 Supabase Postgres에 저장한다.
3. WHEN Gold 집계가 실행될 때, THE Gold 계층 SHALL Silver 레코드를 `as_of_date` + `ticker` 기준으로 집계하고, 동일 날짜 복수 공식 소스가 있을 때 issuer별 포맷 우선순위 매트릭스(Req 4~7)를 적용해 단일 primary 레코드를 선택하여 Supabase Postgres에 저장한다.
4. WHEN Runtime Cache(`.cache/btc_etf/`)가 사용될 때, THE 시스템 SHALL 해당 캐시를 fetch 재사용·rate limit 완화 목적으로만 사용하고 Bronze/Silver/Gold 계층의 영구 저장소로 사용하지 않는다.
5. WHEN Bronze 계층에 원문이 존재하지 않을 때, THE Silver/Gold 계층 SHALL 해당 종목 날짜에 대해 실행되지 않는다.

---

### Requirement 4: 수집 대상 1단계 — IBIT (BlackRock / iShares)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 파이프라인 개발자,
I want IBIT 수집 소스를 공식 CSV/JSON 우선으로 재정렬하길,
so that HTML 구조 변경에 의한 파싱 실패 빈도를 줄이고 수집 안정성을 높일 수 있다.

#### Acceptance Criteria

1. WHEN IBIT 수집이 실행될 때, THE 수집기 SHALL 아래 우선순위로 소스를 시도한다:
   - 1순위: 공식 CSV 다운로드 (`ishares.com` 도메인, `source_type="official_csv"`)
   - 2순위: 공식 페이지 내 구조화 JSON (`source_type="official_json"`)
   - 3순위: 공식 HTML 라벨 기반 파싱 (`source_type="official_html"`)
2. WHEN IBIT 수집이 성공할 때, THE 수집기 SHALL 아래 필드를 시도한다:
   `net_assets`, `shares_outstanding`, `basket_bitcoin_amount`, `indicative_basket_bitcoin_amount`, `daily_volume`, `closing_price`, `premium_discount`, `total_btc`, `nav`, `sponsor_fee`
3. WHEN `basket_bitcoin_amount`가 수집됐을 때, THE 시스템 SHALL `bitcoin_per_share = basket_bitcoin_amount / 40_000`, `total_btc = bitcoin_per_share × shares_outstanding` 공식을 유지한다.

---

### Requirement 5: 수집 대상 1단계 — BITB (Bitwise)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 파이프라인 개발자,
I want BITB 수집 시 `__NEXT_DATA__` JSON을 우선 활용하고 HTML 파싱을 최후 fallback으로 두길,
so that 페이지 리디자인에도 구조화 데이터 경로가 살아있으면 안정적으로 수집된다.

#### Acceptance Criteria

1. WHEN BITB 수집이 실행될 때, THE 수집기 SHALL 아래 우선순위로 소스를 시도한다:
   - 1순위: 공식 JSON/CSV 다운로드 (`bitbetf.com` 도메인, `source_type="official_json"` 또는 `"official_csv"`)
   - 2순위: 공식 페이지 내 `__NEXT_DATA__` 구조화 JSON (`source_type="official_json"`)
   - 3순위: 공식 HTML 라벨 기반 파싱 (`source_type="official_html"`)
2. WHEN `__NEXT_DATA__` JSON에서 `totalReserve`, `netAssets`, `sharesOutstanding`, `volume`이 모두 추출될 때, THE 스냅샷 SHALL `source_type="official_json"`, `quality_status="ok"`로 기록한다.
3. WHEN BITB 수집이 성공할 때, THE 수집기 SHALL 아래 필드를 시도한다:
   `net_assets_aum`, `shares_outstanding`, `daily_volume`, `bitcoin_in_trust`, `bitcoin_per_share`, `trust_net_assets_btc`, `bitcoin_reserve_btc`, `nav`, `market_price`, `premium_discount`, `sponsor_fee`

---

### Requirement 6: 수집 대상 2단계 — GBTC / BTC (Grayscale)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 브리핑 독자,
I want GBTC(legacy 대형 ETF)와 BTC(Grayscale Bitcoin Mini Trust) 데이터가 포함되길,
so that legacy 유출 흐름과 동일 운용사 내 자금 재배치 흐름을 브리핑에서 볼 수 있다.

#### Acceptance Criteria

1. WHEN GBTC/BTC 수집이 실행될 때, THE 수집기 SHALL 아래 우선순위로 소스를 시도한다:
   - 1순위: 공식 JSON/CSV (`etfs.grayscale.com` 도메인, `source_type="official_json"` 또는 `"official_csv"`)
   - 2순위: 공식 HTML 라벨 기반 파싱 (`source_type="official_html"`)
2. WHEN GBTC 수집이 성공할 때, THE 수집기 SHALL 아래 필드를 시도한다:
   `aum_non_gaap`, `gaap_aum`, `shares_outstanding`, `total_bitcoin_in_trust`, `bitcoin_per_share`, `nav_per_share`, `gaap_nav_per_share`, `market_price`, `premium_discount`, `daily_volume`, `bid_ask_spread_30d`
3. WHEN BTC(Grayscale Bitcoin Mini Trust) 수집이 성공할 때, THE 수집기 SHALL 아래 필드를 시도한다:
   `aum_non_gaap`, `gaap_aum`, `shares_outstanding`, `total_bitcoin_in_trust`, `bitcoin_per_share`, `nav_per_share`, `market_price`, `premium_discount`, `daily_volume`, `bid_ask_spread_30d`, `sponsor_fee`
4. WHEN GBTC와 BTC 수집기가 구현될 때, THE 시스템 SHALL Grayscale 공식 페이지 구조가 동일하므로 공용 파서(`_parse_grayscale_snapshot(ticker, issuer, url, text)`)를 재사용한다.
5. WHEN Grayscale 페이지가 HTTP 429로 차단될 때, THE 시스템 SHALL `quality_status="critical"`로 기록하고 파이프라인을 중단하지 않는다.

---

### Requirement 7: 수집 대상 3단계 — FBTC (Fidelity, 후순위)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 브리핑 독자,
I want FBTC 데이터가 포함되길,
so that 미국 현물 BTC ETF 시장에서 대형 유입 축인 Fidelity의 흐름을 브리핑에서 볼 수 있다.

#### Acceptance Criteria

1. WHEN FBTC 수집이 실행될 때, THE 수집기 SHALL Fidelity 공식 도메인에서 JSON/CSV 우선, 없으면 공식 HTML 순서로 시도한다.
2. WHEN FBTC 수집이 성공할 때, THE 수집기 SHALL 아래 필드를 시도한다:
   `market_price`, `nav`, `shares_outstanding`, `primary_exchange`
3. WHEN PDF 배제 정책으로 인해 FBTC의 `total_btc` 수집이 불가능할 때, THE 시스템 SHALL `total_btc` 필드를 `None`으로 저장하고 `quality_status="degraded"`로 기록한다.
4. IF FBTC에서 `total_btc` 추정치 사용이 검토될 때, THEN THE 시스템 SHALL 해당 값을 `estimated_total_btc` 별도 컬럼에만 저장하고 공식 원천값 컬럼(`total_btc`)에는 저장하지 않는다.
5. WHEN FBTC 수집이 구현될 때, THE 시스템 SHALL Fidelity 공식 도메인(`digital.fidelity.com`)을 공식 issuer domain whitelist에 등록한다.
5. WHEN FBTC 수집이 구현될 때, THE 시스템 SHALL Fidelity 공식 도메인(`digital.fidelity.com`)을 공식 issuer domain whitelist에 등록한다.

---

### Requirement 8: 품질 상태 분류 체계

**카테고리:** 비즈니스 로직/분류

**User Story:**
As a 파이프라인 운영자,
I want 수집 결과를 `ok` / `degraded` / `critical` 3단계로 자동 분류하길,
so that downstream 소비 로직이 상태별로 다르게 대응하고 이상 상황을 빠르게 감지할 수 있다.

#### Acceptance Criteria

1. WHEN 핵심 필드(`total_btc`, `aum_usd`, `shares_outstanding`) 3개가 모두 수집되고 `as_of_date`가 정상 파싱됐을 때, THE 시스템 SHALL `quality_status="ok"`로 분류한다.
2. WHEN 핵심 필드 중 1개가 누락되거나 `source_type="official_html"`으로만 수집이 성공했을 때, THE 시스템 SHALL `quality_status="degraded"`로 분류한다.
3. WHEN 핵심 필드 중 2개 이상 미수집, `as_of_date` 파싱 실패, 또는 원천 페이지 접근 자체 실패일 때, THE 시스템 SHALL `quality_status="critical"`로 분류한다.
4. WHEN `quality_status="critical"`인 종목이 있을 때, THE 파이프라인 SHALL 전체 중단 없이 해당 종목을 건너뛰고 나머지 종목 수집을 계속 진행한다.
5. WHEN `quality_status`가 `ok`가 아닌 종목이 있을 때, THE 시스템 SHALL 구조화 로그(`event="etf.collection_quality"`, `level=WARNING`)로 상태와 누락 필드 목록을 기록한다.

---

### Requirement 9: 이상치 검증 규칙

**카테고리:** 비즈니스 로직/분류

**User Story:**
As a 파이프라인 운영자,
I want 수집된 값에 대한 기본 이상치 검증이 자동 실행되길,
so that 스크래핑 오류나 페이지 변경으로 인한 이상값이 downstream에 그대로 흘러가지 않는다.

#### Acceptance Criteria

1. WHEN `shares_outstanding <= 0`일 때, THE 시스템 SHALL 해당 필드를 `None`으로 처리하고 `quality_status`를 `critical`로 격상하며 경고 로그(`event="etf.anomaly_invalid_field"`, `level=WARNING`)를 남긴다.
2. WHEN `total_btc < 0`일 때, THE 시스템 SHALL 해당 필드를 `None`으로 처리하고 `quality_status`를 `critical`로 격상하며 경고 로그(`event="etf.anomaly_invalid_field"`, `level=WARNING`)를 남긴다.
3. WHEN `abs(premium_discount_pct) > 5.0`일 때, THE 시스템 SHALL 경고 로그(`event="etf.anomaly_premium_discount"`, `level=WARNING`)를 남기되 수집을 중단하지 않는다.
4. WHEN 전일 대비 `total_btc` 또는 `aum_usd` 변화율이 20% 초과일 때, THE 시스템 SHALL 경고 로그(`event="etf.anomaly_rapid_change"`, `level=WARNING`)를 남긴다. 전일 값은 Runtime Cache(`.cache/btc_etf/`)에서 읽으며, 캐시가 없는 경우 해당 검증을 건너뛴다.
5. WHEN 동일 `as_of_date`·동일 종목에 대해 원천 소스와 집계 사이트 값이 불일치할 때, THE 시스템 SHALL 원천 값을 primary 컬럼에 사용하고 집계 사이트 값은 별도 `reference_*` 컬럼에만 보관한다.

---

### Requirement 10: Coinglass / Farside 집계 소스 분리

**카테고리:** 데이터 수집/입력

**User Story:**
As a 데이터 파이프라인 개발자,
I want Coinglass·Farside 데이터가 원천 데이터와 동일 컬럼에 절대 혼입되지 않길,
so that 분석 리포트에서 원천값과 집계값이 같은 컬럼에 섞이는 사고를 방지한다.

#### Acceptance Criteria

1. WHEN 집계 사이트(Coinglass, Farside) 데이터가 사용될 때, THE 시스템 SHALL `source_type="aggregator"`로 태깅하고 Silver/Gold 계층의 primary 컬럼에는 저장하지 않는다.
2. WHEN 브리핑 생성 프롬프트에 ETF 데이터가 전달될 때, THE 시스템 SHALL `source_type`이 `"official_json"`, `"official_csv"`, `"official_html"` 중 하나인 데이터만 primary 값으로 포함한다.
3. WHEN 집계 사이트 값이 교차검증 목적으로 저장될 때, THE 시스템 SHALL 해당 값을 `reference_*` prefix 컬럼에만 저장한다.
4. WHEN 공식 원천 수집이 실패하고 집계 사이트 값만 존재할 때, THE 시스템 SHALL Gold primary 레코드를 생성하지 않고 `reference_*` 컬럼 또는 별도 reference 레코드로만 보관하며 경고 로그(`event="etf.reference_only_snapshot"`, `level=WARNING`)를 남긴다.

---

### Requirement 11: 선물 시장 지표 수집 — 펀딩비·미결제약정

**카테고리:** 데이터 수집/입력

**User Story:**
As a 분석 파이프라인 개발자,
I want 비트코인 무기한 선물의 펀딩비와 미결제약정(OI) Lag-1 데이터를 `sentiment_join` 마스터 데이터셋에 포함하길,
so that 레버리지 과열 신호가 뉴스 감성·ETF 유입량과 함께 수익률 예측력을 높이는지 검증할 수 있다.

#### Acceptance Criteria

1. WHEN 선물 지표 수집이 실행될 때, THE 수집기 SHALL 아래 우선순위로 소스를 시도한다:
   - 1순위: Binance 공식 REST API (`https://fapi.binance.com`) — 인증 불필요, 공개 엔드포인트
     - 펀딩비 이력: `GET /fapi/v1/fundingRate?symbol=BTCUSDT&startTime={ms}&limit=1000`
     - OI 이력: `GET /futures/data/openInterestHist?symbol=BTCUSDT&period=1d&startTime={ms}&limit=1000`
   - 2순위: Coinglass API — Binance 수집 실패 시에만 fallback으로 사용하며 `source_type="aggregator"`로 태깅
2. WHEN Binance API에서 수집이 성공할 때, THE 시스템 SHALL 아래 방식으로 일별 값을 산출한다:
   - `funding_rate`: 해당 일 8시간 주기 3회 값의 **합산** (평균 아님)
   - `open_interest_usd`: 해당 일 종가 기준 `sumOpenInterestValue` 필드 값
3. WHEN 마스터 데이터셋에 선물 지표가 조인될 때, THE 시스템 SHALL Lag-1 처리(`funding_rate_lag1`, `oi_change_pct_lag1`)를 적용하여 당일 수익률과의 미래 오염을 방지한다.
4. WHEN 선물 지표 수집이 실패할 때(Binance·Coinglass 모두), THE 시스템 SHALL 해당 컬럼(`funding_rate`, `open_interest_usd`, `funding_rate_lag1`, `oi_change_pct_lag1`)을 `NaN`으로 채우고 파이프라인을 중단하지 않는다.
5. WHEN 선물 지표 소스가 구현될 때, THE 시스템 SHALL `src/morning_brief/analysis/sentiment_join/sources/futures.py`에 독립 모듈로 추가한다.

---

### Requirement 12: 통계 검정 파이프라인 — ADF·Granger

**카테고리:** 비즈니스 로직/분류

**User Story:**
As a 분석 파이프라인 개발자,
I want ADF 정상성 검정과 Granger 인과성 검정이 파이프라인 실행 시 자동으로 수행되길,
so that 뉴스 감성·선물 펀딩비가 BTC 수익률을 얼마나 선행하는지 통계적으로 입증할 수 있다.

#### Acceptance Criteria

1. WHEN 통계 검정이 실행될 때, THE 시스템 SHALL `btc_log_return` 컬럼에 대해 ADF Test를 수행하고, p-value ≥ 0.05이면 경고 로그(`event="stats.adf_non_stationary"`, `level=WARNING`)를 남긴다.
2. WHEN ADF Test가 통과(p-value < 0.05)됐을 때, THE 시스템 SHALL `btc_log_return`을 분석 대상 컬럼으로 확정하고 원시 가격(`btc_close`)은 회귀 분석에 사용하지 않는다.
3. WHEN Granger 인과성 검정이 실행될 때, THE 시스템 SHALL 아래 조합을 `lag=1`, `lag=2`, `lag=3` 각각에 대해 검정한다:
   - `news_sentiment_mean` → `btc_log_return`
   - `funding_rate_lag1` → `btc_log_return`
   - `fng_value` → `btc_log_return`
4. WHEN Granger 검정 결과 p-value < 0.05인 조합이 있을 때, THE 시스템 SHALL 해당 결과를 구조화 로그(`event="stats.granger_significant"`)로 기록하고, Parquet schema metadata의 `sentiment_join_stats` 키에 저장되는 JSON 요약에 포함한다.
5. WHEN 통계 검정 모듈이 구현될 때, THE 시스템 SHALL `src/morning_brief/analysis/sentiment_join/statistical_tests.py`에 독립 모듈로 추가한다.
6. IF 데이터 행 수가 30 미만일 때, THEN THE 시스템 SHALL 통계 검정을 건너뛰고 경고 로그(`event="stats.insufficient_rows"`)를 남긴다.
7. WHEN 통계 검정 실행 중 예외가 발생할 때, THE 시스템 SHALL 해당 검정만 건너뛰고 경고 로그를 남기며 파이프라인을 중단하지 않는다.

---

### Requirement 13: 하이브리드 지수 설계 — PCA·VIF

**카테고리:** 비즈니스 로직/분류

**User Story:**
As a 분석 파이프라인 개발자,
I want 뉴스 감성·FnG·ETF 유입량·선물 펀딩비를 PCA로 통합한 하이브리드 지수를 생성하길,
so that 변수 간 다중공선성을 해소하고 단일 복합 신호로 BTC 수익률과의 상관관계를 분석할 수 있다.

#### Acceptance Criteria

1. WHEN 하이브리드 지수 생성 전, THE 시스템 SHALL DataFrame에 존재하는 후보 변수(`news_sentiment_mean`, `fng_value`, `funding_rate_lag1`, `etf_net_inflow_usd` 중 실제로 컬럼이 있는 것만)의 VIF를 계산하고 결과를 구조화 로그(`event="stats.vif_diagnostics"`)로 기록한다. `etf_net_inflow_usd`는 미구현 상태이므로 컬럼이 없으면 조용히 제외한다.
2. WHEN VIF ≥ 10인 변수가 있을 때, THE 시스템 SHALL **VIF가 가장 높은 변수 1개를 제거 → VIF 재계산** 방식을 반복하여 모든 변수의 VIF가 10 미만이 될 때까지 순차 제거한다. 각 제거 시 `event="stats.vif_feature_removed"` 로그에 해당 변수명과 VIF 값을 기록한다.
3. WHEN PCA가 실행될 때, THE 시스템 SHALL VIF 통과 변수들을 표준화(StandardScaler)한 뒤 PCA를 적용하여 누적 설명 분산 ≥ 80%를 달성하는 최소 주성분 수를 자동 선택한다.
4. WHEN PCA 결과가 생성될 때, THE 시스템 SHALL 첫 번째 주성분을 `hybrid_index` 컬럼으로 마스터 데이터셋에 추가하고 각 변수의 기여 가중치(PC1 loadings)를 구조화 로그(`event="stats.pca_complete"`)에 기록한다.
5. WHEN 하이브리드 지수 모듈이 구현될 때, THE 시스템 SHALL `src/morning_brief/analysis/sentiment_join/hybrid_index.py`에 독립 모듈로 추가하며 기존 `pipeline.py` (브리핑 파이프라인)와 완전히 분리를 유지한다.
6. IF PCA 입력 변수가 2개 미만으로 줄어들 때, THEN THE 시스템 SHALL PCA를 건너뛰고 `hybrid_index` 컬럼을 `NaN`으로 채우며 경고 로그(`event="stats.pca_insufficient_features"`)를 남긴다.
7. IF PCA 실행 가능한 행 수가 10 미만일 때, THEN THE 시스템 SHALL PCA를 건너뛰고 `hybrid_index` 컬럼을 `NaN`으로 채우며 경고 로그(`event="stats.pca_insufficient_features"`)를 남긴다.

---

### Requirement 14: 실행 추적성·재처리·멱등성

**카테고리:** 데이터 운영/관측성

**User Story:**
As a 데이터 엔지니어,
I want ETF 수집과 정규화 실행이 run 단위로 추적 가능하고 동일 입력 재처리에 멱등적으로 동작하길,
so that 장애 복구·백필·스키마 변경 시 중복 적재 없이 특정 실행을 정확히 재현할 수 있다.

#### Acceptance Criteria

1. WHEN Bronze/Silver/Gold 레코드가 생성될 때, THE 시스템 SHALL 모든 레코드와 구조화 로그에 동일한 `run_id`를 기록한다.
2. WHEN Bronze 원문이 저장될 때, THE 시스템 SHALL `schema_version`, `source_checksum`, `fetch_timestamp_utc`, `http_status`를 함께 저장해 재파싱 입력을 고정한다.
3. WHEN 동일 `ticker`·`as_of_date`·`field_name`·`source_type`·`source_checksum` 조합이 재처리될 때, THE Silver 계층 SHALL 중복 insert 대신 upsert 또는 no-op로 멱등 처리한다.
4. WHEN 동일 `ticker`·`as_of_date` Gold 집계가 재실행될 때, THE 시스템 SHALL 최신 `run_id` 기준으로 단일 primary 레코드만 유지하고 중복 일별 스냅샷을 남기지 않는다.
5. WHEN Silver/Gold 변환 규칙이 변경될 때, THE 시스템 SHALL `schema_version` 차이를 기준으로 Bronze 원문 재처리 가능 여부를 판단할 수 있어야 한다.
6. WHEN 실행이 부분 실패할 때, THE 시스템 SHALL 종목별 성공/실패/skip 건수를 구조화 로그(`event="etf.run_summary"`)와 실행 메타데이터에 기록한다.

---

## 구현 의존성

Req 11~13을 구현하려면 `requirements-analysis.txt`에 아래 패키지를 추가해야 한다.

| 패키지 | 버전 | 사용 목적 |
|--------|------|-----------|
| `statsmodels` | ≥ 0.14 | ADF Test (`adfuller`), Granger 검정 (`grangercausalitytests`), VIF (`variance_inflation_factor`) |
| `scikit-learn` | ≥ 1.4 | StandardScaler, PCA |

해당 패키지들은 분석 배치 전용(`make sentiment-join`) 의존성이며 브리핑 파이프라인(`python main.py`) 실행 시에는 불필요하다.
