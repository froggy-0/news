# Requirements Document

## Introduction

현재 Sentiment Time Join 파이프라인은 BTC 현물 가격을 CoinGecko(1차) → yfinance(폴백) 순으로 수집하며, 선물 시장 파생 지표는 Binance Futures 공개 API를 통해 `funding_rate`·`open_interest_usd`를 수집하고 있다(구현 완료). 그러나 다음 세 가지 공백이 남아 있다.

1. **BTC 현물 소스**: CoinGecko는 무료 티어 Rate Limit이 낮고 데이터 레이턴시가 있어 정밀도가 부족하다. 바이낸스 Spot API(`/api/v3/klines`)는 UTC 00:00 캔들 종가를 직접 제공하며, 거래대금(quote asset volume)도 동시에 수집할 수 있다.
2. **Long/Short Ratio**: 레버리지 포지션 분포를 나타내는 선행 지표로, 현재 `futures.py`에 구현되어 있지 않다.
3. **이상값 탐지 범위**: `join.py`의 롤링 IQR 이상값 탐지가 `btc_return`·`usdkrw_return`에만 적용되어 있으며, 신규 파생 지표(funding rate, OI, long/short ratio)가 누락되어 있다.

**목표**: 바이낸스 Spot API로 BTC 현물 소스를 마이그레이션하고, 거래대금과 Long/Short Ratio를 추가하여 FinBERT 뉴스 감성과 선물 시장 선행 지표 간 인과관계(Granger 검정, PCA) 분석에 즉시 투입 가능한 시계열 데이터셋을 완성한다.

---

## Glossary

- **Binance Spot API**: `api.binance.com/api/v3` — 공개 엔드포인트는 API Key 없이 호출 가능. API Key를 헤더에 포함하면 요청 가중치(weight) 한도가 상향된다
- **Binance Futures API**: `fapi.binance.com` — 공개 시장 데이터 엔드포인트 (인증 불필요). 현재 `futures.py`에서 펀딩비·미결제약정 수집에 사용 중
- **klines**: 바이낸스 캔들 데이터 — `[open_time, open, high, low, close, volume, close_time, quote_asset_volume, ...]` 형태의 배열. **주의: 가격·거래량 필드(인덱스 1~10)는 모두 `str` 타입으로 반환된다. 반드시 `float()`로 변환해야 한다.** 타임스탬프(인덱스 0, 6)만 `int`
- **open_time**: klines 배열 인덱스 0. 해당 캔들의 시작 시각(UTC 자정 00:00:00.000). 일별 캔들의 날짜 기준으로 사용한다
- **quote_asset_volume**: klines 배열 인덱스 7. 해당 캔들 기간 내 USDT 기준 누적 거래대금. 단순 거래량(BTC 수량, 인덱스 5)과 구분. **str 타입 반환**
- **Long/Short Ratio**: 전체 사용자 계정 중 롱(매수) 포지션 대 숏(매도) 포지션의 비율 (`globalLongShortAccountRatio`). 값이 < 1이면 숏 계정 우세(약세 심리). 실측 예: `longAccount=0.4689 / shortAccount=0.5311 = longShortRatio=0.8829`
- **daily funding rate (sum)**: 하루 3회(00:00/08:00/16:00 UTC) 펀딩비의 **합산값**. 단순 평균이 아니라 해당일 실제 포지션 보유 비용(P&L 영향)을 나타낸다. 기존 `futures.py`의 `_aggregate_daily_funding()`이 `sum`을 사용하며, 이는 의도적 설계 결정이다
- **funding_rate_lag1**: 펀딩비 Lag-1 처리값 — 미래 오염(look-ahead bias) 방지를 위해 분석 시 사용. 현재 `join.py`에 구현됨
- **weight limit**: 바이낸스 API의 분당 요청 가중치 한도(기본 1200 weight/min). 엔드포인트별 weight: klines=2, fundingRate=5, openInterestHist=1, globalLongShortAccountRatio=1. 4개 합산 = 9/회 실행 (한도 대비 0.75%)

---

## Current State (구현 완료된 항목)

아래 항목은 이미 코드베이스에 구현되어 있으며 이 spec의 대상이 아니다.

| 항목 | 위치 | 상태 |
|------|------|------|
| Binance Futures 펀딩비 (`funding_rate`) | `sources/futures.py` | 완료 |
| Binance Futures 미결제약정 (`open_interest_usd`) | `sources/futures.py` | 완료 |
| Lag-1 처리 (`funding_rate_lag1`, `oi_change_pct_lag1`) | `join.py:_add_futures_lag_columns()` | 완료 |
| 스키마 검증 (위 4개 컬럼 포함) | `validate.py:MASTER_SCHEMA` | 완료 |
| PCA 하이브리드 지수 (`hybrid_index`) | `hybrid_index.py` | 완료 |

---

## Requirements

### Requirement 1: BTC 현물 소스 — Binance Spot API로 마이그레이션

**User Story:**
As a 데이터 과학자,
I want BTC 일별 종가 수집원이 바이낸스 Spot API가 되기를,
so that UTC 00:00 캔들 기준 정밀한 종가를 안정적으로 수집하고 CoinGecko Rate Limit 의존도를 제거할 수 있다.

#### Acceptance Criteria

1. WHEN BTC 현물 데이터를 수집할 때, THE 수집기 SHALL `src/morning_brief/analysis/sentiment_join/sources/binance.py`에 독립 구현되어야 하며, 기존 `btc_prices.py`·`futures.py` 및 운영 파이프라인(`src/morning_brief/data/`)을 수정하지 않아야 한다

2. WHEN Binance Spot API를 호출할 때, THE 수집기 SHALL `GET https://api.binance.com/api/v3/klines` 엔드포인트에 `symbol=BTCUSDT`, `interval=1d`, `startTime={unix_ms}`, `limit={n}` 파라미터로 요청해야 하며, 각 캔들의 `open_time`(인덱스 0, UTC 자정 00:00:00.000 ms 타임스탬프) 기준 UTC 날짜를 `YYYY-MM-DD` 문자열로 변환하여 `date` 컬럼으로 사용해야 한다. `close_time`(인덱스 6)은 23:59:59.999 UTC로 동일한 날짜이나, 의미적으로 캔들 시작일인 `open_time`이 정확하다

3. WHEN Binance Spot API 응답을 파싱할 때, THE 수집기 SHALL 각 행이 12개 원소의 배열임을 확인하고, `close`(인덱스 4, **str → float 변환**)와 `btc_quote_volume`(인덱스 7, quote asset volume, **str → float 변환**)을 `float64`로 추출하여 `{"date": str, "close": float64, "btc_quote_volume": float64}` 구조의 DataFrame을 반환해야 한다. 실측 형식: `close='72962.70000000'`, `quote_asset_volume='1259195636.05566300'`

4. WHEN Binance Spot API 호출이 실패(4xx/5xx/timeout)할 때, THE 수집기 SHALL 기존 `btc_prices.py`의 `fetch_btc_close()`(CoinGecko → yfinance 체인)를 폴백으로 호출해야 한다. 폴백 사용 시 `WARNING` 레벨 구조화 로그(`event=fallback.used | source=btc | reason`)를 출력하고, 폴백 경로에서는 `btc_quote_volume`을 `NaN`으로 채운다

5. WHEN `SENTIMENT_JOIN_BINANCE_KEY` 환경변수가 설정된 경우, THE 수집기 SHALL Binance Spot API 요청 헤더에 `X-MBX-APIKEY: {key}` 를 포함해야 한다. 환경변수가 없으면 헤더 없이 공개 엔드포인트로 요청한다

6. WHEN Binance Spot API 단일 요청으로 전체 기간을 수집할 때, THE 수집기 SHALL `limit=lookback_days+2`로 단일 요청을 수행해야 한다. `config.py`의 `SENTIMENT_JOIN_LOOKBACK_DAYS` 최대값이 730이고 klines 엔드포인트 최대 limit이 1000이므로, 현재 설정 범위에서는 단일 요청으로 전체 기간 수집이 보장된다. 단, `limit` 파라미터가 1000을 초과하는 경우 `ValueError`를 발생시켜야 한다 (향후 설정 변경 방어)

7. WHEN `pipeline.py`의 `fetch_btc_close()` 호출 위치를, THE 파이프라인 SHALL 신규 `binance.py`의 `fetch_btc_close_binance()` 호출로 교체해야 한다. 반환 DataFrame의 `close` 컬럼 의미와 `attrs["fallback_used"]` 인터페이스는 기존과 동일하게 유지한다

---

### Requirement 2: BTC 거래대금 컬럼 추가 (`btc_quote_volume`)

**User Story:**
As a 데이터 과학자,
I want 일별 BTC 거래대금(USDT)이 마스터 데이터셋에 포함되기를,
so that 단순 가격 변동이 아닌 실질 자금 유입 규모를 감성 지표와 함께 분석할 수 있다.

#### Acceptance Criteria

1. WHEN Binance Spot klines 데이터를 수집할 때, THE 수집기 SHALL Requirement 1.3에 명시된 대로 `btc_quote_volume`(quote asset volume, 인덱스 7)을 `float64`로 추출해야 한다

2. WHEN 마스터 DataFrame을 결합할 때, THE 결합기(`join.py`) SHALL `btc_quote_volume` 컬럼을 BTC returns DataFrame과 함께 inner join에 포함해야 한다. Binance 폴백 경로(CoinGecko/yfinance)로 수집된 경우 해당 컬럼은 `NaN`으로 채운다

3. WHEN 마스터 DataFrame의 스키마를 검증할 때, THE 검증기(`validate.py`) SHALL `btc_quote_volume` 컬럼을 `float64`, nullable=True 조건으로 `MASTER_SCHEMA`에 추가해야 한다

4. WHEN `btc_quote_volume`이 통계 검정 대상 컬럼에 포함될 때, THE 파이프라인 SHALL 이 컬럼에 대해서도 ADF 정상성 검정을 수행할 수 있도록 데이터 타입이 `float64`로 일관되게 유지해야 한다

---

### Requirement 3: Long/Short Ratio 추가 (`btc_long_short_ratio`)

**User Story:**
As a 데이터 과학자,
I want 바이낸스 선물 시장의 Long/Short Ratio가 마스터 데이터셋에 포함되기를,
so that 레버리지 포지션 분포가 뉴스 감성 변화에 선행하는지 Granger 검정으로 확인할 수 있다.

#### Acceptance Criteria

1. WHEN Long/Short Ratio를 수집할 때, THE 수집기(`futures.py`) SHALL `GET https://fapi.binance.com/futures/data/globalLongShortAccountRatio` 엔드포인트에 `symbol=BTCUSDT`, `period=1d`, `startTime={unix_ms}`, `limit=500` 파라미터로 요청해야 한다 (Binance 문서 기준 최대 limit=500)

2. WHEN Long/Short Ratio 응답을 파싱할 때, THE 수집기 SHALL 각 항목의 `timestamp`(해당 기간의 open_time, UTC 자정 ms 타임스탬프) 기준 UTC 날짜를 키로, `longShortRatio` 필드(`str → float 변환`)를 `float64` 값으로 추출하여 `{"date": str, "btc_long_short_ratio": float64}` 구조로 변환해야 한다. 실측 응답 구조: `{"symbol": str, "longAccount": str, "longShortRatio": str, "shortAccount": str, "timestamp": int}`. 수집기는 `longShortRatio` 필드만 사용하고 `longAccount`·`shortAccount`는 무시한다

3. WHEN Long/Short Ratio API 호출이 실패할 때, THE 수집기 SHALL 기존 `fetch_futures_data()` 폴백 패턴과 동일하게 `WARNING` 로그를 출력하고 해당 날짜의 `btc_long_short_ratio`를 `NaN`으로 채운 뒤 계속 진행해야 한다. Long/Short 수집 실패가 펀딩비·미결제약정 수집을 중단시키지 않아야 한다

4. WHEN `fetch_futures_data()`가 DataFrame을 반환할 때, THE 수집기 SHALL 반환 컬럼에 `btc_long_short_ratio` (float64, nullable)를 포함해야 한다

5. WHEN 마스터 DataFrame의 스키마를 검증할 때, THE 검증기(`validate.py`) SHALL `btc_long_short_ratio` 컬럼을 `float64`, nullable=True, 값 범위 ≥0 조건으로 `MASTER_SCHEMA`에 추가해야 한다

6. WHEN `join.py`의 `_add_futures_lag_columns()`를 실행할 때, THE 결합기 SHALL `btc_long_short_ratio`에 대해서도 `btc_long_short_ratio_lag1` Lag-1 컬럼을 추가해야 하며, 해당 컬럼도 `MASTER_SCHEMA`에 포함되어야 한다

---

### Requirement 4: 이상값 탐지 범위 확장

**User Story:**
As a 데이터 과학자,
I want 선물 시장 파생 지표에도 이상값 탐지가 적용되기를,
so that 펀딩비·미결제약정·Long/Short 비율의 극단값이 플래그 처리되어 통계 분석 결과를 왜곡하지 않는다.

#### Acceptance Criteria

1. WHEN `join.py`의 `detect_outliers_rolling_iqr()` 호출 시, THE 결합기 SHALL 이상값 탐지 대상 컬럼을 현재의 `["btc_return", "usdkrw_return"]`에서 `["btc_return", "usdkrw_return", "funding_rate", "open_interest_usd", "btc_long_short_ratio"]`로 확장해야 한다

2. WHEN 이상값이 탐지될 때, THE 결합기 SHALL 기존과 동일하게 해당 행의 `is_outlier` 컬럼을 `True`로 설정하고 `WARNING` 레벨 구조화 로그(`event=outlier.detected | date | column | value | threshold`)를 출력해야 한다. 이상값 행은 제거하지 않고 플래그만 설정한다

3. WHEN `NaN` 값이 있는 컬럼에 이상값 탐지를 적용할 때, THE 탐지기 SHALL `NaN` 값을 가진 행은 이상값 판정 대상에서 제외하고 `is_outlier=False`로 처리해야 한다 (기존 `series.notna()` 조건이 이미 이를 처리하므로 로직 변경 불필요, 컬럼 목록 확장만 수행)

---

### Requirement 5: 환경변수 및 설정 확장

**User Story:**
As a 데이터 엔지니어,
I want 바이낸스 API Key가 환경변수로 안전하게 관리되기를,
so that 자격증명이 코드에 노출되지 않고 Rate Limit 상향 혜택을 받을 수 있다.

#### Acceptance Criteria

1. WHEN `SentimentJoinSettings`를 로드할 때, THE 설정 모듈(`config.py`) SHALL `binance_api_key: str` 필드를 추가해야 하며, 이는 `SENTIMENT_JOIN_BINANCE_KEY` 환경변수에서 읽어야 한다. 환경변수가 없으면 빈 문자열(`""`)을 기본값으로 사용하며, 미설정 시에도 공개 엔드포인트를 통해 수집이 진행되어야 한다

2. WHEN `SENTIMENT_JOIN_BINANCE_KEY` 환경변수가 설정되어 있을 때, THE 수집기 SHALL API 키 값을 로그에 출력하거나 예외 메시지에 포함시키지 않아야 한다

3. WHEN `pipeline.py`에서 설정을 수집기에 전달할 때, THE 파이프라인 SHALL `settings.binance_api_key`를 `binance.py`의 수집 함수에 전달해야 한다

---

### Requirement 6: 소스 메타데이터 추적

**User Story:**
As a 데이터 엔지니어,
I want Parquet 파일에 BTC 현물 데이터 소스 이력이 기록되기를,
so that 분석 시 어느 소스로 수집된 데이터인지 역추적할 수 있다.

#### Acceptance Criteria

1. WHEN Binance Spot API로 BTC 종가를 수집할 때, THE 수집기 SHALL 반환 DataFrame의 `attrs["btc_source"]`를 `"binance"`로 설정해야 한다

2. WHEN 폴백 경로(CoinGecko 또는 yfinance)로 수집할 때, THE 수집기 SHALL `attrs["btc_source"]`를 각각 `"coingecko"` 또는 `"yfinance"`로 설정해야 한다

3. WHEN Parquet 파일을 저장할 때(`storage.py`), THE 파이프라인 SHALL Parquet custom metadata(`pandas_metadata` 또는 별도 key)에 `btc_source` 값을 포함하여 데이터 소스 이력을 파일에 기록해야 한다

---

## Non-Functional Requirements

### Requirement 7: Rate Limit 준수

**User Story:**
As a 데이터 엔지니어,
I want 바이낸스 API Rate Limit을 초과하지 않기를,
so that 수집 중 IP 차단(HTTP 418/429)이 발생하지 않는다.

#### Acceptance Criteria

1. WHEN 바이낸스 Spot API를 호출할 때, THE 수집기 SHALL `get_list_with_retry()` 래퍼(klines·fundingRate 등 list 응답 전용, `get_json_with_retry()`의 dict 검사와 별도)를 사용하여 `429/5xx/timeout`에 대해 최대 3회 지수 백오프 재시도를 적용해야 한다. `404`는 재시도하지 않는다. `get_list_with_retry()`는 `http_client.py`에 신규 추가되며 기존 `get_json_with_retry()`는 변경하지 않는다

2. WHEN 여러 바이낸스 엔드포인트(Spot klines, Futures funding rate, OI, Long/Short ratio)를 순차 호출할 때, THE 수집기 SHALL 각 호출 사이에 최소 100ms의 지연을 적용하여 분당 가중치 한도(기본 1200 weight/min)를 초과하지 않아야 한다

3. WHEN HTTP 418 응답을 수신할 때, THE 수집기 SHALL `ERROR` 레벨 로그를 출력하고 재시도 없이 즉시 폴백 경로로 전환해야 한다 (IP 차단 상태에서 재시도 금지)

---

### Requirement 8: 하방 호환성 (Parquet 스키마)

**User Story:**
As a 데이터 엔지니어,
I want 기존 Parquet 파일의 분석 코드가 신규 컬럼 추가 후에도 동작하기를,
so that 스키마 변경이 기존 분석 노트북을 깨트리지 않는다.

#### Acceptance Criteria

1. WHEN `validate.py`의 `MASTER_SCHEMA`에 신규 컬럼을 추가할 때, THE 검증기 SHALL 신규 컬럼을 모두 `nullable=True`로 정의해야 한다. 기존 컬럼의 nullable·범위 조건은 변경하지 않는다

2. WHEN 신규 수집 모듈(`binance.py`) 장애로 신규 컬럼 전체가 `NaN`이 되었을 때, THE 파이프라인 SHALL 스키마 검증을 통과하고 Parquet 파일을 정상 저장해야 한다

---

## 컬럼 추가 요약

마이그레이션 완료 후 마스터 DataFrame에 추가되는 컬럼:

| 컬럼명 | 타입 | nullable | 출처 | 비고 |
|--------|------|----------|------|------|
| `btc_quote_volume` | float64 | Yes | Binance Spot klines[7] | 폴백 시 NaN |
| `btc_long_short_ratio` | float64 | Yes | Binance Futures `globalLongShortAccountRatio` | 수집 실패 시 NaN |
| `btc_long_short_ratio_lag1` | float64 | Yes | `btc_long_short_ratio.shift(1)` | 미래 오염 방지 |

기존 컬럼(`funding_rate`, `open_interest_usd`, `funding_rate_lag1`, `oi_change_pct_lag1`, `hybrid_index`)은 이미 스키마에 정의되어 있으며 변경 없음.

---

## 구현 대상 파일

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `sources/binance.py` | **신규** | BTC Spot klines 수집 (`close`, `btc_quote_volume`), Binance API Key 헤더 처리 |
| `sources/futures.py` | **수정** | Long/Short Ratio 수집 추가, 반환 DataFrame에 `btc_long_short_ratio` 포함 |
| `join.py` | **수정** | 이상값 탐지 컬럼 목록 확장, `_add_futures_lag_columns()`에 `btc_long_short_ratio_lag1` 추가 |
| `validate.py` | **수정** | `MASTER_SCHEMA`에 3개 신규 컬럼 추가 |
| `config.py` | **수정** | `SentimentJoinSettings`에 `binance_api_key` 필드 추가 |
| `pipeline.py` | **수정** | `fetch_btc_close()` 호출을 `fetch_btc_close_binance()` 로 교체, `btc_source` 메타데이터 전달 |
| `storage.py` | **수정** | Parquet custom metadata에 `btc_source` 기록 |
