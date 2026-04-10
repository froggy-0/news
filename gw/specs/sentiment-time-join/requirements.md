# Requirements Document

## Introduction

현재 모닝 브리핑 파이프라인은 FinBERT 감성 점수(`sentiment_score`, -1.0~1.0)를 뉴스 항목별로 산출하여 R2에 저장하고, Fear & Greed Index와 BTC 가격은 별도로 수집한다. 그러나 이 세 데이터 소스는 날짜 기준으로 결합된 적이 없어, 감성-가격 간 상관·인과 분석을 수행할 수 없다. **Sentiment Time Join 파이프라인**은 R2의 뉴스 감성 점수, Alternative.me Fear & Greed Index, BTC 일별 로그 수익률, USD/KRW 환율을 날짜 키로 병합한 마스터 데이터프레임을 로컬 Parquet 파일로 생성한다. 기존 모닝 브리핑 파이프라인과 완전히 독립된 분석용 배치로 동작하며, Granger 인과성 검정 등 정량적 시계열 분석의 입력 데이터셋으로 활용된다.

---

## Glossary

- **lookback**: 파이프라인 실행 기준일로부터 과거로 수집할 일수 (기본 180일)
- **마스터 데이터프레임**: 4개 소스를 날짜 키로 inner join한 최종 분석 데이터셋
- **로그 수익률**: `ln(P_t / P_{t-1})` — Granger 인과성 검정 등 정상성(stationarity) 가정 모델에 적합
- **단순 수익률**: `(P_t - P_{t-1}) / P_{t-1}` — 직관적 해석 용도로 병렬 저장
- **is_outlier**: 롤링 IQR 기반 이상값 플래그 — 제거하지 않고 분석 시 필터링 옵션 제공
- **n_articles**: 해당 날짜의 감성 점수 산출에 사용된 뉴스 기사 수 — 감성 평균의 신뢰도 가중치로 활용
- **sentimentStatus**: R2 brief JSON의 `meta.sentimentStatus` 필드 (`ok` / `skipped` / `degraded`)
- **idempotency**: 동일 날 재실행 시 동일한 출력 파일을 덮어쓰며, 중복 파일을 생성하지 않는 성질

---

## Requirements

### Requirement 1: 파이프라인 독립성

**User Story:**
As a 데이터 분석가,
I want Sentiment Time Join 파이프라인이 기존 모닝 브리핑 파이프라인과 완전히 독립적으로 실행되기를,
so that 분석 배치 장애가 운영 브리핑 발송에 영향을 주지 않는다.

#### Acceptance Criteria

1. WHEN Sentiment Time Join 파이프라인이 실행될 때, THE 파이프라인 SHALL `pipeline.py`·`run_pipeline()`·`main.py`의 코드·설정·스케줄을 수정하지 않아야 한다
2. WHEN Sentiment Time Join 파이프라인이 예외로 종료될 때, THE 파이프라인 SHALL 예외를 내부에서 포착하고 비-0 종료 코드로만 전달하며, 모닝 브리핑 파이프라인의 동작을 중단시키지 않아야 한다
3. WHEN 파이프라인을 실행할 때, THE 파이프라인 SHALL 단독 진입점(`scripts/build_sentiment_join.py` 또는 동등한 스크립트)으로 실행 가능하며, `main.py`·`pipeline.py`를 import하지 않아야 한다

---

### Requirement 2: R2 뉴스 감성 점수 수집

**User Story:**
As a 데이터 엔지니어,
I want R2에서 일별 감성 집계값과 기사 수를 함께 수집하기를,
so that 감성 평균의 통계적 신뢰도(n_articles)를 분석에 활용할 수 있다.

#### Acceptance Criteria

1. WHEN R2에서 뉴스 감성 점수를 수집할 때, THE 수집기 SHALL R2 공개 버킷의 `briefs/{YYYY-MM-DD}.json`에서 `meta.newsSentiment.mean`, `meta.newsSentiment.std`, `meta.newsSentiment.count` 필드를 읽어야 한다 (`count`는 감성 산출에 사용된 기사 수, `n_articles` 컬럼으로 저장)
2. WHEN lookback 범위(기본 180일) 내 특정 날짜의 brief JSON이 R2에 존재하지 않을 때, THE 수집기 SHALL 해당 날짜를 결측으로 처리하고 파이프라인 전체를 중단하지 않아야 한다
3. WHEN `meta.newsSentiment.mean`이 `null`이거나 `meta.sentimentStatus`가 `"skipped"`일 때, THE 수집기 SHALL 해당 날짜의 `news_sentiment_mean`, `news_sentiment_std`, `n_articles`를 `NaN`으로 설정해야 한다
4. WHEN R2 접근이 전체 실패할 때, THE 수집기 SHALL `WARNING` 로그(`event=source.failed | source=r2 | reason`)를 출력하고 `news_sentiment_mean`·`news_sentiment_std`·`n_articles` 컬럼 전체를 `NaN`으로 채운 상태로 이후 소스 수집을 계속해야 한다
5. WHEN R2에서 brief JSON을 병렬 요청으로 수집할 때, THE 수집기 SHALL 최대 동시 요청 수를 환경변수 `SENTIMENT_JOIN_R2_MAX_CONCURRENCY`(기본값: `10`)로 제한해야 한다

---

### Requirement 3: Fear & Greed Index 수집

**User Story:**
As a 데이터 엔지니어,
I want Alternative.me FNG 데이터를 안정적으로 수집하기를,
so that 시장 심리 지수가 감성-가격 분석에 포함된다.

#### Acceptance Criteria

1. WHEN Fear & Greed Index를 수집할 때, THE 수집기 SHALL Alternative.me historical endpoint(`https://api.alternative.me/fng/?limit=N&date_format=us`)를 호출하여 lookback 범위에 해당하는 일별 FNG 값을 수집해야 한다. `limit` 파라미터는 lookback 일수에 여유분 7일을 더한 값을 전달해야 한다
2. WHEN Alternative.me API 호출이 실패하거나 응답이 비어 있을 때, THE 수집기 SHALL `fng_value` 컬럼 전체를 `NaN`으로 채우고 `WARNING` 로그를 출력한 뒤 계속해야 한다. `404`는 재시도하지 않으며, `429/5xx/timeout`은 최대 3회 지수 백오프로 재시도한다
3. WHEN FNG 응답의 날짜 형식이 `MM/DD/YYYY`(date_format=us)로 수신될 때, THE 수집기 SHALL 파싱 후 UTC 기준 `YYYY-MM-DD` string으로 변환해야 한다

---

### Requirement 4: BTC 일별 수익률 수집

**User Story:**
As a 데이터 과학자,
I want BTC 일별 로그 수익률과 단순 수익률을 모두 저장하기를,
so that Granger 인과성 검정(로그 수익률 기반)과 직관적 해석(단순 수익률 기반)을 동시에 지원한다.

#### Acceptance Criteria

1. WHEN BTC 일별 종가를 수집할 때, THE 수집기 SHALL CoinGecko `market_chart` endpoint를 1차 소스로 사용하여 lookback 범위의 일별 종가(USD)를 수집해야 한다. 수익률 계산을 위해 lookback 시작일보다 1일 앞선 날짜까지 수집해야 한다
2. WHEN CoinGecko 호출이 실패할 때, THE 수집기 SHALL yfinance `BTC-USD`를 fallback으로 사용해야 한다. 두 소스 모두 실패할 때 `btc_log_return`·`btc_return` 컬럼 전체를 `NaN`으로 채우고 `WARNING`을 출력한 뒤 계속해야 한다
3. WHEN BTC 종가 데이터가 수집될 때, THE 수집기 SHALL 다음 두 수익률을 모두 계산하여 저장해야 한다:
   - `btc_log_return`: `ln(close_t / close_{t-1})` — 정상성 가정 모델(Granger 검정 등) 입력용
   - `btc_return`: `(close_t - close_{t-1}) / close_{t-1}` — 직관적 해석 및 이상값 탐지용

---

### Requirement 5: USD/KRW 환율 수집

**User Story:**
As a 데이터 엔지니어,
I want USD/KRW 환율 수익률을 BTC와 동일한 방식으로 수집하기를,
so that 원화 환율 변동이 국내 투자 심리에 미치는 영향을 분석할 수 있다.

#### Acceptance Criteria

1. WHEN USD/KRW 환율을 수집할 때, THE 수집기 SHALL KIS `FHKST03030100` TR ID를 1차 소스로 사용하여 일별 환율을 수집해야 한다
2. WHEN KIS 호출이 실패하거나 자격증명이 없을 때, THE 수집기 SHALL yfinance `KRW=X`를 fallback으로 사용해야 한다. 두 소스 모두 실패할 때 `usdkrw_log_return`·`usdkrw_return` 컬럼 전체를 `NaN`으로 채우고 계속해야 한다
3. WHEN USD/KRW 환율 데이터가 수집될 때, THE 수집기 SHALL Requirement 4.3과 동일한 방식으로 `usdkrw_log_return`(로그 수익률)과 `usdkrw_return`(단순 수익률)을 모두 계산하여 저장해야 한다

---

### Requirement 6: 데이터 정제 (Pre-Join)

**User Story:**
As a 데이터 과학자,
I want 분석 전 데이터가 날짜 기준으로 정규화되고 이상값이 플래그 처리되기를,
so that 통계 분석에 적합한 품질의 데이터셋이 보장된다.

#### Acceptance Criteria

1. WHEN 각 소스의 날짜 컬럼을 처리할 때, THE 정제기 SHALL 모든 날짜를 UTC 기준 `YYYY-MM-DD` string으로 통일해야 한다. 타임존 정보가 있는 경우 UTC로 변환 후 날짜를 추출한다
2. WHEN 가격 데이터(BTC, USD/KRW)에 결측치가 있을 때, THE 정제기 SHALL forward fill을 최대 2일까지 적용해야 한다. 2일을 초과하는 연속 결측은 `NaN`으로 유지하며 임의로 채우지 않아야 한다 (주말/공휴일 gap 허용)
3. WHEN 이상값을 탐지할 때, THE 정제기 SHALL 컬럼별 롤링 30일 IQR 기반 방식을 사용해야 한다: `|value - rolling_median| > 3 × rolling_IQR`인 행의 `is_outlier` 컬럼을 `True`로 설정하고 `WARNING` 레벨 구조화 로그(`event=outlier.detected | date | column | value | threshold`)를 출력해야 한다. 이상값 행은 제거하지 않고 플래그만 설정한다
4. WHEN `news_sentiment_mean`이 `NaN`인 날짜가 있을 때, THE 정제기 SHALL 해당 행을 결합 결과에서 제외해야 한다 (inner join 또는 dropna로 제거). 감성 데이터가 없는 날은 분석 대상으로 포함하지 않는다. 이 동작은 생존 편향 가능성이 있으므로 `WARNING` 로그(`event=rows.dropped | reason=no_sentiment | count`)로 명시해야 한다

---

### Requirement 7: 시간 기준 결합 (Time-based Join)

**User Story:**
As a 데이터 과학자,
I want 4개 소스가 날짜 키로 병합된 마스터 데이터프레임을 얻기를,
so that 단일 데이터셋에서 감성-가격 상관 분석을 수행할 수 있다.

#### Acceptance Criteria

1. WHEN 소스별 데이터프레임을 결합할 때, THE 결합기 SHALL `pd.merge(on='date', how='inner')` 방식으로 날짜 키 기준 inner join을 수행해야 한다. 결합 순서는 뉴스 감성 → FNG → BTC → USD/KRW 순으로 순차 merge한다

2. WHEN 결합이 완료될 때, THE 결합기 SHALL 마스터 데이터프레임이 다음 10개 컬럼을 포함해야 한다:

   | 컬럼명 | 타입 | nullable | 범위 | 출처 |
   |--------|------|----------|------|------|
   | `date` | str (`YYYY-MM-DD`) | No | — | 결합 키 |
   | `news_sentiment_mean` | float64 | No* | -1.0~1.0 | R2 `meta.newsSentiment.mean` |
   | `news_sentiment_std` | float64 | Yes | ≥0 | R2 `meta.newsSentiment.std` |
   | `n_articles` | int64 | Yes | ≥0 | R2 `meta.newsSentiment.count` |
   | `fng_value` | int64 | Yes | 0~100 | Alternative.me |
   | `btc_log_return` | float64 | Yes | — | CoinGecko / yfinance |
   | `btc_return` | float64 | Yes | — | CoinGecko / yfinance |
   | `usdkrw_log_return` | float64 | Yes | — | KIS / yfinance |
   | `usdkrw_return` | float64 | Yes | — | KIS / yfinance |
   | `is_outlier` | bool | No | — | 롤링 IQR 플래그 |

   *`news_sentiment_mean`은 inner join 후 NaN 행 제거로 non-null 보장

3. WHEN 결합 후 행 수가 30 미만일 때, THE 결합기 SHALL `WARNING` 레벨 로그(`event=join.insufficient_rows | rows | min_required=30`)를 출력해야 한다. 파이프라인은 중단하지 않고 계속 실행한다
4. WHEN 결합이 완료될 때, THE 결합기 SHALL 결과를 `{SENTIMENT_JOIN_OUTPUT_DIR}/master_{YYYYMMDD}.parquet` 경로에 snappy 압축 Parquet 형식으로 저장해야 한다. `YYYYMMDD`는 실행 당일 날짜이다
5. WHEN 출력 파일을 저장할 때, THE 파이프라인 SHALL 출력 디렉토리가 없으면 자동 생성해야 한다

---

### Requirement 8: 스키마 유효성 검사

**User Story:**
As a 데이터 엔지니어,
I want 출력 데이터프레임이 저장 전에 스키마·범위 검사를 통과하기를,
so that 후속 분석 코드가 잘못된 타입이나 범위의 데이터를 받지 않는다.

#### Acceptance Criteria

1. WHEN 마스터 데이터프레임을 저장하기 전, THE 파이프라인 SHALL pandera 또는 동등한 스키마 검증 라이브러리로 다음을 검사해야 한다:
   - `date` 컬럼이 `YYYY-MM-DD` 형식이며 중복 없음
   - `news_sentiment_mean` 값이 -1.0~1.0 범위 (non-null)
   - `fng_value` 값이 0~100 범위 (nullable)
   - `n_articles` 값이 ≥0 정수 (nullable)
2. WHEN 스키마 검증이 실패할 때, THE 파이프라인 SHALL `ERROR` 레벨 로그를 출력하고 Parquet 파일을 저장하지 않고 비-0 종료 코드로 종료해야 한다

---

### Requirement 9: Idempotency 및 파일 보존

**User Story:**
As a 데이터 엔지니어,
I want 동일한 날 파이프라인을 재실행해도 중복 파일이 생성되지 않기를,
so that 실패 후 재시도 시 저장소가 오염되지 않는다.

#### Acceptance Criteria

1. WHEN 동일한 날(`YYYYMMDD`) 파이프라인을 재실행할 때, THE 파이프라인 SHALL 기존 `master_{YYYYMMDD}.parquet` 파일을 덮어써야 한다 (append/중복 생성 금지)
2. WHEN `SENTIMENT_JOIN_RETAIN_DAYS` 환경변수가 설정된 경우, THE 파이프라인 SHALL 출력 디렉토리 내 해당 일수보다 오래된 Parquet 파일을 삭제해야 한다. 기본값은 `30`(일)이며, `0`으로 설정 시 삭제하지 않는다

---

### Requirement 10: Lookback 설정

**User Story:**
As a 데이터 분석가,
I want lookback 기간과 출력 경로를 환경변수로 조정하기를,
so that 분석 목적에 따라 유연하게 설정할 수 있다.

#### Acceptance Criteria

1. WHEN 파이프라인을 실행할 때, THE 파이프라인 SHALL lookback 기간을 `SENTIMENT_JOIN_LOOKBACK_DAYS` 환경변수로 설정 가능해야 하며, 기본값은 `180`이어야 한다
2. WHEN `SENTIMENT_JOIN_LOOKBACK_DAYS`가 30 미만 또는 730 초과로 설정될 때, THE 파이프라인 SHALL `ValueError`를 발생시키고 실행을 중단해야 한다
3. WHEN 파이프라인을 실행할 때, THE 파이프라인 SHALL 출력 디렉토리를 `SENTIMENT_JOIN_OUTPUT_DIR` 환경변수로 설정 가능해야 하며, 기본값은 `data/sentiment_join`이어야 한다

---

## Non-Functional Requirements

### Requirement 11: 성능

**User Story:**
As a 데이터 엔지니어,
I want 파이프라인이 60초 내에 완료되기를,
so that 스케줄 실행 시 다음 배치와 충돌하지 않는다.

#### Acceptance Criteria

1. WHEN 파이프라인이 기본 설정(lookback 180일)으로 실행될 때, THE 파이프라인 SHALL 전체 실행 완료 시간이 60초 미만이어야 한다
2. WHEN R2에서 brief JSON을 수집할 때, THE 수집기 SHALL 날짜별 순차 요청 대신 `asyncio` 또는 `ThreadPoolExecutor` 기반 병렬 요청을 사용하여 네트워크 대기 시간을 최소화해야 한다 (최대 동시성: `SENTIMENT_JOIN_R2_MAX_CONCURRENCY`, 기본값 10)

---

### Requirement 12: 소스 장애 허용

**User Story:**
As a 데이터 엔지니어,
I want 개별 소스 장애가 전체 파이프라인을 중단시키지 않기를,
so that 부분적인 데이터셋이라도 분석에 활용할 수 있다.

#### Acceptance Criteria

1. WHEN 개별 데이터 소스 수집이 실패할 때, THE 파이프라인 SHALL 해당 소스의 컬럼만 `NaN`으로 처리하고 파이프라인을 계속 실행해야 한다
2. WHEN 모든 소스 수집이 실패할 때, THE 파이프라인 SHALL 빈 데이터프레임임을 나타내는 `ERROR` 로그를 출력하고 Parquet 파일 생성 없이 비-0 종료 코드로 종료해야 한다 (빈 파일을 저장하지 않는다)

---

### Requirement 13: 옵저버빌리티

**User Story:**
As a 데이터 엔지니어,
I want 파이프라인 실행 상태가 구조화 로그로 기록되기를,
so that 장애 원인을 신속하게 파악할 수 있다.

#### Acceptance Criteria

1. WHEN 결합이 완료될 때, THE 파이프라인 SHALL 다음 필드를 포함한 구조화 로그를 출력해야 한다:
   `event=join.complete | rows | date_range_start | date_range_end | sources_used | outlier_count | dropped_no_sentiment`
2. WHEN 개별 소스 수집이 완료될 때, THE 파이프라인 SHALL `event=source.complete | source | rows | fallback_used` 구조화 로그를 출력해야 한다
3. WHEN fallback 소스가 사용될 때, THE 파이프라인 SHALL `WARNING` 레벨로 `event=fallback.used | source | reason`을 출력해야 한다. 잡음 `DEBUG` 로그는 추가하지 않는다

---

### Requirement 14: R2 업로드 확장성

**User Story:**
As a 데이터 엔지니어,
I want 향후 Parquet 파일을 R2에 업로드할 수 있도록 확장점이 준비되기를,
so that 분석 결과를 팀원이 클라우드에서 직접 접근할 수 있다.

#### Acceptance Criteria

1. WHEN 향후 Parquet 파일을 R2에 업로드하도록 확장할 때, THE 코드 SHALL 업로드 로직이 로컬 저장 로직과 분리된 함수(`upload_to_r2()`)로 구현되어야 한다. 현재 버전에서는 로컬 저장만 구현하며, `upload_to_r2()`는 stub(no-op)으로 남긴다
