# Sovereign Brief — Sentiment-Join 파이프라인 중간 보고서

> 작성일: 2026-04-16 · 샘플 데이터 기준일: 2026-04-15 run

---

## 1. 데이터 수집

### 1.1 수집 소스 및 파이프라인 구조

sentiment-join 파이프라인(`run_sentiment_join`)은 6개 독립 소스를 수집한 뒤 날짜 기준 inner/left join으로 마스터 테이블을 생성합니다.

| # | 소스 | 함수 | 1차 | 폴백 | 샘플 상태 |
|---|---|---|---|---|---|
| 1 | 뉴스 감성 | `fetch_r2_sentiment` | R2 공개 버킷 (일별 JSON) | — (NaN) | ✅ 1행 수집 |
| 2 | Fear & Greed Index | `fetch_fng` | alternative.me API | — (NaN) | ✅ fng_value=21 |
| 3 | BTC 종가 | `fetch_btc_close_binance` | Binance Spot klines | yfinance `BTC-USD` | ✅ binance |
| 4 | USD/KRW 환율 | `fetch_usdkrw_close` | KIS 해외환율 API | yfinance `KRW=X` | ✅ |
| 5 | 선물 지표 | `fetch_futures_data` | Binance fapi → Lambda 프록시 → Bybit | NaN 컬럼 | ✅ funding_rate 수집 |
| 6 | ETF 보유량 | `fetch_etf_flow_features` | Supabase gold table → latest snapshot | NaN 컬럼 | ❌ 전부 NaN |

### 1.2 수집 기간 설정

| 파라미터 | 값 | 출처 |
|---|---|---|
| `SENTIMENT_JOIN_LOOKBACK_DAYS` | 기본 **180일** (범위: 1–730) | `config.py` `_env_bounded_int` |
| 샘플 실행에서 R2 응답이 있던 날짜 | 약 **31일** | exclusion 29 + invalid 1 + 통과 1 |
| 품질 게이트 통과 | **1일** (2026-04-14) | parquet 1행 |

→ lookback 180일을 시도했으나 R2에 감성 데이터가 적재된 날짜가 약 31일뿐이었고, 그 중 29일은 `_backfill` 마커 부재로 제외되었습니다.

### 1.3 HTTP 재시도 및 장애 격리

모든 외부 호출은 `_request_with_retry`를 거칩니다:
- 기본 재시도: **3회**, 백오프: **1.2초**, 최대 백오프: **12.0초**, 지터: **20%**
- 429 응답 시 `Retry-After` 헤더 파싱 (`respect_retry_after=True`)
- DNS 해석 불가 시 즉시 실패 (불필요한 대기 방지)
- 개별 소스 실패는 NaN으로 채우고 파이프라인은 계속 진행 (graceful degradation)
- 429/연속 실패 시 `open_circuit`으로 해당 provider를 런 내에서 비활성화 (서킷 브레이커)

provider별 정책 (`ProviderPolicy`, `provider_runtime.py`):

| Provider | min_interval | base_backoff | max_backoff | max_attempts |
|---|---|---|---|---|
| `perplexity` | 0.5초 | 1.5초 | 10.0초 | 3 |
| `grok_official` | 0.5초 | 1.5초 | 10.0초 | 3 |
| `grok_keyword` | 0.5초 | 1.5초 | 10.0초 | 3 |
| `coingecko` | 0.25초 | 1.2초 | 12.0초 | 3 |
| `fred` | 0.1초 | 1.0초 | 12.0초 | 3 |
| `kis` | 0.4초 | 1.0초 | 12.0초 | 5 |
| `btc_etf_official` | 0.25초 | 1.0초 | 12.0초 | 3 |

### 1.4 데이터 전처리 흐름

```
수집 → normalize_dates → forward_fill_prices(max_periods=2)
     → compute_returns(log + simple) → merge_sources
     → 감성 품질 게이트 → 롤링 IQR 이상치 탐지
     → validate_master(pandera 스키마) → save_parquet
```

**forward fill**: 가격 결측은 최대 2일까지 전방 보간. 샘플에서 `ffill_days=0` (보간 불필요).

**수익률 계산**: `log_return = ln(close_t / close_{t-1})`, `return = pct_change`

---

## 2. 감성 품질 게이트 및 이상치 탐지

### 2.1 감성 품질 게이트 (`_apply_sentiment_quality_gate`)

merge 이전에 저품질 감성 관측치를 제거합니다:

| 제외 규칙 | 조건 | 샘플 제외 건수 |
|---|---|---|
| `missing_backfill_marker` | `is_backfill_valid=False` + 사유에 "missing_backfill_marker" 포함 | **29** |
| `invalid_contract` | `is_backfill_valid=False` + 기타 사유 | **1** |
| `skipped_sentiment` | `sentiment_status="skipped"` | 0 |
| `insufficient_article_count` | `n_articles ≤ 1` | 0 |
| `no_sentiment` | `news_sentiment_mean`이 NaN | 0 |

→ lookback 기간 중 **30일치 중 29일**이 backfill 마커 부재로 제외되어 최종 **1행**만 남았습니다.

### 2.2 롤링 IQR 이상치 탐지 (`detect_outliers_rolling_iqr`)

| 파라미터 | 값 |
|---|---|
| window | 30 |
| min_periods | 15 |
| iqr_multiplier | 3.0 |
| 대상 컬럼 | `btc_return`, `usdkrw_return`, `funding_rate`, `open_interest_usd`, `btc_long_short_ratio` |

판정: `|value - rolling_median| > 3.0 × rolling_IQR` → `is_outlier=True`

### 2.3 현재 샘플 이상치 통계

| 항목 | 값 |
|---|---|
| 필터 전 행 수 | 1 |
| 필터 후 행 수 | 1 |
| 제거 건수 | 0 |
| 제거 비율 | **0.0%** |

> ⚠️ 1행이므로 롤링 윈도우가 작동하지 않아 이상치 탐지가 무의미합니다. 최소 31행 이상에서 유효합니다.

---

## 3. FinBERT 감성 분석 모델

### 3.1 모델 구성

| 항목 | 값 (코드 기반) |
|---|---|
| 모델 | `ProsusAI/finbert` (`FINBERT_MODEL` 환경변수) |
| 버전 고정 | `FINBERT_MODEL_REVISION` (commit hash, 시계열 연속성 보장) |
| 배치 크기 | 16 (범위: 1–64, `FINBERT_BATCH_SIZE`) |
| 최대 토큰 | 512 (`_MAX_TOTAL_TOKENS`) |
| bullish 임계값 | ≥ 0.3 (`FINBERT_BULLISH_THRESHOLD`) |
| bearish 임계값 | ≤ -0.3 (`FINBERT_BEARISH_THRESHOLD`) |
| 활성화 | `FINBERT_ENABLED=true` (기본값) |

**임계값 설정 근거**: ProsusAI/finbert는 3-class softmax(positive, negative, neutral)를 출력하며, 본 파이프라인은 `score = p_positive - p_negative`로 연속 점수를 산출합니다. ±0.3 임계값은 neutral 확률이 지배적인 구간(약 -0.3~+0.3)을 중립으로 분류하기 위한 실용적 기준입니다. 이 값은 `FINBERT_BULLISH_THRESHOLD` / `FINBERT_BEARISH_THRESHOLD` 환경변수로 조정 가능하나, 현재 임계값의 최적성을 검증한 백테스트 결과는 없습니다.

### 3.2 점수 산출 방식

```python
probs = softmax(model_output.logits)  # [positive, negative, neutral]
score = round(p_positive - p_negative, 4)   # 범위: -1.0 ~ +1.0
confidence = round(max(p_pos, p_neg, p_neu), 4)
label = "bullish" if score >= 0.3 else "bearish" if score <= -0.3 else "neutral"
```

### 3.3 입력 텍스트 구성

`combine_fields(title, summary, why_it_matters)` — 필드별 토큰 제한 (64, 224, 224), 전체 512 토큰 상한.

### 3.4 신뢰도 분석 (샘플 기준)

#### 뉴스 (12건, curated_btc 기준)

| 지표 | 값 |
|---|---|
| mean | 0.2079 |
| median | 0.0391 |
| std | 0.3273 |
| min / max | -0.0037 / 0.9234 |
| bullish 비율 | 25.0% (3/12) |
| bearish 비율 | 0.0% (0/12) |

분포 특성: 대부분 중립(0 근처)에 집중, 0.9 이상 강한 긍정 2건이 평균을 끌어올리는 **오른쪽 꼬리 분포**.

| 구간 | 건수 | 비고 |
|---|---|---|
| 0.90 ~ 1.00 | 2 | 강한 긍정 |
| 0.30 ~ 0.40 | 1 | |
| 0.02 ~ 0.10 | 8 | 중립 근처 |
| -0.01 ~ 0.00 | 1 | 약한 부정 |

#### X 시그널 (8건)

| 지표 | 값 |
|---|---|
| mean | 0.3687 |
| median | 0.8823 |
| std | **0.6980** |
| bullish 비율 | 62.5% |
| bearish 비율 | 25.0% |

→ 시그널은 뉴스보다 **양극화**가 심합니다. 강한 긍정(+0.88~+0.94)과 강한 부정(-0.66, -0.88)이 공존.

#### 카테고리별

| 카테고리 | 평균 | 건수 |
|---|---|---|
| bitcoin | 0.1919 | 8 |
| macro | 0.3126 | 3 |

### 3.5 Confidence 분포 분석 (샘플 기준)

#### 뉴스 confidence (12건)

| 지표 | 값 |
|---|---|
| mean | 0.837 |
| std | 0.174 |
| min / max | 0.365 / 0.948 |
| conf < 0.5 | **1건** (score=-0.0037, conf=0.365) |

→ 12건 중 11건이 confidence ≥ 0.5로 모델이 비교적 확신 있는 예측을 내놓았습니다. 유일한 저신뢰 건(conf=0.365)은 score도 -0.0037로 거의 중립이어서, 모델이 positive/negative/neutral 사이에서 결정하지 못한 경우입니다.

#### X 시그널 confidence (8건)

| 지표 | 값 |
|---|---|
| mean | 0.844 |
| std | 0.138 |
| min / max | 0.587 / 0.954 |
| conf < 0.5 | **0건** |

→ 시그널은 전체적으로 confidence가 높습니다. 다만 이는 짧은 텍스트에서 모델이 극단적 확률을 내놓기 쉬운 특성일 수 있어, 높은 confidence가 곧 높은 정확도를 의미하지는 않습니다.

#### confidence와 score 절대값의 관계

| score 절대값 구간 | 평균 confidence | 건수 |
|---|---|---|
| |score| ≥ 0.5 | 0.912 | 7 |
| 0.1 ≤ |score| < 0.5 | 0.694 | 2 |
| |score| < 0.1 | 0.889 | 11 |

→ 중립 근처(|score|<0.1)에서도 confidence가 높은 이유는 neutral 클래스 확률이 지배적이기 때문입니다. confidence는 "가장 높은 클래스 확률"이므로, neutral이 확실한 경우에도 높게 나옵니다.

### 3.6 모델 신뢰도 한계

> ⚠️ **확인 필요 — 아직 부족한 부분**
>
> 1. **confidence 분포 분석**: 샘플에서 confidence 범위는 0.365~0.954이나, 장기 데이터에서의 분포와 confidence가 낮은 예측의 정확도 검증이 필요합니다.
> 2. **금융 도메인 적합성**: ProsusAI/finbert는 금융 뉴스에 특화되어 있으나, X 시그널(짧은 트윗)에 대한 적합성은 별도 검증이 필요합니다.
> 3. **한국어 뉴스 미적용**: FinBERT는 영문 원본에만 적용됩니다. 한국어 번역본에는 감성 점수가 부여되지 않습니다.

---

## 4. 통계적 인과관계 검증

### 4.1 ADF 정상성 검정

시계열 분석의 전제 조건인 정상성(stationarity)을 Augmented Dickey-Fuller 검정으로 확인합니다.

| 대상 컬럼 | 최소 행 수 | 유의 수준 |
|---|---|---|
| `btc_log_return` | 30 | p < 0.05 |
| `funding_rate` | 30 | p < 0.05 |
| `oi_change_pct_lag1` | 30 | p < 0.05 |
| `btc_long_short_ratio` | 30 | p < 0.05 |
| `etf_net_inflow_usd_lag1` | 30 | p < 0.05 |

> ⚠️ **미실행** — 현재 1행으로 최소 30행 미충족. `adf: {}`

### 4.2 Granger 인과성 검정

#### 검정 설계

| Predictor | Target | Lags | 검정 방법 |
|---|---|---|---|
| `news_sentiment_mean` | `btc_log_return` | 1, 2, 3 | SSR F-test |
| `fng_value` | `btc_log_return` | 1, 2, 3 | SSR F-test |
| `funding_rate_lag1` | `btc_log_return` | 1, 2, 3 | SSR F-test |
| `btc_long_short_ratio_lag1` | `btc_log_return` | 1, 2, 3 | SSR F-test |
| `etf_net_inflow_usd_lag1` | `btc_log_return` | 1, 2, 3 | SSR F-test |

- 최소 행 수: **180행** (약 6개월)
- 유의 수준: p < 0.05
- `statsmodels.tsa.stattools.grangercausalitytests` 사용

#### 시차별 P-value 테이블

> ⚠️ **미실행** — `granger_executed: null`, `granger_results: []`

| Predictor | Lag 1 | Lag 2 | Lag 3 |
|---|---|---|---|
| `news_sentiment_mean` | — | — | — |
| `fng_value` | — | — | — |
| `funding_rate_lag1` | — | — | — |
| `btc_long_short_ratio_lag1` | — | — | — |
| `etf_net_inflow_usd_lag1` | — | — | — |

#### 차트 설계 (데이터 확보 후)

- X축: Lag (1, 2, 3)
- Y축: P-value (log scale 권장)
- 선: predictor별 색상 구분
- 수평 점선: p = 0.05 임계선
- 해석: 임계선 아래 = 해당 시차에서 유의미한 Granger 인과성

#### 뉴스 감성 vs F&G Index 관계

> ⚠️ **구조적 한계**
>
> 현재 `GRANGER_PAIRS`에 `(news_sentiment_mean → fng_value)` 직접 쌍이 **없습니다**.
> 둘 다 `btc_log_return`을 target으로 검정하므로, 두 predictor의 P-value를 나란히 비교하여
> "FinBERT 감성 지표 vs F&G Index의 BTC 수익률 예측력 차이"를 분석할 수 있습니다.
>
> 직접 인과성 검정이 필요하면 `statistical_tests.py`의 `GRANGER_PAIRS`에 추가 필요:
> ```python
> ("news_sentiment_mean", "fng_value"),
> ```

---

## 5. PCA 하이브리드 지수

### 5.1 방법론

1. VIF(분산팽창인자) ≥ 10인 변수 제거
2. StandardScaler 정규화
3. PCA — 누적 설명 분산 ≥ 80% 달성하는 최소 주성분 수 자동 선택
4. 첫 번째 주성분 = `hybrid_index`

후보 변수 (`HYBRID_FEATURE_CANDIDATES`, `hybrid_index.py`):

| # | 변수 |
|---|---|
| 1 | `news_sentiment_mean` |
| 2 | `fng_value` |
| 3 | `funding_rate_lag1` |
| 4 | `btc_long_short_ratio_lag1` |
| 5 | `etf_net_inflow_usd_lag1` |

상수:

| 파라미터 | 값 |
|---|---|
| `VIF_THRESHOLD` | 10.0 |
| `MIN_PCA_FEATURES` | 2 |
| `MIN_PCA_ROWS` | 10 |
| `TARGET_EXPLAINED_VARIANCE` | 0.80 (80%) |

### 5.2 현재 상태

> ⚠️ **미실행** — `status: "insufficient_rows"` (clean data 0행)

---

## 6. API 호출 한도 및 운영 제약

### 6.1 외부 API 호출 현황

| API | 호출 빈도 | 알려진 제한 | 현재 대응 |
|---|---|---|---|
| FRED | 일 1회 (최근 15 관측값) | 일 120회 (API key당) | ✅ 충분 |
| alternative.me (F&G) | 일 1회 | 공개 API, 명시적 제한 없음 | ✅ |
| Binance Spot klines | 일 1회 | IP당 1200 req/min | ✅ 충분 |
| Binance fapi | 일 1회 | US IP 차단 (HTTP 451) | Lambda 프록시 → Bybit 폴백 |
| KIS 해외주식 | 일 수회 | 초당 20건, max_attempts=5 | ✅ provider_retry + min_interval 0.4초 |
| CoinGecko | 일 1회 | 무료 30 req/min, min_interval 0.25초 | ✅ |
| R2 감성 데이터 | 일 lookback_days회 | S3 호환, 제한 없음 | 동시성 10 (설정 가능) |
| Perplexity (Search + Sonar) | 뉴스 수집 시 다수 호출 | 429 시 서킷 브레이커 발동, min_interval 0.5초 | ⚠️ 월간 한도 미문서화 |
| Grok (Official + Keyword + Web) | 뉴스/시그널 수집 시 다수 호출 | 429 시 서킷 브레이커 발동, min_interval 0.5초 | ⚠️ 월간 한도 미문서화 |

> ⚠️ **Perplexity/Grok API 한도 관련**
>
> 코드에는 429 응답 시 `open_circuit`으로 해당 provider를 런 내에서 비활성화하는 서킷 브레이커가 구현되어 있습니다.
> 그러나 **월간/일간 호출 한도 수치**는 코드에 하드코딩되어 있지 않고, 외부 플랜에 의존합니다.
> 현재 사용 중인 플랜의 구체적 한도와 실제 사용량 대비 여유분은 별도 확인이 필요합니다.

### 6.2 장애 격리 설계

```
소스 실패 → NaN 컬럼으로 계속 진행
모든 소스 실패 → return 1 (파이프라인 중단)
통계 검정 실패 → 로그만 남기고 계속 진행
스키마 검증 실패 → 예외 발생, 파이프라인 중단
429/연속 실패 → open_circuit으로 provider 비활성화 (런 내 서킷 브레이커)
```

---

## 7. 시장 데이터 스냅샷 (2026-04-15 기준)

| 지표 | 값 | 변동 | 방향 |
|---|---|---|---|
| 미국 10년물 | 4.26% | -4bp | ↓ |
| 달러 인덱스 | 111.43 | -0.01% | ↓ |
| VIX | 18.36 | -3.97% | ↓ |
| 다우30 | 48,463.72 | -0.15% | ↓ |
| SPX | — | anomaly 제외 | — |
| QQQ | 637.92 | +1.48% | ↑ |
| SOXX | 401.45 | +0.05% | ↑ |
| BTC | $74,998 | +1.21% | ↑ |
| F&G Index | 23 | 극단적 공포 | — |

주요 기술주:

| 종목 | 가격 | 변동 |
|---|---|---|
| MSFT | $413.77 | +5.26% |
| AVGO | $395.63 | +3.90% |
| AAPL | $266.64 | +3.02% |
| ASML | $1,477.87 | -2.66% |
| META | $673.70 | +1.69% |
| GOOGL | $337.09 | +1.26% |
| AMD | $258.10 | +1.19% |
| NVDA | $198.45 | +0.99% |
| TSM | $377.18 | -0.71% |
| AMZN | $248.31 | -0.29% |

---

## 8. Parquet 마스터 테이블 (1행, 2026-04-14)

| 컬럼 | 값 | 비고 |
|---|---|---|
| `news_sentiment_mean` | **-0.1159** | 약한 부정 |
| `news_sentiment_std` | 0.355 | |
| `n_articles` | 12 | |
| `fng_value` | 21 | 극단적 공포 |
| `btc_log_return` | -0.003856 | |
| `btc_return` | -0.003849 | |
| `btc_quote_volume` | 1.98B USD | |
| `usdkrw_log_return` | -0.006767 | |
| `funding_rate` | -0.000084 | |
| `open_interest_usd` | 6.96B USD | |
| `btc_long_short_ratio` | 0.7434 | Short 우세 |
| `etf_*` | 전부 NaN | ETF 데이터 미수집 |
| `*_lag1` | 전부 NaN | 2행 이상 필요 |
| `hybrid_index` | NaN | PCA 미실행 |
| `is_outlier` | False | |

---

## 9. 연구 한계

### 9.1 선택 편향 (Selection Bias)

감성 품질 게이트가 lookback 기간 중 **30일 중 29일을 제거**했습니다. 제거 사유의 96.7%가 `missing_backfill_marker`로, 이는 R2에 감성 데이터가 적재되었으나 `_backfill` 마커가 누락된 날짜입니다. 남은 1행(2026-04-14)이 전체 기간을 대표한다고 볼 수 없으며, 제거된 29일의 감성 분포가 다를 가능성을 배제할 수 없습니다.

이는 데이터 품질 문제이지 분석 설계의 결함은 아닙니다. R2 적재 파이프라인에서 `_backfill` 마커를 일관되게 부여하면 해소됩니다.

### 9.2 외부 타당성 (External Validity)

샘플 데이터는 단일 날짜(2026-04-14), 단일 시장 국면(F&G=21 극단적 공포, BTC $74,998)의 스냅샷입니다. 이 조건에서의 감성-시장 관계가 다른 시장 국면(강세장, 중립장)에서도 유효한지는 장기 데이터 확보 후 검증이 필요합니다.

### 9.3 Granger 인과성의 해석적 한계

Granger 인과성은 "X의 과거값이 Y 예측에 통계적으로 유의미한 정보를 추가하는가"를 검정하며, 진정한 인과관계(causation)를 증명하지 않습니다. 또한 현재 설계에서 `news_sentiment_mean → fng_value` 직접 쌍이 없어, 두 지표 간 관계는 `btc_log_return`을 매개로 한 간접 비교만 가능합니다.

### 9.4 FinBERT 모델의 도메인 한계

- ProsusAI/finbert는 영문 금융 뉴스 코퍼스로 학습되었으며, X 시그널(짧은 트윗, 비정형 문체)에 대한 적합성은 별도 검증되지 않았습니다.
- 한국어 번역본에는 감성 점수가 부여되지 않아, 한국어 고유 뉘앙스는 분석에 반영되지 않습니다.
- ±0.3 임계값의 최적성을 검증한 백테스트 결과가 없습니다. 현재 값은 neutral 확률 지배 구간을 분리하기 위한 실용적 기준입니다.

---

## 10. 부족한 부분 종합 및 향후 계획

### 🔴 Critical — 보고서 완성에 필수

| # | 항목 | 현재 상태 | 필요 조건 | 해결 방법 |
|---|---|---|---|---|
| 1 | Granger P-value 테이블 & 차트 | 미실행 | 180행+ | `SENTIMENT_JOIN_LOOKBACK_DAYS=200` 재실행 |
| 2 | ADF 정상성 검정 | 미실행 | 30행+ | 동일 |
| 3 | 이상치 제거 비율 (유의미한 수치) | 0% (1행) | 31행+ | 동일 |
| 4 | FinBERT 감성 시계열 분포 | 단일 날짜 | 다수 날짜 | 동일 |
| 5 | PCA hybrid_index | 미실행 | 충분한 clean rows | 동일 |
| 6 | `news_sentiment_mean → fng_value` 직접 Granger | GRANGER_PAIRS 미포함 | 코드 수정 | `GRANGER_PAIRS` 추가 |

### 🟡 보완 권장

| # | 항목 | 설명 |
|---|---|---|
| 7 | SPX 시장 데이터 | anomaly(700.23)로 제외됨 — 대체 소스 또는 수동 보정 |
| 8 | ETF 보유 현황 | Supabase gold table 연결 확인 필요 |
| 9 | 한국 투자자 참고 지표 | Market Packet `korea_watch` 빈 배열 |
| 10 | Perplexity/Grok API 월간 한도 | 사용 중인 플랜의 구체적 한도 수치 문서화 필요 |
| 11 | FinBERT 임계값 백테스트 | ±0.3 임계값의 최적성 검증 |
| 12 | X 시그널 FinBERT 적합성 | 짧은 트윗에 대한 모델 성능 별도 벤치마크 |
| 13 | Lambda 프록시 운영 | 동시 실행 한도 및 비용 모니터링 |

### 근본 원인

R2에 적재된 일별 감성 데이터 중 `_backfill` 마커가 없는 날짜가 29일치 → 품질 게이트에서 제외 → 1행만 남음.

### 해결 경로

```bash
# 1. 충분한 lookback으로 재실행
SENTIMENT_JOIN_LOOKBACK_DAYS=200 make sentiment-join

# 2. 또는 R2에 적재된 장기 parquet 직접 다운로드
```

---

## 부록 A: 데이터 정합성 교차 검증

| 검증 항목 | 결과 |
|---|---|
| `analytics_btc.newsSentiment.mean` = `curated_btc.meta.newsSentiment.mean` | ✅ 0.2079 일치 |
| `curated_btc.meta.sourceCounts` = `public_context.source_counts` | ✅ 일치 |
| Parquet `sentiment_status` = "ok" | ✅ |
| Parquet `btc_source` = "binance" | ✅ |
| Market Packet SPY anomaly → `data_footer_notes` 기록 | ✅ |
| `publicNewsAnalysis` 12건 중 10 성공 / 2 실패 → `status: "partial"` | ✅ |
| Parquet pandera 스키마 검증 (26컬럼 strict) | ✅ 통과 |

## 부록 B: Parquet 메타데이터 전문

```json
{
  "run_id": "sentiment-join-20260415",
  "generated_at_utc": "2026-04-15T23:05:49.413707+00:00",
  "adf": {},
  "granger_results": [],
  "granger_eligible_rows": null,
  "granger_executed": null,
  "rows_before_outlier_filter": 1,
  "rows_after_outlier_filter": 1,
  "outlier_filtered_count": 0,
  "outlier_filtered_ratio": 0.0,
  "pca_summary": { "status": "insufficient_rows", "rows": 0 },
  "vif_diagnostics": [],
  "hybrid_signal_label": null,
  "exclusion_counts": {
    "missing_backfill_marker": 29,
    "invalid_contract": 1,
    "insufficient_article_count": 0,
    "no_sentiment": 0,
    "skipped_sentiment": 0
  }
}
```
