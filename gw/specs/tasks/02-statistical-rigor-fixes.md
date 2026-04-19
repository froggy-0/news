# 2순위: 통계적 엄밀성(Rigor) — 코드 리뷰 결과

> 실제 코드베이스 + 백필 코드 대조 기반.
> **전제: 1순위 태스크(`01-pre-backfill-fixes.md`)가 완료되어 `news_sentiment_mean_lag1`, `fng_value_lag1` 컬럼이 존재하고 `GRANGER_PAIRS`가 lag1 버전으로 치환된 상태**를 가정합니다.
>
> _2026-04-17 업데이트: data-engineer / data-scientist 관점에서 아래 이슈를 추가 반영했습니다 — 이상치 제거로 인한 time-index gap, uploader `_is_pipeline_file` 보호 로직의 스키마 이전 후 오작동, Granger lag 자동 선택, KPSS 공동 검정, HAC/HC 로버스트 추론, 백필 진단 필드 보존 전략._

---

## 1. ADF 정상성 검정

### 현재 구현 상태

`_run_adf` ([statistical_tests.py:31-45](src/morning_brief/analysis/sentiment_join/statistical_tests.py#L31-L45))는 `statsmodels.tsa.stattools.adfuller`를 사용하며, p < 0.05 기준으로 정상성을 판정합니다.

ADF 대상 (`ADF_TARGETS`):

| 컬럼 | 변환 상태 | 판정 |
|---|---|---|
| `btc_log_return` | ✅ `ln(close_t / close_{t-1})` — `compute_returns`에서 변환 | 적절 |
| `funding_rate` | 원본 비율값 (이미 정상성 가능) | 적절 |
| `oi_change_pct_lag1` | `pct_change().shift(1)` — 변화율 | 적절 |
| `btc_long_short_ratio` | 원본 비율값 | 적절 |
| `etf_net_inflow_usd_lag1` | 원본 USD 금액 shift(1) | ⚠️ 원본은 누적 AUM 아닌 flow이므로 수용 가능하지만, 단기 클러스터링 확인 필요 |

`compute_returns` ([transform.py:44](src/morning_brief/analysis/sentiment_join/transform.py#L44)):

```python
close = pd.to_numeric(computed[price_col], errors="coerce").where(lambda values: values > 0)
computed[f"{price_col}_log_return"] = np.log(close / close.shift(1))
computed[f"{price_col}_return"] = close.pct_change(fill_method=None)
```

→ BTC 가격은 로그 수익률로 변환된 상태에서 ADF를 수행합니다. **이 부분은 요구사항에 부합합니다.**

### 🟡 개선 필요: ADF 대상에 Granger predictor 누락

1순위 태스크에서 lag1로 치환된 predictor 기준:

| Granger Predictor | ADF 대상 포함 | 문제 |
|---|---|---|
| `news_sentiment_mean_lag1` | ❌ **미포함** | 정상성 미검증 상태로 Granger 투입 |
| `fng_value_lag1` | ❌ **미포함** | 동일. 0~100 bounded + 고도로 persistent |
| `funding_rate_lag1` | △ `funding_rate`만 포함 | `_run_adf`는 원본·lag1이 실질 동일하다고 볼 수 있으나, 명시성 보장 위해 lag1 자체도 포함 권장 |
| `btc_long_short_ratio_lag1` | △ 원본만 포함 | 동일 |
| `etf_net_inflow_usd_lag1` | ✅ 포함 | — |

Granger 검정은 **양쪽 시계열이 모두 정상**이라는 전제에 선다. 현재 predictor 중 `news_sentiment_mean_lag1`과 `fng_value_lag1`은 정상성 검증 없이 Granger에 투입됩니다.

**수정**:
- `ADF_TARGETS`에 `news_sentiment_mean_lag1`, `fng_value_lag1`, `funding_rate_lag1`, `btc_long_short_ratio_lag1` 추가.
- ADF 실패(p ≥ 0.05)인 predictor는 1차 차분(`.diff().dropna()`) 버전으로 재검정. 그래도 정상 아니면 해당 페어 스킵 + `stats.granger_skipped_non_stationary` 로그.

### 🟡 개선 필요: 정상성 게이트가 Granger 실행을 실제로 차단하지 않음

`run_statistical_tests` ([statistical_tests.py:103-165](src/morning_brief/analysis/sentiment_join/statistical_tests.py#L103-L165))에서 ADF와 Granger는 **독립적으로 실행**됩니다. `btc_log_return`이 ADF를 통과하지 못해도 Granger가 그대로 실행됩니다.

**수정** (두 단계로 나누어 구현):

1. **최소**: ADF 결과를 참조해 각 Granger 결과 entry에 `target_stationary`, `predictor_stationary` 불리언 기록. `significant`와 별개로 `reliable = significant & target_stationary & predictor_stationary`를 함께 노출.
2. **권장**: 비정상 시 차분 재시도(위 수정의 연장) → 차분 후에도 비정상이면 skip. skip 이유를 결과 리스트에 empty entry 대신 `{"predictor": ..., "lag": ..., "status": "skipped_non_stationary"}`로 기록해 다운스트림이 "존재 여부"를 판단할 수 있게.

### 🟢 개선 권장: KPSS 보완 검정

ADF는 귀무가설이 "단위근 있음"(=비정상)이라 고도로 persistent한 0~100 bounded series(`fng_value`)에 대해 **검정력이 낮습니다**. 반대 귀무가설의 **KPSS**와 함께 돌려 둘 다 동의할 때만 "정상/비정상"으로 판정하는 표준 관행을 권장합니다.

```python
from statsmodels.tsa.stattools import adfuller, kpss
adf_p = adfuller(series.dropna())[1]
kpss_p = kpss(series.dropna(), regression="c", nlags="auto")[1]
# adf_p<0.05 && kpss_p>0.05 → stationary
# adf_p>=0.05 && kpss_p<=0.05 → non-stationary
# 불일치 → "trend_stationary" 또는 "difference_stationary" 로 라벨, 차분 재시도
```

ADF 단독보다 false positive/negative 모두 줄일 수 있습니다. Granger gate는 이 합의 결과를 기준으로 판정.

---

## 2. Granger 인과성 검정

### 현재 구현 상태

`_run_granger` ([statistical_tests.py:48-100](src/morning_brief/analysis/sentiment_join/statistical_tests.py#L48-L100)):

```python
result = grangercausalitytests(work, maxlag=lag, verbose=False)
pvalue = float(result[lag][0]["ssr_ftest"][1])
```

- SSR F-test 사용 ✅
- Lag 1, 2, 3 ✅
- p < 0.05 유의 수준 ✅
- 결과에 `predictor`, `target`, `lag`, `pvalue`, `significant` 기록 ✅

### ✅ 컬럼 순서 (확인)

```python
work = df[[target, predictor]].copy()  # [btc_log_return, news_sentiment_mean_lag1]
result = grangercausalitytests(work, maxlag=lag, verbose=False)
```

`statsmodels.grangercausalitytests`는 **두 번째 컬럼이 첫 번째 컬럼을 Granger-cause하는지** 검정합니다. 현재 `[target, predictor]` 순서이므로 "predictor → target"을 올바르게 검정합니다.

### 🟡 개선 권장: 고정 lag [1,2,3] 대신 정보기준 기반 최적 lag

서로 다른 predictor는 최적 lag가 다를 수 있습니다. 현재처럼 `[1, 2, 3]` 전수 보고는 다중검정 부담만 가중시킵니다.

**수정 방안**:
- `statsmodels.tsa.vector_ar.var_model.VAR`의 `select_order(maxlags=5)`로 AIC/BIC 기반 최적 lag `k*`를 구하고, `k*`에서만 Granger 검정을 보고.
- 호환성을 위해 `[1, 2, 3]` 결과도 `granger_all_lags`로 부수 기록하되, `granger_primary`는 `k*` 결과만.
- 보고서/메타데이터에는 `optimal_lag` 필드 명시.

### 🟡 개선 권장: HAC / robust 추론

SSR F-test는 i.i.d. 잔차를 가정하지만, BTC 수익률과 감성 시계열은 변동성 군집(heteroskedasticity)과 잔차 자기상관을 동반합니다. 유의성 판정이 낙관적으로 나올 수 있습니다.

**수정 방안**:
- statsmodels는 `grangercausalitytests`에 HAC 옵션을 직접 제공하지 않으므로, 대안으로:
  1. VAR로 수동 피팅 후 `wald_test(..., cov_type="HAC", cov_kwds={"maxlags": lag})`로 F-test 재계산.
  2. 또는 잔차 기반 블록 부트스트랩으로 p-value를 재산출(stationary bootstrap, 블록 길이 ≈ √n).
- 최소한 메타데이터에 `inference = "ssr_ftest_ols"` 라벨을 남겨 다운스트림이 추론 방식을 알 수 있게.

### 🟢 개선 권장: Reverse-causality 회귀 (task 01에서 중복 언급)

§4.3(1순위 문서)과 연동. 역방향 pair를 같은 테이블에 기록하면 "BTC가 감성에 반응한 것"인지 분리 해석 가능. 본 문서에서는 구현만 연결:

```python
GRANGER_PAIRS_REVERSE = [(t, p) for (p, t) in GRANGER_PAIRS]
```

결과 dict 키는 `granger_forward`, `granger_reverse`로 분리.

---

## 3. 유효 표본 게이트 및 백필 JSON 스키마

### 현재 구현 상태

```python
# statistical_tests.py:12-13
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

백필 uploader (`build_minimal_brief_json`, [uploader.py:38-57](scripts/backfill/uploader.py#L38-L57))가 생성하는 JSON:

```json
{
  "meta": {
    "date": "2026-01-01",
    "sentimentStatus": "ok",
    "newsSentiment": {"mean": 0.1, "std": 0.2, "count": 5},
    "_backfill": true,
    "_backfillSource": "coindesk+alpaca+finbert",
    "_backfillGeneratedAt": "...",
    "signalSentimentStatus": "skipped",
    "signalSentiment": null,
    "generatedAt": "...+09:00"
  }
}
```

실제 analytics 계약 ([analytics_contract.py:15-26](src/morning_brief/data/storage/analytics_contract.py#L15-L26)) 허용 키는 정확히 8개:

```python
_ANALYTICS_ALLOWED_KEYS = frozenset({
    "schemaVersion", "producer", "generatedAt", "date",
    "symbol", "sentimentStatus", "newsSentiment", "_backfill",
})
```

`validate_analytics_sentiment_payload` ([analytics_contract.py:75-112](src/morning_brief/data/storage/analytics_contract.py#L75-L112))의 검증 순서:

```python
if not payload.get("_backfill"):          # ← 백필 JSON은 top-level에 없음
    return {"valid": False, "reason": "missing_backfill_marker"}
```

→ 백필이 올린 JSON은 **1단계에서 즉시 실패**합니다.

### 수정

`build_minimal_brief_json`을 analytics 계약에 맞게 재작성:

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

`_backfillSource`, `_backfillGeneratedAt`, `signalSentimentStatus`, `signalSentiment`는 **모두 제거**해야 `extra_fields` 검증을 통과합니다.

### 🔴 연쇄 문제: `_is_pipeline_file` 보호 로직 붕괴

위 스키마 이전을 적용하면 **uploader 자체의 덮어쓰기 보호가 깨집니다**. 현재 로직:

```python
# scripts/backfill/uploader.py:60-62
def _is_pipeline_file(existing_json: dict) -> bool:
    """_backfill 필드 없는 파일 = 파이프라인 원본 → 덮어쓰기 금지."""
    return "_backfill" not in existing_json.get("meta", {})
```

flat 스키마로 전환 후에는:
- 기존에 백필이 업로드해 둔 파일은 `meta` 래퍼가 사라져 `existing.get("meta", {})`가 빈 dict → `"_backfill" not in {}` → True → **자기 백필 파일을 "pipeline 원본"으로 오인해 `--force` 재실행이 거부됨**.
- 실제 파이프라인 원본도 flat 구조 + `_backfill=True`로 기록되므로(파이프라인 `build_analytics_sentiment_payload` [analytics_contract.py:47-72](src/morning_brief/data/storage/analytics_contract.py#L47-L72)), `meta` 기준 구분 자체가 더 이상 유효하지 않습니다.

**수정** (§3과 한 PR에서 함께 적용):

```python
def _is_pipeline_file(existing_json: dict) -> bool:
    producer = str(existing_json.get("producer", ""))
    return not producer.startswith("backfill.")
```

`producer` 접두사로 구분하는 것이 계약상 의도와 일치합니다. 실제 파이프라인은 `producer="public_site.publish_public_brief"`로 기록하고, 백필은 `producer="backfill.scorer"`로 기록하므로 접두사 기준이 안정적입니다.

### 🟡 개선 권장: 백필 진단 정보 보존(사이드카)

`_backfillSource`, `_backfillGeneratedAt`는 문제 추적에 유용합니다. analytics 계약을 늘리지 않고 보존하려면 **사이드카**에 분리:

- 본체: `analytics/btc/{date}.json` (계약 준수, 8키)
- 사이드카: `analytics/btc/{date}.backfill-meta.json` (진단 전용, 계약 비적용)

`upload_all`에 사이드카 업로드 스텝을 추가하고, `_is_pipeline_file` 류의 분기는 본체만 바라보게 유지.

---

## 4. 다중 검정 보정 (Multiple Testing Correction) 없음

### 현상

task 01의 gate(ADF, reverse-causality 포함 여부 등)에 따라 달라지지만, 현행 설계 기준 **기본 5 pairs × 3 lags = 15개 검정**을 개별 α=0.05로 판정합니다. 다중 검정 보정이 적용되지 않습니다.

### 문제

```
FWER = 1 - (1 - 0.05)^15 ≈ 0.537  (53.7%)
```

### 수정 방안

Bonferroni는 지나치게 보수적입니다. **Benjamini–Hochberg(BH) FDR이 탐색적 분석에는 적합**합니다. 둘 다 남기고 `significant` 판정은 조정 후 기준으로:

1. 전체 Granger 결과 리스트 수집 후 `statsmodels.stats.multitest.multipletests(pvalues, method="fdr_bh")`로 `pvalue_adjusted`, `reject_bh` 부여.
2. 함께 Bonferroni 임계값도 계산해 메타데이터에 기록.
3. `significant` 필드는 BH 조정 후 기준으로 True/False 설정하고, `pvalue_raw`는 별도 보존.

```python
entry = {
    "predictor": ..., "target": ..., "lag": ...,
    "pvalue": pvalue_raw,
    "pvalue_bh": pvalue_adjusted_bh,
    "significant": bool(reject_bh),
    "bonferroni_threshold": 0.05 / n_tests,
}
```

수정 대상:

| 파일 | 변경 |
|---|---|
| `statistical_tests.py` | 결과 리스트에 BH 보정 적용 + `n_granger_tests`, `bonferroni_threshold`, 각 entry에 `pvalue_bh` 추가 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `granger_correction={method, n_tests, threshold}` 필드 추가 |
| `tests/analysis/test_sentiment_join/test_statistical_tests.py` | 보정 결과 단위 테스트 추가 |

---

## 5. Granger 검정 쌍별 유효 행 수 미기록

### 현상

`_run_granger`에서 `work = work.dropna()` 후 실제 검정에 사용된 행 수가 결과에 기록되지 않습니다.

### 수정 방안

`_run_granger` 반환값에 `effective_rows`, `date_range`, `calendar_span_days` 필드 추가:

```python
entry: dict[str, Any] = {
    "predictor": predictor,
    "target": target,
    "lag": lag,
    "pvalue": pvalue,
    "significant": pvalue < 0.05,
    "effective_rows": len(work),
    "calendar_span_days": _calendar_span(df.loc[work.index, "date"]),
}
```

**`effective_rows`만으로는 부족**한 이유는 §8 참조 — 이상치 제거로 달력 연속성이 깨지면 `effective_rows=180`이어도 실제 span은 220일이 될 수 있습니다.

---

## 6. `grangercausalitytests` 중복 호출 (효율성)

### 현상

```python
for lag in GRANGER_LAGS:  # [1, 2, 3]
    entry = _run_granger(df, predictor, target, lag)
```

`grangercausalitytests(work, maxlag=lag)`은 내부적으로 lag 1…maxlag 전부를 돌립니다. 결과적으로 lag=1은 3번, lag=2는 2번 중복 계산.

### 수정 방안

`_run_granger_all_lags`로 일회 호출, 모든 lag 결과 추출:

```python
def _run_granger_all_lags(df, predictor, target, max_lag=3):
    ...
    result = grangercausalitytests(work, maxlag=max_lag, verbose=False)
    return [
        {
            "predictor": predictor, "target": target, "lag": lag,
            "pvalue": float(result[lag][0]["ssr_ftest"][1]),
            "f_statistic": float(result[lag][0]["ssr_ftest"][0]),
            "df_num": int(result[lag][0]["ssr_ftest"][2]),
            "df_denom": int(result[lag][0]["ssr_ftest"][3]),
            "effective_rows": len(work),
        }
        for lag in range(1, max_lag + 1)
    ]
```

§2의 AIC/BIC 자동 선택을 도입하면 이 구조가 그대로 `optimal_lag` 추출에 재사용됩니다.

---

## 7. F-statistic과 자유도 미기록

### 현상

```python
pvalue = float(result[lag][0]["ssr_ftest"][1])
# 원본 tuple: (F_statistic, p_value, df_denom, df_num)
```

p-value만 기록. 효과 크기(F-statistic)와 자유도(`df_num`, `df_denom`)가 누락되어 재현·메타분석 불가.

### 수정

§6의 구현이 이미 `f_statistic`, `df_num`, `df_denom`을 포함하도록 설계했습니다. 별도 작업 없이 §6와 함께 처리.

추가로 **효과 크기**를 해석 가능하게 전달하려면 `sample_size`와 함께 `f_statistic / effective_rows` 또는 `partial R²` 수준의 파생 지표를 계산해 메타데이터에 싣는 것이 유용합니다.

---

## 8. 🔴 이상치 제거로 인한 time-index gap (신규)

### 현상

[pipeline.py:246](src/morning_brief/analysis/sentiment_join/pipeline.py#L246):

```python
analysis_df = master_df.loc[~master_df["is_outlier"]].reset_index(drop=True)
...
statistical_results = run_statistical_tests(analysis_df)
```

`is_outlier=True`인 행은 **analysis_df에서 완전히 제거**된 뒤 통계 검정에 투입됩니다. 그런데 `grangercausalitytests`는 DataFrame 행 순서를 균일한 시간 간격으로 가정합니다. 달력상 불연속이 생기면:

- `[2026-03-10, 2026-03-12, 2026-03-14]` (중간 11·13일이 outlier로 제거)을 넣으면 "lag-1"이 실제로는 **calendar lag-2**에 해당.
- 15번의 rolling IQR 탐지로 연간 5~20행이 제거될 수 있어 정량적으로 무시 못할 bias.

### 수정 방안

세 가지 선택지 중 하나:

**A. 값만 NaN으로 마스킹 (권장)**: 해당 날짜 행은 남기고 수치 컬럼만 NaN 처리. Granger 단계의 `work.dropna()`가 이를 제거하지만, 연속 구간 경계가 코드에 드러나 후속 개선(예: 스플라인 보간, 블록 기준 검정)이 쉬워짐. 동시에 **연속 gap 길이 분포**를 메타데이터에 로깅.

**B. 선형 보간**: 이상치 자리를 `np.nan` → `interpolate("time")`으로 채움. 단 한두 행에 대해서만 허용하고, 연속 2행 이상 gap이면 skip.

**C. 세그먼트 분할**: 연속 구간별로 Granger를 돌리고 결과를 메타분석. 구현이 가장 무겁지만 가장 정직한 방식.

**최소 방어**: 어떤 전략을 택하든 `effective_rows`와 함께 `calendar_span_days`, `max_consecutive_gap_days`를 메타데이터에 기록. `max_consecutive_gap_days > 1` 경우 Granger 결과에 `warning: "non_contiguous_dates"` 플래그.

### 구현 위치

- `pipeline.py:246`의 필터를 `analysis_df = master_df.copy(); analysis_df.loc[analysis_df["is_outlier"], <numeric_cols>] = np.nan`으로 변경 (A안).
- `_run_granger`에 gap 진단 코드 추가.
- `tests/analysis/test_sentiment_join/test_join.py` / `test_statistical_tests.py`에 gap 감지·보고 테스트 추가.

**영향도**: 🔴 통계 결과의 해석 자체를 바꾸는 문제. §4·§5와 함께 반드시 처리해야 함.

---

## 9. 🟡 자기상관/Heteroskedasticity 요약 진단 누락 (신규)

BTC 수익률의 **자기상관(Ljung-Box)** 과 **조건부 이분산(ARCH LM)** 은 Granger 해석에 직접 영향을 줍니다. 현재 `adf_results`만 기록되어, Granger 결과를 신뢰할 수 있는지 사후 판단 재료가 부족합니다.

**수정 방안**:

```python
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

diagnostics = {
    "ljung_box_lag10_p": float(acorr_ljungbox(series, lags=[10])["lb_pvalue"].iloc[0]),
    "arch_lm_lag5_p": float(het_arch(series, nlags=5)[1]),
}
```

`run_statistical_tests` 반환 dict에 `residual_diagnostics` 키로 추가하고, `build_stats_metadata_payload`에 전달.

---

## 10. 🟢 백필 `_backfill=True` 무조건 표기의 의미론 누수 (신규)

[analytics_contract.py:47-72](src/morning_brief/data/storage/analytics_contract.py#L47-L72)의 `build_analytics_sentiment_payload`는 **실제 파이프라인에서도 `_backfill=True`를 강제로 기록**합니다. 이는 원래 의도(백필인지 실시간인지 구분)를 흐리게 만들어, `validate_analytics_sentiment_payload`가 `_backfill` 없는 레거시 파일만 걸러내는 "존재 여부 체크"로 축소되어 있습니다.

영향:
- §3에서 제안한 `producer` 접두사 기반 구분이 유일한 백필/실시간 판별 수단이 됨 → `producer` 필드 규약이 깨지면 보호 로직도 무효.

**수정 제안**:
- `build_analytics_sentiment_payload`의 `_backfill` 값을 호출자가 지정하도록 파라미터화(기본 False)하고, 실제 파이프라인은 False로 기록.
- 기존 레거시 파일을 마이그레이션하거나, validator에서 `_backfill is True` 대신 "필수 필드 존재" 체크로 약화.

영향도는 낮지만, §3 수정 시 의미론 정합성을 위해 함께 정리 권장.

---

## 수정 우선순위 (2순위 내, task 01 완료 전제)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **2-1** | 백필 JSON 구조 불일치 + `_is_pipeline_file` 동반 수정 (§3) | 🔴 180행 확보 불가 / `--force` 재실행 차단 | 저 |
| **2-2** | 이상치 제거로 인한 time-index gap (§8) | 🔴 Granger 해석 전제 붕괴 | 중 |
| **2-3** | ADF 대상에 predictor(lag1) 누락 + KPSS 공동 검정 (§1) | 🟡 전제 조건 미검증 / 검정력 부족 | 저~중 |
| **2-4** | ADF 비정상 시 Granger gate 미작동 + 차분 재시도 (§1) | 🟡 spurious 인과 | 저 |
| **2-5** | 다중 검정 보정(BH-FDR 중심) (§4) | 🟡 FWER 53.7% | 저 |
| **2-6** | 쌍별 `effective_rows`, `calendar_span_days` 미기록 (§5) | 🟡 gap 탐지·재현 기반 | 저 |
| **2-7** | HAC / 로버스트 추론 또는 블록 부트스트랩 (§2) | 🟡 변동성 군집에서 over-rejection | 중 |
| **2-8** | 잔차 진단(Ljung-Box, ARCH LM) 요약 (§9) | 🟡 해석 신뢰도 | 저 |
| **2-9** | Lag 자동 선택(AIC/BIC) (§2) | 🟢 보고 구조 정돈 | 중 |
| **2-10** | F-statistic·df 기록, 중복 호출 제거 (§6·§7) | 🟢 재현성 / 효율 | 저 |
| **2-11** | `_backfill` 플래그 의미론 정리 (§10) | 🟢 계약 정합성 | 저 |

**2-1·2-2가 가장 치명적**입니다. 2-1은 백필을 돌려도 데이터가 통과하지 못하는 문제, 2-2는 설령 데이터가 통과해도 통계 해석이 잘못되는 문제입니다. 둘은 독립적으로 해결되어야 하며, 둘 다 해결된 뒤에야 2-3~2-8의 "결과 품질 개선" 작업들이 의미를 갖습니다.

### 권장 PR 분할

| PR | 항목 | 비고 |
|---|---|---|
| PR-A | 2-1 (§3) | uploader·contract·uploader 보호 로직 묶음. CI에 계약 검증 단위 테스트 추가 |
| PR-B | 2-2 (§8) | 이상치 마스킹 전환 + gap 메트릭. Granger 단위 테스트 갱신 |
| PR-C | 2-3·2-4·2-5·2-6 | ADF/KPSS gate + BH 보정 + effective_rows. 의미 연쇄이므로 한 PR |
| PR-D | 2-7·2-8·2-9·2-10·2-11 | 품질 개선·보고 구조 정리 |
