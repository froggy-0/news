# Sentiment Time Join — 데이터 사전

이 문서는 Sentiment Time Join 파이프라인이 수집·변환·결합하는 데이터의 흐름과 최종 Parquet 스키마를 정리합니다.

## 파이프라인 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│                         소스 수집 (Phase 1)                          │
│                                                                     │
│  R2 브리핑 JSON ──→ [date, news_sentiment_mean, std, n_articles]    │
│  alternative.me ──→ [date, fng_value]                               │
│  CoinGecko/yf   ──→ [date, close]  (BTC-USD)                       │
│  KIS/yf         ──→ [date, close]  (USD/KRW)                       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                       변환·정제 (Phase 2)                            │
│                                                                     │
│  normalize_dates()        날짜 → "YYYY-MM-DD" 통일                  │
│  forward_fill_prices()    가격 결측 ffill (최대 2일)                  │
│  compute_returns()        close → log_return + return (close 삭제)  │
│  trim_to_date_range()     수익률 계산용 extra row 제거               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                     결합·이상값 탐지 (Phase 3)                       │
│                                                                     │
│  merge_sources()          4개 소스 inner join on date               │
│  detect_outliers()        롤링 IQR → is_outlier 플래그              │
│  validate_master()        pandera 스키마 검증 (strict)              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                        저장·업로드 (Phase 4)                         │
│                                                                     │
│  로컬: data/sentiment_join/master_YYYYMMDD.parquet (snappy)         │
│  R2:   {R2_PUBLIC_BUCKET}/sentiment_join/master_YYYYMMDD.parquet    │
└─────────────────────────────────────────────────────────────────────┘
```

## 소스별 수집 상세

### 1. R2 뉴스 감성 점수

| 항목 | 내용 |
|------|------|
| 엔드포인트 | `{R2_PUBLIC_BUCKET}/briefs/{YYYY-MM-DD}.json` (public HTTP GET) |
| 파싱 경로 | `meta.newsSentiment.{mean, std, count}`, `meta.sentimentStatus` |
| 병렬 수집 | `ThreadPoolExecutor(max_workers=R2_MAX_CONCURRENCY)` |
| 재시도 | 429/5xx/timeout → 3회, 404 → NaN (재시도 없음) |
| NaN 조건 | `sentimentStatus=skipped`, `mean=null`, 404, 전체 실패 |
| 출력 컬럼 | `date(str)`, `news_sentiment_mean(float)`, `news_sentiment_std(float)`, `n_articles(Int64)` |

### 2. Fear & Greed Index

| 항목 | 내용 |
|------|------|
| 엔드포인트 | `https://api.alternative.me/fng/?limit={lookback_days+7}&date_format=us` |
| 재시도 | 3회 (`get_json_with_retry`) |
| 날짜 변환 | `MM/DD/YYYY` → `YYYY-MM-DD` |
| 값 변환 | `"75"` (string) → `75` (Int64), 파싱 실패 시 NaN |
| 출력 컬럼 | `date(str)`, `fng_value(Int64)` |

### 3. BTC 일별 종가

| 항목 | 내용 |
|------|------|
| 1차 소스 | CoinGecko `/api/v3/coins/bitcoin/market_chart/range` (단일 요청) |
| 2차 fallback | yfinance `BTC-USD` |
| 리샘플링 | ≤90일 범위: 시간별 → 일별 (마지막 값 = 종가), >90일: 일별 그대로 |
| 수익률 계산 | `compute_returns("close")` → `btc_log_return`, `btc_return` (close 삭제) |
| extra row | `start_date - 1일`부터 수집 → 수익률 계산 후 `trim_to_date_range()`로 제거 |
| 출력 컬럼 | `date(str)`, `btc_log_return(float)`, `btc_return(float)` |

### 4. USD/KRW 일별 종가

| 항목 | 내용 |
|------|------|
| 1차 소스 | KIS `FHKST03030100` TR ID (`FX@KRW`) |
| 2차 fallback | yfinance `KRW=X` |
| KIS 미설정 | `KIS_APP_KEY` 빈 문자열 → 즉시 yfinance 전환 |
| 수익률 계산 | `compute_returns("close")` → `usdkrw_log_return`, `usdkrw_return` (close 삭제) |
| 출력 컬럼 | `date(str)`, `usdkrw_log_return(float)`, `usdkrw_return(float)` |

## 변환 규칙

| 함수 | 입력 | 출력 | 규칙 |
|------|------|------|------|
| `normalize_dates` | 타임존 포함 datetime 또는 string | `"YYYY-MM-DD"` string | UTC 변환 후 포맷 통일 |
| `forward_fill_prices` | 가격 컬럼에 NaN 포함 | NaN 채움 + fill 횟수 | `ffill(limit=2)`, 3일 이상 연속 결측은 NaN 유지 |
| `compute_returns` | `close` 컬럼 | `log_return` + `return` | `ln(close/close.shift(1))`, `pct_change()`, close ≤ 0 → NaN, 첫 행 NaN |
| `trim_to_date_range` | extra row 포함 DataFrame | 범위 내 행만 | `date >= start_date` 필터 |

## 결합 규칙

- join 전 `news_sentiment_mean`이 NaN인 행은 제거 (WARNING 로그)
- 4개 소스를 `date` 기준 **inner join** 순차 실행
- 결합 후 `btc_return`, `usdkrw_return`에 롤링 IQR 이상값 탐지 적용
  - `window=30`, `iqr_multiplier=3.0`, `min_periods=15`
  - cold start 구간 (15행 미만): `is_outlier=False`
- 결합 후 행수 < 30: WARNING 로그

## 최종 Parquet 스키마 (strict)

| 컬럼 | dtype | nullable | 범위/제약 | 설명 |
|------|-------|----------|-----------|------|
| `date` | `str` | No | `YYYY-MM-DD`, unique | 기준 날짜 |
| `news_sentiment_mean` | `float64` | No | -1.0 ~ 1.0 | FinBERT 뉴스 감성 평균 |
| `news_sentiment_std` | `float64` | Yes | ≥ 0 | FinBERT 뉴스 감성 표준편차 |
| `n_articles` | `Int64` | Yes | ≥ 0 | 감성 분석 대상 기사 수 |
| `fng_value` | `Int64` | Yes | 0 ~ 100 | Fear & Greed Index (0=극도 공포, 100=극도 탐욕) |
| `btc_log_return` | `float64` | Yes | — | BTC 일별 로그수익률 |
| `btc_return` | `float64` | Yes | — | BTC 일별 단순수익률 |
| `usdkrw_log_return` | `float64` | Yes | — | USD/KRW 일별 로그수익률 |
| `usdkrw_return` | `float64` | Yes | — | USD/KRW 일별 단순수익률 |
| `is_outlier` | `bool` | No | — | 롤링 IQR 이상값 플래그 |

- `strict=True`: 위 10개 컬럼 외 여분 컬럼이 있으면 검증 실패
- `n_articles`, `fng_value`는 반드시 pandas `Int64Dtype()` (nullable integer)
- Parquet 압축: snappy

## Parquet 메타데이터

| 키 | 타입 | 설명 |
|----|------|------|
| `ffill_days` | `bytes` (문자열 인코딩) | `forward_fill_prices()`로 채운 총 행 수 |

## 저장 경로

| 위치 | 경로 | 비고 |
|------|------|------|
| 로컬 | `{SENTIMENT_JOIN_OUTPUT_DIR}/master_{YYYYMMDD}.parquet` | 기본값: `data/sentiment_join/` |
| R2 | `{R2_PUBLIC_BUCKET}/sentiment_join/master_{YYYYMMDD}.parquet` | public 접근 가능 |

- 동일 날짜 파일은 덮어씀 (idempotent)
- `SENTIMENT_JOIN_RETAIN_DAYS` 초과 로컬 파일은 자동 삭제 (기본 30일)
- R2 업로드 실패 시 파이프라인은 중단하지 않음 (WARNING 로그, degraded 처리)

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SENTIMENT_JOIN_LOOKBACK_DAYS` | `180` | 수집 기간 (30~730) |
| `SENTIMENT_JOIN_OUTPUT_DIR` | `data/sentiment_join` | 로컬 출력 디렉토리 |
| `SENTIMENT_JOIN_R2_MAX_CONCURRENCY` | `10` | R2 병렬 수집 스레드 수 (1~64) |
| `SENTIMENT_JOIN_RETAIN_DAYS` | `30` | 로컬 파일 보존 기간 (0=삭제 안 함) |
| `R2_PUBLIC_BUCKET` | — | R2 public 버킷 URL (기존 파이프라인과 공유) |
| `R2_S3_ENDPOINT` | — | R2 S3 호환 엔드포인트 (빈 문자열이면 업로드 건너뜀) |
| `R2_ACCESS_KEY_ID` | — | R2 접근 키 |
| `R2_SECRET_ACCESS_KEY` | — | R2 비밀 키 |
| `KIS_APP_KEY` | — | 한국투자증권 API 키 (빈 문자열이면 yfinance 전환) |
| `KIS_APP_SECRET` | — | 한국투자증권 API 시크릿 |

## 실행

```bash
make sentiment-join
# 또는
python scripts/build_sentiment_join.py
```

종료 코드: `0`=성공, `1`=실패 (빈 결과, 스키마 검증 실패 등)
