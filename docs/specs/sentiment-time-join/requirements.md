# Requirements Document

## Introduction

현재 모닝 브리핑 파이프라인은 FinBERT 감성 점수(`sentiment_score`, -1.0~1.0)를 뉴스 항목별로 산출하여 R2에 저장하고, Fear & Greed Index와 BTC 가격은 별도로 수집한다. 그러나 이 세 데이터 소스는 날짜 기준으로 결합된 적이 없어, 감성-가격 간 상관·인과 분석을 수행할 수 없다. Sentiment Time Join 파이프라인은 R2의 뉴스 감성 점수, Alternative.me Fear & Greed Index, BTC 일별 종가, USD/KRW 환율을 날짜 키로 병합한 마스터 데이터프레임을 로컬 Parquet 파일로 생성한다. 기존 모닝 브리핑 파이프라인과 완전히 독립된 분석용 배치로 동작하며, 향후 통계 분석(Granger 인과성 검정 등)의 입력 데이터셋으로 활용된다.

## Functional Requirements

### 파이프라인 독립성

1.1 WHEN Sentiment Time Join 파이프라인이 실행될 때 THEN 기존 모닝 브리핑 파이프라인(`pipeline.py`, `run_pipeline()`)의 코드·설정·스케줄을 수정하지 않아야 한다. 두 파이프라인은 공유 상태 없이 독립적으로 실행되어야 한다

1.2 WHEN Sentiment Time Join 파이프라인이 실패할 때 THEN 모닝 브리핑 파이프라인의 동작에 영향을 주지 않아야 한다. 예외는 파이프라인 내부에서 포착하고 종료 코드로만 전달한다

1.3 WHEN 파이프라인을 실행할 때 THEN 단독 스크립트(`scripts/build_sentiment_join.py` 또는 동등한 진입점)로 실행 가능해야 하며, 기존 `main.py`·`pipeline.py`에 의존하지 않아야 한다

### R2 뉴스 감성 점수 수집

2.1 WHEN R2에서 뉴스 감성 점수를 수집할 때 THEN 시스템은 R2 공개 버킷의 `briefs/{YYYY-MM-DD}.json`에서 `meta.newsSentiment.mean`과 `meta.newsSentiment.std` 필드를 읽어야 한다. 이 값은 기존 `public_site.py`의 `_compute_sentiment_aggregate()`가 저장한 일별 집계값이다

2.2 WHEN lookback 범위(기본 180일) 내 특정 날짜의 brief JSON이 R2에 존재하지 않을 때 THEN 시스템은 해당 날짜를 결측으로 처리하고 파이프라인 전체를 중단하지 않아야 한다

2.3 WHEN `meta.newsSentiment.mean`이 `null`이거나 `meta.sentimentStatus`가 `"skipped"`일 때 THEN 해당 날짜의 `news_sentiment_mean`·`news_sentiment_std`는 `NaN`으로 설정해야 한다

2.4 WHEN R2 접근이 전체 실패할 때 THEN 시스템은 `WARNING` 로그를 출력하고 `news_sentiment_mean` 컬럼 전체를 `NaN`으로 채운 상태로 이후 소스 수집을 계속해야 한다

### Fear & Greed Index 수집

3.1 WHEN Fear & Greed Index를 수집할 때 THEN 시스템은 Alternative.me historical endpoint(`https://api.alternative.me/fng/?limit=N&date_format=us`)를 호출하여 lookback 범위에 해당하는 일별 FNG 값을 수집해야 한다. `limit` 파라미터는 lookback 일수에 여유분 7일을 더한 값을 전달해야 한다

3.2 WHEN Alternative.me API 호출이 실패하거나 응답이 비어 있을 때 THEN 시스템은 `fng_value` 컬럼 전체를 `NaN`으로 채우고 WARNING 로그를 출력한 뒤 계속해야 한다. `404`는 재시도하지 않는다. `429/5xx/timeout`은 최대 3회, 지수 백오프로 재시도한다

3.3 WHEN FNG 응답의 날짜 형식이 `MM/DD/YYYY`(date_format=us)로 수신될 때 THEN 시스템은 파싱 후 `YYYY-MM-DD` UTC 기준 string으로 변환해야 한다

### BTC 일별 종가 수집

4.1 WHEN BTC 일별 종가를 수집할 때 THEN 시스템은 CoinGecko `market_chart` endpoint를 1차 소스로 사용하여 lookback 범위의 일별 종가(USD)를 수집해야 한다

4.2 WHEN CoinGecko 호출이 실패할 때 THEN 시스템은 yfinance `BTC-USD`를 fallback으로 사용해야 한다. 두 소스 모두 실패할 때 THEN `btc_return` 컬럼 전체를 `NaN`으로 채우고 WARNING을 출력한 뒤 계속해야 한다

4.3 WHEN BTC 종가 데이터가 수집될 때 THEN 시스템은 일일 단순 수익률 `(close_t - close_{t-1}) / close_{t-1}`을 계산하여 `btc_return` 컬럼에 저장해야 한다. 수익률 계산에 필요한 t-1 데이터는 lookback 시작일보다 1일 앞선 날짜까지 수집해야 한다

### USD/KRW 환율 수집

5.1 WHEN USD/KRW 환율을 수집할 때 THEN 시스템은 KIS `FHKST03030100` TR ID를 1차 소스로 사용하여 일별 환율을 수집해야 한다

5.2 WHEN KIS 호출이 실패하거나 자격증명이 없을 때 THEN 시스템은 yfinance `KRW=X`를 fallback으로 사용해야 한다. 두 소스 모두 실패할 때 THEN `usdkrw_return` 컬럼 전체를 `NaN`으로 채우고 계속해야 한다

5.3 WHEN USD/KRW 환율이 수집될 때 THEN 시스템은 BTC 수익률과 동일한 방식으로 일일 단순 수익률을 계산하여 `usdkrw_return` 컬럼에 저장해야 한다

### 데이터 정제 (Pre-Join)

6.1 WHEN 각 소스의 날짜 컬럼을 처리할 때 THEN 시스템은 모든 날짜를 UTC 기준 `YYYY-MM-DD` string으로 통일해야 한다. 타임존 정보가 있는 경우 UTC로 변환 후 날짜를 추출한다

6.2 WHEN 가격 데이터(BTC, USD/KRW)에 결측치가 있을 때 THEN 시스템은 forward fill을 최대 2일까지 적용해야 한다. 2일을 초과하는 연속 결측은 `NaN`으로 유지하며 임의로 채우지 않아야 한다

6.3 WHEN `|btc_return|` 또는 `|usdkrw_return|`이 0.5를 초과할 때 THEN 시스템은 해당 행의 `is_outlier` 컬럼을 `True`로 설정하고 `WARNING` 레벨 구조화 로그(`event=outlier.detected | date | column | value`)를 출력해야 한다. 이상값 행은 제거하지 않고 플래그만 설정한다

6.4 WHEN 뉴스 감성 점수가 없는 날짜가 있을 때 THEN 해당 행은 결합 결과에서 제외해야 한다(`news_sentiment_mean`이 `NaN`인 row는 inner join 또는 dropna로 제거). 뉴스 없는 날은 분석 대상으로 포함하지 않는다

### 시간 기준 결합 (Time-based Join)

7.1 WHEN 소스별 데이터프레임을 결합할 때 THEN 시스템은 `pd.merge(on='date', how='inner')` 방식으로 날짜 키 기준 inner join을 수행해야 한다. 결합 순서는 뉴스 감성 → FNG → BTC → USD/KRW 순으로 순차 merge한다

7.2 WHEN 결합이 완료될 때 THEN 마스터 데이터프레임의 컬럼은 다음 7개여야 한다:

| 컬럼명 | 타입 | 출처 |
|--------|------|------|
| `date` | str (`YYYY-MM-DD`) | 결합 키 |
| `news_sentiment_mean` | float (-1.0~1.0) | R2 `meta.newsSentiment.mean` |
| `news_sentiment_std` | float (≥0) | R2 `meta.newsSentiment.std` |
| `fng_value` | int (0~100) | Alternative.me |
| `btc_return` | float | CoinGecko / yfinance |
| `usdkrw_return` | float | KIS / yfinance |
| `is_outlier` | bool | 이상값 플래그 |

7.3 WHEN 결합 후 행 수가 30 미만일 때 THEN 시스템은 `WARNING` 레벨 로그(`event=join.insufficient_rows | rows | min_required=30`)를 출력해야 한다. 파이프라인은 중단하지 않고 계속 실행한다

7.4 WHEN 결합이 완료될 때 THEN 시스템은 결과를 `data/sentiment_join/master_{YYYYMMDD}.parquet` 경로에 Parquet 형식으로 저장해야 한다. `YYYYMMDD`는 실행 당일 날짜이다

7.5 WHEN 출력 파일을 저장할 때 THEN `data/sentiment_join/` 디렉토리가 없으면 자동 생성해야 한다

### Lookback 설정

8.1 WHEN 파이프라인을 실행할 때 THEN lookback 기간은 환경변수 `SENTIMENT_JOIN_LOOKBACK_DAYS`로 설정 가능해야 하며, 기본값은 `180`이어야 한다

8.2 WHEN `SENTIMENT_JOIN_LOOKBACK_DAYS`가 30 미만 또는 730 초과로 설정될 때 THEN 시스템은 `ValueError`를 발생시키고 실행을 중단해야 한다

## Non-Functional Requirements

### 성능

9.1 WHEN 파이프라인이 기본 설정(lookback 180일)으로 실행될 때 THEN 전체 실행 완료 시간은 60초 미만이어야 한다

9.2 WHEN R2에서 brief JSON을 수집할 때 THEN 날짜별 순차 요청 대신 가능한 경우 병렬 요청을 사용하여 네트워크 대기 시간을 최소화해야 한다

### 소스 장애 허용

10.1 WHEN 개별 데이터 소스 수집이 실패할 때 THEN 해당 소스의 컬럼만 `NaN`으로 처리하고 파이프라인은 계속 실행해야 한다. 단일 소스 실패가 전체 파이프라인을 중단해서는 안 된다

10.2 WHEN 모든 소스 수집이 실패할 때 THEN 시스템은 빈 데이터프레임임을 나타내는 `WARNING`을 출력하고 Parquet 파일 생성 없이 종료해야 한다 (빈 파일을 저장하지 않는다)

### 옵저버빌리티

11.1 WHEN 결합이 완료될 때 THEN 시스템은 다음 필드를 포함한 구조화 로그를 출력해야 한다: `event=join.complete | rows | date_range_start | date_range_end | sources_used | outlier_count`

11.2 WHEN 개별 소스 수집이 완료될 때 THEN 시스템은 `event=source.complete | source | rows | fallback_used` 구조화 로그를 출력해야 한다

11.3 WHEN fallback 소스가 사용될 때 THEN 시스템은 `WARNING` 레벨로 `event=fallback.used | source | reason`을 출력해야 한다. 잡음 `DEBUG` 로그는 추가하지 않는다

### R2 업로드 확장성

12.1 WHEN 향후 Parquet 파일을 R2에 업로드하도록 확장할 때 THEN 업로드 로직은 로컬 저장 로직과 분리된 함수로 구현되어야 한다. 현재 버전에서는 로컬 저장만 구현하며, R2 업로드 함수는 stub으로 남긴다
