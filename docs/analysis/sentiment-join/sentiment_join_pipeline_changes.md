# Sentiment Join 파이프라인 변경 요약 및 운영 체크포인트

## 1. 무엇이 달라졌나

### 1.1 예측 호라이즌 단순화

| 구분 | 변경 전 | 변경 후 |
|---|---:|---:|
| 예측 호라이즌 | T+1 / T+3 / T+7 | T+7 단일 |
| 실험 Grid | 48 cells | 16 cells |
| Grid 구조 | 다중 호라이즌 | 2 × 4 × 1 × 2 |

**의미**

- 이제는 **1주일 후 누적 수익률(T+7)** 만 예측합니다.
- 다음날 예측(T+1)과 3일 후 예측(T+3)은 더 이상 평가하지 않습니다.

---

### 1.2 Sharpe 연환산 인자 통일

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| baselines | `sqrt(252)` | `sqrt(365)` |
| experiments | `sqrt(252)` | `sqrt(365)` |
| statistical_tests | `sqrt(365)` | `sqrt(365)` |
| 기준 상수 | 혼재 | `ANNUALIZATION_FACTOR = 365` |

**핵심**

- 기존에는 코드 위치마다 Sharpe 연환산 기준이 달랐습니다.
- `strategy_sharpe - baseline_sharpe` 계산 시 서로 다른 스케일을 빼고 있었습니다.
- 그 결과 strategy 쪽 Sharpe가 약 **+20% 인플레이션** 되었을 수 있습니다.
- 과거에 `promote` 된 일부 결과는 이 편향의 영향을 받았을 가능성이 있습니다.
- BTC는 24/7 거래되고 데이터도 달력일 기준이므로 `365`가 더 일관됩니다.

**주의**

- 과거 Sharpe 수치와 신규 Sharpe 수치를 직접 비교하면 안 됩니다.
- README, 보고서, 대시보드의 historical Sharpe 값은 변경 사실을 명시해야 합니다.

---

### 1.3 Bootstrap Confidence Interval 신규 도입

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 평가 방식 | 점추정만 사용 | 95% Bootstrap CI 추가 |
| 예시 | `hit_rate = 0.55` | `hit_rate_ci_lower / upper` |
| 문제점 | overlapping T+7 샘플의 자기상관 무시 | block bootstrap으로 보정 |

**신규 모듈**

- `src/morning_brief/analysis/sentiment_join/bootstrap.py`

**기본 설정**

```text
method = circular block bootstrap
block_length = 14
n_bootstrap = 1000
```

**의미**

- 모든 실험 셀에 다음 필드가 추가됩니다.
  - `hit_rate_ci_lower`
  - `hit_rate_ci_upper`
  - `sharpe_ci_lower`
  - `sharpe_ci_upper`

---

### 1.4 격상 게이트 강화: `decision_strict` 추가

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 운영 판단 | `decision` 단일 | `decision` + `decision_strict` |
| 기준 | 5조건 점추정 AND | CI separation + FDR 보정까지 포함 |

**기존 `decision`**

- 기존 5조건 점추정 기반 AND 로직 유지
- 결과:
  - `promote`
  - `research_only`

**신규 `decision_strict` 조건**

`decision_strict = "promote"` 가 되려면 아래 조건을 모두 만족해야 합니다.

1. `decision == "promote"`
2. signal hit rate CI 하한 ≥ baseline hit rate CI 상한
3. signal Sharpe CI 하한 ≥ baseline Sharpe CI 상한
4. BH-FDR `q <= 0.10`

하나라도 실패하면:

```text
decision_strict = "research_only"
```

**의미**

- 기존 `decision`은 유지하되, 운영 승격용으로 더 보수적인 판단 기준을 추가했습니다.
- `decision_strict`는 통계적으로 더 강한 alpha 후보만 통과시키는 advisory gate입니다.

---

### 1.5 다중검정 보정 신규 도입

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 비교 수 | 128 comparisons | 동일 |
| 보정 여부 | 무보정 | BH-FDR 보정 |
| 문제 | false positive 증가 가능 | `fdr_q` 필드 추가 |

**비교 구조**

```text
predictor 16개 × baseline 4개 × horizon 1개 × index 2개 = 128 비교
```

**변경 후 방식**

1. 각 `(predictor, horizon)` 셀에서 baseline 전체와 비교
2. max p-value 산출
3. BH-FDR 적용
4. `fdr_q` 필드 부착

**의미**

- 여러 실험을 동시에 돌릴 때 우연히 좋아 보이는 결과를 alpha로 착각할 가능성을 줄입니다.

---

### 1.6 데이터 무결성 가드 신규 추가

**추가된 검증**

1. `*_lag1` 16개 컬럼 lookahead 단위 테스트
   - 각 컬럼에 대해 다음 조건 검증:

```text
lag1[t] == raw[t-1]
```

2. forward target causality 회귀 테스트
   - `btc_fwd_ret_Nd[t]` 가 `t-k` 변화에 영향을 받지 않는지 검증

3. Pandera 검증
   - 다중행 master DataFrame의 첫 행에 대해 `*_lag1` 값이 반드시 `NaN` 인지 강제

**의미**

- lookahead bias와 target leakage 가능성을 테스트 레벨에서 방어합니다.

---

### 1.7 파이프라인 산출물 형태 변경

**변경 대상**

- Parquet metadata
- `latest.json`

**변경 내용**

다음 메타데이터 키들이 모두 `"7"` 키만 포함합니다.

```text
horizon_metrics
walk_forward_horizons
baseline_metrics
```

각 셀에는 신규 필드가 추가됩니다.

```text
hit_rate_ci_lower
hit_rate_ci_upper
sharpe_ci_lower
sharpe_ci_upper
pvalue_vs_baselines
fdr_q
```

**유지되는 부분**

- 기존 `decision` 게이트 로직은 변경되지 않았습니다.

---

### 1.8 Sparse abstain filter 연구 지표 추가

**변경 배경**

T+7 hit rate 개선은 신규 단일 피처를 계속 추가하는 문제라기보다, 기존 volatility regime 신호에서 **언제 거래하고 언제 쉬는지**를 정하는 abstain filter 문제에 가까웠다. 따라서 이번 변경은 production 승격보다 research artifact에 daily 검정 가능한 sparse rule을 추가하는 방식으로 반영했다.

**신규 baseline**

| 이름 | 설명 | 채택 파라미터 |
|---|---|---|
| `vol_regime_v2` | VIX regime 방향을 BTC realized-vol regime이 확인할 때만 거래 | VIX 90D q40 + BTC realized-vol 45D q45 |

**신규 research-only rules**

| predictor | 목적 |
|---|---|
| `vix_low_long_only` | VIX 저위험 구간 long-only 효과 확인 |
| `vote_vol_sent_fng5_2of3` | vol/sentiment/FNG 3개 중 2개 이상 합의 |
| `vote_vol_vix_sent_fng5_3of4` | vol/VIX/sentiment/FNG 4개 중 3개 이상 합의 |
| `vol_regime_v2_vix_realized_vol_2of2` | VIX threshold + realized-vol threshold 2D grid 최종 채택 rule |
| `vol_regime_v3_vix_realized_vol_ma200_2of3` | VIX/realized-vol/MA200 3개 중 2개 이상 합의 |

**artifact 계약**

위 rule들은 `data/sentiment_join/latest.json`의 아래 경로에 포함된다.

```text
alpha.horizonMetrics["7"].hit_rates[]
alpha.horizonMetrics["7"].backtest[]
alpha.baselineMetrics["7"].vol_regime_v2
```

각 research row에는 다음 필드가 포함된다.

```text
research_rule
research_rule_family
abstain_filter_diagnostics
kept_baseline_hit_rate
dropped_baseline_hit_rate
kept_baseline_hit_rate_lift
kept_gt_dropped_pvalue
kept_n
dropped_n
```

**최신 로컬 산출물 기준 결과**

| 항목 | 값 |
|---|---:|
| `vol_regime_v2` hit rate | 61.64% |
| coverage | 56.48% |
| Sharpe | 5.71 |
| kept > dropped p-value | 0.0107 |

**해석**

- `vol_regime_v2`는 hit rate를 높이는 데 가장 유효한 후보로 확인됐다.
- coverage가 56.48%이므로 전체 시장 예측기가 아니라 **high-confidence regime overlay**로 해석해야 한다.
- `vol_regime_v2_vix_realized_vol_2of2` row는 baseline과 동일한 rule을 research artifact에도 노출하기 때문에, best baseline 대비 lift가 0에 가까울 수 있다.
- 이 상태는 의도된 동작이며, 운영 승격보다는 kept/dropped 검정을 누적 확인하는 용도다.

---

## 2. 어떤 부분을 주의깊게 봐야 하나

### 2.1 첫 파이프라인 실행 직후 핵심 Sanity Check

`scripts/build_sentiment_join.py` 실행 직후 아래 명령으로 확인합니다.

```bash
jq '.alpha.horizonMetrics["7"].hit_rates[] |
    {predictor, hit_rate, hit_rate_ci_lower, hit_rate_ci_upper,
     pvalue_vs_baselines, fdr_q}' \
   data/sentiment_join/latest.json
```

**기대 결과**

1. 모든 셀에 CI가 채워져 있어야 합니다.
   - CI가 `NaN`이면 bootstrap 미실행 가능성이 있습니다.
2. 점추정 값이 CI 내부에 있어야 합니다.

```text
hit_rate_ci_lower < hit_rate < hit_rate_ci_upper
```

3. `fdr_q`는 `[0, 1]` 범위에 있어야 합니다.
4. 작은 p-value일수록 작은 q-value가 나와야 합니다.
5. bootstrap 설정이 아래와 일치해야 합니다.

```text
bootstrap_config.method == "circular"
bootstrap_config.block_length == 14
bootstrap_config.n_bootstrap == 1000
```

**위험 신호**

| 신호 | 의미 |
|---|---|
| `lower == upper` | CI 폭이 0. strategy_returns가 모두 동일할 수 있음. 예: position 0 edge case |
| `pvalue_vs_baselines`가 모두 `1.0` | paired bootstrap이 baseline 길이 mismatch로 실패했을 가능성 |
| CI가 `NaN` | bootstrap 미실행 또는 입력 데이터 부족 가능성 |
| `bootstrap_n == 0` | bootstrap 입력 배열이 비어 있어 스킵된 상태 |

**특히 주의할 구현 포인트**

- `_baseline_hits_array` 가 `signal != 0` 행만 active로 잡는 점을 확인해야 합니다.
- signal과 baseline의 active row가 다르면 paired bootstrap 해석력이 약해질 수 있습니다.

---

### 2.2 `decision` 과 `decision_strict` 의 갭 확인

한 사이클 결과에서 아래 두 값을 비교합니다.

```text
decision == "promote" 셀 수
decision_strict == "promote" 셀 수
```

**해석 기준**

| 관찰 결과 | 해석 |
|---|---|
| 갭이 큼. 예: 10 vs 0 | 기존 `decision` 결과가 통계적으로 약했을 가능성. 운영상 강건한 alpha가 아니었을 수 있음 |
| 갭이 거의 없음 | 기존 게이트도 충분히 conservative 했고, Sharpe 편향만 일부 있었을 가능성 |
| `decision_strict`만 극히 적음 | 실제 alpha 후보를 엄격히 줄이는 효과가 있음 |

**의미**

- `decision_strict`를 운영 결정 기준으로 승격할지 판단하는 핵심 근거가 됩니다.
- 실제 상황에서는 기존 `decision`과 `decision_strict` 사이에 갭이 있을 가능성이 큽니다.

---

### 2.3 Block Length 14 적정성 확인

현재 설정:

```text
T+7 overlapping target
block_length = 2 × horizon = 14
```

**가정**

- T+7 누적 수익률의 overlapping 구조를 감안해 block length를 14로 설정했습니다.
- 하지만 실제 자기상관 길이가 14보다 길 수 있습니다.

**확인 방법**

1. signal hits 시계열의 ACF 확인
2. lag 14 근처에서 자기상관이 충분히 0에 가까워지는지 확인
3. decay가 충분하지 않으면 block length를 늘려야 합니다.

**추가 검토 가능 항목**

- Politis-White (2004) 자동 block-length selector 도입 검토

---

### 2.4 Sharpe `sqrt(365)` 변경의 영향

**핵심 영향**

- 이전 보고서나 대시보드의 Sharpe 숫자와 새 Sharpe 숫자의 비교 가능성이 깨졌습니다.
- 기존에 `sqrt(252)` 기준으로 계산되던 baselines / experiments 셀은 `sqrt(365)`로 바뀌며 약 **+20% 수준 차이**가 발생합니다.
- 기존에 이미 `sqrt(365)`였던 statistical_tests 셀은 동일합니다.

**주의사항**

- 과거 parquet의 Sharpe 값과 새 parquet의 Sharpe 값을 직접 비교하면 안 됩니다.
- stakeholder 보고용 차트나 README에 historical Sharpe가 있다면 기준 변경을 명시해야 합니다.
- 이전 `promote` 결과 일부는 Sharpe scale mismatch의 영향을 받았을 수 있습니다.

---

### 2.5 `n_bootstrap = 1000` 비용 확인

**계산량**

```text
1셀당 bootstrap metric 계산:
- signal bootstrap 1000회
- baseline paired bootstrap 4개 × 1000회
= 셀당 약 5000회 metric 계산

전체:
16 cells × 2 index(full/core) × 5000
= 약 160,000회 metric 계산
```

**성능 영향**

- hit rate 계산은 상대적으로 빠릅니다.
- Sharpe 계산은 standard deviation, ddof 계산이 포함되어 더 무겁습니다.
- 한 사이클이 기존 대비 수십 초에서 수분 정도 느려질 수 있습니다.

**운영 체크**

- 실제 운영 환경에서 파이프라인 실행 시간을 측정해야 합니다.
- 너무 느리면 아래와 같이 낮추는 방안을 검토할 수 있습니다.

```python
BootstrapConfig(n_bootstrap=500)
```

**주의**

- `n_bootstrap=500`으로 낮추면 결과 변동성이 약 5% 수준 증가할 수 있습니다.

---

### 2.6 `_baseline_hits_array` 길이 정렬 점검

**현재 구현**

- `signal_hits` 와 `baseline_hits` 길이가 다르면 `min(n)` 기준으로 자릅니다.
- 하지만 이 방식은 인덱스 정렬을 보장하지 않습니다.

**문제 가능성**

- baseline의 active row와 signal의 active row가 일치하지 않으면 paired bootstrap의 의미가 약해집니다.
- 현재는 구현 단순성 중심이라 실용적으로는 충분할 수 있습니다.
- 정밀한 통계 검증을 위해서는 공통 인덱스 기준으로 정렬한 paired bootstrap이 더 정확합니다.

**운영 후 점검 필요**

- signal active row와 baseline active row가 같은 시점 기준으로 매칭되는지 확인해야 합니다.

---

### 2.7 Frontend CI 시각화 미완

**현재 상태**

- 데이터는 backend 산출물에 포함됩니다.
- 하지만 `AnalysisDashboardPanels.tsx` 에서는 아직 아래 항목을 시각화하지 않습니다.
  - CI error bar
  - `decision_strict` badge
  - FDR q-value 표시

**영향**

- 사용자나 PM이 대시보드만 보면 변경이 없어 보일 수 있습니다.
- 실제 변경 확인은 아래 산출물을 직접 봐야 합니다.

```text
parquet metadata
data/sentiment_join/latest.json
```

**후속 작업**

- 후속 PR에서 frontend 시각화 추가 필요

---

### 2.8 CI / 계산 도중 NaN 처리 검증

**주의할 케이스**

| 상황 | 결과 |
|---|---|
| `n_valid < 2` | Sharpe CI 또는 paired p-value가 `NaN` 가능 |
| 입력 배열 empty | `bootstrap_n == 0` |
| 일부 셀만 NaN | 데이터 부족, 의도된 skip, 버그 여부 구분 필요 |

**확인 포인트**

- NaN이 의도된 데이터 부족 때문인지 확인해야 합니다.
- bootstrap 자체가 스킵된 셀이 있는지 확인해야 합니다.
- 일부 predictor / baseline 조합만 NaN이면 alignment 또는 filtering 문제 가능성이 있습니다.

---

### 2.9 Sparse rule 운영 체크

**확인 명령**

```bash
jq '.alpha.horizonMetrics["7"].hit_rates[] |
    select(.research_rule == true) |
    {predictor, hit_rate, coverage, strategy_sharpe,
     kept_baseline_hit_rate, dropped_baseline_hit_rate,
     kept_gt_dropped_pvalue, decision_strict}' \
   data/sentiment_join/latest.json
```

```bash
jq '.alpha.baselineMetrics["7"].vol_regime_v2 |
    {hit_rate, coverage, sharpe,
     hit_rate_ci_lower, hit_rate_ci_upper,
     sharpe_ci_lower, sharpe_ci_upper}' \
   data/sentiment_join/latest.json
```

**정상 기대값**

| 항목 | 기대 |
|---|---|
| `vol_regime_v2` | baseline metrics에 존재 |
| `vol_regime_v2_vix_realized_vol_2of2` | research hit_rates/backtest에 존재 |
| `kept_gt_dropped_pvalue` | `NaN`이 아니어야 함 |
| `decision_strict` | 당분간 `research_only`가 정상 |
| coverage | 50~65% 수준이면 현재 설계와 일치 |

**위험 신호**

| 신호 | 의미 |
|---|---|
| `vol_regime_v2` coverage가 0% | realized-vol 컬럼 누락 또는 threshold 계산 실패 |
| `kept_n == 0` | research signal이 전부 abstain |
| `dropped_n == 0` | filter가 baseline과 동일해 kept/dropped 검정 불가 |
| p-value가 장기간 0.20 초과 | abstain filter의 분리력이 약해졌을 가능성 |
| coverage가 80% 이상으로 상승 | sparse overlay가 아니라 일반 baseline처럼 변질됐을 가능성 |

---

## 3. 핵심 운영 우선순위

다음 운영 사이클에서 가장 먼저 확인할 항목은 아래 2개입니다.

### 3.1 첫 실행 Sanity Check

확인 대상:

```text
CI 정상 생성 여부
hit_rate가 CI 내부에 있는지
fdr_q 범위와 정렬성
bootstrap_config 설정값
pvalue_vs_baselines 이상치 여부
bootstrap_n == 0 여부
```

### 3.2 `decision` vs `decision_strict` 갭

확인 대상:

```text
decision == "promote" 셀 수
decision_strict == "promote" 셀 수
두 값의 차이
```

**해석**

- 갭이 크면 기존 alpha 후보가 통계적으로 약했을 가능성이 큽니다.
- 갭이 작으면 기존 decision gate도 보수적으로 작동했을 가능성이 있습니다.

---

### 3.3 다음 작업 우선순위

1. `vol_regime_v2`를 frontend analysis 화면에서 high-confidence regime baseline으로 표시한다.
2. `research_rule_family == "sparse_abstain_filter"` 행을 일반 alpha 후보와 구분해 보여준다.
3. 매일 `kept_baseline_hit_rate`, `dropped_baseline_hit_rate`, `kept_gt_dropped_pvalue`를 저장해 drift를 본다.
4. coverage 50~65%, p-value 0.10 이하, Sharpe CI 하한 개선이 2~4주 유지되면 promotion gate 별도 설계를 검토한다.
5. 운영 승격 전에는 `vol_regime_v2`를 단독 매매 신호가 아니라 기존 전략의 confidence overlay로 먼저 적용한다.

---

## 4. 한 줄 요약

이전에는 노이즈를 alpha로 착각할 수 있는 통계적 함정이 있었고, 이제는 그 함정을 검출할 bootstrap CI, FDR, strict decision 인프라가 추가되었습니다. 여기에 `vol_regime_v2` sparse abstain filter가 추가되어 hit rate 개선 후보를 daily artifact에서 검정할 수 있습니다. 단, frontend 시각화는 아직 후속 작업이므로 최소 한 사이클은 `latest.json` 과 parquet metadata를 직접 검증해야 합니다.
