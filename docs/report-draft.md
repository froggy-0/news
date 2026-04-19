# Sovereign Brief — Sentiment-Join 파이프라인 코드 기반 보고서

> 작성일: 2026-04-19 · 기준: 현재 저장소 코드베이스
> 범위: `src/morning_brief/analysis/sentiment_join/`와 직접 연동되는 upstream FinBERT/R2 analytics 계약

---

## 0. 요약

이 문서는 특정 과거 실행 샘플의 시장값을 고정해서 설명하지 않는다. 현재 파이프라인은 실행일 기준 lookback 기간의 일별 데이터를 수집하고, R2 감성 데이터 품질 게이트를 통과한 날짜만 F&G, BTC, USD/KRW와 inner join한 뒤 futures, BTC ETF, VIX를 left join한다. 통계 분석용 데이터에서는 이상치 행을 삭제하지 않고 수치 컬럼만 NaN으로 마스킹해 날짜 연속성을 최대한 유지한다.

현재 구현 기준으로 중요한 변경점은 다음과 같다.

| 항목 | 현재 코드 기준 |
|---|---|
| 핵심 수집 소스 | R2 analytics 감성, F&G, BTC 현물, USD/KRW, VIX, BTC futures, BTC ETF |
| 필수 inner join 축 | R2 감성, F&G, BTC 수익률, USD/KRW 수익률 |
| 보조 left join 축 | futures, ETF, VIX |
| 단일 `hybrid_index` | 삭제됨. `full_hybrid_index`, `core_hybrid_index`와 각각의 0~100 score 사용 |
| 이상치 처리 | 행 제거가 아니라 분석용 수치 컬럼 NaN 마스킹 |
| 정상성 검정 | ADF 단독이 아니라 ADF+KPSS 공동 판정 |
| Granger 쌍 | target 8쌍 + cross 8쌍 + reverse 5쌍, lag 1~3, 총 최대 63개 검정 |
| 다중검정 보정 | Benjamini-Hochberg FDR 보정 후 `significant` 판정 |
| Alpha validation | hit rate, correlation, backtest, walk-forward validation 생성 |

주요 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:219`, `src/morning_brief/analysis/sentiment_join/join.py:233`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:14`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:15`.

---

## 1. 실행 범위와 설정

### 1.1 기간 설정

`SENTIMENT_JOIN_LOOKBACK_DAYS` 기본값은 180일이고, 최종 허용 범위는 1~730일이다. 내부 `_env_bounded_int`는 일단 0~10000으로 파싱하지만, 이후 명시적으로 1~730 범위를 벗어나면 예외를 발생시킨다. 근거: `src/morning_brief/analysis/sentiment_join/config.py:53`, `src/morning_brief/analysis/sentiment_join/config.py:59`.

| 설정 | 기본값 | 허용 범위 | 사용처 |
|---|---:|---:|---|
| `SENTIMENT_JOIN_LOOKBACK_DAYS` | 180 | 1~730 | 분석 기간 |
| `SENTIMENT_JOIN_OUTPUT_DIR` | `data/sentiment_join` | 경로 | Parquet 저장 위치 |
| `SENTIMENT_JOIN_R2_MAX_CONCURRENCY` | 10 | 1~64 | R2 일별 JSON 병렬 fetch |
| `SENTIMENT_JOIN_RETAIN_DAYS` | 30 | 0~3650 | 로컬 Parquet 보존 기간 |

### 1.2 실행일 기준 날짜 계산

파이프라인은 UTC 오늘을 `end_date`로 잡고, lookback만큼 과거를 `start_date`로 계산한다. BTC와 USD/KRW 수익률은 전일 대비 계산이 필요하므로 `lookback_days + 1`일부터 종가를 가져온다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:221`, `src/morning_brief/analysis/sentiment_join/pipeline.py:224`.

---

## 2. 데이터 수집 소스

### 2.1 소스 목록

| # | 소스 | 진입 함수 | 역할 | 실패 처리 |
|---:|---|---|---|---|
| 1 | R2 analytics 감성 | `fetch_r2_sentiment` | `analytics/btc/{date}.json`에서 `newsSentiment` 집계 로드 | 결측 행 생성, 전체 실패 경고 |
| 2 | Fear & Greed Index | `fetch_fng` | alternative.me F&G 값 로드 | 날짜 grid에 `pd.NA` |
| 3 | BTC 현물 | `fetch_btc_close_binance` | Binance Spot 일봉 종가와 quote volume | yfinance `BTC-USD` fallback |
| 4 | USD/KRW | `fetch_usdkrw_close` | KIS 해외지수 일봉 또는 yfinance `KRW=X` | 빈 close frame |
| 5 | VIX | `fetch_vix_history` | FRED `VIXCLS` optional feature | 빈 frame, downstream NaN |
| 6 | BTC futures | `fetch_futures_data` | funding, OI, long/short ratio | Supabase cache, Binance, Lambda, Bybit, NaN |
| 7 | BTC ETF | `fetch_etf_flow_features` | IBIT/BITB/GBTC 보유량과 AUM 기반 flow feature | Supabase gold, latest snapshot fallback, NaN |

수집 순서는 `run_sentiment_join`에 명시되어 있다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:227`, `src/morning_brief/analysis/sentiment_join/pipeline.py:238`, `src/morning_brief/analysis/sentiment_join/pipeline.py:245`, `src/morning_brief/analysis/sentiment_join/pipeline.py:255`, `src/morning_brief/analysis/sentiment_join/pipeline.py:267`, `src/morning_brief/analysis/sentiment_join/pipeline.py:275`, `src/morning_brief/analysis/sentiment_join/pipeline.py:282`.

### 2.2 R2 analytics 감성 계약

sentiment-join은 원문 뉴스나 개별 FinBERT 결과를 직접 다시 계산하지 않는다. R2 public bucket의 `analytics/btc/{date}.json`만 읽고, 이 JSON은 `schemaVersion`, `date`, `symbol`, `sentimentStatus`, `newsSentiment`, `_backfill`, `textSchemaVersion`만 허용한다. 근거: `src/morning_brief/analysis/sentiment_join/sources/r2_sentiment.py:96`, `src/morning_brief/data/storage/analytics_contract.py:15`, `src/morning_brief/data/storage/analytics_contract.py:87`.

`_backfill` 키가 없으면 `missing_backfill_marker`로 invalid 처리된다. `schemaVersion`은 현재 `v1`만 지원한다. 근거: `src/morning_brief/data/storage/analytics_contract.py:12`, `src/morning_brief/data/storage/analytics_contract.py:91`.

### 2.3 FinBERT upstream 범위

FinBERT는 upstream 뉴스/시그널 enrichment 모듈에서 실행된다. sentiment-join은 그 결과가 집계되어 R2 analytics payload에 들어온 `newsSentiment.mean/std/count`만 소비한다. FinBERT의 현재 기본 모델은 `ProsusAI/finbert`, batch size 기본값은 16, bullish/bearish 임계값은 각각 0.3/-0.3이다. 근거: `src/morning_brief/config.py:239`, `src/morning_brief/config.py:243`, `src/morning_brief/config.py:246`.

FinBERT 점수 산식은 `p_positive - p_negative`, confidence는 세 클래스 확률 중 최댓값이다. 입력 텍스트는 title, summary, why_it_matters 계열을 합쳐 512 토큰 상한으로 자른다. 근거: `src/morning_brief/data/finbert_sentiment.py:148`, `src/morning_brief/data/finbert_sentiment.py:154`, `src/morning_brief/data/finbert_sentiment.py:196`, `src/morning_brief/data/finbert_sentiment.py:218`.

---

## 3. 전처리와 결합

### 3.1 날짜 정규화와 forward fill

수집 결과는 `normalize_dates`를 통과한 뒤 결합된다. USD/KRW는 외환시장 휴장 때문에 전체 달력으로 reindex하고 최대 3일 forward fill한다. VIX는 optional feature이며, 미국 시장 휴장일 때문에 전체 달력 reindex 후 최대 2일 forward fill한다. BTC close도 forward fill 대상이다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:294`, `src/morning_brief/analysis/sentiment_join/pipeline.py:301`, `src/morning_brief/analysis/sentiment_join/pipeline.py:309`, `src/morning_brief/analysis/sentiment_join/pipeline.py:314`.

### 3.2 ETF flow 계산

ETF source는 `etf_total_btc`, `etf_total_aum_usd`를 ffill한 뒤 BTC close와 merge하고, `etf_total_btc.diff() * close`로 `etf_net_inflow_usd`를 만든다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:319`, `src/morning_brief/analysis/sentiment_join/pipeline.py:327`.

### 3.3 join 구조

R2 감성, F&G, BTC 수익률, USD/KRW 수익률은 날짜 기준 inner join이다. futures, ETF, VIX는 left join이며 실패 시 해당 컬럼을 NaN으로 둔다. 근거: `src/morning_brief/analysis/sentiment_join/join.py:242`, `src/morning_brief/analysis/sentiment_join/join.py:244`, `src/morning_brief/analysis/sentiment_join/join.py:248`, `src/morning_brief/analysis/sentiment_join/join.py:256`, `src/morning_brief/analysis/sentiment_join/join.py:264`.

### 3.4 lag와 파생 컬럼

PCA와 correlation에는 lag1 컬럼을 사용하고, Granger 검정에는 raw 컬럼을 사용한다. 이유는 Granger 함수가 내부적으로 lag를 생성하므로 `_lag1`을 넣으면 double-lag가 발생하기 때문이다. 근거: `src/morning_brief/analysis/sentiment_join/join.py:77`, `src/morning_brief/analysis/sentiment_join/join.py:121`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:18`.

| 파생 컬럼 | 생성 기준 |
|---|---|
| `funding_rate_lag1` | `funding_rate.shift(1)` |
| `oi_change_pct` | `open_interest_usd.pct_change()` |
| `oi_change_pct_lag1` | `oi_change_pct.shift(1)` |
| `btc_long_short_ratio_lag1` | `btc_long_short_ratio.shift(1)` |
| `etf_net_inflow_usd_lag1` | `etf_net_inflow_usd.shift(1)` |
| `volume_change_pct` | `btc_quote_volume.pct_change()` |
| `volume_change_pct_lag1` | `volume_change_pct.shift(1)` |
| `vix_lag1` | `vix.shift(1)` |
| `news_sentiment_mean_lag1` | `news_sentiment_mean.shift(1)` |
| `fng_value_lag1` | `fng_value`를 float 변환 후 shift |
| `usdkrw_log_return_lag1` | `usdkrw_log_return.shift(1)` |

---

## 4. 품질 게이트

### 4.1 감성 품질 게이트

감성 품질 게이트는 조인 전에 R2 감성 관측치를 제거한다. 제외 사유는 `missing_backfill_marker`, `insufficient_article_count`, `skipped_sentiment`, `invalid_contract`, `no_sentiment` 다섯 가지다. 근거: `src/morning_brief/analysis/sentiment_join/join.py:150`.

| 제외 사유 | 조건 |
|---|---|
| `missing_backfill_marker` | `is_backfill_valid=False`이고 reason에 `missing_backfill_marker` 포함 |
| `invalid_contract` | `is_backfill_valid=False`이나 missing marker가 아닌 계약 오류 |
| `skipped_sentiment` | `sentiment_status == "skipped"` |
| `insufficient_article_count` | `n_articles <= 1` |
| `no_sentiment` | `news_sentiment_mean`이 NaN |

근거: `src/morning_brief/analysis/sentiment_join/join.py:164`, `src/morning_brief/analysis/sentiment_join/join.py:179`, `src/morning_brief/analysis/sentiment_join/join.py:185`, `src/morning_brief/analysis/sentiment_join/join.py:191`.

### 4.2 structured source coverage gate

futures와 ETF는 raw master에는 붙지만, 분석용 DataFrame에서는 coverage 품질에 따라 특정 feature를 NaN으로 마스킹한다.

| feature group | gate 조건 | 제외 reason |
|---|---|---|
| ETF flow | source mode가 `gold_history`가 아니거나 history quality가 `ok`가 아님 | `btc_etf_history_unavailable` |
| OI | 최근 30일 OI quality가 `ok`가 아님 | `futures_oi_incomplete` |
| Long/Short Ratio | 최근 30일 LSR quality가 `ok`가 아님 | `futures_lsr_incomplete` |
| Funding | funding quality가 `ok`가 아님 | `futures_funding_incomplete` |

근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:150`, `src/morning_brief/analysis/sentiment_join/pipeline.py:159`, `src/morning_brief/analysis/sentiment_join/pipeline.py:171`, `src/morning_brief/analysis/sentiment_join/pipeline.py:180`, `src/morning_brief/analysis/sentiment_join/pipeline.py:189`.

coverage의 `ok` 기준은 0.60 이상이다. 근거: `src/morning_brief/analysis/sentiment_join/quality.py:3`.

### 4.3 futures coverage 특이점

Binance OI/LSR API 보존 제약을 고려해 OI/LSR gate는 전체 lookback이 아니라 최근 30일 윈도우 quality를 우선 사용한다. 전체 lookback coverage는 진단용 metadata로 남는다. 근거: `src/morning_brief/analysis/sentiment_join/sources/futures.py:433`, `src/morning_brief/analysis/sentiment_join/sources/futures.py:446`, `src/morning_brief/analysis/sentiment_join/sources/futures.py:501`.

### 4.4 이상치 탐지와 처리

이상치 탐지는 rolling IQR 방식이다. window는 30, min_periods는 15, multiplier는 3.0이다. 판정 대상은 변화율/수익률 계열로 제한된다. 근거: `src/morning_brief/analysis/sentiment_join/join.py:29`, `src/morning_brief/analysis/sentiment_join/join.py:282`.

| 대상 컬럼 |
|---|
| `btc_return` |
| `usdkrw_return` |
| `funding_rate` |
| `oi_change_pct` |
| `volume_change_pct` |
| `etf_net_inflow_usd` |

중요: 현재 코드는 이상치 행을 삭제하지 않는다. `analysis_df`에서 `date`, `is_outlier`, status/label/version 계열을 제외한 수치 컬럼만 NaN으로 마스킹한다. Parquet master에는 원 행이 유지되고, metadata에는 masked count/ratio가 기록된다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:393`, `src/morning_brief/analysis/sentiment_join/pipeline.py:407`, `src/morning_brief/analysis/sentiment_join/pipeline.py:414`.

---

## 5. 통계 검정

### 5.1 정상성 검정

최소 30행 이상일 때 정상성 검정을 시도한다. ADF 단독 판정이 아니라 ADF+KPSS 공동 판정이며, 둘이 모두 정상성을 지지할 때만 `stationary=True`다. 비정상이면 Granger gate에서 1차 차분을 시도하고, 차분 후에도 정상성을 만족하지 않으면 해당 pair는 건너뛴다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:14`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:96`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:145`.

검정 대상 raw 컬럼은 다음 9개다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:66`.

| 컬럼 |
|---|
| `btc_log_return` |
| `news_sentiment_mean` |
| `fng_value` |
| `funding_rate` |
| `btc_long_short_ratio` |
| `oi_change_pct` |
| `etf_net_inflow_usd` |
| `usdkrw_log_return` |
| `volume_change_pct` |

### 5.2 Granger 검정 설계

최소 180행 이상일 때 Granger 검정을 시도한다. lag는 1, 2, 3이며, pair별로 `grangercausalitytests`를 한 번 호출해 전체 lag 결과를 만든다. 결과에는 raw p-value, F-statistic, 자유도, effective rows, calendar span, 최대 연속 날짜 gap, AIC 기반 optimal lag, primary flag가 포함된다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:15`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:16`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:189`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:267`.

#### Target pairs: BTC 수익률 예측력

target은 모두 `btc_log_return`이다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:20`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:26`.

| predictor | target |
|---|---|
| `news_sentiment_mean` | `btc_log_return` |
| `fng_value` | `btc_log_return` |
| `funding_rate` | `btc_log_return` |
| `btc_long_short_ratio` | `btc_log_return` |
| `oi_change_pct` | `btc_log_return` |
| `etf_net_inflow_usd` | `btc_log_return` |
| `usdkrw_log_return` | `btc_log_return` |
| `volume_change_pct` | `btc_log_return` |

#### Cross pairs: 지표 간 정보 전파

`news_sentiment_mean -> fng_value` 직접 쌍은 현재 포함되어 있다. 과거 초안의 "직접 쌍 없음" 설명은 더 이상 맞지 않아 제거했다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:39`.

| predictor | target |
|---|---|
| `news_sentiment_mean` | `fng_value` |
| `fng_value` | `news_sentiment_mean` |
| `news_sentiment_mean` | `funding_rate` |
| `news_sentiment_mean` | `etf_net_inflow_usd` |
| `fng_value` | `btc_long_short_ratio` |
| `fng_value` | `etf_net_inflow_usd` |
| `usdkrw_log_return` | `volume_change_pct` |
| `funding_rate` | `etf_net_inflow_usd` |

#### Reverse pairs: 가격 선행 여부 확인

역방향 pair는 단순 선행 해석을 막기 위한 진단이다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:54`.

| predictor | target |
|---|---|
| `btc_log_return` | `news_sentiment_mean` |
| `btc_log_return` | `funding_rate` |
| `btc_log_return` | `fng_value` |
| `btc_log_return` | `btc_long_short_ratio` |
| `btc_log_return` | `etf_net_inflow_usd` |

총 family는 `(16 forward/cross + 5 reverse) * 3 lag = 63`개 검정이다. 유의성은 raw p-value가 아니라 Benjamini-Hochberg FDR 보정 후 `pvalue_adjusted < 0.05`로 판정한다. 근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:64`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:308`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:400`.

---

## 6. 하이브리드 지수

### 6.1 현재 지수 버전

현재 feature schema version은 `v4`다. 이전 단일 `hybrid_index` 컬럼은 삭제되었고, full/core 이중 지수와 0~100 score가 저장된다. 근거: `src/morning_brief/analysis/sentiment_join/hybrid_index.py:35`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:36`, `src/morning_brief/analysis/sentiment_join/validate.py:52`.

| 지수 | 후보 feature | VIF gate |
|---|---|---|
| full | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `btc_long_short_ratio_lag1`, `etf_net_inflow_usd_lag1`, `volume_change_pct_lag1`, `vix_lag1` | 10.0 이상 반복 제거 |
| core | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `volume_change_pct_lag1` | 없음 |

근거: `src/morning_brief/analysis/sentiment_join/hybrid_index.py:18`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:29`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:39`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:61`.

### 6.2 계산 방식

1. 후보 feature 중 존재하고 전 행 NaN이 아닌 컬럼만 사용한다.
2. 최소 feature 수는 2개, 최소 clean row 수는 10개다.
3. full 지수는 VIF 10.0 이상 feature를 반복 제거한다.
4. StandardScaler로 정규화한 뒤 PCA를 수행한다.
5. 누적 설명 분산 80% 이상이 되는 최소 component 수를 선택한다.
6. PC1 raw 값을 지수로 쓰고, min-max로 0~100 score를 만든다.
7. `fng_value_lag1` loading이 양수가 되도록 부호를 고정한다.

근거: `src/morning_brief/analysis/sentiment_join/hybrid_index.py:40`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:41`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:42`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:393`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:437`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:451`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:460`.

### 6.3 지수 품질 metadata

각 지수는 `vif_diagnostics`, `pca_summary`, `coverage`, `excluded_features`, `quality_status`, `quality_reasons`, `signal_label`, `signal_zscore`를 metadata에 남긴다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:522`.

full 지수는 확장 feature(`btc_long_short_ratio_lag1`, `etf_net_inflow_usd_lag1`, `vix_lag1`)가 하나도 선택되지 않으면 `missing_full_expansion_features`로 degraded 처리된다. 근거: `src/morning_brief/analysis/sentiment_join/hybrid_index.py:43`, `src/morning_brief/analysis/sentiment_join/hybrid_index.py:151`.

---

## 7. Alpha validation

### 7.1 평가 대상 predictor

Alpha validation은 하이브리드 지수 계산 후 lag1 score를 추가한 다음 실행된다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:479`, `src/morning_brief/analysis/sentiment_join/pipeline.py:486`.

| predictor | threshold | inverted |
|---|---:|---|
| `news_sentiment_mean_lag1` | 0 | false |
| `fng_value_lag1` | 50 | false |
| `vix_lag1` | 24 | true |
| `full_hybrid_index_score_lag1` | 50 | false |
| `core_hybrid_index_score_lag1` | 50 | false |

근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1052`.

### 7.2 산출물

| 산출물 | 내용 |
|---|---|
| hit rates | BTC 방향 `up/down/flat` 중 flat 제외, threshold 기준 예측 방향과 실제 방향 비교 |
| correlations | predictor vs `btc_log_return`, predictor 간 Pearson/Spearman |
| backtest | threshold 기반 buy/cash 전략, 거래비용 10 bps 기본값 |
| walk-forward | full/core 각각 train 120일, test 30일 fold 평가 |

근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:470`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:602`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:719`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:849`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1087`.

---

## 8. 저장 스키마와 메타데이터

### 8.1 Master schema

Parquet master는 pandera strict schema로 검증된다. 즉 schema에 없는 컬럼이 들어오면 실패하고, `n_articles`, `fng_value`는 pandas nullable `Int64` dtype이어야 한다. 근거: `src/morning_brief/analysis/sentiment_join/validate.py:13`, `src/morning_brief/analysis/sentiment_join/validate.py:72`, `src/morning_brief/analysis/sentiment_join/validate.py:76`.

주요 컬럼 카테고리는 다음과 같다.

| 카테고리 | 컬럼 |
|---|---|
| 날짜/감성 | `date`, `news_sentiment_mean`, `news_sentiment_std`, `n_articles`, `sentiment_status`, `is_backfill_valid`, `ingest_validation_reason`, `text_schema_version` |
| 시장 수익률 | `fng_value`, `btc_log_return`, `btc_return`, `btc_quote_volume`, `usdkrw_log_return`, `usdkrw_return` |
| 이상치/방향 | `is_outlier`, `btc_direction_label` |
| futures | `funding_rate`, `open_interest_usd`, `funding_rate_lag1`, `oi_change_pct`, `oi_change_pct_lag1`, `btc_long_short_ratio`, `btc_long_short_ratio_lag1` |
| ETF | `etf_total_btc`, `etf_total_aum_usd`, `etf_net_inflow_usd`, `etf_net_inflow_usd_lag1` |
| volume/VIX | `volume_change_pct`, `volume_change_pct_lag1`, `vix`, `vix_lag1` |
| lag predictors | `news_sentiment_mean_lag1`, `fng_value_lag1`, `usdkrw_log_return_lag1` |
| hybrid v4 | `full_hybrid_index`, `full_hybrid_index_score`, `core_hybrid_index`, `core_hybrid_index_score`, `full_hybrid_index_score_lag1`, `core_hybrid_index_score_lag1` |

근거: `src/morning_brief/analysis/sentiment_join/validate.py:15`.

### 8.2 Parquet metadata

`save_parquet`는 `ffill_days`, `btc_source`, `sentiment_join_stats` metadata를 저장한다. 저장 파일명은 `master_{YYYYMMDD}.parquet`이며 snappy compression을 사용한다. 근거: `src/morning_brief/analysis/sentiment_join/storage.py:19`, `src/morning_brief/analysis/sentiment_join/storage.py:29`, `src/morning_brief/analysis/sentiment_join/storage.py:32`.

`sentiment_join_stats`에는 정상성/Granger 결과, hybrid diagnostics, outlier mask 통계, exclusion counts, Granger correction, alpha validation 결과, structured source metadata가 들어간다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:597`.

### 8.3 R2 업로드

로컬 저장 후 보존 기간을 넘긴 파일을 정리하고, R2 endpoint가 설정되어 있으면 `sentiment_join/{파일명}`으로 업로드한다. R2 endpoint가 비어 있으면 업로드를 건너뛴다. 근거: `src/morning_brief/analysis/sentiment_join/pipeline.py:623`, `src/morning_brief/analysis/sentiment_join/pipeline.py:632`, `src/morning_brief/analysis/sentiment_join/pipeline.py:633`, `src/morning_brief/analysis/sentiment_join/storage.py:64`.

---

## 9. 보고서 데이터 추출

`scripts/extract_report_data.py`는 최신 `master_*.parquet`를 찾아 `sentiment_join_stats` metadata와 본문 DataFrame을 출력한다. 현재 출력 범위는 Granger, structured source coverage, 시계열 미리보기, 이상치 통계, 감성 분포, ADF, PCA/VIF 진단이다. 근거: `scripts/extract_report_data.py:22`, `scripts/extract_report_data.py:29`, `scripts/extract_report_data.py:97`, `scripts/extract_report_data.py:119`, `scripts/extract_report_data.py:148`, `scripts/extract_report_data.py:159`, `scripts/extract_report_data.py:171`, `scripts/extract_report_data.py:188`.

실행 예:

```bash
python scripts/extract_report_data.py data/sentiment_join
```

주의: 이 스크립트의 fallback 문구에는 "GRANGER_PAIRS에 직접 쌍이 없다"는 예전 설명이 남아 있지만, 실제 `GRANGER_PAIRS_CROSS`에는 `news_sentiment_mean -> fng_value`가 포함되어 있다. 이 문구는 granger 결과가 없거나 필터링 결과가 비었을 때의 안내문이며, 현재 코드 구조 설명에는 사용하지 않는다. 근거: `scripts/extract_report_data.py:104`, `src/morning_brief/analysis/sentiment_join/statistical_tests.py:42`.

---

## 10. 제거한 오래된 내용

이 갱신에서 다음 내용을 제거했다.

| 제거 항목 | 제거 사유 |
|---|---|
| 2026-04-15 시장 스냅샷 표 | 현재 코드에서 생성되는 일반 문서가 아니라 특정 과거 실행값 |
| 1행 parquet 샘플값 | 현재 실행 결과를 대표하지 않음 |
| "ETF 전부 NaN" 단정 | 현재는 Supabase gold history와 latest snapshot fallback, coverage gate 구조가 있음 |
| "Granger 직접 쌍 없음" | 현재 `news_sentiment_mean -> fng_value` cross pair가 있음 |
| 단일 `hybrid_index` 설명 | v4에서 삭제되고 full/core 지수로 대체됨 |
| 이상치 "제거" 표현 | 현재는 분석용 NaN 마스킹이며 행은 유지됨 |
| 부록의 예시 metadata 전문 | 실제 저장값이 아닌 설명용 예시라 오해 가능 |

---

## 11. 현재 한계와 확인 필요 항목

| 항목 | 현재 상태 | 필요 조치 |
|---|---|---|
| 장기 통계 검정 | Granger는 180행 미만이면 실행되지 않음 | 충분한 R2 analytics 유효 일수 확보 |
| Walk-forward | train 120일 + test 30일 미만이면 미실행 | 최소 150일 이상 clean data 확보 |
| ETF flow | `gold_history`가 아니면 분석용 flow feature gate로 NaN | Supabase gold table 적재/coverage 점검 |
| VIX | `FRED_API_KEY` 없으면 optional NaN | VIX를 full 지수에 쓰려면 FRED key와 coverage 확인 |
| FinBERT threshold | 기본 ±0.3, 코드상 백테스트 최적화 없음 | threshold 민감도 별도 실험 필요 |
| Pairwise Granger 해석 | omitted variable bias 가능 | VAR/causal design은 별도 연구로 분리 |

---

## 12. 루브릭 검증

`docs/development-standards.md:79`의 리뷰 루브릭 기준으로 문서 갱신을 자체 검증했다.

| 루브릭 | 검증 결과 |
|---|---|
| 정확성 | 코드 라인 근거가 없는 샘플 수치와 과거 가정을 제거하고, 현재 함수/상수/스키마 기준으로 다시 작성했다. |
| 일관성 | 수집, join, gate, stats, hybrid, alpha validation, 저장 metadata의 용어를 코드명과 맞췄다. |
| 격리성 | futures/ETF/VIX 실패가 전체 결과를 무너뜨리지 않고 NaN/metadata로 격리되는 구조를 별도 섹션에 반영했다. |
| 가시성 | `sentiment_join_stats`, structured source metadata, extract script 출력 범위를 문서화했다. |
| 유지보수성 | 삭제된 단일 `hybrid_index`와 샘플 전문을 제거하고, v4 full/core 기준으로 문서 책임을 정리했다. |
| 문서성 | 보고서 내용이 `validate.py` strict schema와 `pipeline.py` metadata 생성 경로를 따라가도록 구성했다. |

## 13. 검증 명령

문서 변경 후 권장 검증 순서:

```bash
python scripts/extract_report_data.py data/sentiment_join
make lint
make test
make typecheck
```

실제 pipeline 재실행이 필요한 경우:

```bash
SENTIMENT_JOIN_LOOKBACK_DAYS=180 make sentiment-join
python scripts/extract_report_data.py data/sentiment_join
```
