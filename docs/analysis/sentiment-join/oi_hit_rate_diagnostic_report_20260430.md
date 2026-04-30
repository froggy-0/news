# OI Divergence Hit-Rate Diagnostic Report

작성일: 2026-04-30  
대상 master: `data/sentiment_join/master_20260430.parquet`  
주요 실험 결과: `data/sentiment_join/experiments/20260430-2207-dd4ca89`

## 1. 목적

OI-Price Divergence feature 추가 이후 hit-rate를 높이기 위한 다음 단계를 판단하기 위해,
다음 세 가지를 분리해서 확인했다.

- 오답 유형: false positive와 false negative가 어떤 국면에서 발생하는가
- threshold / neutral-zone: `score > 50` 고정 판단이 문제인가
- feature 추가 방향: 신규 지표를 바로 추가해도 되는 단계인가

결론부터 말하면, 신규 지표를 많이 추가하기 전에 `ExperimentRunner`의 hit-rate 계산 경로를 먼저 보정해야 한다.
현재 `net_sharpe`는 feature-set별 custom hybrid score를 반영하지만, `hit_rate`는 내부 `walk_forward_validate()`가 기본 `INDEX_SPECS`로 다시 계산하는 구조라 feature-set 효과가 섞인다.

## 2. 이미 적용된 개선

이번 작업에서 masking artifact는 제거했다.

- `row` outlier policy에서는 treatment feature가 row 전체 삭제를 유발하지 않도록 baseline mask columns를 사용한다.
- `masked_ratio` denominator를 `mask_cols` 수가 아니라 실제 maskable cell 수로 보정했다.
- `winsorize`가 nullable `Int64` 컬럼에서 실패하던 문제를 float clip으로 수정했다.

관련 파일:

- `src/morning_brief/analysis/sentiment_join/experiments.py`
- `src/morning_brief/analysis/sentiment_join/outlier_policy.py`
- `tests/test_experiment_runner.py`
- `tests/analysis/test_sentiment_join/test_outlier_policies.py`

보정 후 `row` 정책에서 feature-set별 `masked_ratio_delta`는 모두 `0.0000`이 되었고,
기존처럼 `oi_price_divergence_score_7d_lag1`가 추가 row mask를 만들어 성능을 띄우는 현상은 사라졌다.

## 3. 핵심 발견

### 3.1 Hit-rate에는 divergence보다 OI change가 더 유망

custom OOS 방식으로 feature-set별 score를 재계산했다.
기준은 T+7, `standard` scaler, 13 folds다.

| Cell | Fixed 50 Hit Rate | Baseline 대비 | Train-tuned Threshold Hit Rate |
|---|---:|---:|---:|
| `full + column + baseline` | 0.5510 | 기준 | 0.5374 |
| `full + column + oi_change_7d` | 0.5616 | +0.0106 | 0.5788 |
| `full + column + oi_divergence_flag_7d` | 0.5019 | -0.0491 | 0.4943 |
| `full + column + oi_divergence_score_7d` | 0.5061 | -0.0449 | 0.5020 |
| `full + winsorize + baseline` | 0.5319 | 기준 | 0.5213 |
| `full + winsorize + oi_divergence_score_7d` | 0.5266 | -0.0053 | 0.5426 |

해석:

- Hit-rate 개선 목적이라면 `open_interest_change_7d_lag1` 단독이 현재 가장 유망하다.
- divergence flag/score는 Sharpe나 payoff 구조에는 일부 도움이 될 수 있지만 hit-rate 개선 feature로는 약하다.
- `oi_divergence_all`은 여러 정책에서 hit-rate를 깎는 경향이 있어 promotion 후보로 보기 어렵다.

### 3.2 오답은 FN 쪽이 더 크다

`full + column + baseline` 기준 confusion:

- TP: 72
- TN: 90
- FP: 57
- FN: 75

FN이 FP보다 많다. 즉 현재 모델은 상승 반전을 놓치는 문제가 더 크다.

FN median 특징:

- `vix_lag1`: 19.86
- `fng_value_lag1`: 30
- `btc_long_short_ratio_lag1`: 1.7405
- `btc_realized_vol_20d_lag1`: 0.0232

FP median 특징:

- `vix_lag1`: 16.52
- `fng_value_lag1`: 64
- `btc_long_short_ratio_lag1`: 0.904
- `open_interest_change_7d_lag1`: +0.0268

해석:

- FN은 공포/고변동/롱숏 과열처럼 보이는 구간에서 실제 반등을 놓친다.
- FP는 risk-on처럼 보이지만 OI가 증가한 crowded long 구간에서 하락을 맞는다.

### 3.3 Neutral-zone은 우선순위가 낮다

오답이 `score` 50 근처에만 몰려 있지 않다.
`full + column + baseline`에서 `|score - 50| > 15` 구간 hit-rate는 0.5311에 그쳤고,
FP 40건, FN 58건이 발생했다.

따라서 단순 neutral-zone으로 애매한 신호만 제거하는 방식은 효과가 제한적이다.
문제는 threshold 근처 노이즈라기보다 국면별 calibration 실패에 가깝다.

### 3.4 Threshold는 fold별로 크게 흔들린다

`full + column + baseline`의 train-tuned threshold는 35~65까지 분산됐다.

예시:

- 2025-08~2025-10 구간은 threshold가 35 근처로 내려간다.
- 2025-03~2025-05, 2026-03 구간은 threshold가 58~65로 올라간다.

해석:

- 단일 고정 threshold `50`만의 문제는 아니다.
- fold별 시장 국면이 바뀌며 필요한 decision boundary가 이동한다.
- 다음 개선은 neutral-zone보다 regime-aware threshold가 더 맞다.

## 4. 현재 코드상 남은 주요 문제

`ExperimentRunner`의 fold-level `hit_rate`는 아직 custom feature-set score와 완전히 정렬되어 있지 않다.

원인:

- `ExperimentRunner._run_one()`은 feature-set별 custom `IndexSpec`으로 `enriched` score를 계산한다.
- 하지만 `walk_forward_validate()` 내부는 기본 `INDEX_SPECS`를 다시 가져와 score와 hit-rate를 계산한다.
- 그 결과 `net_sharpe`, `coverage`는 custom score 기반인데, `hit_rate`는 기본 index 성격이 섞일 수 있다.

다음 작업자는 이 문제를 먼저 고치는 것이 좋다.

추천 방향:

- `walk_forward_validate()`에 optional `specs` 또는 `index_spec` 인자를 추가한다.
- 또는 `ExperimentRunner` 내부에서 train/test score를 직접 계산하고 hit-rate도 같은 score로 산출한다.
- 수정 후 `full + column + oi_change_7d`의 hit-rate 개선이 유지되는지 다시 검증한다.

## 5. 다음 단계 제안

### Step 1. Hit-rate 계산 경로 보정

우선순위 1순위다.
현재 promotion 판단에서 `hit_rate`와 `net_sharpe`가 서로 다른 score 경로를 볼 수 있으므로,
feature 추가 전에 이 정합성을 맞춰야 한다.

검증 포인트:

- 동일 cell에서 `folds.parquet.hit_rate`와 직접 계산한 custom score hit-rate가 일치해야 한다.
- feature-set별 hit-rate가 실제로 달라져야 한다.
- 기존 `sharpe`, `net_sharpe`, `coverage`, `masked_ratio`는 하위 호환 유지.

### Step 2. `oi_change_7d`를 1순위 후보로 full grid 검증

현재 결과상 hit-rate 목적의 1순위 후보는 `oi_change_7d`다.

검증 명령 예시:

```bash
.venv/bin/python scripts/run_outlier_ablation.py \
  --master data/sentiment_join/master_20260430.parquet \
  --out-dir data/sentiment_join/experiments \
  --horizons 7 \
  --scalers standard,robust \
  --masks column,winsorize,none,row \
  --indices full,core \
  --feature-sets baseline,oi_change_7d
```

### Step 3. 신규 feature는 FP/FN 원인별로 좁게 추가

바로 여러 지표를 넣기보다 오답 유형에 대응하는 소수 후보만 넣는 것이 좋다.

FN 대응 후보:

- `btc_drawdown_7d_lag1`
- `vix_change_5d_lag1`
- `fng_rebound_3d_lag1`

목적: 공포/고변동 구간의 반등을 놓치는 문제 완화.

FP 대응 후보:

- `lsr_change_7d_lag1`
- `lsr_zscore_30d_lag1`
- `oi_change_7d_lag1 * btc_long_short_ratio_lag1`

목적: risk-on처럼 보이지만 crowded long인 구간의 false positive 완화.

### Step 4. Regime-aware threshold 실험

단일 `score > 50` 대신 국면별 threshold를 검증한다.

후보:

- high VIX / low VIX 분리 threshold
- high LSR / low LSR 분리 threshold
- rolling median threshold
- 최근 120일 train 기준 quantile threshold

단, threshold는 반드시 train fold에서만 선택하고 test fold에 적용해야 한다.

## 6. 추천 의사결정

현재 단계에서의 추천은 다음과 같다.

- 신규 지표 추가는 가능하지만, 먼저 hit-rate 계산 정합성을 고친다.
- divergence score/flag는 hit-rate 개선용으로는 보류한다.
- `oi_change_7d`를 다음 promotion 후보로 둔다.
- 신규 feature는 FN rebound detector와 FP crowding filter로 나눠 소수만 추가한다.
- neutral-zone은 우선순위 낮음. 문제는 애매한 score가 아니라 regime calibration이다.

## 7. 재현/검증 명령

관련 테스트:

```bash
.venv/bin/python -m pytest \
  tests/test_experiment_runner.py \
  tests/analysis/test_sentiment_join/test_outlier_policies.py \
  tests/test_variance_report.py \
  -v
```

정책별 corrected ablation:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_outlier_ablation.py \
  --master data/sentiment_join/master_20260430.parquet \
  --out-dir data/sentiment_join/experiments \
  --horizons 7 \
  --scalers standard \
  --masks row,column,winsorize,none \
  --indices full,core
```

현재 로컬 기준 최신 corrected artifact:

- `data/sentiment_join/experiments/20260430-2207-dd4ca89/folds.parquet`
- `data/sentiment_join/experiments/20260430-2207-dd4ca89/summary.md`
- `data/sentiment_join/experiments/20260430-2207-dd4ca89/tracking.json`
