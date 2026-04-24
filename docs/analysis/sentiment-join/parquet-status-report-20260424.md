# Sentiment Join Parquet 현황 리포트
> 작성일: 2026-04-24 | 대상 파일: master_20260424.parquet

---

## 1. 데이터 구성

| 항목 | 값 |
|---|---|
| 기간 | 2025-04-29 ~ 2026-04-24 (358행) |
| 컬럼 수 | 50개 |
| 소스 | 뉴스 감성 / BTC 가격 / 선물(funding·OI·LSR) / ETF / VIX / USD/KRW |
| 선물 소스 | 전량 `lambda` (GitHub Actions US IP → 451 차단 우회) |
| 감성 상태 | 전행 `ok` — 백필 실패 없음 |

---

## 2. 결측치 현황

| 컬럼 | 결측 | 원인 |
|---|---|---|
| `usdkrw_return` | 10행 (2.8%) | 환율 데이터 자연 결측 |
| `etf_net_inflow_usd` 외 lag1 컬럼들 | 1~4행 (0.3~1.1%) | 기간 시작/끝 경계 |
| `full_hybrid_index` | 3행 (0.8%) | PCA 입력 결측 전파 |
| `core_hybrid_index` | 2행 (0.6%) | 동일 |
| `ingest_validation_reason` | 358행 (100%) | 정상 — 전행 수집 성공 시 None |

OI/LSR 0% 결측 — `sentiment-join.yml`에 Supabase 환경변수 누락 수정으로 완전 해결 (이전 7.8%).

---

## 3. 이상치 처리

- `is_outlier=True`: **73행 / 358행 = 20.4%**
- 정책: `column` — 셀 단위 NaN, 행 전체 보존 (이전 `row` 정책 대비 커버리지 개선)
- 최근 outlier 집중 날짜: 2026-03-04~12, 2026-04-10~19 (BTC 급락 구간)
- 통계 분석 실제 투입 행: **285행** (outlier 제외)

---

## 4. 주요 피처 현황

| 피처 | 전체 평균 | 최근 30일 평균 | 해석 |
|---|---|---|---|
| `news_sentiment_mean` | +0.015 | -0.066 | 최근 부정 심화 |
| `fng_value` (Fear & Greed) | 39.8 | 16.3 | 최근 극단적 공포 |
| `btc_return` | -0.05% | +0.18% | 최근 소폭 반등 |
| `funding_rate` | +0.01% | -0.00% | 최근 중립~약음 |
| `vix` | 18.5 | 22.6 | 최근 변동성 확대 |
| `full_hybrid_index_score` | 49.8 | 34.0 | 최근 약세 국면 |

---

## 5. 정상성 검정 (ADF, is_outlier=False 기준 285행)

| 피처 | ADF 통계량 | p-value | 정상성 |
|---|---|---|---|
| `btc_return` | -17.05 | 0.000 | O |
| `funding_rate` | -4.74 | 0.000 | O |
| `oi_change_pct` | -17.29 | 0.000 | O |
| `btc_long_short_ratio` | -3.22 | 0.019 | O |
| `etf_net_inflow_usd` | -4.78 | 0.000 | O |
| `vix` | -3.38 | 0.012 | O |
| `full_hybrid_index_score` | -2.97 | 0.038 | O |
| `news_sentiment_mean` | -2.14 | 0.230 | **X — 비정상** |

`news_sentiment_mean`만 단위근 의심. 차분 또는 rolling z-score 고려 필요.

---

## 6. 예측력 (lag1 → btc_return 피어슨 상관)

| 피처 | r | p-value | n |
|---|---|---|---|
| `news_sentiment_mean_lag1` | -0.024 | 0.657 | 357 |
| `fng_value_lag1` | -0.007 | 0.894 | 357 |
| `funding_rate_lag1` | -0.028 | 0.603 | 357 |
| `oi_change_pct_lag1` | -0.053 | 0.322 | 356 |
| `btc_long_short_ratio_lag1` | -0.052 | 0.330 | 357 |
| `etf_net_inflow_usd_lag1` | -0.050 | 0.347 | 356 |
| `vix_lag1` | +0.066 | 0.212 | 356 |
| `full_hybrid_index_score_lag1` | -0.025 | 0.641 | 354 |
| `core_hybrid_index_score_lag1` | -0.039 | 0.459 | 355 |

전체 lag1 피처 모두 p > 0.05 — 통계적으로 유의미한 선형 예측력 없음.

### 피처 간 다중공선성

| 쌍 | r |
|---|---|
| `fng_value_lag1` ↔ `full_hybrid_index_score_lag1` | **0.907** |
| `news_sentiment_mean_lag1` ↔ `full_hybrid_index_score_lag1` | **0.770** |
| `btc_long_short_ratio_lag1` ↔ `full_hybrid_index_score_lag1` | **-0.761** |

PCA 기반 hybrid index가 fng + sentiment + LSR을 이미 통합하고 있으나, 통합 지수 자체의 예측력도 낮음.

---

## 7. Hit Rate

| 예측 신호 | 전체 | 2025-Q2 | 2025-Q3 | 2025-Q4 | 2026-Q1 | 2026-Q2 |
|---|---|---|---|---|---|---|
| `full_hybrid_index_score_lag1` (>50 → up) | **47.2%** | 51.7% | 43.5% | 52.2% | 44.4% | 40.0% |
| `core_hybrid_index_score_lag1` | **48.2%** | — | — | — | — | — |
| `news_sentiment_mean_lag1` (>0 → up) | **48.2%** | — | — | — | — | — |
| `fng_value_lag1` (>50 → up) | **50.4%** | — | — | — | — | — |
| `funding_rate_lag1` (>0 → up) | **51.3%** | — | — | — | — | — |

전반적으로 47~51% — 랜덤 수준. 최근 2026-Q2는 40.0%로 역신호 구간.

---

## 8. 종합 판단

| 구분 | 상태 | 비고 |
|---|---|---|
| 데이터 수집 | 정상 | OI/LSR 포함 전 소스 완전 |
| 커버리지 | 99.2% | 이전 78% → 완전 해결 |
| 이상치 비율 | 20.4% | 시장 급락 구간 집중, column 정책 유지 |
| 정상성 | 7/8 통과 | `news_sentiment_mean`만 비정상 |
| 예측력 | 없음 | 모든 lag1 피처 p>0.05, hit 47~51% |
| Regime Index 용도 | 적합 | 예측 모델 아닌 국면 분류 목적 |

현재 파이프라인은 데이터 품질 측면에서 정상 작동하고 있으나, lag1 피처의 선형 예측력은 통계적으로 유의하지 않다. Regime Index 본래 목적(국면 분류)으로는 사용 가능하며, 알파 신호로 활용하려면 비선형 모델이나 추가 피처 엔지니어링이 필요하다.
