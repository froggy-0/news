# Bugfix Requirements Document

## Introduction

매일 아침 미국 기술주+비트코인 시장 브리핑을 자동 생성하는 파이프라인에서 3개 데이터 소스가 구조적으로 수집에 실패하고 있다. 최근 10회 연속 실행 로그 분석 결과, DXY(달러 인덱스)는 yfinance 티커 문제로 10/10 실패, Perplexity BTC ETF structured query는 10/10 빈 배열 반환, GBTC direct fetch는 Grayscale의 HTTP 429 차단으로 10/10 실패한다. 이로 인해 거시 지표 5종 중 1종(DXY)이 매일 누락되고, BTC ETF 보유량 수집 경로에 불필요한 Perplexity API 비용이 발생하며, GBTC 데이터는 어떤 경로로도 수집 불가한 상태이다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `fetch_macro_points()`가 DXY를 수집할 때 yfinance 티커 `DX-Y.NYB`를 사용하면 THEN 시스템은 "possibly delisted" 오류로 3회 재시도 후 실패하고, 캐시에도 이전 성공 값이 없어 `validation_status=missing`으로 DXY가 브리핑에서 완전 누락된다

1.2 WHEN `fetch_macro_points()`에서 DXY를 수집할 때 THEN 시스템은 다른 지표(SPY, QQQ, SOXX, 빅테크)와 달리 Stooq fallback 경로가 없어 yfinance 단독 경로만 시도하고, yfinance 실패 시 대안이 없다

1.3 WHEN `fetch_official_btc_etf_snapshots()`가 Perplexity structured query로 IBIT/BITB/GBTC 보유량을 요청하면 THEN 시스템은 매번 `{"snapshots": []}` 빈 배열을 반환받아 Perplexity API 비용만 소모하고 유효한 데이터를 얻지 못한다

1.4 WHEN Perplexity structured query가 빈 배열을 반환하여 direct fetch fallback이 발동하면 THEN 시스템은 IBIT+BITB 2건만 성공적으로 수집하지만, 항상 실패하는 Perplexity 요청에 불필요한 지연 시간과 API 비용이 발생한다

1.5 WHEN `_fetch_direct_reference_snapshots()`에서 GBTC 데이터를 수집하려 하면 THEN Grayscale 공식 사이트가 HTTP 429로 scraping을 차단하여 GBTC 보유량을 어떤 경로로도 가져올 수 없다

### Expected Behavior (Correct)

2.1 WHEN `fetch_macro_points()`가 DXY를 수집할 때 THEN 시스템은 Stooq를 우선 시도하고, Stooq 실패 시 yfinance `DX=F`(ICE 달러 선물)를 fallback으로 사용하여 DXY 값을 안정적으로 수집해야 한다 (기존 `_safe_stooq_point()` 패턴 활용)

2.2 WHEN DXY 수집 경로가 변경된 후 THEN 시스템은 `MACRO_FALLBACK_TARGETS`에서 DXY를 제거하고, 별도의 Stooq 우선 경로로 DXY를 수집하며, `market_policy.py`의 `CANONICAL_KEY_BY_SOURCE`에 새 티커 매핑을 추가해야 한다

2.3 WHEN `fetch_official_btc_etf_snapshots()`가 BTC ETF 보유량을 수집할 때 THEN 시스템은 Perplexity structured query를 거치지 않고 direct fetch(IBIT+BITB)를 primary 경로로 바로 사용하여 불필요한 API 비용과 지연을 제거해야 한다

2.4 WHEN Perplexity structured query가 제거된 후 THEN 시스템은 Perplexity Sonar의 다른 용도(토픽 요약, 뉴스 수집 등)에는 영향을 주지 않아야 한다

2.5 WHEN GBTC 보유량 데이터가 브리핑 프롬프트에서 명시적으로 요구되지 않고, IBIT+BITB 2종만으로 `official_etf_snapshots` 필드를 충분히 채울 수 있으면 THEN 시스템은 GBTC 수집을 시도하지 않고 IBIT+BITB 2종만으로 운영해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN DXY 외의 거시 지표(us10y, us3m, vix)를 수집할 때 THEN 시스템은 기존 `MACRO_FALLBACK_TARGETS` + FRED 우선 → yfinance fallback 경로를 그대로 유지해야 한다

3.2 WHEN 미국 지수(SPY, QQQ, SOXX)와 빅테크 10종을 수집할 때 THEN 시스템은 기존 Stooq 우선 → yfinance fallback 패턴을 그대로 유지해야 한다

3.3 WHEN BTC ETF 가격·거래량(IBIT, FBTC, ARKB, BITB, GBTC)을 수집할 때 THEN 시스템은 기존 `_safe_stooq_point_and_volume()` 경로를 그대로 유지해야 한다

3.4 WHEN BTC ETF 보유량 캐시 구조(`btc-etf-snapshots-YYYYMMDD`)를 사용할 때 THEN 시스템은 기존 캐시 파일 경로, 로드/저장 로직, TTL 정책을 그대로 유지해야 한다

3.5 WHEN Perplexity Sonar가 토픽 요약, 뉴스 수집, 맥락 분석 등 BTC ETF structured query 외의 용도로 사용될 때 THEN 시스템은 해당 기능에 어떤 영향도 주지 않아야 한다

3.6 WHEN `build_market_packet()`이 최종 packet을 구성할 때 THEN 시스템은 기존 packet 구조(`macro`, `korea_watch`, `us_indices`, `tech_stocks`, `bitcoin` 등)와 데이터 검증·캐시 대체 로직을 그대로 유지해야 한다

3.7 WHEN DXY 값이 수집된 후 검증될 때 THEN 시스템은 기존 validation bounds `(95.0, 115.0)` 범위를 그대로 적용해야 한다

3.8 WHEN 기존 테스트를 실행할 때 THEN 모든 기존 테스트가 수정 없이 통과해야 한다
