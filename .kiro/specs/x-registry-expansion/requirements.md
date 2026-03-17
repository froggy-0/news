# 요구사항 문서

## 소개

X 시그널 레지스트리(`official_signal_registry.json`)에 9개의 신규 엔티티를 추가하여 모니터링 커버리지를 확장한다. 현재 빅테크 10종 중 X 검색 대상이 5개에 불과하고, BTC ETF 주요 운용사 3곳이 누락되어 있으며, 백악관/대통령 공식 계정이 없어 관세·무역 정책 시그널을 놓치고 있다. 신규 엔티티 추가 시 `macro_and_equity` 그룹이 기존 `MAX_X_HANDLES_PER_GROUP=10` 한도를 초과(11건)하므로 이에 대한 대응도 포함한다.

## 용어집

- **Registry**: `official_signal_registry.json` 파일. 공식 시그널 엔티티 목록을 JSON 형식으로 관리하는 단일 데이터 소스
- **Entity**: Registry 내 하나의 항목. `entity_id`, `x_handle`, `x_search_group`, `x_search_priority` 등의 필드를 포함
- **Registry_Loader**: `official_signal_registry.py` 모듈. Registry를 로드하고 그룹별 핸들 목록을 제공하는 Python 코드
- **X_Search_Group**: Entity가 속하는 검색 그룹 (`ai_bigtech_primary`, `crypto_and_etf`, `macro_and_equity`, `btc_etf_primary`)
- **X_Search_Priority**: 그룹 내 Entity의 우선순위 (숫자가 낮을수록 높은 우선순위). 그룹 한도 초과 시 우선순위가 낮은 Entity가 탈락
- **MAX_X_HANDLES_PER_GROUP**: 하나의 X_Search_Group에 포함될 수 있는 최대 핸들 수를 정의하는 상수
- **Validation_Function**: `registry_validation_errors()` 함수. Registry의 무결성을 검증하고 오류 목록을 반환

## 요구사항

### 요구사항 1: ai_bigtech_primary 그룹 엔티티 추가

**사용자 스토리:** 투자자로서, Google·Amazon·Tesla·Broadcom의 공식 X 계정을 모니터링하고 싶다. 이를 통해 AI/반도체 빅테크 커버리지 공백을 해소할 수 있다.

#### 인수 조건

1. WHEN Registry가 로드될 때, THE Registry SHALL Google 엔티티를 포함한다 (entity_id: `google`, x_handle: `Google`, ticker: `GOOGL`, x_search_group: `ai_bigtech_primary`, x_search_priority: 2, x_verified: true)
2. WHEN Registry가 로드될 때, THE Registry SHALL Amazon 엔티티를 포함한다 (entity_id: `amazon`, x_handle: `AmazonNews`, ticker: `AMZN`, x_search_group: `ai_bigtech_primary`, x_search_priority: 2, x_verified: true)
3. WHEN Registry가 로드될 때, THE Registry SHALL Tesla 엔티티를 포함한다 (entity_id: `tesla`, x_handle: `Tesla`, ticker: `TSLA`, x_search_group: `ai_bigtech_primary`, x_search_priority: 2, x_verified: true)
4. WHEN Registry가 로드될 때, THE Registry SHALL Broadcom 엔티티를 포함한다 (entity_id: `broadcom`, x_handle: `Broadcom`, ticker: `AVGO`, x_search_group: `ai_bigtech_primary`, x_search_priority: 2, x_verified: true)
5. WHEN 4개의 신규 엔티티가 추가된 후, THE ai_bigtech_primary 그룹 SHALL 총 9개의 활성 엔티티를 포함한다


### 요구사항 2: crypto_and_etf 그룹 엔티티 추가

**사용자 스토리:** 투자자로서, VanEck·Franklin Templeton·Invesco의 공식 X 계정을 모니터링하고 싶다. 이를 통해 BTC ETF 운용사 커버리지를 확대할 수 있다.

#### 인수 조건

1. WHEN Registry가 로드될 때, THE Registry SHALL VanEck 엔티티를 포함한다 (entity_id: `vaneck`, x_handle: `vaneck_us`, ticker: `HODL`, x_search_group: `crypto_and_etf`, x_search_priority: 2, x_verified: true)
2. WHEN Registry가 로드될 때, THE Registry SHALL Franklin Templeton 엔티티를 포함한다 (entity_id: `franklin_templeton`, x_handle: `FTI_US`, ticker: `EZBC`, x_search_group: `crypto_and_etf`, x_search_priority: 2, x_verified: true)
3. WHEN Registry가 로드될 때, THE Registry SHALL Invesco 엔티티를 포함한다 (entity_id: `invesco`, x_handle: `InvescoUS`, ticker: `BTCO`, x_search_group: `crypto_and_etf`, x_search_priority: 2, x_verified: true)
4. WHEN 3개의 신규 엔티티가 추가된 후, THE crypto_and_etf 그룹 SHALL 총 9개의 활성 엔티티를 포함한다

### 요구사항 3: macro_and_equity 그룹 엔티티 추가

**사용자 스토리:** 투자자로서, 백악관과 대통령 공식 계정을 모니터링하고 싶다. 이를 통해 관세·무역 정책 등 시장 영향력이 큰 정부 발표를 실시간으로 포착할 수 있다.

#### 인수 조건

1. WHEN Registry가 로드될 때, THE Registry SHALL White House 엔티티를 포함한다 (entity_id: `white_house`, x_handle: `WhiteHouse`, category: `macro_regulator`, x_search_group: `macro_and_equity`, x_search_priority: 1, x_verified: true)
2. WHEN Registry가 로드될 때, THE Registry SHALL POTUS 엔티티를 포함한다 (entity_id: `potus`, x_handle: `POTUS`, category: `macro_regulator`, x_search_group: `macro_and_equity`, x_search_priority: 1, x_verified: true)
3. WHEN 2개의 신규 엔티티가 추가된 후, THE macro_and_equity 그룹 SHALL 총 11개의 활성 엔티티를 포함한다

### 요구사항 4: 그룹 한도 초과 대응

**사용자 스토리:** 시스템 운영자로서, macro_and_equity 그룹이 MAX_X_HANDLES_PER_GROUP 한도를 초과하지 않도록 하고 싶다. 이를 통해 Validation_Function이 오류를 보고하지 않고 모든 신규 엔티티가 검색 대상에 포함될 수 있다.

#### 인수 조건

1. WHEN macro_and_equity 그룹에 11개의 활성 엔티티가 존재할 때, THE Registry_Loader SHALL MAX_X_HANDLES_PER_GROUP 값을 12 이상으로 설정하여 모든 엔티티를 수용한다
2. WHEN MAX_X_HANDLES_PER_GROUP 값이 변경된 후, THE Validation_Function SHALL macro_and_equity 그룹에 대해 한도 초과 오류를 반환하지 않는다
3. WHEN MAX_X_HANDLES_PER_GROUP 값이 변경된 후, THE Registry_Loader의 `grouped_verified_x_handles()` SHALL macro_and_equity 그룹의 모든 11개 핸들을 반환한다

### 요구사항 5: 엔티티 데이터 무결성

**사용자 스토리:** 시스템 운영자로서, 신규 추가된 모든 엔티티가 기존 스키마와 동일한 형식을 따르도록 하고 싶다. 이를 통해 Registry_Loader가 오류 없이 데이터를 처리할 수 있다.

#### 인수 조건

1. THE Registry SHALL 각 신규 엔티티에 대해 `entity_id`, `entity_name`, `ticker`, `category`, `primary_domain`, `newsroom_or_ir_url`, `x_handle`, `x_verified`, `verification_source_url`, `verification_method`, `verified_at`, `x_search_group`, `x_search_priority`, `enabled`, `notes` 필드를 모두 포함한다
2. THE Registry SHALL 모든 신규 엔티티의 `entity_id` 값이 기존 엔티티와 중복되지 않도록 한다
3. THE Registry SHALL 모든 신규 엔티티의 `x_verified` 값을 true로 설정한다 (검증 완료된 계정만 추가)
4. THE Registry SHALL 모든 신규 엔티티의 `enabled` 값을 true로 설정한다
5. WHEN 모든 신규 엔티티가 추가된 후, THE Validation_Function SHALL 빈 오류 목록을 반환한다 (검증 통과)

### 요구사항 6: 기존 기능 호환성 유지

**사용자 스토리:** 시스템 운영자로서, 신규 엔티티 추가가 기존 파이프라인에 영향을 주지 않도록 하고 싶다. 이를 통해 기존 모니터링 대상이 그대로 유지된다.

#### 인수 조건

1. WHEN 신규 엔티티가 추가된 후, THE Registry_Loader의 `grouped_verified_x_handles()` SHALL 기존에 반환하던 모든 핸들을 동일하게 포함한다
2. WHEN 신규 엔티티가 추가된 후, THE Registry SHALL 기존 25개 엔티티의 모든 필드 값을 변경하지 않는다
3. THE Registry SHALL JSON 파싱 후 재직렬화 시 동일한 구조를 유지한다 (라운드트립 속성)
