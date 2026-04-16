# 2순위: 통계적 엄밀성(Rigor) — 코드 리뷰 결과

> 실제 코드베이스 + 백필 코드 대조 기반

---

## 1. ADF 정상성 검정

### 현재 구현 상태

`_run_adf` (`statistical_tests.py:31-45`)는 `statsmodels.tsa.stattools.adfuller`를 사용하며, p < 0.05 기준으로 정상성을 판정합니다.

ADF 대상 (`ADF_TARGETS`):

| 컬럼 | 변환 상태 | 판정 |
|---|---|---|
| `btc_log_return` | ✅ `ln(close_t / close_{t-1})` — `compute_returns`에서 변환 | 적절 |
| `funding_rate` | 원본 비율값 (이미 정상성 가능) | 적절 |
| `oi_change_pct_lag1` | `pct_change().shift(1)` — 변화율 | 적절 |
| `btc_long_short_ratio` | 원본 비율값 | 적절 |
| `etf_net_inflow_usd_lag1` | 원본 USD 금액 shift(1) | ⚠️ 아래 참조 |

`compute_returns` (`transform.py:38-47`):

```python
close = pd.to_numeric(computed[price_col], errors="coerce").where(lambda values: values > 0)
computed[f"{price_col}_log_return"] = np.log(close / close.shift(1))
computed[f"{price_col}_return"] = close.pct_change(fill_method=None)
```

→ BTC 가격은 로그 수익률로 변환된 상태에서 ADF를 수행합니다. **이 부분은 요구사항에 부합합니다.**

### 🟡 개선 필요: ADF 대상에 Granger predictor 누락

Granger predictor 5개 중 ADF 대상에 포함된 것과 빠진 것:

| Granger Predictor | ADF 대상 포함 | 문제 |
|---|---|---|
| `news_sentiment_mean` | ❌ **미포함** | 정상성 미검증 상태로 Granger 투입 |
| `fng_value` | ❌ **미포함** | 동일 |
| `funding_rate_lag1` | △ `funding_rate`만 포함 | lag1 자체는 미검증 |
| `btc_long_short_ratio_lag1` | △ 원본만 포함 | 동일 |
| `etf_net_inflow_usd_lag1` | ✅ 포함 | — |

Granger 검정의 전제 조건은 **양쪽 시계열 모두 정상**이어야 합니다. 현재 predictor 중 `news_sentiment_mean`과 `fng_value`는 ADF 검정 없이 Granger에 투입됩니다.

**수정**: `ADF_TARGETS`에 `news_sentiment_mean`, `fng_value` 추가. 비정상 시 차분 또는 경고 로그.

### 🟡 개선 필요: ADF 비정상 시 Granger 진행 차단 없음

`run_statistical_tests`에서 ADF와 Granger는 **독립적으로 실행**됩니다:

```python
# statistical_tests.py:125-145
# ADF 실행
adf_results: dict[str, Any] = {}
for col in ADF_TARGETS:
    ...
    adf_results[col] = _run_adf(df[col])
results["adf"] = adf_results

# Granger 실행 — ADF 결과를 참조하지 않음
if len(df) >= MIN_ROWS_FOR_GRANGER:
    for predictor, target in GRANGER_PAIRS:
        for lag in GRANGER_LAGS:
            entry = _run_granger(df, predictor, target, lag)
```

`btc_log_return`이 ADF를 통과하지 못해도 Granger 검정이 그대로 실행됩니다. 결과의 통계적 유효성이 보장되지 않습니다.

**수정**: ADF에서 target(`btc_log_return`)이 비정상이면 Granger 결과에 `"adf_warning": "target_non_stationary"` 플래그를 추가하거나, 메타데이터에 경고를 기록.

---

## 2. Granger 인과성 검정

### 현재 구현 상태

`_run_granger` (`statistical_tests.py:48-100`):

```python
result = grangercausalitytests(work, maxlag=lag, verbose=False)
pvalue = float(result[lag][0]["ssr_ftest"][1])
```

- SSR F-test 사용 ✅
- Lag 1, 2, 3 ✅
- p < 0.05 유의 수준 ✅
- 결과에 `predictor`, `target`, `lag`, `pvalue`, `significant` 기록 ✅

### 🔴 개선 필요: `news_sentiment_mean`에 Lag-1 미적용 (1순위 문서와 동일)

pre-backfill-fixes.md §1에서 이미 식별한 문제입니다. `news_sentiment_mean`과 `fng_value`가 shift 없이 같은 날짜의 `btc_log_return`과 비교됩니다.

Granger 검정에서 "어제의 뉴스 감성이 오늘의 BTC 수익률을 예측하는가"를 검정하려면, `grangercausalitytests`에 넣기 전에 predictor가 target보다 시간적으로 앞서야 합니다. `grangercausalitytests` 자체가 내부적으로 lag를 적용하지만, 이는 **이미 시간 정렬된 데이터**를 전제합니다. 같은 날짜의 감성과 수익률이 나란히 있으면, lag=1은 "전일 감성 → 당일 수익률"이 아니라 "당일 감성 → 익일 수익률"을 검정하게 됩니다.

### 🟡 개선 필요: `grangercausalitytests` 컬럼 순서

```python
work = df[[target, predictor]].copy()  # [btc_log_return, news_sentiment_mean]
result = grangercausalitytests(work, maxlag=lag, verbose=False)
```

`statsmodels.grangercausalitytests`는 **두 번째 컬럼이 첫 번째 컬럼을 Granger-cause하는지** 검정합니다. 현재 `[target, predictor]` 순서이므로 "predictor가 target을 cause하는가"를 올바르게 검정합니다. **이 부분은 정확합니다.**

---

## 3. 유효 표본 게이트

### 현재 구현 상태

```python
# statistical_tests.py:13-14
MIN_ROWS_FOR_ADF = 30
MIN_ROWS_FOR_GRANGER = 180
```

- ADF: 30행 미만 시 전체 건너뜀 ✅
- Granger: 180행 미만 시 건너뜀 ✅
- 개별 `_run_granger`에서도 dropna 후 180행 미만이면 None 반환 ✅
- 메타데이터에 `granger_eligible_rows`, `granger_executed` 기록 ✅

### 🔴 근본 원인: 백필 JSON 구조가 analytics 계약과 불일치

> **[최우선 — 데이터 계약 및 가용성 확보]**
> 이 항목이 해결되지 않으면 백필을 아무리 돌려도 180일 유효 표본 게이트를 통과할 수 없습니다.
> 모든 후속 통계 분석(ADF, Granger, PCA)의 전제 조건입니다.

**이것이 샘플 parquet에서 29일치가 `missing_backfill_marker`로 제외된 직접 원인입니다.**

백필 uploader (`build_minimal_brief_json`, `uploader.py:38-57`)가 생성하는 JSON:

```json
{
  "meta": {
    "date": "2026-01-01",
    "sentimentStatus": "ok",
    "newsSentiment": {"mean": 0.1, "std": 0.2, "count": 5},
    "_backfill": true,
    ...
  }
}
```

실제 analytics 계약 (`analytics_contract.py`)이 기대하는 JSON:

```json
{
  "schemaVersion": "v1",
  "date": "2026-01-01",
  "symbol": "btc",
  "sentimentStatus": "ok",
  "newsSentiment": {"mean": 0.1, "std": 0.2, "count": 5},
  "_backfill": true,
  ...
}
```

차이점:

| 항목 | 백필 JSON | analytics 계약 |
|---|---|---|
| 구조 | `meta` 래퍼 안에 모든 필드 | **top-level에 flat** |
| `_backfill` 위치 | `meta._backfill` | **top-level `_backfill`** |
| `schemaVersion` | ❌ 없음 | ✅ `"v1"` 필수 |
| `symbol` | ❌ 없음 | ✅ `"btc"` 필수 |
| `producer` | ❌ 없음 | ✅ 필수 |

`validate_analytics_sentiment_payload`의 검증 순서:

```python
# 1단계: top-level _backfill 확인
if not payload.get("_backfill"):          # ← 백필 JSON은 top-level에 없음
    return {"valid": False, "reason": "missing_backfill_marker"}  # ← 여기서 실패

# 2단계: schemaVersion 확인 (도달하지 못함)
# 3단계: 필수 필드 확인 (도달하지 못함)
```

→ 백필이 R2에 올린 JSON은 **1단계에서 즉시 실패**하여 `missing_backfill_marker`로 제외됩니다.

**수정**: `build_minimal_brief_json`을 analytics 계약에 맞게 수정:

```python
def build_minimal_brief_json(date: str, aggregate: DailyAggregate) -> dict:
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schemaVersion": "v1",
        "producer": "backfill.scorer",
        "generatedAt": now_utc,
        "date": date,
        "symbol": "btc",
        "sentimentStatus": aggregate.status,
        "newsSentiment": {
            "mean": aggregate.mean,
            "std": aggregate.std,
            "count": aggregate.count,
        },
        "_backfill": True,
    }
```

주의: 계약에 `extra_fields` 검사가 있으므로 (`_ANALYTICS_ALLOWED_KEYS` 이외의 키가 있으면 실패), 현재 백필의 `_backfillSource`, `_backfillGeneratedAt`, `signalSentimentStatus`, `signalSentiment` 등의 추가 필드는 **넣으면 안 됩니다**. 허용 키는 정확히 8개입니다:

```python
_ANALYTICS_ALLOWED_KEYS = {
    "schemaVersion", "producer", "generatedAt", "date",
    "symbol", "sentimentStatus", "newsSentiment", "_backfill",
}
```

---

## 4. 다중 검정 보정 (Multiple Testing Correction) 없음

### 현상

5쌍 × 3 lags = **15개 검정**을 개별 유의 수준 p < 0.05로 판정합니다. 다중 검정 보정(Bonferroni, Holm, BH-FDR 등)이 적용되지 않습니다.

### 문제

15개 독립 검정에서 하나라도 우연히 유의하게 나올 확률(familywise error rate):

```
FWER = 1 - (1 - 0.05)^15 = 0.5367 (53.7%)
```

즉, 실제로 인과성이 전혀 없어도 **절반 이상의 확률로 최소 1개가 유의**하게 나옵니다. 이 상태로 "뉴스의 선행성을 발견했다"고 선언하면 1종 오류 위험이 큽니다.

### 수정 방안

Granger 결과 메타데이터에 보정된 p-value를 추가합니다. 가장 보수적인 Bonferroni 기준:

```
보정 유의 수준 = 0.05 / 15 = 0.0033
```

`_run_granger` 결과에 `n_tests` 필드를 추가하고, `build_stats_metadata_payload`에서 `bonferroni_threshold`를 기록하면 보고서에서 해석할 수 있습니다. 코드에서 `significant` 판정 자체를 바꾸지 않더라도, 메타데이터에 보정 기준을 함께 남기는 것이 최소 요건입니다.

수정 대상:

| 파일 | 변경 |
|---|---|
| `statistical_tests.py` | `run_statistical_tests` 결과에 `n_granger_tests`, `bonferroni_threshold` 추가 |
| `etf_storage.py` | `build_stats_metadata_payload`에 해당 필드 전달 |

---

## 5. Granger 검정 쌍별 유효 행 수 미기록

### 현상

`_run_granger`에서 `work = work.dropna()` 후 실제 검정에 사용된 행 수가 결과에 기록되지 않습니다.

```python
work = df[[target, predictor]].copy()
work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
work = work.dropna()          # ← 이 시점의 len(work)가 기록되지 않음

if len(work) < MIN_ROWS_FOR_GRANGER:
    return None
```

메타데이터의 `granger_eligible_rows`는 이상치 제거 후 **전체 DataFrame 행 수**이며, 특정 predictor-target 쌍에서 NaN이 많으면 실제 검정 행 수는 이보다 적을 수 있습니다.

### 수정 방안

`_run_granger` 반환값에 `effective_rows` 필드 추가:

```python
entry: dict[str, Any] = {
    "predictor": predictor,
    "target": target,
    "lag": lag,
    "pvalue": pvalue,
    "significant": pvalue < 0.05,
    "effective_rows": len(work),  # ← 추가
}
```

---

## 6. `grangercausalitytests` 중복 호출 (효율성)

### 현상

```python
for lag in GRANGER_LAGS:  # [1, 2, 3]
    entry = _run_granger(df, predictor, target, lag)
```

`_run_granger(df, pred, tgt, lag=3)`은 내부적으로 `grangercausalitytests(work, maxlag=3)`을 호출하며, 이는 lag 1, 2, 3을 **모두** 검정합니다. 그런데 `result[3]`만 추출합니다. 결과적으로 lag=1은 3번, lag=2는 2번 중복 계산됩니다.

### 영향

결과의 정확성에는 영향 없음. 계산 비용만 3배. 180행 규모에서는 무시할 수준이지만, 구조적으로는 `maxlag=3`으로 한 번 호출하여 lag 1, 2, 3 결과를 모두 추출하는 것이 깔끔합니다.

### 수정 방안 (선택)

```python
def _run_granger_all_lags(df, predictor, target, max_lag=3):
    ...
    result = grangercausalitytests(work, maxlag=max_lag, verbose=False)
    return [
        {"predictor": predictor, "target": target, "lag": lag,
         "pvalue": float(result[lag][0]["ssr_ftest"][1]),
         "significant": float(result[lag][0]["ssr_ftest"][1]) < 0.05,
         "effective_rows": len(work)}
        for lag in range(1, max_lag + 1)
    ]
```

---

## 7. F-statistic 미기록

### 현상

`grangercausalitytests`는 SSR F-test에서 F-statistic과 p-value를 모두 반환하지만, 현재 p-value만 추출합니다:

```python
pvalue = float(result[lag][0]["ssr_ftest"][1])
# result[lag][0]["ssr_ftest"] = (F_statistic, p_value, df_denom, df_num)
```

### 문제

보고서에서 효과 크기(effect size)를 논의하려면 F-statistic이 필요합니다. p-value만으로는 "유의하다/아니다"만 알 수 있고, 예측력의 크기를 판단할 수 없습니다.

### 수정 방안

`_run_granger` 반환값에 `f_statistic` 추가:

```python
f_stat = float(result[lag][0]["ssr_ftest"][0])
entry = {
    ...
    "f_statistic": f_stat,
    "pvalue": pvalue,
    ...
}
```

---

## 수정 우선순위 (2순위 내)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **2-1** | 백필 JSON 구조 불일치 + extra_fields 주의 (§3) | 🔴 180행 확보 불가 | 저 |
| **2-2** | ADF 대상에 predictor 누락 (§1) | 🟡 통계적 전제 조건 미검증 | 저 |
| **2-3** | ADF 비정상 시 Granger 경고 없음 (§1) | 🟡 결과 해석 신뢰도 | 저 |
| **2-4** | 다중 검정 보정 없음 (§4) | 🟡 1종 오류 53.7% | 저 |
| **2-5** | 쌍별 유효 행 수 미기록 (§5) | 🟢 진단 정보 부족 | 저 |
| **2-6** | F-statistic 미기록 (§7) | 🟢 효과 크기 판단 불가 | 저 |
| **2-7** | grangercausalitytests 중복 호출 (§6) | 🟢 효율성만 | 저 |

**§3(백필 JSON 구조)이 가장 치명적입니다.** 이것이 해결되지 않으면 백필을 아무리 돌려도 sentiment-join에서 전부 `missing_backfill_marker`로 제외되어 180행을 확보할 수 없습니다.
