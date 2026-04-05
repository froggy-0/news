# Requirements Document

## Introduction

현재 파이프라인에서 미국 주식 가격 데이터를 제공하는 Stooq가 4일 연속 100% 실패하여 모든 요청이 yfinance fallback으로 처리되고 있다. Stooq를 한국투자증권 Open API(KIS)로 교체하고, yfinance로 직접 수집 중인 USD/KRW는 KIS로 전환한다. `nq_futures`는 프론트월 계약 선택 규칙이 확정되기 전까지 기존 yfinance 경로를 유지한다. FRED(거시지표)·CoinGecko(BTC 현물)·Alternative.me(공포탐욕지수)는 현행 유지한다.

## Glossary

- **KIS**: 한국투자증권 Open API (`openapi.koreainvestment.com:9443`)
- **access_token**: KIS OAuth2 토큰. 일반고객 기준 1일 유효이며, 재발급은 분당 1회 제한이 공식 샘플 README에 명시되어 있다. 파이프라인은 실행 중 메모리에서만 재사용한다.
- **EGW00201**: KIS 초당 거래건수 초과 에러 코드 (HTTP 500 body에 포함)
- **EXCD**: KIS 해외주식 거래소 코드 (`NAS`=나스닥, `NYS`=뉴욕증권거래소, `AMS`=AMEX/NYSE Arca)
- **SRS_CD**: KIS 해외선물 종목코드. Yahoo Finance 티커(`NQ=F`)와 다르며 KIS 종목마스터 기준 코드(`BRNF25` 등)를 사용한다.
- **sCalcDesz**: KIS 해외선물 종목마스터(`ffcode.mst`)의 가격 소수점 스케일 정보
- **MarketPoint**: 파이프라인 내 시장 데이터 단위 (`price`, `change_pct`, `canonical_key` 등 포함)
- **ProviderPolicy**: 공급자별 재시도/레이트리밋 정책 (`src/morning_brief/data/sources/provider_runtime.py`)
- **KIS 대상 19개**: Stooq 교체 18개 + yfinance 교체 1개 (USD/KRW)

---

## Research-backed Constraints (2026-04-05)

- KIS 공식 상세 문서 기준 해외주식 현재체결가는 `/uapi/overseas-price/v1/quotations/price`, TR ID `HHDFS00000300`이며 실전/모의 모두 지원한다.
- KIS 공식 상세 문서 기준 해외선물종목현재가는 `/uapi/overseas-futureoption/v1/quotations/inquire-price`, TR ID `HHDFC55010000`이며 모의투자는 지원하지 않는다.
- KIS 공식 API 목록 기준 환율은 별도 `exchange-rate` 현재가 엔드포인트가 아니라 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice`에서 `FID_COND_MRKT_DIV_CODE="X"`로 문서화되어 있다.
- KIS 공식 예시 기준 해외선물 현재가 요청은 `SRS_CD` 하나만 받으며, 예시 코드는 `BRNF25`, `BONU25`, `ESZ23`처럼 Yahoo 티커와 다른 계약코드 체계를 사용한다.
- KIS 공식 문서 기준 해외선물 현재가의 `last_price`, `prev_price` 등은 `ffcode.mst`의 `sCalcDesz`를 적용해 해석해야 한다.
- KIS 공식 README와 공지 기준 EGW00201은 모의투자에서 더 쉽게 발생할 수 있고, 2026-03-20 기준 신규 실전 고객은 신청 후 3일간 초당 3건 제한이 적용된다.
- 위 제약을 기준으로 1차 범위에서는 `usdkrw`만 KIS로 전환하고, `nq_futures`의 KIS 이관은 2차 작업으로 분리한다.

---

## Requirements

### Requirement 1: KIS 인증 — 매 실행마다 신규 발급

**카테고리:** 데이터 수집/입력 — 인증

**User Story:**
As a 파이프라인,
I want 실행 시작 시 KIS access_token을 한 번 발급받아 해당 실행 내 모든 KIS 호출에 재사용하고 싶다,
so that 인증 오버헤드 없이 매일 파이프라인이 안정적으로 실행될 수 있다.

#### Acceptance Criteria

1. WHEN `KIS_APP_KEY`, `KIS_APP_SECRET` 환경변수가 설정되어 있으면, THE 인증 모듈 SHALL 파이프라인 실행 시작 시 `POST /oauth2/tokenP`로 access_token을 1회 발급한다.
2. WHEN 토큰 발급에 성공하면, THE 인증 모듈 SHALL 해당 토큰을 실행 중 메모리에만 보유하며 파일 캐시는 사용하지 않는다.
3. WHEN 토큰 발급이 실패하면, THE 인증 모듈 SHALL `HttpFetchError`를 발생시키고 KIS 전체 수집을 건너뛰어 yfinance fallback으로 넘어간다.
4. IF `KIS_APP_KEY` 또는 `KIS_APP_SECRET`이 없으면, THEN THE 인증 모듈 SHALL 토큰 발급을 시도하지 않고 즉시 전체 항목을 yfinance fallback으로 처리한다.
5. WHEN 같은 실행에서 여러 KIS 호출이 발생하면, THE 인증 모듈 SHALL access_token을 재발급하지 않고 기존 메모리 토큰을 재사용한다.

---

### Requirement 2: KIS 해외주식 현재가 조회 (Stooq 교체 18개)

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인,
I want KIS API로 18개 티커(지수 ETF 3종, 빅테크 10종, BTC ETF 5종)의 종가·등락률·거래량을 조회하고 싶다,
so that Stooq 없이도 동일한 MarketPoint 데이터를 생성할 수 있다.

#### Acceptance Criteria

1. WHEN KIS API 호출이 성공하면, THE KIS 모듈 SHALL `(close: float, change_pct: float, volume: int)` 튜플을 반환한다 — 기존 `fetch_close_change_and_volume()` 반환 타입과 동일.
2. WHEN 티커별 EXCD 코드를 매핑할 때, THE KIS 모듈 SHALL 아래 거래소 코드를 사용한다:
   - `NAS`: QQQ, SOXX, NVDA, MSFT, AAPL, AMZN, GOOGL, META, AMD, ASML, AVGO, IBIT
   - `NYS`: TSM
   - `AMS`: SPY, FBTC, ARKB, BITB, GBTC
3. WHEN KIS 응답의 `rt_cd == "0"` 이고 `output.last`가 유효한 값이면, THE KIS 모듈 SHALL 해당 값을 정상 데이터로 처리한다.
4. WHEN KIS 응답의 `rt_cd != "0"` 이면, THE KIS 모듈 SHALL `HttpFetchError`를 발생시킨다.
5. WHEN `output.last`가 빈 문자열이거나 `"0"`이면, THE KIS 모듈 SHALL 해당 응답을 실패로 간주하고 `HttpFetchError`를 발생시킨다 (장 마감 후 미확정 데이터 방지).

---

### Requirement 3: KIS USD/KRW 환율 조회 (1차 범위) + NQ Futures 현행 유지

**카테고리:** 데이터 수집/입력

**User Story:**
As a 파이프라인,
I want USD/KRW 환율은 KIS API로 조회하고 NQ Futures는 기존 경로를 유지하고 싶다,
so that 범위를 안전하게 줄이면서도 Stooq 장애와 환율 primary 문제를 먼저 해결할 수 있다.

#### Acceptance Criteria

1. WHEN KIS 환율 조회가 성공하면, THE KIS 모듈 SHALL 공식 문서에 공개된 `/uapi/overseas-price/v1/quotations/inquire-daily-chartprice` 경로와 사전에 확정된 concrete `FID_INPUT_ISCD="FX@KRW"` 값을 사용해 USD/KRW의 최신 가용 가격과 등락률을 `(rate: float, change_pct: float)` 형태로 반환한다 — 기존 `_safe_yfinance_point("usdkrw", "KRW=X")` 반환 형식과 동일한 MarketPoint를 생성할 수 있어야 한다.
2. WHEN `fetch_korea_investor_points()`를 실행하면, THE 함수 SHALL `usdkrw`에는 KIS primary를 적용하고 `nq_futures`에는 기존 `_safe_yfinance_point("nq_futures", "NQ=F")` 경로를 유지한다.
3. WHEN USD/KRW KIS 조회가 실패하면, THE `fetch_korea_investor_points()` SHALL `usdkrw`에 한해 기존 `_safe_yfinance_point()`로 fallback한다.
4. WHEN KIS 환율 엔드포인트를 사용할 때, THE KIS 모듈 SHALL 해외주식 현재가 조회(Req 2)와 동일한 access_token 및 `min_interval_seconds=0.4` 간격을 공유한다.
5. WHILE 1차 범위를 수행하는 동안, THE 파이프라인 SHALL `nq_futures`의 KIS primary 전환을 시도하지 않는다.
6. WHEN 구현을 시작할 때, THE 구현 계획 SHALL placeholder나 런타임 추측값이 아니라 spec에 기록된 concrete `FID_INPUT_ISCD`만 사용해야 한다.

> **구현 주의**: 공개 문서 기준 USD/KRW 전용 `exchange-rate` 현재가 엔드포인트는 확인되지 않았다. 환율은 `inquire-daily-chartprice`의 환율 구분값(`FID_COND_MRKT_DIV_CODE="X"`)을 사용하는 방향으로 설계한다. concrete `FID_INPUT_ISCD`는 KIS 공식 마스터 `frgn_code.mst`의 환율 구분(`X`) 레코드와 한국투자증권 공식 환율 화면 기본값을 교차 확인해 `FX@KRW`로 확정한다. NQ Futures는 `/uapi/overseas-futureoption/v1/quotations/inquire-price` + `SRS_CD` 조합이 문서화되어 있지만, 프론트월 선택 규칙이 확정될 때까지 2차 범위로 미룬다.

---

### Requirement 4: EGW00201 레이트리밋 처리

**카테고리:** 오류 처리/복원

**User Story:**
As a 파이프라인,
I want KIS 초당 거래건수 초과(EGW00201) 발생 시 자동으로 재시도하고 싶다,
so that 일시적인 레이트리밋으로 수집이 실패하지 않는다.

#### Acceptance Criteria

1. WHEN KIS가 HTTP 500 + body `"message": "EGW00201"`을 반환하면, THE KIS 모듈 SHALL 이를 일반 HTTP 에러가 아닌 레이트리밋으로 식별하고 재시도한다.
2. WHEN EGW00201 재시도 시, THE KIS 모듈 SHALL `1 → 2 → 4 → 8`초 exponential backoff를 적용한다.
3. WHEN 최대 5회 재시도 후에도 EGW00201이 계속되면, THE KIS 모듈 SHALL `HttpFetchError`를 발생시켜 yfinance fallback으로 전환한다.
4. WHEN 정상 요청 간격을 유지할 때, THE KIS 모듈 SHALL 요청 간 최소 0.4초 간격(`min_interval_seconds=0.4`)을 적용하여 EGW00201을 사전 예방한다.
5. WHEN EGW00201이 아닌 HTTP 500이 발생하면, THE KIS 모듈 SHALL 기존 `ProviderPolicy`의 `retryable_statuses` 정책대로 처리한다.

> **운영 주의**: 2026-03-20 공지 기준 신규 실전 고객은 신청 후 3일간 초당 3건 제한이 적용된다. `min_interval_seconds=0.4`는 이 제한보다 보수적이며, 1차 범위에서는 `nq_futures`를 KIS로 호출하지 않는다.

---

### Requirement 5: 기존 fallback·cache 체계 유지

**카테고리:** 오류 처리/복원

**User Story:**
As a 파이프라인,
I want KIS 실패 시에도 yfinance fallback과 cache recovery가 기존과 동일하게 작동하기를 원한다,
so that KIS 장애가 전체 파이프라인 실패로 이어지지 않는다.

#### Acceptance Criteria

1. WHEN KIS 해외주식 조회가 실패하면, THE `_safe_kis_point()` 및 `_safe_kis_point_and_volume()` SHALL 기존과 동일하게 `_safe_yfinance_point()`를 호출한다.
2. WHEN KIS 환율 조회가 실패하면, THE `fetch_korea_investor_points()` SHALL `usdkrw`에 대해 기존과 동일하게 `_safe_yfinance_point()`를 호출한다.
3. WHEN KIS + yfinance 모두 실패하면, THE 파이프라인 SHALL 기존 `_resolve_point_from_cache()` 로직으로 최대 26시간 이내 캐시 데이터를 복원한다.
4. WHEN KIS fallback이 발생하면, THE 파이프라인 SHALL `event=fallback.used | reason=kis_fallback_{ticker}` 형식으로 WARNING 로그를 남긴다 (기존 `stooq_fallback_` 패턴 대체).
5. IF KIS 인증 정보가 없으면, THEN THE 파이프라인 SHALL KIS를 건너뛰고 즉시 yfinance를 primary로 사용하며 WARNING 로그 없이 INFO 로그만 남긴다.

---

### Requirement 6: KIS 소스 모듈 신설 및 Stooq 모듈 제거

**카테고리:** 데이터 모델/구조

**User Story:**
As a 개발자,
I want Stooq 의존성을 완전히 제거하고 KIS 모듈로 교체하고 싶다,
so that 죽은 코드 없이 유지보수성을 확보한다.

#### Acceptance Criteria

1. WHEN 마이그레이션이 완료되면, THE 코드베이스 SHALL `src/morning_brief/data/sources/kis.py` 파일을 포함한다.
2. WHEN `kis.py`의 공개 인터페이스를 정의할 때, THE 모듈 SHALL 아래 함수를 노출한다:
   - `fetch_close_change_and_volume(ticker: str) -> tuple[float, float, int]` — 해외주식 18개
   - `fetch_usdkrw_point() -> tuple[float, float]` — 환율 1개 (`usdkrw`)
   - `is_available() -> bool` — KIS 환경변수 존재 여부
3. WHEN 마이그레이션이 완료되면, THE 코드베이스 SHALL `src/morning_brief/data/sources/stooq.py`를 삭제한다.
4. WHEN `market.py`에서 Stooq 참조를 KIS helper로 교체할 때, THE `_safe_kis_point()` 및 `_safe_kis_point_and_volume()` 함수 SHALL 기존 호출부 기준의 반환 타입과 fallback 의미를 유지한다.
5. WHEN `market.py`에서 `fetch_korea_investor_points()`를 교체할 때, THE 함수 SHALL `usdkrw`에만 `kis.fetch_usdkrw_point()`를 primary로 사용하고 `nq_futures`는 기존 yfinance 경로를 유지한다.
6. WHEN `ProviderPolicy`를 업데이트할 때, THE `PROVIDER_POLICIES` SHALL `"stooq"` 키를 `"kis"`로 교체하고 `min_interval_seconds=0.4`, `max_attempts=5`, `base_backoff_seconds=1.0`을 적용한다.

---

### Requirement 7: 환경변수 및 CI 설정

**카테고리:** 설정/환경

**User Story:**
As a 운영자,
I want KIS 인증 정보를 환경변수로 주입하고 싶다,
so that 코드 변경 없이 인증 정보를 관리할 수 있다.

#### Acceptance Criteria

1. WHEN `config.py`에 KIS 설정을 추가할 때, THE 설정 모듈 SHALL `KIS_APP_KEY`, `KIS_APP_SECRET` 두 개의 환경변수를 읽는다.
2. WHEN 두 값 중 하나라도 비어있으면, THE 설정 모듈 SHALL `kis_available=False`로 설정하고 경고 로그 없이 처리한다.
3. WHEN GitHub Actions workflow에 시크릿을 추가할 때, THE CI SHALL `KIS_APP_KEY`, `KIS_APP_SECRET`을 파이프라인 실행 환경에 주입한다.
4. WHEN CI에 KIS 시크릿을 주입할 때, THE 운영 환경 SHALL 모의투자가 아닌 실전 KIS 인증정보를 사용한다.

---

### Requirement 8: 기존 테스트 업데이트

**카테고리:** 테스트/검증

**User Story:**
As a 개발자,
I want 기존 Stooq 테스트가 KIS 기준으로 업데이트되길 원한다,
so that 마이그레이션 후 회귀 없이 CI가 통과된다.

#### Acceptance Criteria

1. WHEN `tests/test_stooq.py`를 교체할 때, THE 테스트 SHALL `tests/test_kis_source.py`로 대체되어 `fetch_close_change_and_volume()`과 `fetch_usdkrw_point()` 동작을 단위 검증한다.
2. WHEN `test_market_btc_official_flow.py`의 Stooq mock을 교체할 때, THE 테스트 SHALL KIS 모듈을 mock하되 동일한 검증 시나리오를 유지한다.
3. WHEN `test_preservation_properties.py`의 Stooq 관련 assertion을 업데이트할 때, THE 테스트 SHALL `stooq_symbol`, `to_stooq_symbol()` 참조를 KIS 기준으로 교체한다.
4. WHEN `fetch_korea_investor_points()` 테스트를 추가할 때, THE 테스트 SHALL `usdkrw`의 KIS 성공·실패와 `nq_futures`의 기존 yfinance 유지 시나리오를 검증한다.
5. WHEN `make check`를 실행하면, THE CI SHALL lint + typecheck + 전체 테스트를 통과한다.

---

### Requirement 9: 운영 문서 및 사용자 노출 출처 정합성

**카테고리:** 출력/리포트/UI

**User Story:**
As a 운영자,
I want 문서와 브리핑의 출처 표기가 실제 primary/fallback 경로와 일치하길 원한다,
so that 배포 후 운영 문서와 사용자 노출 텍스트가 데이터 수집 경로를 정확히 설명할 수 있다.

#### Acceptance Criteria

1. WHEN `docs/data-sources.md`를 갱신할 때, THE 문서 SHALL `usdkrw`의 1차 소스를 KIS 환율 엔드포인트로, 폴백을 yfinance `KRW=X`로 명시한다.
2. WHEN `docs/data-flow.md`를 갱신할 때, THE 문서 SHALL `korea_watch`에서 `usdkrw`는 KIS primary, `nq_futures`는 yfinance primary로 명시한다.
3. WHEN 브리핑이 KIS에서 가져온 `usdkrw` 포인트를 렌더링할 때, THE formatter SHALL `[출처: KIS]`를 노출한다.
4. WHEN 브리핑이 yfinance fallback으로 가져온 `usdkrw` 포인트를 렌더링할 때, THE formatter SHALL `[출처: yfinance]`를 노출한다.
5. WHEN 브리핑이 `nq_futures` 포인트를 렌더링할 때, THEN THE formatter SHALL 기존과 동일하게 `[출처: yfinance]`를 유지한다.
