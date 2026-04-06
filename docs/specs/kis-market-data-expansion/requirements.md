# Requirements Document

## Introduction

현재 KIS API는 미국 주요 ETF(SPY·QQQ·SOXX), 빅테크 10종, BTC ETF 5종, USD/KRW 환율만 수집한다. 해외 주요 지수(S&P 500·NASDAQ·DOW·DAX·NIKKEI), 추가 환율(JPY·EUR·CNY/KRW), KOSPI/KOSDAQ, 국채금리(3Y·10Y), 원자재(WTI·Gold·Silver)는 yfinance 또는 FRED에 의존하거나 아예 수집하지 않는다. KIS API는 공식 라이선스 기반의 실시간 데이터를 제공하며 Grok 호출보다 저렴하고 신뢰도가 높다. 이 기능은 KIS 수집 대상을 확장하여 시장 데이터 품질을 높이고, LLM 프롬프트 내 yfinance·Grok 의존 항목을 줄이는 것을 목표로 한다.

## Functional Requirements

### 해외 주요 지수 수집

1.1 WHEN 파이프라인이 시장 데이터를 수집할 때 THEN 시스템은 KIS `FHKST03030100` TR ID(해외 지수 차트 TR)를 사용하여 S&P 500, NASDAQ Composite, DOW Jones, DAX, NIKKEI 225의 실제 지수 레벨·등락률을 수집해야 한다. ETF proxy(EWG, EWJ 등) 티커는 사용하지 않는다

1.2 WHEN KIS 해외 주요 지수 수집이 실패할 때 THEN 시스템은 yfinance fallback으로 동일 지수를 수집하고, 두 소스 모두 실패할 때만 해당 항목을 `validation_status: "missing"`으로 표시해야 한다

1.3 WHEN 해외 지수 fetcher를 구현하기 전에 THEN KIS `FHKST03030100` endpoint의 실제 FID 파라미터(FID_INPUT_ISCD 코드값 등)를 검증하는 standalone 테스트 스크립트를 먼저 실행하여 파라미터를 확정해야 한다. 미검증 파라미터로 구현을 진행하지 않는다

1.4 WHEN `FID_INPUT_ISCD`에 등록되지 않은 지수 코드가 요청될 때 THEN 시스템은 `HttpFetchError`를 발생시키고 fallback으로 전환해야 한다

### 추가 환율 수집

2.1 WHEN 파이프라인이 환율 데이터를 수집할 때 THEN 시스템은 KIS `FHKST03030100` TR ID를 사용하여 JPY/KRW, EUR/KRW, CNY/KRW 환율·등락률을 수집해야 한다

2.2 WHEN KIS 환율 수집이 실패할 때 THEN 시스템은 yfinance fallback(JPYKRW=X, EURKRW=X, CNYKRW=X)으로 전환해야 한다

2.3 WHEN `fetch_usdkrw_point()`와 동일한 TR ID·경로를 사용할 때 THEN 시스템은 `FID_INPUT_ISCD` 파라미터만 교체하여 재사용해야 한다 (`FX@KRW` → `FX@JPY`, `FX@EUR`, `FX@CNY`)

### KOSPI/KOSDAQ 수집

3.1 WHEN 파이프라인이 국내 지수를 수집할 때 THEN 시스템은 KIS 국내 지수 현재가 TR ID(`FHPUP02100000` 또는 동등한 TR)를 사용하여 KOSPI·KOSDAQ 지수 레벨·등락률을 수집해야 한다

3.2 WHEN KOSPI/KOSDAQ 수집이 실패할 때 THEN 시스템은 yfinance fallback(^KS11, ^KQ11)으로 전환해야 한다

3.3 WHEN KOSPI/KOSDAQ 데이터를 `MarketPoint`에 매핑할 때 THEN `change_bps`는 None으로 설정하고, `change_pct`만 제공해야 한다

3.4 WHEN 파이프라인이 KST 09:00~15:30 사이에 실행될 때 THEN KOSPI/KOSDAQ는 KIS API가 제공하는 당일 실시간에 준한 지수 값을 수집해야 한다

3.5 WHEN 파이프라인이 KST 15:30 이전에 실행되어 US 시장 데이터가 전일 종가일 때 THEN 해당 `MarketPoint`의 `data_as_of` 필드에 전일 종가 기준임을 명시해야 한다

### 국내 국채금리 수집

4.1 WHEN 파이프라인이 금리 데이터를 수집할 때 THEN 시스템은 KIS `FHKST03030400` TR ID(채권 시세 TR)를 사용하여 국내 국채 3Y·10Y 수익률(%)을 수집해야 한다

4.2 WHEN 국채금리 데이터를 `MarketPoint`에 매핑할 때 THEN `change_pct`는 None으로 설정하고, 전일 대비 변화는 `change_bps`(bp 단위)로만 표시해야 한다. 이는 기존 `is_rate_canonical_key()` 로직과 동일하다

4.3 WHEN KIS 국채금리 수집이 실패할 때 THEN 시스템은 FRED fallback(DGS3, DGS10)으로 전환하고, FRED도 실패할 때만 해당 항목을 skip해야 한다

### 원자재 수집

5.1 WHEN 파이프라인이 원자재 데이터를 수집할 때 THEN 시스템은 KIS `FHKST03030300` TR ID(해외 선물 TR)를 사용하여 WTI 원유(CL=F), Gold(GC=F) 가격·등락률을 수집해야 한다

5.2 WHEN KIS 원자재 수집이 실패할 때 THEN 시스템은 yfinance fallback(CL=F, GC=F)으로 전환해야 한다

5.3 WHEN 원자재 가격을 수집할 때 THEN 거래량(`tvol`)도 함께 수집하여 유동성 이상 탐지에 활용할 수 있어야 한다

### KIS Rate Limit 및 인증 요구사항

6.1 WHEN KIS API에서 HTTP 500과 `message: "EGW00201"` 응답이 올 때 THEN 시스템은 `_KisRateLimitError`를 발생시키고 `retryable: true`로 표시하여 기존 `execute_with_provider_retry` 정책으로 처리해야 한다

6.2 WHEN 토큰이 만료되거나 401 응답이 올 때 THEN 시스템은 토큰 캐시(`_TOKEN`)를 무효화하고 재발급을 1회 시도해야 한다. 재발급도 실패하면 fallback으로 전환한다

6.3 WHEN 신규 티커에 대해 `_EXCD_MAP`을 확장할 때 THEN KIS 공식 거래소 코드(`NAS`, `NYS`, `AMS`, `TSE`, `FRA`, `SHS` 등)를 사용해야 하며, 비공식 코드는 사용하지 않는다

6.4 WHEN KIS 토큰을 발급할 때 THEN 기존 `_ensure_token()` 모듈-레벨 singleton 패턴을 유지해야 한다. `kis_market_fetcher.py`는 `kis.py`의 `_ensure_token()`을 공유하여 불필요한 토큰 재발급을 방지해야 한다

### 캐싱 (TTL 기반, 중복 호출 방지)

7.1 WHEN 동일 티커에 대해 파이프라인 내 2회 이상 호출이 발생할 때 THEN 시스템은 TTL 기반 인메모리 캐시로 KIS API 중복 호출을 방지해야 한다. TTL은 `MARKET_POINT_CACHE_MAX_AGE_HOURS`(현재 26h)를 따른다

7.2 WHEN 캐시된 값이 TTL 내에 있을 때 THEN 시스템은 KIS API를 호출하지 않고 캐시 값을 반환해야 한다

7.3 WHEN 캐시 미스가 발생하거나 TTL이 만료됐을 때 THEN 시스템은 KIS API를 새로 호출하고 결과를 캐시에 저장해야 한다

7.4 WHEN 캐시 저장에 실패할 때 THEN 시스템은 캐시 오류를 무시하고 신규 수집 값을 반환해야 한다 (캐시는 best-effort)

### Fallback 요구사항

8.1 WHEN KIS API 호출이 실패할 때 THEN 시스템은 카테고리별 정의된 순서(KIS → yfinance → skip 또는 KIS → FRED → skip)로 fallback을 시도해야 한다

8.2 WHEN 모든 fallback이 실패할 때 THEN 해당 항목은 `validation_status: "missing"`으로 `MarketPoint`를 반환하며 파이프라인 전체를 중단하지 않아야 한다. 집계 로직은 부분 성공을 허용한다

8.3 WHEN fallback이 사용될 때 THEN 시스템은 `WARNING` 레벨 구조화 로그(`provider`, `ticker`, `reason` 포함)를 출력해야 한다. `DEBUG` 레벨 잡음 로그는 추가하지 않는다

8.4 WHEN KIS `is_available()` 체크가 `False`일 때 THEN 시스템은 해당 카테고리 전체를 즉시 fallback으로 전환하고 경고 1회만 출력해야 한다 (`_info_once` 패턴)

## Non-Functional Requirements

### 성능

9.1 WHEN 단일 티커 fetch가 완료될 때 THEN 소요 시간은 2초 미만이어야 한다 (`_TIMEOUT_SECONDS = 15` 기존 상한은 유지하되, 정상 응답은 2초 내 완료 목표)

9.2 WHEN 카테고리별 배치 fetch가 실행될 때 THEN 전체 시장 데이터 수집 단계는 기존 파이프라인 타임아웃 기준 내에서 완료되어야 한다

9.3 WHEN 파이프라인이 어느 시각에 실행되더라도 THEN 시스템은 Pre-market(KST 06:00~09:00)·장중(09:00~15:30)·장후(15:30 이후) 구분 없이 KIS API가 제공하는 가장 최신 데이터를 수집하여 정상 동작해야 한다

### LLM 프롬프트 감소

10.1 WHEN KIS 확장 수집이 완료될 때 THEN LLM 프롬프트(`build_market_packet`)에서 yfinance 단독 의존 항목(VIX 제외)은 KIS 데이터로 대체되어 Grok 보조 검색 호출 횟수가 감소해야 한다

10.2 WHEN 추가 환율(JPY·EUR·CNY), KOSPI/KOSDAQ, 원자재가 KIS로 수집될 때 THEN 해당 항목은 LLM 프롬프트의 `signals` 섹션이 아닌 직접 렌더링 경로(`fetch_newsletter_display_data`)로 제공되어야 한다

### 옵저버빌리티

11.1 WHEN `kis_market_fetcher.py`의 fetch 함수가 완료될 때 THEN 성공·실패 여부와 무관하게 `observer.record_provider_usage(provider='kis', ...)` 를 호출해야 한다

11.2 WHEN fallback provider(yfinance, FRED)가 사용될 때 THEN 해당 provider도 `observer.record_provider_usage(provider='yfinance'` 또는 `'fred', ...)`로 별도 기록해야 한다

11.3 WHEN 신규 파일이 provider usage를 기록할 때 THEN `test_logging_surface.py`의 `EXPECTED_OBSERVER_CALL_FILES` allowlist에 해당 파일명을 추가해야 한다. 이는 이전 PR에서 반복된 allowlist 누락 패턴을 방지하기 위함이다
