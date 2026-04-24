# OUTLIER_POLICY_REVIEW — IQR vs Winsorize 결정 분석
> 작성일: 2026-04-24 | 대상 파이프라인: `sentiment_join` | 기준 데이터: master_20260419.parquet (360 rows)

---

## 1. 현황 요약

| 지표 | 값 |
|---|---|
| 전체 행 | 360 |
| `outlier_filtered_count` | 74 |
| `outlier_filtered_ratio` | **20.56%** |
| `full_hybrid_index` 커버리지 | **283/360 = 78.61%** |
| `core_hybrid_index` 커버리지 | **284/360 = 78.89%** |
| 결측 비율 (hybrid 기준) | **~21.4%** |

현재 기본 정책은 `row` 모드: 하나의 컬럼에서라도 IQR×3 이상치가 검출되면 **해당 행 전체 수치 컬럼**을 NaN 처리. 결과적으로 PCA 입력에서 `dropna()`로 탈락.

---

## 2. 핵심 질문: IQR 배수 상향 vs Winsorize

### 2-1. IQR 배수를 3.0 → 4.0~5.0으로 올리는 경우

**장점**
- 구조 변경 없음, 코드 1줄 (`IQR_MULTIPLIER`)
- 마스킹 행이 줄어 커버리지 직접 개선
- 극단값을 실제로 보존

**단점/위험**
- 금융 시계열에서 3.0 IQR은 이미 매우 관대한 기준 (정규분포 기준 3σ ≒ 2.0 IQR)
- 4.0~5.0은 사실상 이상치를 거의 탐지하지 못함 → 정책의 의미가 사라짐
- 근본 원인을 해결하지 않고 증상만 완화
- `post-backfill-review`의 "극단값이 신호" 지적과 상충: 마스킹 대상이 줄어도 PCA 수렴 불안정 리스크 존재

**결론: 권장하지 않음.** 배수 조정은 임시방편이며 통계적 근거가 없다.

---

### 2-2. Winsorize (`q01/q99` clip) 정책으로 전환하는 경우

현재 코드: `outlier_policy.py:281` `WinsorizePolicy`가 이미 구현되어 있음.

```python
# outlier_policy.py:37-38
WINSOR_LOW_Q = 0.01
WINSOR_HIGH_Q = 0.99
```

**장점**
- NaN 마스킹이 없으므로 **커버리지 100% 유지** (data_error 제외)
- 극단값을 제거하지 않고 분포 내로 압축 → PCA 수렴 안정
- 이미 구현됨, 파라미터 1개 변경으로 실험 가능

**금융 데이터에서의 부정적 측면 — 실제 위험도**

| 우려 | 실제 영향 | 판단 |
|---|---|---|
| 진짜 이상치(급락/급등)를 왜곡 | **크다** — 그러나 이 파이프라인은 예측 모델이 아닌 Regime Index | 허용 가능 |
| 2026-04-13/17/18 같은 시장 스트레스 날을 인위적으로 완화 | **있음** — 하지만 현재 `row` 정책은 해당 날을 아예 NaN 처리함 | Winsorize가 오히려 낫다 |
| 알파 신호 목적에 부적합 | **맞다** — 그러나 현재 hit rate가 47~49%로 알파가 없음 | 알파 신호 기준은 지금 적용 불가 |
| q01/q99가 너무 좁다 | rolling이 아닌 전체 기간 분위수 사용 → 룩어헤드 바이어스 있음 | **이것이 실제 문제** |

**Winsorize의 실제 문제: 룩어헤드 바이어스**

`WinsorizePolicy.apply()`는 전체 기간 `q_low = series.quantile(0.01)`로 clip.
이는 미래 데이터를 참조하여 과거 값을 클리핑하는 것 → 시뮬레이션/walk-forward 결과를 낙관적으로 오염시킬 수 있음.

→ 현재 용도(Regime Index, 분석 목적)에서는 허용 가능하지만, 알파 검증 시에는 반드시 rolling-window winsorize로 교체해야 함.

---

## 3. 이상치의 실제 성격: 데이터 오류 vs 시장 스트레스

`post-backfill-review`에서 이미 지적됨:

> "In financial time series, extreme rows are often the signal, not merely bad data."

`run-issues-20260418.md`의 이상치 감지 날짜: `2026-04-13/14/15/16/17` — 이 기간은 BTC 급락 이벤트와 일치.

**현재 `row` 정책의 실질적 결함**:
- 데이터 오류(`open_interest_usd < 0`, `|funding_rate| > 0.05`)와 시장 스트레스(BTC 급락)를 동일하게 처리
- 시장이 가장 격변할 때 Regime Index가 NaN → 가장 필요한 순간에 신호 없음

이미 `outlier_policy.py:16-17`에 `Reason` 타입 정의가 있고, `ColumnMaskPolicy`에 `regime_stress` 분류가 구현되어 있음.

---

## 4. 정책별 커버리지 예측

| 정책 | hybrid 커버리지 예측 | NaN 방식 | 비고 |
|---|---|---|---|
| `row` (현재) | ~78% | 행 전체 NaN | 기본값 |
| `column` | **~85~90%** | 셀 단위 NaN | regime_stress 보존 |
| `winsorize` | **~97~99%** | NaN 없음 (clip) | 룩어헤드 바이어스 주의 |
| `none` | ~99% | data_error만 NaN | 이상치 미처리 |
| IQR × 4.0 (`row`) | ~85% | 행 전체 NaN | 임시방편 |

---

## 5. 권고사항

### 단기 실험 (즉시 가능)

1. **`column` 정책 우선 테스트** — `regime_stress` 보존 로직이 이미 구현됨
   ```python
   feature_store.load_features(outlier_policy="column")
   ```
   기대: 커버리지 ~85~90%, 시장 스트레스 날 보존, 룩어헤드 없음

2. **`winsorize` 정책 비교 실험** — 커버리지 최대화가 목적인 경우
   ```python
   feature_store.load_features(outlier_policy="winsorize")
   ```
   주의: walk-forward 검증 시 룩어헤드 바이어스 존재 → 성능 수치 낙관편향 가능

3. **IQR 배수 상향은 하지 말 것** — 통계적 근거 없는 튜닝

### 중기 개선 (필요 시)

- `WinsorizePolicy`를 rolling-window 방식으로 교체
  - 각 날짜의 clip 기준을 전체 기간이 아닌 직전 N일 분위수로 계산
  - 룩어헤드 바이어스 제거 → walk-forward 검증에도 사용 가능

---

## 6. 최종 판단

| 질문 | 답 |
|---|---|
| IQR 배수를 올려야 하나? | **아니오** — 임시방편, 근거 없음 |
| Winsorize는 금융 데이터에 부정적인가? | **이 용도에서는 아니다** — Regime Index이므로 허용 가능. 단, 룩어헤드 바이어스 인지 필수 |
| 무엇을 먼저 시도해야 하나? | **`column` 정책 실험** — 이미 구현됨, 룩어헤드 없음, regime_stress 보존 |
| 결측 14.5% → 21.4% 문제의 근본 원인? | `row` 정책이 셀 1개 이상치를 행 전체로 전파하는 구조. `column`으로 전환하면 즉시 개선 |

