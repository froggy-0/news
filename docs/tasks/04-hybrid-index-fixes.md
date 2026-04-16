# 3순위: 하이브리드 지수 모델링 — 코드 리뷰 결과

> 1순위(Lag-1, 백필 동기화), 2순위(ADF/Granger 엄밀성, 백필 JSON 구조) 완료 후 적용

---

## 현재 구현 상태 요약

`compute_hybrid_index` (`hybrid_index.py`) 흐름:

```
후보 변수 선별 → 수치형 변환 + dropna → VIF 반복 제거(≥10)
→ StandardScaler → PCA(누적 분산 ≥80%) → 첫 번째 주성분 = hybrid_index
```

### ✅ 이미 올바른 부분

| 항목 | 구현 | 코드 위치 |
|---|---|---|
| VIF 반복 제거 | 가장 높은 VIF 변수를 하나씩 제거, 임계값 10.0 | `_select_low_vif_features` |
| StandardScaler 정규화 | VIF 계산과 PCA 모두에 적용 | `_select_low_vif_features`, `compute_hybrid_index` |
| 누적 설명 분산 자동 선택 | ≥80% 달성하는 최소 주성분 수 | `np.searchsorted(cumvar, 0.80)` |
| loadings 기록 | 변수별 PC1 기여 가중치를 메타데이터에 저장 | `pca_summary.loadings` |
| 최소 변수/행 수 게이트 | 변수 < 2 또는 행 < 10이면 NaN | 3단계 분기 |
| VIF 진단 로그 | 매 반복마다 구조화 로그 | `stats.vif_diagnostics` |

---

## 🔴 개선 필요: 0~100 스케일링 없음

### 현상

현재 `hybrid_index`는 PCA 첫 번째 주성분의 **원시 값**(StandardScaler 후 PCA 투영)입니다. 범위가 고정되어 있지 않고, 데이터에 따라 음수~양수 임의 범위를 가집니다.

```python
# hybrid_index.py:170
result.loc[clean_idx, "hybrid_index"] = components[:, 0]  # 원시 PC1 값
```

가이드라인은 **0~100 사이의 '소버린 하이브리드 감성 지표'**를 요구합니다.

### 수정 방안

PCA 투영 후 rolling window 기반 min-max 스케일링을 적용합니다:

```python
raw_pc1 = components[:, 0]
# 전체 기간 min-max → 0~100
pc1_min, pc1_max = raw_pc1.min(), raw_pc1.max()
if pc1_max - pc1_min > 0:
    scaled = (raw_pc1 - pc1_min) / (pc1_max - pc1_min) * 100
else:
    scaled = np.full_like(raw_pc1, 50.0)
result.loc[clean_idx, "hybrid_index"] = scaled
```

메타데이터에 `pc1_min`, `pc1_max`를 기록하면 새 데이터 추가 시 동일 스케일로 변환할 수 있습니다.

수정 대상:

| 파일 | 변경 |
|---|---|
| `hybrid_index.py` | PC1 → 0~100 min-max 스케일링 추가 |
| `validate.py` | `MASTER_SCHEMA`의 `hybrid_index`에 `Check.between(0, 100)` 추가 |
| `intelligence.py` | `_hybrid_signal_label`의 z-score 기반 해석을 0~100 기준으로 조정 |
| `pipeline.py` | 동일 함수 조정 |

---

## 🔴 개선 필요: PC1 부호 안정성 미보장

### 현상

PCA의 첫 번째 주성분은 **부호가 임의적**입니다. 같은 데이터라도 라이브러리 버전이나 수치 오차에 따라 PC1의 부호가 뒤집힐 수 있습니다. 현재 부호 보정(sign convention) 로직이 없습니다.

### 문제

- 어떤 run에서는 `hybrid_index` 높음 = risk-on, 다른 run에서는 높음 = risk-off가 될 수 있음
- `_hybrid_signal_label`이 z-score ≥ 0.5를 `risk_on`으로 해석하는데, PC1 부호가 뒤집히면 의미가 반전됨
- 시계열 연속성이 깨짐

### 수정 방안

PC1의 부호를 `fng_value` loading 기준으로 고정합니다. F&G Index는 높을수록 탐욕(risk-on)이므로, `fng_value`의 loading이 양수가 되도록 보정합니다:

```python
if "fng_value" in selected:
    fng_idx = selected.index("fng_value")
    if pca_final.components_[0, fng_idx] < 0:
        components[:, 0] *= -1
        pca_final.components_[0] *= -1
```

`fng_value`가 VIF 제거로 빠진 경우에는 `news_sentiment_mean` 등 다른 앵커 변수를 사용합니다.

---

## 🟡 개선 필요: VIX 후보 변수 미포함

### 현상

가이드라인에서 "F&G 지수, 뉴스 점수, VIX 중 서로 겹치는 정보가 있는지 VIF로 확인"을 요구하지만, 현재 `HYBRID_FEATURE_CANDIDATES`에 VIX가 없습니다:

```python
HYBRID_FEATURE_CANDIDATES = [
    "news_sentiment_mean",
    "fng_value",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",
    "etf_net_inflow_usd_lag1",
]
# VIX 없음
```

VIX는 Market Packet에는 수집되지만 sentiment-join 마스터 테이블에는 합류하지 않습니다.

### 수정 방안

1순위 Lag-1 수정과 함께 VIX를 sentiment-join 소스로 추가합니다:

| 파일 | 변경 |
|---|---|
| `pipeline.py` | VIX 수집 소스 추가 (FRED `VIXCLS` — 이미 `fetch_macro_points`에 구현됨) |
| `join.py` | `merge_sources`에 VIX DataFrame 조인 |
| `hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES`에 `"vix_lag1"` 추가 |
| `validate.py` | `MASTER_SCHEMA`에 `vix`, `vix_lag1` 컬럼 추가 |
| `statistical_tests.py` | `ADF_TARGETS`에 `vix` 추가 (선택) |

---

## 🟡 개선 필요: `_hybrid_signal_label` 중복 구현

### 현상

`_hybrid_signal_label`이 두 곳에 별도 구현되어 있습니다:

| 파일 | 반환 타입 | z-score 반환 |
|---|---|---|
| `pipeline.py:91-106` | `str \| None` | ❌ |
| `intelligence.py:56-72` | `tuple[str, float \| None]` | ✅ |

로직은 동일(z-score ±0.5 기준)하지만 시그니처가 다릅니다. 한쪽을 수정하면 다른 쪽을 놓칠 위험이 있습니다.

### 수정 방안

`intelligence.py` 버전을 정본으로 하고, `pipeline.py`에서 import하여 재사용합니다.

---

## 수정 우선순위 (3순위 내)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **3-1** | 0~100 스케일링 (§1) | 🔴 가이드라인 핵심 요구사항 | 중 |
| **3-2** | PC1 부호 안정성 (§2) | 🔴 시계열 해석 신뢰도 | 저 |
| **3-3** | VIX 후보 변수 추가 (§3) | 🟡 가이드라인 명시 항목 | 중 |
| **3-4** | `_hybrid_signal_label` 중복 제거 (§4) | 🟢 유지보수 | 저 |
