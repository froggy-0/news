# 3순위: 하이브리드 지수 모델링 — 최신 코드 기준 정리

> 2026-04-18 기준 업데이트.
> 이 문서는 최초 리뷰안에서 **이미 반영된 항목**과 **아직 진행할 가치가 있는 항목**을 다시 분리한 최신 버전입니다.

---

## 현재 구현 상태 요약

`compute_hybrid_index` (`src/morning_brief/analysis/sentiment_join/hybrid_index.py`) 흐름:

```text
후보 변수 선별
→ 수치형 변환 + dropna
→ VIF 반복 제거 (>= 10)
→ StandardScaler
→ PCA (누적 설명 분산 >= 80%)
→ PC1 부호 정규화 (fng_value_lag1 loading 양수 고정)
→ raw PC1 값을 hybrid_index로 저장
```

### ✅ 이미 반영된 부분

| 항목 | 현재 상태 | 코드 위치 |
|---|---|---|
| VIF 반복 제거 | 구현 완료 | `hybrid_index.py:_select_low_vif_features` |
| StandardScaler 정규화 | 구현 완료 | `hybrid_index.py:_select_low_vif_features`, `compute_hybrid_index` |
| 누적 설명 분산 자동 선택 | 구현 완료 | `hybrid_index.py:164-169` |
| loadings 기록 | 구현 완료 | `hybrid_index.py:174-205` |
| 최소 변수/행 수 게이트 | 구현 완료 | `hybrid_index.py:103-158` |
| PC1 부호 안정화 | **이미 구현 완료** | `hybrid_index.py:177-184` |
| feature schema version 기록 | 구현 완료 | `hybrid_index.py:25-30`, `197-207` |
| `volume_change_pct_lag1` 후보 추가 | 구현 완료 (`v3`) | `hybrid_index.py:16-28` |

### ✅ 이미 맞지 않는 옛 제안

기존 문서의 아래 항목은 더 이상 "개선 필요"가 아닙니다.

1. **PC1 부호 안정성 미보장**
현재는 `HYBRID_SIGN_ANCHOR = "fng_value_lag1"` 기준으로 부호 정규화가 들어가 있습니다.

2. **후보 변수 목록이 옛 버전**
현재 후보는 raw `news_sentiment_mean`, `fng_value`가 아니라 lag1 기반 `v3` 스키마입니다.

---

## 🔴 여전히 중요: 0~100 스케일링은 필요하지만 `hybrid_index` 원본을 덮어쓰면 안 됩니다

### 현재 상태

현재 `hybrid_index`는 raw PC1 값입니다.

```python
# hybrid_index.py:197
result.loc[clean_idx, "hybrid_index"] = components[:, 0]
```

이 값은 run마다 범위가 달라질 수 있어 UI/리포트에 직접 노출하면 해석이 불편합니다.

### 수정 방향

기존 문서처럼 `hybrid_index` 자체를 0~100으로 덮어쓰는 것은 권장하지 않습니다.

이유:

- raw 분석 지표와 표시용 score가 섞입니다.
- 새 데이터가 들어올 때 min/max가 바뀌면 과거 값 의미가 흔들립니다.
- 기존 parquet 비교와 migration 부담이 커집니다.

### 권장안

`hybrid_index`는 **raw PC1 그대로 유지**하고, 별도 `hybrid_index_score`를 추가합니다.

예시:

```python
raw_pc1 = components[:, 0]
pc1_min, pc1_max = raw_pc1.min(), raw_pc1.max()
if pc1_max - pc1_min > 0:
    score = (raw_pc1 - pc1_min) / (pc1_max - pc1_min) * 100
else:
    score = np.full_like(raw_pc1, 50.0)

result.loc[clean_idx, "hybrid_index"] = raw_pc1
result.loc[clean_idx, "hybrid_index_score"] = score
```

메타데이터에는 최소 아래 값을 함께 저장합니다.

- `pc1_min`
- `pc1_max`
- `score_scale_method`
- `hybrid_index_score_schema_version`

수정 대상:

| 파일 | 변경 |
|---|---|
| `hybrid_index.py` | `hybrid_index_score` 생성 |
| `validate.py` | `hybrid_index_score`를 `0~100` 범위로 스키마 추가 |
| `pipeline.py` | raw index와 score를 함께 메타에 기록 |
| `intelligence.py` | UI/리포트용 해석은 score 우선 사용 검토 |

---

## 🔴 새로 중요: feature sparsity 때문에 `hybrid_index` coverage가 너무 낮습니다

### 현재 상태

2026-04-18 parquet 기준:

- 전체 행: `180`
- `hybrid_index` non-null: `25`
- PCA feature complete rows: 약 `29`

즉, 현재의 더 큰 문제는 "0~100 미스케일링"보다 **지수가 너무 드물게 계산된다**는 점입니다.

### 원인

현재 구현은 PCA 후보 변수 전체가 존재하는 행만 사용합니다.

```python
# hybrid_index.py:123-124
clean_idx = work.dropna().index
df_clean = work.loc[clean_idx]
```

그리고 실제 운영 데이터에서 아래 feature들이 매우 sparse 합니다.

- `open_interest_usd`
- `btc_long_short_ratio`
- `etf_total_aum_usd`
- `etf_net_inflow_usd_lag1`

### 수정 방향

`hybrid_index`를 계속 운영 신호로 쓸 생각이라면, VIX 추가보다 먼저 **degradation path**를 설계해야 합니다.

권장안:

1. `full_hybrid_index`
   - 선물/ETF feature 포함 full feature set
2. `core_hybrid_index`
   - 뉴스 감성 + F&G + funding + volume 같은 상대적으로 coverage 높은 핵심 feature만 사용
3. 메타데이터에 coverage 기록
   - `hybrid_index_coverage_rows`
   - `hybrid_index_coverage_ratio`
   - `selected_features`

이렇게 하면 sparse한 날에도 core 지수는 유지하고, full 지수는 품질 좋은 구간에서만 비교할 수 있습니다.

---

## 🟡 여전히 유효: VIX 후보 변수 추가

### 현재 상태

VIX는 아직 sentiment-join 마스터 테이블과 hybrid feature set에 포함되지 않습니다.

이 제안은 여전히 유효합니다. 다만 **우선순위는 기존 문서보다 낮춰야** 합니다.

이유:

- 현재 병목은 VIX 부재보다 feature sparsity와 coverage 부족입니다.
- VIX를 추가해도 결측 구조가 개선되지 않으면 실제 hybrid coverage는 크게 늘지 않을 수 있습니다.

### 진행 조건

VIX를 추가한다면 아래 원칙으로 진행합니다.

1. `optional feature`로 추가
2. 없다고 파이프라인이 깨지지 않아야 함
3. `feature_schema_version`을 올리고 migration 영향 명시

수정 대상:

| 파일 | 변경 |
|---|---|
| `pipeline.py` | VIX 수집/주입 |
| `join.py` | VIX 조인 |
| `hybrid_index.py` | `vix_lag1` 후보 추가 |
| `validate.py` | `vix`, `vix_lag1` 컬럼 추가 |
| `statistical_tests.py` | 필요 시 `ADF_TARGETS` 확장 |

---

## 🟡 여전히 유효: `_hybrid_signal_label` 중복 제거

### 현재 상태

아직 두 곳에 중복 구현이 있습니다.

| 파일 | 반환 타입 |
|---|---|
| `pipeline.py:104-119` | `str \| None` |
| `intelligence.py:56-72` | `tuple[str, float \| None]` |

로직은 거의 같지만 시그니처가 달라 drift 위험이 있습니다.

### 권장안

`intelligence.py` 버전을 정본으로 두고 공용 함수로 추출합니다.

예시 후보:

- `analysis/sentiment_join/signals.py`
- 또는 `intelligence.py`에 두고 `pipeline.py`에서 import

---

## 수정 우선순위 (최신판)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **3-1** | feature sparsity 대응 / degradation path | 🔴 운영 활용성 핵심 | 중~상 |
| **3-2** | `hybrid_index_score` 추가 (raw 유지) | 🔴 해석 가능성 개선 | 중 |
| **3-3** | `_hybrid_signal_label` 중복 제거 | 🟡 유지보수 / drift 방지 | 저 |
| **3-4** | VIX optional feature 추가 | 🟡 모델 확장 | 중 |

---

## 권장 결론

현재 기준에서는 아래 순서가 안전합니다.

1. `hybrid_index` raw 값은 유지
2. 별도 `hybrid_index_score` 도입
3. sparse feature 대응 설계
4. 그 다음 VIX 추가

즉, 원래 문서의 핵심 아이디어 중 일부는 여전히 좋지만, **"PC1 부호 안정성"은 이미 완료**, **"0~100 스케일링"은 raw overwrite 대신 별도 score**, **"VIX 추가"보다 "coverage 개선"이 더 우선**으로 보는 것이 현재 코드 상태에 맞습니다.
