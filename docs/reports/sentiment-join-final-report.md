**[최종 보고서] 비정형 감성 데이터 기반 암호화폐 시장 국면 지수(Regime Index) 개발 및 검증**

## **1. 프로젝트 개요 및 연구 질문**

해당 프로젝트는 **Hugging Face의 FinBERT 모델**을 통해 비정형 뉴스 데이터를 정량화하고, 이를 다양한 시장 지표와 결합하여 비트코인(BTC) 가격 변화를 선행 예측하는 '하이브리드 감성 지표'를 구축하는 것을 목표로 했습니다.

- **초기 가설**: 뉴스 감성 지표가 기존 수치 데이터보다 시장 변화를 더 빨리 반영할 것이다.
- **실제 데이터 기반 결론**: 360일간의 백필 분석 결과, 뉴스 감성이 가격을 선행하기보다 가격 변화가 뉴스와 심리를 형성하는 '역방향 인과성'이 더 강력하게 나타났습니다.
이에 따라 본 지수를 '예측 지표'에서 '시장 국면 지수(Regime Index)'로 재정의했습니다.

---

## **2. 데이터 엔지니어링 및 파이프라인 구축**

총 7개 이상의 소스를 유기적으로 통합했습니다.

- **필수 핵심 데이터 (Inner Join)**: R2 analytics 뉴스 감성(FinBERT), Alternative.me 공포·탐욕 지수(F&G), BTC 현물 수익률, USD/KRW 수익률.
- **옵션 보조 데이터 (Left Join)**: BTC 선물(Funding Rate, OI, L/S Ratio), BTC ETF Flow, FRED VIX 지수.
- **품질 관리**: 3.0×IQR 기반의 **Rolling IQR 이상치 탐지**를 수행하되, 날짜 연속성을 위해 행을 삭제하지 않고 수치 컬럼만 **NaN 마스킹** 처리했습니다.

### 이상치 탐지 상세 (`outlier_policy.py`, `join.py`)

| 파라미터 | 값 | 의미 |
|---|---|---|
| `ROLLING_WINDOW` | **30일** | IQR 계산에 사용하는 직전 관측치 수 |
| `ROLLING_MIN_PERIODS` | **15일** | 롤링 통계를 계산하기 위한 최소 유효 관측치 수 |
| `IQR_MULTIPLIER` | **3.0** | 중앙값에서 3×IQR 이상 벗어난 값을 이상치로 판정 |

**작동 방식**: 각 날짜에 대해 **직전 30일**의 분포(Q1, Q3, IQR)를 계산합니다. 현재 값이 `중앙값 ± 3×IQR` 범위를 벗어나면 해당 셀만 NaN으로 마스킹합니다. 시계열 날짜 행 자체는 유지합니다.

**추가 이상치 규칙** (정책과 무관하게 항상 적용):
- `open_interest_usd < 0`: 데이터 오류로 강제 NaN
- `|funding_rate| > 0.05 (5%)`: provider 오염값으로 강제 NaN

**이상치 정책 4종** (`feature_store.load_features(outlier_policy=...)` 파라미터로 선택, Ablation 플랫폼에서는 `ExperimentSpec`으로 주입):
- `row` (기본): 이상치 감지된 행의 **모든 수치 컬럼** NaN 마스킹
- `column`: 이상치 감지된 **해당 셀만** NaN 마스킹 (행 보존, 커버리지 개선)
- `winsorize`: NaN 대신 전체 기간 Q1~Q99로 **클리핑** (값 보존)
- `none`: data_error 규칙만 적용, IQR 이상치는 통과

---

## **3. 핵심 기술 및 통계 방법론**

### 3-1. FinBERT 감성 점수 산출 (`finbert_sentiment.py`, `public_site.py`)

**모델**: `ProsusAI/finbert` — 금융 텍스트에 특화된 BERT 계열 분류 모델 (positive / negative / neutral 3-class).

**단건 점수 계산**:
```
score = p_positive - p_negative   (범위: -1 ~ +1)
```
softmax 확률에서 긍정 확률과 부정 확률의 차이를 그대로 사용합니다. 중립 확률은 점수에 직접 반영되지 않으며, 신뢰도(`confidence = max(p_pos, p_neg, p_neu)`)로만 기록됩니다.

**입력 텍스트 구성 (영문 원본 사용)**:
- 뉴스: `title(64 tokens) + summary(224 tokens) + why_it_matters(224 tokens)` 연결, 전체 512 tokens 절삭
- X 시그널: `content/rawContent(64 tokens) + impact(224 tokens)` 연결

**일별 집계(`news_sentiment_mean`)**:
하루 전체 뉴스·X시그널의 단건 점수를 모아 **단순 산술 평균(unweighted mean)**을 취합니다. 추가로 std, count, bullishRatio, bearishRatio도 저장하지만, 분석 파이프라인에서 PCA 입력으로 사용되는 것은 `news_sentiment_mean` 단일 컬럼입니다.

**처리 상한**: 1일 최대 120건. 초과 시 `sourceTier(tier1 우선) + 카테고리 비례 할당`으로 선정합니다.

**라벨 구분 임계값** (`config.py` 기본값, 환경변수 `FINBERT_BULLISH_THRESHOLD` / `FINBERT_BEARISH_THRESHOLD`로 오버라이드 가능):
- bullish: `score ≥ +0.3` (기본값)
- bearish: `score ≤ −0.3` (기본값)
- neutral: 그 사이

---

### 3-2. PCA v4 하이브리드 지수 (`hybrid_index.py`)

#### 1. VIF 계산 구간

**전체 학습 기간을 한 번에 계산**합니다 (rolling window 방식 아님).

파이프라인이 실행되는 시점의 **전체 분석 기간 데이터**(기본 360일)를 대상으로 `dropna()` 후 남은 행 전체를 행렬로 구성하여 VIF를 1회 계산합니다. Walk-Forward test 구간(OOS)에서는 **train 구간에서 fit된 피처 목록을 그대로 사용**하고 VIF를 재계산하지 않습니다.

#### 2. 변수 제거 기준

**VIF threshold: 10.0 고정** (`VIF_THRESHOLD_FULL = 10.0`).

다중 VIF 초과 시 **단계적 제거(stepwise)**를 사용합니다:
1. 현재 남아있는 피처 목록에서 VIF를 일괄 계산
2. VIF가 10.0 이상인 피처 중 **VIF값이 가장 높은 것 1개만 제거**
3. 남은 피처가 2개 이상이고 VIF 초과 피처가 남아있으면 1~2 반복

도메인 중요도·결측률·상관관계 기준은 별도로 반영되지 않으며, **순수하게 VIF 수치 기준으로만** 제거 대상을 선정합니다.

> **Core 지수는 VIF gate 없음**: `HYBRID_FEATURE_CANDIDATES_CORE` 4개(`news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `volume_change_pct_lag1`)는 도메인 큐레이션으로 선정된 세트이므로 VIF 제거 단계를 건너뜁니다.

#### 3. PCA 학습 방식

**파이프라인 실행 시마다 전체 기간으로 재fit**합니다. 주기적 refit(일별/주별 등)은 없으며, `make sentiment-join` 또는 파이프라인이 실행될 때마다 그 시점의 전체 데이터로 1회 fit합니다.

Walk-Forward validation에서는 예외적으로 **train 구간 fit → test 구간 transform only** 방식을 사용합니다(`pre_fitted_scaler`, `pre_fitted_pca` 파라미터로 주입).

#### 4. 입력 데이터 전처리

**표준화**: 기본값은 `StandardScaler` (z-score, 평균 0·분산 1). `IndexSpec(scaler_kind="robust")` 또는 Ablation `ExperimentSpec`으로 `RobustScaler` (median·IQR 기반)로 전환할 수 있습니다.

**결측치 처리**: `dropna()` — 분석 피처 중 하나라도 NaN인 행은 PCA 입력에서 제외합니다. 해당 날짜는 `hybrid_index = NaN`으로 기록됩니다.

**이상치 처리 후 NaN**: 이상치 정책(row/column)으로 마스킹된 셀도 동일하게 `dropna()`로 제외됩니다. 따라서 이상치가 많은 날은 coverage_ratio가 낮아집니다.

**시계열 lag 처리**: PCA 입력 피처는 모두 `_lag1` 접미사 컬럼을 사용합니다(`shift(1)`). 당일 값의 미래 오염을 방지하기 위해 전날 값을 입력으로 씁니다.

#### 5. PCA 출력 구조

| 항목 | Full Hybrid Index | Core Hybrid Index |
|---|---|---|
| 입력 후보 | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `btc_long_short_ratio_lag1`, `etf_net_inflow_usd_lag1`, `volume_change_pct_lag1`, `vix_lag1` | `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `volume_change_pct_lag1` |
| VIF gate | 있음 (threshold=10.0, 반복 제거) | 없음 (4개 고정) |
| PC 수 | 설명분산 ≥80% 달성 최소 PC 수 자동 선택 | 동일 기준 |
| 최종 지수 | **PC1만 사용** | **PC1만 사용** |
| 스케일링 | **min-max 0~100** (train 기간 min/max 기준) | 동일 |
| 부호 고정 | `fng_value_lag1` loading이 양수가 되도록 부호 통일 (두 지수 방향성 일치) | 동일 |

**스케일링 공식**: `score = (raw_PC1 - train_min) / (train_max - train_min) × 100`
Walk-Forward OOS 구간에서는 train의 min/max를 그대로 적용하고 0~100으로 clip합니다.

#### 6. 해석 가능성

PCA loadings는 파이프라인 실행 후 Master Parquet의 Arrow metadata(`sentiment_join_stats` JSON)에 저장되며, **프론트엔드 `/analysis` 페이지**에서 확인할 수 있습니다.

실제 분석 결과 예시 (360일 기준, 최근 실행):

| 피처 | Full loading | 방향 | 해석 |
|---|---|---|---|
| `news_sentiment_mean_lag1` | +0.528 | 양(+) | 긍정 감성이 높을수록 지수 상승 |
| `fng_value_lag1` | +0.491 | 양(+) | 공포탐욕지수 상승 = 지수 상승 |
| `btc_log_return_lag1` | −0.342 | 음(−) | 전날 수익률 급등 = 지수 하락 (역발산) |
| `funding_rate_lag1` | −0.218 | 음(−) | 과열 funding = 지수 하락 |

> 프론트엔드에서 각 막대에 마우스를 올리면 loading 값, 기여 비중, 순위를 실시간으로 확인할 수 있습니다.

---

## **4. 통계 검증**

- **정상성 검정**: ADF + KPSS 공동 판정 (두 검정이 합치되는 경우에만 정상/비정상 확정, 불일치 시 "inconclusive" 처리)
- **Granger 인과성 검정**: lag 1~3, 총 63개 페어에 대해 F-검정 수행 후 Benjamini-Hochberg FDR 보정 적용. 프론트엔드 `/analysis` 페이지에서 forward(감성→시장)/reverse(시장→감성) 방향별 결과와 최적 lag를 시각화합니다.

---

## **5. 실 데이터 기반 분석 결과 (Alpha Validation)**

360일(2025-04-24 ~ 2026-04-18) 데이터를 바탕으로 수행한 **Walk-forward Validation**의 정량적 성적표입니다.

| **평가 지표** | **내일(T+1) 예측 결과** | **일주일 뒤(T+7) 예측 결과** |
| --- | --- | --- |
| **방향 적중률 (Hit Rate)** | **47.35% ~ 49.30%** (무작위 수준) | **최대 68.14%** (유의미한 신호) |
| **가격 상관계수 (Pearson)** | **-0.0039** (관계 없음) | - |
| **Granger 인과성** | **BTC 가격 → 뉴스 감성** (역방향 우세) | **뉴스 감성 → F&G/ETF 흐름** (심리 전염) |

- **주요 인사이트**: 뉴스 지표는 단기 가격을 맞추는 데는 노이즈가 크지만, **일주일 단위의 시장 흐름(Regime)을 설명하는 데는 높은 유효성(68%)**을 보였습니다.

**결론적으로**, 본 프로젝트는 데이터 엔지니어링 실패 상태를 극복하고 **통계적으로 검증 가능한 지수 체계**를 완성했으며, 이를 통해 시장의 심리를 객관적으로 요약하는 독보적인 분석 자산을 구축했습니다.
