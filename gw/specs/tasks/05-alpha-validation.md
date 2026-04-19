# 5순위: 실전 예측 성능 검증 (Alpha Validation)

> 01~04 완료 후 적용. Lag-1 처리, 백필 JSON 수정, 180행 확보가 선행 조건입니다.
> 이 단계 없이는 "통계적으로 유의하다"만 있고 "실제로 맞췄다"가 없습니다.

---

## 선행 조건 (반드시 완료 후 진행)

| 조건 | 사유 | 태스크 | 상태 |
|---|---|---|---|
| Lag-1 처리 | 당일 감성 vs 당일 수익률 비교 시 look-ahead bias → 적중률이 가짜로 높게 나옴 | 01 §1 | ✅ PR #61 |
| 백필 JSON flat 구조 | 180행 미확보 시 적중률/백테스트에 통계적 신뢰도 없음 | 02 §3 | ✅ PR #62 |
| ADF 정상성 검증 | 비정상 시계열로 상관 분석하면 spurious correlation 위험 | 02 §1 | ✅ PR #62 (ADF+KPSS) |

> **2026-04-18**: 선행 조건 모두 완료. 진행 가능.

---

## 코드베이스 현황 검증 (2026-04-18 20:30 KST)

### Parquet 현황 (`data/sentiment_join/master_20260418.parquet`)

33 컬럼. `btc_direction_label`, `btc_log_return`, `news_sentiment_mean_lag1`, `fng_value_lag1` 등 hit-rate 산출에 필요한 ground truth + predictor lag1이 이미 존재.

**없는 것**: `full_hybrid_index_score_lag1`, `core_hybrid_index_score_lag1` — 아직 생성 로직 자체가 없음.

### 파일별 현황

| 파일 | 경로 | 현황 |
|---|---|---|
| `join.py` | `src/morning_brief/analysis/sentiment_join/join.py` | `_add_sentiment_lag_columns` (L121-147)에 `news_sentiment_mean_lag1`, `fng_value_lag1`, `usdkrw_log_return_lag1`만 생성. hybrid score lag1 없음 |
| `hybrid_index.py` | `src/morning_brief/analysis/sentiment_join/hybrid_index.py` | `compute_hybrid_indices` (L300-324) → `_compute_single_index` (L134-297). scaler/PCA 외부 주입 불가 — 내부에서 fit+transform 일체 |
| `pipeline.py` | `src/morning_brief/analysis/sentiment_join/pipeline.py` | hybrid index 생성 L328-349, stats metadata 조립 L355-370. lag1 생성 호출 없음 |
| `validate.py` | `src/morning_brief/analysis/sentiment_join/validate.py` | `MASTER_SCHEMA` (L13-67) strict=True, 40 컬럼. hybrid score lag1 미등록 |
| `statistical_tests.py` | `src/morning_brief/analysis/sentiment_join/statistical_tests.py` | `run_statistical_tests` (L344-441) → `stationarity_results`, `granger`, `granger_eligible_rows`, `granger_executed`, `power_warning` 반환. hit_rate/correlation/backtest 함수 **없음** |
| `etf_storage.py` | `src/morning_brief/data/etf_storage.py` | `build_stats_metadata_payload` (L266-299) → `adf`, `granger_results`, `hybrid_indices`, outlier stats, `exclusion_counts`. hit_rates/correlations/backtest 필드 **없음** |

### 테스트 현황

- `tests/analysis/test_sentiment_join/` 16개 파일 존재
- `test_statistical_tests.py` (31.8 KB) — Granger/ADF 테스트만 커버
- `hit_rate`, `backtest`, `walk_forward` 관련 테스트 **전무** (전체 tests/ 검색 0건)

### 핵심 gap 요약

1. **hybrid score lag1 컬럼 미존재** — join.py 또는 pipeline.py에서 `compute_hybrid_indices` 호출 후 `.shift(1)` 추가 필요
2. **alpha validation 함수 전무** — `compute_hit_rate`, `compute_correlations`, `compute_backtest`, `walk_forward_backtest` 모두 미구현
3. **metadata payload에 결과 저장 경로 없음** — `build_stats_metadata_payload`에 `hit_rates`, `correlations`, `backtest` 필드 추가 필요
4. **scaler/PCA 외부 주입 불가** — walk-forward validation을 위해 `_compute_single_index`에 pre-fitted scaler/PCA 주입 인터페이스 필요

---

### ⚠️ 태스크 04 반영으로 변경된 컬럼명

태스크 04(PR #66)에서 `hybrid_index` → 이중 지수로 교체됨.

| 구 컬럼 | 현 컬럼 | 비고 |
|---|---|---|
| `hybrid_index` | `full_hybrid_index` / `core_hybrid_index` | raw PC1 값 |
| `hybrid_index` (0~100) | `full_hybrid_index_score` / `core_hybrid_index_score` | 0~100 스케일 — **임계값 비교에 사용** |
| `hybrid_index_lag1` | **미존재** — 별도 생성 필요 | `join.py`에 `.shift(1)` 추가 필요 |

`> 50` 임계값 비교는 `*_score` (0~100) 컬럼 기준. lag1 버전은 이 태스크에서 추가 생성.

> **구현 위치 참고**: `_add_sentiment_lag_columns` (join.py L121-147)은 `merge_sources` 내에서 hybrid index 생성 **이전**에 호출됨 (L276). hybrid score lag1은 `pipeline.py` L349 이후 (`compute_hybrid_indices` 완료 후) `master_df`에 직접 `.shift(1)` 적용하는 것이 올바른 위치.

---

## 1. 방향 적중률 (Hit Rate) 및 분류 성능

### 목적

감성 지표가 Bullish일 때 실제로 BTC가 올랐는가? 가장 직관적인 성능 척도입니다.

### 사용 데이터

마스터 테이블에 이미 존재하는 컬럼:

| 컬럼 | 역할 | 상태 |
|---|---|---|
| `news_sentiment_mean_lag1` | 전일 감성 점수 (predictor) | ✅ 존재 |
| `fng_value_lag1` | 전일 F&G Index (predictor) | ✅ 존재 |
| `full_hybrid_index_score_lag1` | 전일 full 하이브리드 지수 0~100 (predictor) | ❌ join.py에 추가 필요 |
| `core_hybrid_index_score_lag1` | 전일 core 하이브리드 지수 0~100 (predictor) | ❌ join.py에 추가 필요 |
| `btc_direction_label` | 당일 실제 방향 — up/down/flat (ground truth) | ✅ 존재 |
| `btc_log_return` | 당일 실제 수익률 (ground truth) | ✅ 존재 |

### 산출 지표

```
predicted_direction = "up" if predictor_lag1 > 0 else "down"
hit = (predicted_direction == btc_direction_label)
hit_rate = hit.sum() / len(hit)
```

각 predictor별로:

| 지표 | 산출 방법 |
|---|---|
| Hit Rate (%) | 방향 일치 건수 / 전체 건수 |
| Confusion Matrix | TP, FP, TN, FN (bullish/bearish vs up/down) |
| Precision | TP / (TP + FP) — "bullish 신호의 정확도" |
| Recall | TP / (TP + FN) — "실제 상승 중 포착률" |
| F1 Score | 2 × Precision × Recall / (Precision + Recall) |

비교 대상:

| Predictor | 임계값 | 비고 |
|---|---|---|
| `news_sentiment_mean_lag1` | > 0 → bullish | FinBERT 감성 |
| `fng_value_lag1` | > 50 → bullish | F&G 중립 기준 |
| `full_hybrid_index_score_lag1` | > 50 → bullish | 0~100 스케일 full 지수 |
| `core_hybrid_index_score_lag1` | > 50 → bullish | 0~100 스케일 core 지수 |
| 랜덤 기준선 | 50% | 동전 던지기 대비 우위 확인 |

### 수정 대상

| 파일 | 변경 | 위치 |
|---|---|---|
| `join.py` | `full_hybrid_index_score_lag1`, `core_hybrid_index_score_lag1` 컬럼 생성 (`_add_sentiment_lag_columns` 또는 별도 헬퍼) | L121-147 또는 pipeline.py L349 이후 |
| `validate.py` | `MASTER_SCHEMA`에 두 lag1 컬럼 추가 | L13-67 (strict=True이므로 누락 시 실패) |
| `statistical_tests.py` | `compute_hit_rate(df, predictor, threshold)` 함수 추가 | L441 이후 신규 |
| `run_statistical_tests` | hit rate 결과를 `results["hit_rates"]`에 기록 | L344-441 내부 확장 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `hit_rates` 필드 추가 | L266-299 시그니처+payload 확장 |

---

## 2. 수익률 상관 분석 (Pearson / Spearman)

### 목적

감성 점수의 **강도**가 수익률의 **크기**와 비례하는지 확인합니다. Granger가 "시차 예측 기여도"를 보는 반면, 상관 분석은 "방향과 크기의 동조성"을 봅니다.

### 산출 지표

| 지표 | 의미 |
|---|---|
| Pearson r | 선형 상관 (감성 점수 ↑ → 수익률 ↑ 비례 관계) |
| Spearman ρ | 순위 상관 (비선형 단조 관계도 포착) |
| p-value | 상관의 통계적 유의성 |

각 predictor_lag1 vs `btc_log_return` 쌍에 대해 산출합니다.

추가로 predictor 간 상관도 산출하여 다중공선성을 보완합니다:
- `news_sentiment_mean` vs `fng_value` — 감성과 심리의 중복도
- `hybrid_index` vs 개별 predictor — 하이브리드 지수가 개별 지표 대비 추가 정보를 담는지

### 수정 대상

| 파일 | 변경 | 위치 |
|---|---|---|
| `statistical_tests.py` | `compute_correlations(df, pairs)` 함수 추가 | L441 이후 신규 |
| `run_statistical_tests` | 상관 결과를 `results["correlations"]`에 기록 | L344-441 내부 확장 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `correlations` 필드 추가 | L266-299 시그니처+payload 확장 |

---

## 3. 누적 수익 백테스트 + Walk-Forward Validation

### 목적

하이브리드 지수 기반 전략이 단순 보유(Buy & Hold)보다 우수한 성과(Alpha)를 내는지 검증합니다. **반드시 out-of-sample(미래 데이터)에서 검증해야 합니다.**

### 🔴 Walk-Forward Validation 필수

현재 파이프라인은 전체 180일로 PCA fit + 백테스트를 동시에 수행합니다. 이는 in-sample 검증이라 과적합 위험이 있습니다.

```
현재 (in-sample — 과적합 위험):
  [====== 180일 전체로 PCA fit + 적중률 + 백테스트 ======]

Walk-forward (out-of-sample — 공정한 검증):
  [== 120일 train ==][= 30일 test =]
                     [== 120일 train ==][= 30일 test =]
                                        [== 120일 train ==][= 30일 test =]
  → train에서 PCA fit → test에서 적중률/수익 평가
  → test 구간들의 평균 성능 = 실전 기대 성능
```

**train-only로 처리해야 하는 것들:**

| 처리 | 이유 |
|---|---|
| `StandardScaler.fit` + `PCA.fit` | test 구간의 분포가 scaler/PCA에 영향을 주면 안 됨 |
| `detect_outliers_rolling_iqr`의 median/IQR 통계 | test 구간의 미래 데이터가 이상치 판정에 영향을 주면 안 됨 |
| min-max 스케일링의 min/max | test 구간의 극값이 0~100 범위를 결정하면 안 됨 |

→ test 구간에는 train에서 계산된 통계를 **그대로 적용(transform only)**합니다.

구현:

```python
def walk_forward_backtest(
    df, signal_col, return_col, threshold,
    train_days=120, test_days=30,
):
    results = []
    for start in range(0, len(df) - train_days - test_days + 1, test_days):
        train = df.iloc[start : start + train_days]
        test = df.iloc[start + train_days : start + train_days + test_days]

        # train에서 PCA scaler/loadings fit (hybrid_index 재계산)
        # test에 train의 scaler/loadings 적용
        # test 구간에서 적중률 + 수익률 평가

        results.append({
            "test_start": test["date"].iloc[0],
            "test_end": test["date"].iloc[-1],
            "hit_rate": ...,
            "cumulative_return": ...,
            "alpha_vs_bnh": ...,
        })
    return results
```

핵심: **PCA의 scaler와 components를 train 구간에서만 fit하고, test 구간에 transform만 적용**해야 합니다. 현재 `compute_hybrid_index`는 전체 데이터로 fit하므로, walk-forward용으로 train/test를 분리하는 래퍼가 필요합니다.

### 전략 설계

```
매일:
  if hybrid_index_lag1 > 50:  → 매수 포지션 (당일 btc_log_return 적용)
  else:                       → 현금 보유 (수익률 0)

누적 수익 = cumsum(strategy_return)
벤치마크  = cumsum(btc_log_return)  # Buy & Hold
Alpha     = 전략 누적 수익 - 벤치마크 누적 수익
```

### 산출 지표

| 지표 | 의미 |
|---|---|
| 전략 누적 수익률 | 하이브리드 지수 신호 기반 |
| Buy & Hold 누적 수익률 | 벤치마크 |
| Alpha (초과 수익) | 전략 - 벤치마크 |
| Sharpe Ratio | 위험 대비 수익 (연율화) |
| Max Drawdown | 최대 낙폭 |
| 거래 횟수 | 포지션 전환 횟수 |

비교 전략:

| 전략 | 신호 | 비고 |
|---|---|---|
| Full Hybrid Index | `full_hybrid_index_score_lag1 > 50` | full feature set 전략 |
| Core Hybrid Index | `core_hybrid_index_score_lag1 > 50` | coverage 높은 core 전략 |
| FinBERT Only | `news_sentiment_mean_lag1 > 0` | 단일 감성 지표 |
| F&G Only | `fng_value_lag1 > 50` | 단일 심리 지표 |
| Buy & Hold | 항상 매수 | 벤치마크 |

→ "full/core 하이브리드 지수가 개별 지표보다 나은가", "full vs core 차이는 얼마나 나는가"를 비교할 수 있습니다.

### 수정 대상

| 파일 | 변경 | 위치 |
|---|---|---|
| `statistical_tests.py` (또는 별도 `backtest.py`) | `compute_backtest(df, signal_col, threshold, return_col)` 함수 추가 | 신규 파일 또는 L441 이후 |
| `statistical_tests.py` (또는 별도 `backtest.py`) | `walk_forward_backtest(df, ...)` 함수 추가 — PCA train/test 분리 포함 | 신규 |
| `hybrid_index.py` | `compute_hybrid_index`에서 scaler/pca를 외부 주입 가능하도록 인터페이스 확장 (walk-forward용) | `_compute_single_index` L134-297 — 현재 내부 fit+transform 일체, 분리 필요 |
| `run_statistical_tests` | 백테스트 결과를 `results["backtest"]`에 기록 | L344-441 내부 확장 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `backtest` 필드 추가 | L266-299 시그니처+payload 확장 |

---

## 수정 우선순위 (5순위 내)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **5-1** | 방향 적중률 + Confusion Matrix (§1) | 🔴 "맞췄는가"의 직접 증거 | 저 |
| **5-2** | 수익률 상관 분석 (§2) | 🟡 강도-크기 동조성 | 저 |
| **5-3** | 누적 수익 백테스트 (§3) | 🟡 "돈이 되는가"의 최종 증거 | 중 |

---

## 리포트 반영

`report-draft.md`에 새 섹션 추가 필요:

| 리포트 섹션 | 내용 |
|---|---|
| §X 예측 성능 검증 | Hit Rate 테이블 (predictor별), Confusion Matrix |
| §X+1 상관 분석 | Pearson/Spearman 테이블, predictor 간 상관 히트맵 |
| §X+2 백테스트 결과 | 누적 수익 곡선, Alpha, Sharpe, Max Drawdown |
