# Granger 교차 쌍 설계

> pre-backfill-fixes §1 (Lag-1 수정) 시 함께 적용

---

## 설계 원칙

1. **Target**: `btc_log_return` 단일
2. **Predictor**: 마스터 테이블의 모든 정상(또는 정상 변환 가능) 시계열 변수 (lag1 적용)
3. **교차 쌍**: predictor 간 상호 인과성도 검정하여 정보 전파 경로를 파악
4. **다중 검정 보정**: 쌍 수 증가에 따라 Bonferroni 임계값을 메타데이터에 기록

---

## Predictor 변수 목록

마스터 테이블에서 Granger predictor로 사용할 수 있는 시계열 변수:

| # | 변수 (lag1 적용 후) | 원본 | 성격 | 정상성 기대 |
|---|---|---|---|---|
| 1 | `news_sentiment_mean_lag1` | 뉴스 감성 평균 | 감성 | ✅ bounded (-1~1) |
| 2 | `fng_value_lag1` | Fear & Greed Index | 심리 | ✅ bounded (0~100) |
| 3 | `funding_rate_lag1` | 선물 펀딩비 | 선물 | ✅ mean-reverting |
| 4 | `btc_long_short_ratio_lag1` | Long/Short 비율 | 선물 | ✅ bounded ratio |
| 5 | `oi_change_pct_lag1` | 미결제약정 변화율 | 선물 | ✅ 이미 pct_change |
| 6 | `etf_net_inflow_usd_lag1` | ETF 일별 순유입 | ETF | ✅ 이미 diff 성격 |
| 7 | `usdkrw_log_return_lag1` | 원/달러 로그 수익률 | 환율 | ✅ 수익률 변환 완료 |
| 8 | `btc_quote_volume_lag1` | BTC 거래량 | 거래량 | ⚠️ 레벨값 — `volume_change_pct_lag1`로 변환 권장 |

> **`btc_quote_volume` 정상성 문제**: USD 단위 절대 거래량은 전형적인 비정상 시계열입니다. Granger 검정의 정상성 전제를 충족하려면 `pct_change().shift(1)`로 변환하여 `volume_change_pct_lag1`을 사용하는 것이 적절합니다. 이는 `oi_change_pct_lag1`과 동일한 패턴입니다.

**제외 변수와 사유:**

| 변수 | 제외 사유 |
|---|---|
| `btc_return` | `btc_log_return`과 정보 중복 |
| `usdkrw_return` | `usdkrw_log_return`과 정보 중복 |
| `news_sentiment_std` | 분산 지표 — 방향성 예측보다 불확실성 지표, 우선순위 낮음 |
| `n_articles` | 기사 수 — 감성 강도가 아닌 양적 지표, 우선순위 낮음 |
| `etf_total_btc` | 누적 레벨값 — 비정상 시계열, `etf_net_inflow_usd`로 대표 |
| `etf_total_aum_usd` | 동일 사유 |
| `open_interest_usd` | 레벨값 — `oi_change_pct_lag1`로 대표 |
| `funding_rate` | lag1 버전 사용 |
| `btc_long_short_ratio` | lag1 버전 사용 |
| `etf_net_inflow_usd` | lag1 버전 사용 |

---

## Granger 쌍 설계

### A. 모든 predictor → btc_log_return (핵심)

각 predictor가 BTC 수익률을 선행하는가?

```python
_TARGET = "btc_log_return"
_PREDICTORS = [
    "news_sentiment_mean_lag1",
    "fng_value_lag1",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",
    "oi_change_pct_lag1",
    "etf_net_inflow_usd_lag1",
    "usdkrw_log_return_lag1",
    "volume_change_pct_lag1",
]

# 8쌍
GRANGER_PAIRS_TARGET = [
    (pred, _TARGET) for pred in _PREDICTORS
]
```

### B. predictor 간 교차 인과성 (정보 전파 경로)

핵심 지표 간 상호 선행 관계를 검정합니다. 모든 조합(8C2=28쌍 × 양방향=56쌍)은 과도하므로, 의미 있는 교차 쌍만 선별합니다:

```python
GRANGER_PAIRS_CROSS = [
    # 감성 → 심리: 뉴스가 F&G를 선행하는가?
    ("news_sentiment_mean_lag1", "fng_value"),
    # 심리 → 감성: F&G가 뉴스 톤을 선행하는가?
    ("fng_value_lag1", "news_sentiment_mean"),
    # 감성 → 선물: 뉴스가 선물 시장 심리를 선행하는가?
    ("news_sentiment_mean_lag1", "funding_rate"),
    # 감성 → ETF: 뉴스가 ETF 자금 흐름을 선행하는가?
    ("news_sentiment_mean_lag1", "etf_net_inflow_usd"),
    # 심리 → 선물: 공포지수가 선물 포지션을 선행하는가?
    ("fng_value_lag1", "btc_long_short_ratio"),
    # 심리 → ETF: 공포지수가 ETF 자금 흐름을 선행하는가?
    ("fng_value_lag1", "etf_net_inflow_usd"),
    # 환율 → BTC 거래량: 원/달러 변동이 BTC 거래량 변화를 선행하는가?
    ("usdkrw_log_return_lag1", "volume_change_pct"),
    # 선물 → ETF: 펀딩비가 ETF 흐름을 선행하는가?
    ("funding_rate_lag1", "etf_net_inflow_usd"),
]
```

> **교차 쌍 target의 dtype 주의**: `fng_value`는 `Int64`(nullable integer)입니다. 현재 `_run_granger`는 predictor에만 `pd.to_numeric`을 적용하므로, **target에도 `pd.to_numeric` 변환을 추가**해야 `grangercausalitytests`에서 Int64 관련 오류가 발생하지 않습니다.
>
> ```python
> # _run_granger 수정 필요
> work = df[[target, predictor]].copy()
> work[target] = pd.to_numeric(work[target], errors="coerce")      # ← 추가
> work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
> work = work.dropna()
> ```

### C. 최종 GRANGER_PAIRS

```python
GRANGER_PAIRS = GRANGER_PAIRS_TARGET + GRANGER_PAIRS_CROSS
# 8 + 8 = 16쌍 × 3 lags = 48개 검정
```

### D. 다중 검정 보정

```
Bonferroni 임계값 = 0.05 / 48 = 0.00104
```

---

## 새로 필요한 lag1 컬럼

pre-backfill-fixes §1에서 함께 추가:

| 새 컬럼 | 원본 | 생성 방법 |
|---|---|---|
| `news_sentiment_mean_lag1` | `news_sentiment_mean` | `.shift(1)` |
| `fng_value_lag1` | `fng_value` | `.shift(1)` |
| `usdkrw_log_return_lag1` | `usdkrw_log_return` | `.shift(1)` |
| `volume_change_pct` | `btc_quote_volume` | `.pct_change()` |
| `volume_change_pct_lag1` | `volume_change_pct` | `.shift(1)` (= `pct_change().shift(1)`) |

> `volume_change_pct_lag1`은 `oi_change_pct_lag1`과 동일한 패턴(`pct_change().shift(1)`)입니다.
> `volume_change_pct`(shift 전)는 교차 쌍 B그룹의 target으로 사용됩니다.

기존 lag1 컬럼 (변경 불필요):
- `funding_rate_lag1` — 이미 존재
- `oi_change_pct_lag1` — 이미 존재
- `btc_long_short_ratio_lag1` — 이미 존재
- `etf_net_inflow_usd_lag1` — 이미 존재

---

## ADF_TARGETS 업데이트

Granger에 투입되는 모든 변수의 정상성을 검증합니다.
shift(1)은 정상성을 바꾸지 않으므로 원본에 대해 검정합니다:

```python
ADF_TARGETS = [
    # target
    "btc_log_return",
    # predictor 원본 (lag1은 shift만이므로 정상성 동일)
    "news_sentiment_mean",
    "fng_value",
    "funding_rate",
    "btc_long_short_ratio",
    "etf_net_inflow_usd",
    "usdkrw_log_return",
    # 변환된 시계열 (pct_change 적용 후)
    "oi_change_pct_lag1",
    "volume_change_pct",
]
```

---

## 수정 대상 파일 요약

| 파일 | 변경 |
|---|---|
| `join.py` | `_add_futures_lag_columns`에 5개 컬럼 추가 (`news_sentiment_mean_lag1`, `fng_value_lag1`, `usdkrw_log_return_lag1`, `volume_change_pct`, `volume_change_pct_lag1`) |
| `join.py` | `detect_outliers_rolling_iqr` 호출 시 `cols`에 `news_sentiment_mean`, `fng_value`, `etf_net_inflow_usd`, `btc_quote_volume` 추가 |
| `statistical_tests.py` | `GRANGER_PAIRS` 16쌍으로 교체, `ADF_TARGETS` 9개로 확장, `_run_granger`에서 target에도 `pd.to_numeric` 적용 |
| `validate.py` | `MASTER_SCHEMA`에 5개 컬럼 추가 |
| `hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES`의 변수명을 lag1 버전으로 변경 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `n_granger_tests`, `bonferroni_threshold` 추가 |
| 관련 테스트 | 새 컬럼 존재 검증, 쌍 수 16 검증, `fng_value` target dtype 검증, 이상치 대상 컬럼 검증 |
