# Requirements Document

## Introduction

현재 저장소에는 뉴스 감성 백필 JSON, Binance BTC 시계열 수집, 선물 지표 Lag 처리, ADF/Granger 검정, PCA 기반 하이브리드 지수 계산 기능이 각각 존재한다. 그러나 이 기능들은 "뉴스 감성이 실제 BTC 가격 등락을 선행 설명하는가"라는 최종 분석 질문을 기준으로 하나의 요구사항 문서로 정렬되어 있지 않다. 본 작업은 2024-01-01부터 현재까지의 뉴스 감성 백필과 Binance BTC 시장 데이터를 UTC 날짜 기준으로 결합하고, 최소 180일 이상의 유효 행을 확보한 상태에서 정상성 및 Granger 인과성 검정을 수행하여 분석 가능한 마스터 데이터셋과 재현 가능한 요약 결과를 생성하는 요구사항을 정의한다.

## Glossary

- **뉴스 감성 백필 JSON**: `briefs/{YYYY-MM-DD}.json`에 저장된 `_backfill: true` 마커 포함 감성 집계 파일
- **유효 행**: 뉴스 감성, BTC 수익률, 검정 대상 predictor가 모두 존재하여 통계 분석에 사용할 수 있는 날짜 행
- **로그 수익률**: `ln(close_t / close_{t-1})`
- **Lag-1**: 특정 설명 변수를 하루 뒤 수익률 설명용으로 사용하기 위해 1일 뒤로 밀어 정렬한 컬럼
- **내적 결합 행**: 날짜 기준 inner join 이후 생존한 최종 분석 대상 행
- **하이브리드 지수**: 뉴스 감성, 선물, ETF, 심리 지표를 PCA로 압축한 단일 시장 심리 지수
- **Risk-on/off 라벨**: 하이브리드 지수의 최근 분포 대비 상대적 위치를 바탕으로 부여한 심리 상태 라벨
- **운영 파일 보호**: `_backfill` 마커가 없는 운영 brief JSON을 백필 산출물로 덮어쓰거나 분석 대상에 혼입하지 않는 원칙

## Requirements

### Requirement 1: 분석 목적에 맞는 뉴스 감성 입력 계약

**User Story:**
As a 데이터 분석가,
I want 분석 파이프라인이 백필 뉴스 감성 JSON만 명확하게 식별하여 사용하기를,
so that 운영 파일과 혼동 없이 감성-가격 인과 분석의 입력 무결성을 보장할 수 있다.

#### Acceptance Criteria

1. WHEN 분석 파이프라인이 `briefs/{YYYY-MM-DD}.json`를 읽을 때, THE 수집기 SHALL `meta._backfill == true`인 파일만 백필 감성 입력으로 인정해야 한다
2. IF 대상 JSON에 `_backfill` 마커가 없을 때, THEN THE 수집기 SHALL 해당 날짜를 운영 파일로 간주하고 분석 입력에서 제외해야 한다
3. WHEN 감성 JSON을 파싱할 때, THE 수집기 SHALL 최소한 `meta.date`, `meta.sentimentStatus`, `meta.newsSentiment.mean`, `meta.newsSentiment.std`, `meta.newsSentiment.count`를 읽어야 한다
4. WHEN 감성 입력 수집이 완료될 때, THE 파이프라인 SHALL 전체 대상 날짜 수, 감성 유효 날짜 수, 제외 날짜 수를 로그 또는 리포트에 기록해야 한다

### Requirement 2: 감성 품질 필터와 분석 제외 규칙

**User Story:**
As a 데이터 과학자,
I want 기사 수가 너무 적거나 상태가 불완전한 감성 날짜를 자동으로 제외하기를,
so that 통계 검정이 낮은 신뢰도의 감성 점수에 오염되지 않는다.

#### Acceptance Criteria

1. WHEN `meta.sentimentStatus == "skipped"`일 때, THE 결합기 SHALL 해당 날짜를 유효 감성 행에서 제외해야 한다
2. WHEN `meta.newsSentiment.count <= 1`일 때, THE 결합기 SHALL 해당 날짜를 유효 감성 행에서 제외해야 한다
3. WHEN `meta.sentimentStatus == "degraded"`이고 `meta.newsSentiment.count >= 2`일 때, THE 결합기 SHALL 해당 날짜를 포함할 수 있으나 결과 리포트에 degraded 행 수를 별도로 기록해야 한다
4. IF 감성 평균값이 `null`일 때, THEN THE 결합기 SHALL 해당 날짜를 내적 결합 분석 대상에서 제외해야 한다

### Requirement 3: Binance 현물 시장 데이터 백필

**User Story:**
As a 데이터 엔지니어,
I want 뉴스 백필 범위와 동일한 기간의 Binance BTC 현물 데이터를 연속 시계열로 확보하기를,
so that 뉴스 감성과 실제 시장 등락을 같은 날짜 축에서 정확히 비교할 수 있다.

#### Acceptance Criteria

1. WHEN 시장 데이터 백필을 실행할 때, THE 수집기 SHALL `2024-01-01`부터 실행 시점 현재 UTC 날짜까지의 `BTCUSDT` 일봉 데이터를 수집해야 한다
2. WHEN Binance spot klines를 수집할 때, THE 수집기 SHALL 최소한 종가(`close`)와 거래대금(`quote_volume`)을 함께 수집해야 한다
3. WHEN 조회 범위가 Binance 1,000건 제한을 초과할 때, THE 수집기 SHALL 수정된 페이지네이션 로직을 사용하여 연속 구간 호출로 전체 시계열을 확보해야 한다
4. IF 일부 구간 호출이 실패할 때, THEN THE 수집기 SHALL 수집 가능한 구간은 계속 확보하고 최종 리포트에 누락 날짜 수를 기록해야 한다

### Requirement 4: 가격 방향성 라벨과 수익률 변환

**User Story:**
As a 데이터 분석가,
I want BTC 가격이 실제로 상승했는지 하락했는지를 감성 점수와 나란히 비교할 수 있기를,
so that 감성 점수의 해석이 단순 점수 저장을 넘어 실제 시장 방향 검증으로 이어진다.

#### Acceptance Criteria

1. WHEN BTC 종가 시계열을 변환할 때, THE 변환기 SHALL `btc_log_return = ln(close_t / close_{t-1})`를 계산해야 한다
2. WHEN BTC 종가 시계열을 변환할 때, THE 변환기 SHALL 해석용 컬럼으로 단순 수익률 또는 동등한 방향성 컬럼을 함께 생성해야 한다
3. WHEN 실제 등락 라벨을 생성할 때, THE 변환기 SHALL `btc_log_return > 0`이면 상승, `< 0`이면 하락, `== 0`이면 보합으로 판정할 수 있는 표현을 데이터셋에 포함해야 한다
4. WHEN 최종 Parquet를 저장할 때, THE 저장기 SHALL 뉴스 감성 점수와 실제 BTC 등락 판단값이 같은 행에 나란히 존재하도록 보장해야 한다

### Requirement 5: UTC 날짜 기준 결합

**User Story:**
As a 데이터 엔지니어,
I want 뉴스 감성과 시장 데이터를 UTC 날짜 기준으로 결합하기를,
so that 시차나 일자 경계 차이로 인한 잘못된 매칭을 방지할 수 있다.

#### Acceptance Criteria

1. WHEN 감성 JSON과 Binance 현물 데이터를 결합할 때, THE 결합기 SHALL UTC `YYYY-MM-DD` 기준 날짜 키로 병합해야 한다
2. WHEN 결합 대상 데이터프레임의 날짜 형식이 다를 때, THE 정규화 단계 SHALL 결합 전에 모두 UTC `YYYY-MM-DD` 문자열로 변환해야 한다
3. WHEN 결합이 완료될 때, THE 결합기 SHALL inner join 기준 최종 행 수를 기록해야 한다
4. IF 날짜 파싱 실패 행이 존재할 때, THEN THE 정규화 단계 SHALL 해당 행을 제외하고 제외 건수를 로그에 기록해야 한다

### Requirement 6: 선물 및 보조 지표의 Lag-1 정렬

**User Story:**
As a 데이터 과학자,
I want 선물 및 보조 지표가 하루 지연된 predictor로 정렬되기를,
so that 미래 정보 누설 없이 "어제의 지표가 오늘의 수익률을 설명하는가"를 검정할 수 있다.

#### Acceptance Criteria

1. WHEN 펀딩비, 롱/숏 비율, ETF 순유입 등 보조 지표를 결합할 때, THE 결합기 SHALL 각 지표에 대해 Lag-1 컬럼을 생성해야 한다
2. WHEN Lag-1 컬럼을 생성할 때, THE 결합기 SHALL 당일 predictor 값으로 당일 수익률을 설명하지 않아야 한다
3. WHEN Binance Futures 직접 수집이 실패하거나 리전 제한이 발생할 때, THE 파이프라인 SHALL 한국 리전 Lambda 경유 경로를 사용하여 수집을 계속 시도해야 한다
4. IF 선물 지표를 끝내 확보하지 못할 때, THEN THE 파이프라인 SHALL 가격-감성 분석은 계속 수행하되 선물 predictor 컬럼은 결측으로 유지해야 한다

### Requirement 7: 최소 유효 표본 수 보장

**User Story:**
As a 데이터 분석가,
I want 통계 검정이 의미 있는 표본 수에서만 수행되기를,
so that 작은 표본으로 인한 과도한 해석을 피할 수 있다.

#### Acceptance Criteria

1. WHEN Granger 검정을 수행하기 전, THE 파이프라인 SHALL inner join 이후 유효 행 수가 최소 180일 이상인지 확인해야 한다
2. IF 유효 행 수가 180일 미만일 때, THEN THE 파이프라인 SHALL Granger 검정을 참고용 결과로만 취급하거나 생략하고 부족 사유를 커버리지 리포트에 명시해야 한다
3. WHEN 유효 행 수를 계산할 때, THE 파이프라인 SHALL 감성, BTC 수익률, 각 predictor의 결측 여부를 고려한 실제 검정 투입 행 수를 사용해야 한다
4. WHEN 리포트를 출력할 때, THE 리포터 SHALL 전체 날짜 수와 별도로 검정 가능 유효 날짜 수를 표시해야 한다

### Requirement 8: 정상성 검정과 Granger 인과성 검정

**User Story:**
As a 데이터 과학자,
I want 뉴스 감성의 과거값이 BTC 수익률 예측에 유의미한지 ADF와 Granger 검정으로 확인하기를,
so that 감성의 선행성 주장을 통계적으로 방어할 수 있다.

#### Acceptance Criteria

1. WHEN 정상성 검정을 수행할 때, THE 검정기 SHALL `btc_log_return`과 주요 predictor에 대해 ADF 검정을 수행하고 `p-value < 0.05` 여부를 기록해야 한다
2. WHEN Granger 인과성 검정을 수행할 때, THE 검정기 SHALL 최소한 `news_sentiment_mean -> btc_log_return` 쌍에 대해 lag 1, 2, 3을 평가해야 한다
3. WHEN Granger 검정이 완료될 때, THE 검정기 SHALL predictor, target, lag, p-value, significance 여부를 구조화된 결과로 저장해야 한다
4. IF 하나 이상의 lag에서 `p-value < 0.05`가 관측될 때, THEN THE 결과 리포트 SHALL 뉴스 감성이 BTC 수익률에 대해 통계적으로 유의미한 선행 신호를 보였다고 표시해야 한다

### Requirement 9: 최종 마스터 데이터셋 스키마

**User Story:**
As a 데이터 엔지니어,
I want 최종 분석 산출물이 후속 분석에 바로 사용할 수 있는 일관된 스키마로 저장되기를,
so that 팀원이 별도 전처리 없이 결과를 재사용할 수 있다.

#### Acceptance Criteria

1. WHEN 최종 Parquet를 저장할 때, THE 저장기 SHALL 최소한 `date`, `news_sentiment_mean`, `news_sentiment_std`, `n_articles`, `btc_log_return`, `quote_volume`, 실제 등락 판단 컬럼을 포함해야 한다
2. WHEN 선물 및 보조 지표가 존재할 때, THE 저장기 SHALL Lag-1 predictor 컬럼을 함께 저장해야 한다
3. WHEN 하이브리드 지수를 계산할 수 있을 때, THE 저장기 SHALL `hybrid_index`와 위험 상태 라벨을 포함해야 한다
4. WHEN 최종 산출물을 검증할 때, THE 검증기 SHALL `master_sentiment_join.parquet` 또는 동등한 마스터 파일에 뉴스 점수와 실제 등락이 나란히 존재하는지 확인해야 한다

### Requirement 10: 커버리지 리포트와 무결성 체크리스트

**User Story:**
As a 리서처,
I want 결과물과 함께 데이터 무결성과 통계 검정 가능 여부를 한눈에 확인할 수 있는 리포트를 얻기를,
so that 분석 결과를 과신하지 않고 품질 상태와 함께 해석할 수 있다.

#### Acceptance Criteria

1. WHEN 파이프라인 실행이 끝날 때, THE 리포터 SHALL 전체 날짜 수, 감성 유효 날짜 수, inner join 행 수, Granger 검정 가능 여부를 요약해야 한다
2. WHEN 무결성 체크리스트를 출력할 때, THE 리포터 SHALL `_backfill` 충돌 여부, `skipped` 날짜 제외 여부, Futures Lambda 경유 여부, 최종 Parquet 필수 컬럼 존재 여부를 포함해야 한다
3. IF 검정 입력이 부족하거나 일부 소스가 실패했을 때, THEN THE 리포터 SHALL 해당 제한 사항을 결과 상단에 명시해야 한다
4. WHEN 결과를 저장할 때, THE 파이프라인 SHALL 실행 시각, 입력 범위, 유효 행 수, Granger 요약을 재현 가능한 메타데이터로 함께 남겨야 한다

### Requirement 11: 실패 허용 및 재현 가능한 실행

**User Story:**
As a 시니어 데이터 엔지니어,
I want 개별 소스 실패가 전체 분석을 불필요하게 중단시키지 않으면서도 결과 재현성은 유지되기를,
so that 운영 중 부분 장애가 생겨도 분석 파이프라인을 안정적으로 반복 실행할 수 있다.

#### Acceptance Criteria

1. WHEN 개별 보조 소스가 실패할 때, THE 파이프라인 SHALL 핵심 감성-가격 결합이 가능하면 분석을 계속 수행해야 한다
2. IF 뉴스 감성 입력 또는 BTC 가격 수익률이 전부 비어 있을 때, THEN THE 파이프라인 SHALL 마스터 파일을 저장하지 않고 비-0 종료 코드로 종료해야 한다
3. WHEN 동일 입력 범위로 파이프라인을 재실행할 때, THE 저장기 SHALL 동일 경로의 마스터 파일을 덮어써야 하며 중복 산출물을 생성하지 않아야 한다
4. WHEN 실행 설정을 로드할 때, THE 파이프라인 SHALL lookback, 출력 경로, R2 동시성, Futures Lambda ARN 같은 핵심 설정을 환경변수로 제어 가능하게 해야 한다

