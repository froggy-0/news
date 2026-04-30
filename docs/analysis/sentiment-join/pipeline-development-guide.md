# Sentiment Join Pipeline — 개발 가이드 (2026-04-30)

이 문서는 파이프라인에 기여하거나 신규 피처를 추가하는 모든 작업자를 위한 레퍼런스입니다.  
세 가지 주제를 다룹니다: **주의사항**, **신규 피처 추가 체크리스트**, **현재 보강 필요 항목**.

---

## 1. 주의사항 (Cautions)

### 1-1. `analysis_df` ↔ `master_df` 이중 구조 동기화

`pipeline.py`는 두 개의 DataFrame을 유지합니다.

| DataFrame | 역할 | 저장 위치 |
|-----------|------|-----------|
| `master_df` | 원시 join 결과 — 스키마 검증 대상 | `.parquet` 파일 |
| `analysis_df` | 아웃라이어 마스킹 + 파생 피처 추가 | 분석 전용, 메모리 내 |

**규칙**: `analysis_df`에서만 생성되는 컬럼(예: `etf_net_inflow_usd_log1p`, `usdkrw_gap_flag`)은  
`master_df`에 date-key 매핑으로 **반드시 역동기화** 해야 합니다.  
그렇지 않으면 parquet 재로드 시 컬럼이 유실됩니다.

```python
# 역동기화 패턴 (pipeline.py 참고)
for _col in ("etf_net_inflow_usd_log1p", "etf_net_inflow_usd_log1p_lag1"):
    _map = analysis_df.set_index("date")[_col].to_dict()
    master_df[_col] = master_df["date"].map(_map)
```

### 1-2. Pandera `strict=True` 스키마 업데이트

`validate.py`의 `MASTER_SCHEMA`는 `strict=True`로 선언되어 있어  
**스키마에 없는 컬럼이 DataFrame에 있으면 즉시 실패**합니다.

새 컬럼을 추가할 때는 **반드시** `validate.py`에도 등록해야 합니다.  
기존 parquet에 없을 수 있는 컬럼은 `required=False`를 사용합니다.

```python
# validate.py — 신규 컬럼 등록 예시
"my_new_feature": pa.Column(float, nullable=True, required=False),
"my_new_feature_lag1": pa.Column(float, nullable=True, required=False),
```

`strict=True`는 역방향도 체크합니다: 스키마에 선언된 non-`required=False` 컬럼이  
DataFrame에 없으면 실패합니다. 테스트 fixture가 최소 DataFrame인 경우 주의하세요.

### 1-3. Stability Gate — NaN 처리 규칙

`variance.py`의 `evaluate_promotion_gate`는 다음 조건으로 `stability_ok`를 판정합니다:

```python
stability_ok = not math.isfinite(stability) or stability >= GATE_MIN_STABILITY
```

`stability`가 `NaN`(데이터 부족, 피처 미정의)이면 **게이트를 통과**시킵니다.  
이는 walk-forward가 불가능한 비hybrid 예측자에 대해 `temporal_fold_stability`가 먼저 fallback됩니다.  
`NaN >= 0.50`은 `False`이므로 이전 단순 비교는 오류였습니다.

### 1-4. Bootstrap Block Length 유효성

`bootstrap.py`의 circular block bootstrap은 `block_length=14`(T+7 horizon × 2)를 기본값으로 씁니다.  
**블록 길이는 분석 horizon과 함께 조정되어야 합니다**: 새 horizon을 추가하면 `block_length = 2 × horizon`을 권장합니다.  
현재 block_length의 통계적 타당성(ACF 기반 검증)은 아직 미구현 상태입니다(§ 3-3 참고).

### 1-5. Sharpe 연율화 인수 통일

BTC는 24/7 거래이므로 `ANNUALIZATION_FACTOR = 365`를 사용합니다.  
새 코드에서 `252`(주식 기준)를 쓰면 Sharpe 값이 과소 추정되어 게이트 통과 판정이 달라집니다.  
`variance.py` 상단의 상수를 반드시 import해서 사용하세요.

```python
from morning_brief.analysis.sentiment_join.variance import ANNUALIZATION_FACTOR
```

### 1-6. Paired Bootstrap — Active Row 정렬

`bootstrap_paired`는 signal과 baseline이 **동일한 resample 인덱스**를 씁니다.  
`_signal_hits_series`와 `_baseline_hits_series` 모두 `btc_direction_label != "flat"` 필터를 적용한  
동일한 active row set에서 계산되어야 합니다. baseline만 다른 필터를 쓰면 resampled 행이 불일치합니다.

---

## 2. 신규 피처 추가 체크리스트

신규 예측 피처(predictor) 또는 시장 데이터 컬럼을 추가할 때 아래 단계를 순서대로 완료합니다.

### Step 1: 데이터 수집 / 파이프라인 등록

- [ ] `pipeline.py`의 `merge_sources()` 함수에 데이터 소스 병합 로직 추가
- [ ] `analysis_df`에서만 파생되는 컬럼이라면 `master_df` 역동기화 코드 추가 (§ 1-1 참고)

### Step 2: Lag-1 생성 + NaN 불변량 보장

- [ ] 시계열 예측에 사용할 피처는 `*_lag1` 컬럼을 생성해야 합니다
- [ ] Lag-1 컬럼의 **첫 번째 날짜 행은 반드시 NaN**이어야 합니다 (lookahead 방지)
- [ ] `validate.py`의 `_check_lag1_first_row_nan()`이 이를 자동 감사합니다

```python
df["my_feature_lag1"] = df["my_feature"].shift(1)
# shift(1) 결과로 첫 행은 자동 NaN — 별도 처리 불필요
```

### Step 3: Pandera 스키마 등록 (`validate.py`)

- [ ] `MASTER_SCHEMA`에 원본 컬럼과 lag1 컬럼 모두 추가
- [ ] 기존 parquet fixture에 없을 수 있는 컬럼은 `required=False` 사용
- [ ] 적절한 dtype과 Check 조건 설정 (음수 불가라면 `pa.Check.ge(0)` 등)

### Step 4: 예측자 설정 등록 (`statistical_tests.py`)

alpha 분석 대상 예측자는 `_ALPHA_PREDICTOR_CONFIGS` 딕셔너리에 등록합니다:

```python
"my_feature_lag1": {
    "label": "My Feature",
    "threshold": 0.0,       # 이 값 초과 시 "up" 예측
    "inverted": False,      # True이면 threshold 미만 시 "up" 예측
    "horizon": "1d",        # 또는 "3d", "7d"
},
```

`threshold`와 `inverted` 설정은 도메인 지식에 기반해야 합니다.  
방향성이 불명확한 피처는 별도 연구 후 추가를 권장합니다.

### Step 5: 안정성 자동 계산 확인

- 새 예측자에 대해 `_temporal_fold_stability`가 자동으로 fallback 계산됩니다 (5-fold)
- fold별 hit_rate의 변동계수(std/|mean|)로 안정성을 추정합니다
- 데이터가 100행 미만(`n_folds × min_fold_rows`)이면 `NaN`을 반환하고 게이트를 통과시킵니다 (§ 1-3)

### Step 6: 테스트 추가

- [ ] `validate.py` 테스트 fixture에 신규 컬럼 추가 불필요 (`required=False` 덕분)
- [ ] `statistical_tests.py` 테스트에 새 예측자 설정 포함 여부 확인
- [ ] `423 passed` 기준선 유지

---

## 3. 현재 보강 필요 항목 (Current Gaps)

아래 항목들은 현재 파이프라인의 known limitation입니다.  
신규 피처나 신호가 이 한계에 부딪힐 가능성이 높으므로 사전에 파악해두세요.

### 3-1. vol_regime Baseline 지배 문제 ★ 최우선

실제 데이터(2024-11-06 ~ 2026-04-30, N=540) 분석 결과:

| 항목 | 값 |
|------|-----|
| vol_regime baseline HR | 0.549 |
| vol_regime baseline Sharpe | 2.569 |
| 현재 신호 중 baseline 초과 HR | 0 / 17 |
| 현재 신호의 HR delta 범위 | -0.002 ~ -0.077 |

**의미**: 현재 모든 alpha 신호가 VIX 60일 median regime보다 약합니다.  
신규 피처는 vol_regime과 **낮은 상관관계**(orthogonality)를 가진 방향으로 탐색해야 합니다.

**권장 방향**:
- ETF net inflow + VIX 조합 (유동성 × 공포 이중 필터)
- 온체인 지표 (exchange net flow, miner reserve)
- 뉴스 감성의 VIX-조건부 변종

### 3-2. FDR q-value 전반적 고평가

현재 17개 예측자 전부 `fdr_q ≈ 0.967`입니다. 통계적으로 유의미한 신호가 없습니다.

원인: 현 신호들의 bootstrapped p-value가 모두 0.95~1.0 범위라 BH 보정 후에도 기각 불가.

보강 방향:
- 신호가 유의미해지면 FDR 보정은 자동으로 작동합니다
- 현재 `benjamini_hochberg()` 구현 자체는 정상입니다

### 3-3. Walk-Forward Stability — hybrid 외 미구현

`_walk_forward_stability()`는 `full_hybrid_index_score_lag1`과 `core_hybrid_index_score_lag1`에 대해서만  
실제 walk-forward를 수행합니다. 나머지 예측자는 `NaN`을 반환하고  
`_temporal_fold_stability`(5-fold 단순 분할)로 fallback됩니다.

Walk-forward가 필요한 이유: temporal fold는 피처 선택 bias를 제거하지 못합니다.  
비hybrid 예측자에 대한 실제 expanding-window walk-forward 구현이 필요합니다.

### 3-4. Bootstrap Block Length 통계적 검증 미구현

`block_length=14`는 `2 × T+7 horizon` 경험칙으로 설정됐습니다.  
BTC 수익률의 실제 ACF(자기상관함수)를 기반으로 한 최적 block_length 선택이 필요합니다.

```
권장 구현: np.correlate로 ACF 계산 → first zero crossing 지점을 block_length로 사용
```

### 3-5. 프론트엔드 CI 시각화 미완성

`evaluate_promotion_gate()`는 `hr_ci_low`, `hr_ci_high` 등 CI 경계값을 반환하지만,  
프론트엔드에서 이를 시각화하는 컴포넌트가 아직 없습니다.

CI 시각화가 있으면 `decision_strict` 판정 근거를 운영자가 직관적으로 확인할 수 있습니다.

### 3-6. 단기 데이터 편향

현재 분석 기간: 2024-11-06 ~ 2026-04-30 (약 18개월, N≈540).  
2024-11 이후는 BTC 상승장이 주였으므로 bear regime 신호의 검증이 부족합니다.  
`btc_bear_regime_lag1` 등 약세장 조건 피처의 유효성은 추후 하락장 데이터 확보 후 재평가가 필요합니다.

---

## 빠른 참조

| 파일 | 역할 |
|------|------|
| `pipeline.py` | 데이터 join, analysis_df 파생, master_df 역동기화 |
| `validate.py` | Pandera 스키마 (`MASTER_SCHEMA`, `strict=True`) |
| `statistical_tests.py` | Alpha 평가, `_ALPHA_PREDICTOR_CONFIGS`, bootstrap 호출 |
| `variance.py` | Promotion gate (`evaluate_promotion_gate`), 임계값 상수 |
| `bootstrap.py` | Circular block bootstrap, batched RNG, BH-FDR |
| `experiments.py` | Hybrid index 실험 grid (80 combinations) |

---

*작성: 2026-04-30. 파이프라인 버전: `3367e1e` 이후 적용 변경사항 반영.*
