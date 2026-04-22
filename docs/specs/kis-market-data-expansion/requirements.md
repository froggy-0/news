# Requirements Document

## Introduction

현재 시장 데이터 경로는 KIS 정형 데이터보다 yfinance·FRED·LLM 보조 해석에 의존하는 구간이 많다. 이번 작업의 1차 목표는 한국투자증권 Open API로 안정적으로 검증 가능한 항목부터 확대해, 뉴스레터와 시장 패킷에서 정형 데이터 비중을 높이고 Grok 등 LLM 의존도를 줄이는 것이다.

이번 요구사항은 "많이 붙인다"보다 "검증된 항목만 붙인다"를 우선한다. 금융 데이터는 값 자체보다도 단위, 기준시점, 비교대상 전일값이 더 중요하므로, 검증되지 않은 코드나 잘못된 fallback으로 coverage를 늘리는 방식은 허용하지 않는다.

## Research-backed Constraints (2026-04-07)

- KIS 공식 공개 샘플 기준 해외 기간시세 API `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`, TR ID `FHKST03030100`는 `FID_COND_MRKT_DIV_CODE`로 해외지수(`N`), 환율(`X`), 국채(`I`), 금선물(`S`)를 구분한다.
- 같은 공식 샘플 기준 국내 지수 현재가 API `/uapi/domestic-stock/v1/quotations/inquire-index-price`, TR ID `FHPUP02100000`는 코스피 `0001`, 코스닥 `1001` 코드를 사용한다.
- 현재 코드베이스의 [`MarketPoint`](/Users/giwon/code/news/src/morning_brief/models.py#L8)는 `data_as_of` 필드를 갖고 있지 않다. 기준시점 표시는 별도 메타데이터나 렌더링 계층에서 처리해야 한다.
- 현재 [`build_market_packet()`](/Users/giwon/code/news/src/morning_brief/data/market.py#L1038) 는 `macro`, `us_indices`, `bitcoin`만 포함하고, [`fetch_newsletter_display_data()`](/Users/giwon/code/news/src/morning_brief/data/market.py#L527)는 `korea_watch`, `tech_stocks`, `btc_etf_points`를 렌더링 직전에 수집한다.
- 현재 [`pipeline.py`](/Users/giwon/code/news/src/morning_brief/pipeline.py#L297)는 display data에서 `korea_watch`, `tech_stocks`, `btc_etf_points`만 `render_packet`에 병합한다. 따라서 새 display field를 추가하면 같은 변경에서 pipeline merge 경로도 함께 갱신해야 한다.
- 현재 [`unified_output.py`](/Users/giwon/code/news/src/morning_brief/unified_output.py#L345), [`briefing.py`](/Users/giwon/code/news/src/morning_brief/briefing.py#L679), [`emailer.py`](/Users/giwon/code/news/src/morning_brief/emailer.py#L933)는 `macro`, `korea_watch`, `us_indices`, `bitcoin`의 고정 section/key를 읽는다. 새 packet field를 넣기만 하고 소비자를 갱신하지 않으면 dead field가 된다.
- 현재 [`QuantitativeLayer`](/Users/giwon/code/news/src/morning_brief/unified_output.py#L190)는 `us10y`, `dxy`, `vix`, `usdkrw`, `nq_futures`, `spy`, `qqq`, `soxx`, `btc_spot` 같은 고정 슬롯만 가진다. 따라서 새 시장 지표는 packet 데이터만 추가해서는 노출되지 않고, dataclass와 변환 함수까지 함께 확장해야 한다.
- 현재 [`ProviderPolicy`](/Users/giwon/code/news/src/morning_brief/data/sources/provider_runtime.py#L65) 의 `kis` 정책은 `min_interval_seconds=0.4`, `max_attempts=5`, `base_backoff_seconds=1.0`으로 이미 정의돼 있다.
- 2026-04-07 live probe 기준 `usdkrw/FX@KRW`, `dow30/.DJI`, `kospi/0001`, `kosdaq/1001`는 usable payload가 확인됐다.
- 같은 probe 기준 `.SPX`, `.INX`, `.NDX`, `.IXIC`, `.GDAXI`, `.DAX`, `.N225`, `.NKY`는 `rt_cd="0"`이어도 값이 `0.00`이고 시계열이 비어 있어 1차 범위에서 usable code로 볼 수 없다.
- 같은 probe 기준 `FX@JPY`, `FX@EUR`, `FX@CNY`는 응답은 오지만 값 스케일이 direct `JPY/KRW`, `EUR/KRW`, `CNY/KRW`로 확정되지 않았다. 이 값들은 각각 달러 cross(`USD/JPY`, `EUR/USD`, `USD/CNY`) 계열일 가능성을 먼저 검증해야 한다.
- 한국 국채 3Y·10Y의 fallback으로 미국 FRED `DGS3`, `DGS10`을 사용하는 것은 자산/국가가 다른 데이터 대체이므로 금융적으로 허용할 수 없다.
- 해외 원자재/선물은 Yahoo 티커(`CL=F`, `GC=F`)를 그대로 KIS에 넣는 방식이 아니라 KIS 전용 `SRS_CD`와 소수점 스케일 검증이 필요하다. 이 항목은 1차 범위로 확정하기 어렵다.

## Requirements

### Requirement 1: 1차 범위는 검증된 정형 데이터만 포함한다

**카테고리:** 범위/우선순위

**User Story:**
As a 시장 데이터 파이프라인,
I want 공식 문서와 실제 응답으로 검증된 KIS 항목만 1차 범위에 포함하고 싶다,
so that 정형 데이터 비중을 높이면서도 잘못된 금융 데이터가 들어오는 위험을 줄일 수 있다.

#### Acceptance Criteria

1. WHEN 1차 구현 범위를 확정할 때 THEN 시스템은 해외 주요 지수, 추가 환율, KOSPI/KOSDAQ 중 실제 코드·단위·응답 필드가 검증된 항목만 포함해야 한다.
2. WHEN 1차 구현 범위를 문서화할 때 THEN 시스템은 `usdkrw`, `dow30`, `kospi`, `kosdaq`만 "확정 범위"로 표시해야 한다.
3. WHEN 후보 항목이 공식 문서상 존재하더라도 concrete 코드값 또는 단위 해석이 미검증이면 THEN 해당 항목은 1차 범위에서 제외하고 2차 작업으로 분리해야 한다.
4. WHEN `sp500`, `nasdaq100`, `nasdaq_composite`, `dax`, `nikkei225`, `jpykrw`, `eurkrw`, `cnykrw`, 한국 국채, 원자재를 검토할 때 THEN 시스템은 현재 시점에서는 "사전 검증 후 편입 가능 범위" 또는 "후속 범위"로 기록해야 한다.
5. WHEN coverage와 정확성 사이에 충돌이 생길 때 THEN 시스템은 coverage 확대보다 정확성을 우선해야 한다.

### Requirement 2: 선행 검증 산출물 없이 구현하지 않는다

**카테고리:** 데이터 검증/입력 품질

**User Story:**
As a 개발자,
I want 신규 KIS 항목마다 코드, 단위, 전일 비교 기준을 먼저 검증하고 싶다,
so that 계산된 등락률과 표시 값이 금융적으로 일관되게 유지된다.

#### Acceptance Criteria

1. WHEN 신규 카테고리를 구현하기 전에 THEN 시스템은 standalone 검증 스크립트 또는 fixture 테스트로 아래 항목을 먼저 확정해야 한다:
   - `FID_COND_MRKT_DIV_CODE` 또는 동등 파라미터
   - concrete 종목코드
   - 현재값 필드
   - 전일 기준값 또는 변화율 필드
   - 표시 단위와 정규화 규칙
2. WHEN 검증 산출물을 남길 때 THEN 시스템은 항목별로 `category`, `code`, `unit`, `response field`, `sample as-of`를 표로 정리해야 한다.
3. WHEN `rt_cd="0"`이더라도 현재값이 모두 `0`이거나 시계열 배열이 비어 있으면 THEN 시스템은 이를 usable success로 간주하지 말고 `validation_status: "zero_payload"` 또는 동등한 실패 상태로 기록해야 한다.
4. WHEN 전일 기준값이 없거나 불안정하면 THEN 시스템은 파생 계산을 추정하지 말고 해당 항목을 `validation_status: "missing"` 또는 2차 범위로 처리해야 한다.
5. WHEN 결측값이 발생하면 THEN 시스템은 숫자를 보정하지 말고 결측을 명시적으로 드러내야 한다.

### Requirement 3: 해외 주요 지수는 usable 실제 지수 코드가 확인된 항목만 포함한다

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인,
I want KIS 해외 지수 경로에서 실제 지수 레벨을 수집하고 싶다,
so that SPY·QQQ 같은 ETF proxy와 지수 자체를 혼동하지 않게 된다.

#### Acceptance Criteria

1. WHEN 해외 주요 지수를 수집할 때 THEN 시스템은 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`, TR ID `FHKST03030100`, `FID_COND_MRKT_DIV_CODE="N"`을 사용해야 한다.
2. WHEN 1차 해외 지수 세트를 확정할 때 THEN 시스템은 현재 probe에서 usable payload가 확인된 `dow30/.DJI`만 확정 범위에 포함해야 한다.
3. WHEN `sp500`, `nasdaq100`, `nasdaq_composite`, `dax`, `nikkei225` 후보를 검토할 때 THEN 시스템은 `.SPX`, `.INX`, `.NDX`, `.IXIC`, `.GDAXI`, `.DAX`, `.N225`, `.NKY`를 현재 시점의 usable code로 간주하지 않아야 한다.
4. WHEN 해외 지수 응답이 `rt_cd="0"`이지만 `output1` 가격이 `0.00`이고 `output2`가 비어 있으면 THEN 시스템은 이를 코드 검증 실패로 처리해야 한다.
5. WHEN 해외 주요 지수의 KIS primary가 실패할 때 THEN 시스템은 같은 지수의 yfinance fallback으로 전환하고, KIS와 yfinance 모두 실패할 때만 `validation_status: "missing"`으로 표시해야 한다.
6. WHEN direct index를 production packet에 추가할 때 THEN 시스템은 기존 `us_indices`의 ETF proxy(`spy`, `qqq`, `soxx`)와 canonical key나 의미를 섞지 않아야 한다.
7. WHEN 해외 지수 범위를 다시 넓히려 할 때 THEN 시스템은 KIS 해외지수 마스터 또는 동등 공식 근거로 concrete code를 재확정한 뒤 문서와 probe 결과를 함께 갱신해야 한다.

### Requirement 4: 추가 환율은 direct KRW 단위가 검증될 때만 출시한다

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인,
I want USD/KRW 외 환율도 KIS 정형 데이터로 확장하고 싶다,
so that 뉴스레터의 환율 구간에서 비정형 보조 경로를 줄일 수 있다.

#### Acceptance Criteria

1. WHEN 추가 환율을 수집할 때 THEN 시스템은 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`, TR ID `FHKST03030100`, `FID_COND_MRKT_DIV_CODE="X"`를 사용해야 한다.
2. WHEN 1차 환율 확정 범위를 문서화할 때 THEN 시스템은 direct usable payload가 확인된 `usdkrw/FX@KRW`만 확정 범위에 포함해야 한다.
3. WHEN `FX@JPY`, `FX@EUR`, `FX@CNY`를 검토할 때 THEN 시스템은 현재 응답값을 곧바로 `JPY/KRW`, `EUR/KRW`, `CNY/KRW`로 라벨링하지 않아야 한다.
4. WHEN `jpykrw`, `eurkrw`, `cnykrw`를 future phase에 포함하려 할 때 THEN 시스템은 먼저 각 코드가 나타내는 원 통화쌍과 스케일을 문서로 확정하고, 필요하면 `USD/KRW`와의 cross-rate 계산 규칙까지 검증 산출물에 포함해야 한다.
5. WHEN 환율을 `MarketPoint`에 매핑할 때 THEN 시스템은 direct quote이든 cross-rate이든 모두 최종적으로 "KRW per 1 unit" 기준으로 정규화해야 한다.
6. WHEN JPY 계열 응답이 100엔 기준 또는 다른 관행 단위로 내려오면 THEN 시스템은 렌더링 전에 1엔 기준으로 환산하거나, 정규화 규칙이 확정되기 전까지 해당 항목을 출시하지 않아야 한다.
7. WHEN 추가 환율 KIS 수집이 실패할 때 THEN 시스템은 yfinance fallback으로 전환하되, 단위 체계가 KIS와 동일하게 정규화되는지 함께 검증해야 한다.
8. WHEN `usdkrw` 기존 경로를 재사용할 때 THEN 시스템은 `_ensure_token()`과 기존 KIS provider policy를 공유해야 한다.

### Requirement 5: KOSPI/KOSDAQ는 국내 지수 현재가 경로로 수집한다

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인,
I want KOSPI와 KOSDAQ를 국내 지수 전용 KIS 경로에서 수집하고 싶다,
so that 한국 시장 구간도 정형 데이터 우선 원칙을 적용할 수 있다.

#### Acceptance Criteria

1. WHEN 국내 지수를 수집할 때 THEN 시스템은 `/uapi/domestic-stock/v1/quotations/inquire-index-price`, TR ID `FHPUP02100000`를 사용해야 한다.
2. WHEN KOSPI와 KOSDAQ를 조회할 때 THEN 시스템은 `FID_COND_MRKT_DIV_CODE="U"`, `FID_INPUT_ISCD="0001"`(KOSPI), `FID_INPUT_ISCD="1001"`(KOSDAQ)을 사용해야 한다.
3. WHEN 1차 국내 지수 범위를 문서화할 때 THEN 시스템은 `kospi/0001`, `kosdaq/1001`를 확정 범위로 기록해야 한다.
4. WHEN KOSPI/KOSDAQ 데이터를 `MarketPoint`에 매핑할 때 THEN 시스템은 `change_pct`만 제공하고 `change_bps`는 `None`으로 유지해야 한다.
5. WHEN 장중/장후 구분이 필요할 때 THEN 시스템은 현재 [`MarketPoint`](/Users/giwon/code/news/src/morning_brief/models.py#L8) 스키마를 바꾸지 말고, 렌더링 메타데이터 또는 구조화 로그에서 기준시점을 표현해야 한다.
6. WHEN KOSPI/KOSDAQ 수집이 실패할 때 THEN 시스템은 yfinance fallback(`^KS11`, `^KQ11`)으로 전환해야 한다.

### Requirement 6: 한국 국채와 해외 원자재는 2차 범위로 분리한다

**카테고리:** 범위 통제

**User Story:**
As a 금융 데이터 설계자,
I want 금융적으로 잘못된 대체나 미검증 선물 코드로 1차 범위를 넓히지 않고 싶다,
so that 정형 데이터 확대가 오히려 데이터 왜곡을 만들지 않게 된다.

#### Acceptance Criteria

1. WHEN 국내 국채 3Y·10Y를 검토할 때 THEN 시스템은 한국 금리를 미국 FRED 금리(`DGS3`, `DGS10`)로 대체하는 fallback을 요구사항에서 허용하지 않아야 한다.
2. WHEN 한국 국채를 1차 범위에 넣으려 할 때 THEN 시스템은 KIS 공식 경로, concrete 코드, 응답 필드가 probe와 문서로 동시에 검증되기 전까지 편입하지 않아야 한다.
3. WHEN 한국 국채의 backup source가 필요할 때 THEN 시스템은 KIS 외 한국 금리 공식 소스(예: ECOS/KRX/KOFIA 등) 검토를 별도 작업으로 분리해야 한다.
4. WHEN WTI, Gold, Silver 등 원자재를 검토할 때 THEN 시스템은 KIS 전용 `SRS_CD`, 가격 스케일, 모의/실전 지원 여부가 검증되기 전까지 1차 범위에 포함하지 않아야 한다.
5. WHEN 원자재 항목을 future phase로 넘길 때 THEN 시스템은 Yahoo 티커(`CL=F`, `GC=F`)를 KIS 종목코드처럼 문서화하지 않아야 한다.

### Requirement 7: 인증과 레이트리밋은 기존 KIS 런타임 정책을 재사용한다

**카테고리:** 오류 처리/복원

**User Story:**
As a 파이프라인,
I want KIS 인증과 재시도 로직을 기존 정책 위에서 확장하고 싶다,
so that 신규 항목이 들어와도 운영 동작이 일관되게 유지된다.

#### Acceptance Criteria

1. WHEN KIS access token을 발급할 때 THEN 시스템은 기존 [`_ensure_token()`](/Users/giwon/code/news/src/morning_brief/data/sources/kis.py#L129) 모듈-레벨 singleton 패턴을 유지해야 한다.
2. WHEN KIS가 HTTP 500과 `message="EGW00201"`을 반환할 때 THEN 시스템은 retryable 레이트리밋으로 식별하고 기존 provider policy의 exponential backoff로 처리해야 한다.
3. WHEN 401 또는 토큰 만료가 발생할 때 THEN 시스템은 메모리 토큰을 무효화하고 재발급을 1회 시도한 뒤, 실패하면 fallback으로 전환해야 한다.
4. WHEN 신규 카테고리가 추가될 때 THEN 시스템은 별도 임의 재시도 정책을 만들지 말고 기존 `provider_runtime.py`의 `kis` 정책을 공유해야 한다.

### Requirement 8: 캐시는 "실행 중 중복 방지"와 "디스크 복구"를 분리한다

**카테고리:** 성능/복원

**User Story:**
As a 개발자,
I want 중복 호출 방지와 마지막 성공값 복구를 다른 계층으로 다루고 싶다,
so that TTL 의미가 프로세스 수명과 뒤섞이지 않는다.

#### Acceptance Criteria

1. WHEN 동일 실행에서 같은 KIS 항목이 여러 번 필요할 때 THEN 시스템은 per-run memoization 또는 동등한 방식으로 중복 호출을 방지해야 한다.
2. WHEN 실행이 종료되면 THEN in-memory dedupe cache는 폐기되어야 하며 26시간 TTL 같은 장기 보존 의미를 갖지 않아야 한다.
3. WHEN 마지막 성공값 복구를 사용할 때 THEN 시스템은 기존 market snapshot 디스크 캐시와 [`MARKET_POINT_CACHE_MAX_AGE_HOURS`](/Users/giwon/code/news/src/morning_brief/data/market.py#L52) 정책을 그대로 사용해야 한다.
4. WHEN 캐시가 실패해도 THEN 시스템은 시장 데이터 수집 자체를 실패로 만들지 말고 best-effort로 처리해야 한다.

### Requirement 9: fallback은 "같은 자산, 같은 의미" 원칙을 따른다

**카테고리:** 데이터 품질/복원

**User Story:**
As a 금융 데이터 사용자,
I want fallback이 원래 자산의 의미를 유지하길 원한다,
so that 소스가 바뀌어도 비교 가능한 데이터를 받을 수 있다.

#### Acceptance Criteria

1. WHEN KIS 호출이 실패할 때 THEN 시스템은 같은 자산군과 같은 의미를 유지하는 fallback만 사용해야 한다.
2. WHEN fallback이 한국 금리와 미국 금리처럼 자산 의미를 바꾸게 되면 THEN 해당 fallback은 허용하지 않아야 한다.
3. WHEN 모든 fallback이 실패할 때 THEN 시스템은 `validation_status: "missing"`으로 반환하고 파이프라인 전체를 중단하지 않아야 한다.
4. WHEN fallback이 사용될 때 THEN 시스템은 `provider`, `ticker`, `reason`을 포함한 구조화 로그를 남겨야 한다.
5. WHEN `kis.is_available()`가 `False`일 때 THEN 시스템은 카테고리별로 즉시 fallback으로 전환하고 동일 이유의 안내 로그는 1회만 출력해야 한다.

### Requirement 10: LLM 의존 축소는 고신뢰 structured field부터 적용한다

**카테고리:** 출력/리포트

**User Story:**
As a 뉴스레터 생성 파이프라인,
I want 검증된 structured market point를 직접 렌더링 경로에 넣고 싶다,
so that LLM이 해석해야 하는 시장 숫자 범위를 줄일 수 있다.

#### Acceptance Criteria

1. WHEN KIS 확장 항목이 검증을 통과하면 THEN 시스템은 해당 항목을 가능한 한 직접 렌더링 경로에서 사용해야 한다.
2. WHEN 항목이 아직 단위 또는 코드 검증이 끝나지 않았으면 THEN 시스템은 `signals`나 LLM prompt에 억지로 주입하지 않아야 한다.
3. WHEN `build_market_packet()`에 신규 structured field를 넣을 때 THEN 시스템은 글로벌 비교 의미가 분명한 항목만 추가해야 한다.
4. WHEN `fetch_newsletter_display_data()`에 신규 항목을 넣을 때 THEN 시스템은 렌더링 단계에서 출처 라벨이 KIS와 fallback source를 구분할 수 있게 유지해야 한다.
5. WHEN `build_market_packet()` 또는 `fetch_newsletter_display_data()`의 schema를 변경할 때 THEN 시스템은 같은 변경에서 `pipeline.py` 병합 경로와 `unified_output.py`, `briefing.py`, `emailer.py` 같은 downstream consumer를 함께 갱신하거나, 의도적으로 미사용 필드임을 문서에 명시해야 한다.
6. WHEN `build_market_packet()` schema를 확장할 때 THEN 시스템은 기존 `macro`, `korea_watch`, `us_indices`, `tech_stocks`, `bitcoin` key를 유지하고, 새 key 추가로 깨지는 preservation test를 같은 변경에서 갱신해야 한다.

### Requirement 11: 옵저버빌리티와 테스트는 orchestration 계층에서 보강한다

**카테고리:** 테스트/관측성

**User Story:**
As a 운영자,
I want 신규 KIS 항목이 어떤 경로로 수집됐는지 추적할 수 있길 원한다,
so that 배포 후 데이터 품질 문제를 빠르게 좁힐 수 있다.

#### Acceptance Criteria

1. WHEN 신규 KIS 항목을 추가할 때 THEN 시스템은 [`market.py`](/Users/giwon/code/news/src/morning_brief/data/market.py) 또는 상위 orchestration 계층에서 provider usage를 기록해야 한다.
2. WHEN KIS primary가 성공하거나 fallback이 사용될 때 THEN 시스템은 KIS와 fallback provider usage를 각각 구분해 기록해야 한다.
3. WHEN display-stage 수집 경로에서도 provider usage를 기록하려면 THEN 시스템은 `pipeline.py`가 `observer`를 `fetch_newsletter_display_data()` 또는 동등한 entrypoint로 전달하게 해야 한다.
4. WHEN 신규 파일에서 `observer.record_provider_usage(...)`를 호출할 때 THEN [`tests/test_logging_surface.py`](/Users/giwon/code/news/tests/test_logging_surface.py#L37) allowlist를 함께 갱신해야 한다.
5. WHEN 테스트를 작성할 때 THEN 최소 아래 시나리오를 포함해야 한다:
   - 해외 지수 usable code(`.DJI`) 성공
   - 해외 지수 zero payload(`.SPX`, `.NDX` 등) 실패 분류
   - 추가 환율 direct quote와 cross-rate 단위 정규화 구분
   - KOSPI/KOSDAQ 성공/실패 fallback
   - `kis.is_available() == False` 시 category-level fallback
   - KIS 401, EGW00201 처리
6. WHEN packet/display schema가 바뀔 때 THEN 시스템은 `pipeline.py` render merge, unified output, 이메일 렌더링, public output 경로를 함께 검증하는 통합 테스트를 추가하거나 기존 테스트를 확장해야 한다.
7. WHEN 동작, 범위, 운영 절차가 바뀌면 THEN 관련 README 또는 가장 가까운 운영 문서를 같은 변경에 포함해야 한다.
