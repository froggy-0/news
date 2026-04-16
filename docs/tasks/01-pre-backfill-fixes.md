# Sentiment-Join 파이프라인 — 선행 개선 사항

> 백필 데이터 생성 전에 반드시 해결해야 하는 항목입니다.
> 이 상태로 180일치를 백필하면 Granger 검정 결과가 오염됩니다.

---

## 1. `news_sentiment_mean`, `fng_value`에 Lag-1 미적용

### 현상

`_add_futures_lag_columns` (`join.py:77-96`)에서 선물/ETF 지표에만 `.shift(1)`을 적용합니다.
`news_sentiment_mean`과 `fng_value`는 Lag 처리 없이 같은 날짜의 `btc_log_return`과 나란히 놓입니다.

```python
# join.py — 현재 Lag-1이 적용되는 변수
result["funding_rate_lag1"] = result["funding_rate"].shift(1)
result["oi_change_pct_lag1"] = result["open_interest_usd"].pct_change().shift(1)
result["btc_long_short_ratio_lag1"] = result["btc_long_short_ratio"].shift(1)
result["etf_net_inflow_usd_lag1"] = result["etf_net_inflow_usd"].shift(1)
# news_sentiment_mean → shift 없음
# fng_value → shift 없음
```

그런데 이 두 변수는 `GRANGER_PAIRS`에서 predictor로 사용됩니다:

```python
# statistical_tests.py:15-21
GRANGER_PAIRS = [
    ("news_sentiment_mean", "btc_log_return"),   # ← 원본 그대로
    ("funding_rate_lag1", "btc_log_return"),      # ← lag1 적용됨
    ("fng_value", "btc_log_return"),              # ← 원본 그대로
    ("btc_long_short_ratio_lag1", "btc_log_return"),
    ("etf_net_inflow_usd_lag1", "btc_log_return"),
]
```

### 문제

"어제의 감성/공포지수가 오늘의 BTC 수익률을 예측하는가"를 검정하려면, predictor가 target보다 시간적으로 앞서야 합니다. 현재는 같은 날짜 데이터끼리 비교하므로 **look-ahead bias** 가능성이 있습니다.

R2 감성 데이터가 "전일 뉴스의 집계"라는 시간 의미론이 있을 수 있지만, 이것이 코드에 명시되어 있지 않고 F&G Index도 마찬가지입니다.

### 수정 방안

`join.py`의 `_add_futures_lag_columns` (또는 별도 함수)에서 두 변수에도 shift를 적용하고, `GRANGER_PAIRS`의 predictor명을 lag1 버전으로 변경합니다.

수정 대상 파일:

| 파일 | 변경 |
|---|---|
| `src/morning_brief/analysis/sentiment_join/join.py` | `news_sentiment_mean_lag1`, `fng_value_lag1` 컬럼 생성 |
| `src/morning_brief/analysis/sentiment_join/statistical_tests.py` | `GRANGER_PAIRS`에서 predictor명 변경 |
| `src/morning_brief/analysis/sentiment_join/hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES`에서 `news_sentiment_mean` → `news_sentiment_mean_lag1`, `fng_value` → `fng_value_lag1` |
| `src/morning_brief/analysis/sentiment_join/validate.py` | `MASTER_SCHEMA`에 새 컬럼 추가 |
| 관련 테스트 | lag1 컬럼 존재 및 값 검증 |

---

## 2. 백필 `why_it_matters` 빈 문자열 고정

### 현상

백필 스코어러 (`scripts/backfill/scorer.py:99`):

```python
build_news_sentiment_text({"title": a.title, "summary": a.body, "why_it_matters": ""})
```

실제 파이프라인에서는 뉴스 항목의 `why_it_matters` 필드가 있으면 그대로 전달됩니다:

```python
# finbert_sentiment.py:312-316
text_builder = text_builder or build_news_sentiment_text
texts = [text_builder(items[i]) for i in selected]
# items[i]["why_it_matters"]가 존재하면 combine_fields에 포함
```

`build_news_sentiment_text`는 `combine_fields(title, summary, why_it_matters)`를 호출하며, 필드별 토큰 제한은 (64, 224, 224)입니다. `why_it_matters`가 있으면 최대 224 토큰이 추가로 입력에 포함됩니다.

### 문제

백필 데이터의 FinBERT 입력 텍스트가 실제 파이프라인과 달라집니다. 동일한 기사라도 `why_it_matters` 유무에 따라 감성 점수가 달라질 수 있으며, 이는 시계열의 일관성을 깨뜨립니다.

### 원인

백필 소스(CoinDesk, Alpaca)의 `RawArticle` 구조에 `why_it_matters` 필드가 없습니다:

```python
# scripts/backfill/sources/coindesk.py:26-41
class RawArticle:
    source: Literal["coindesk", "alpaca"]
    article_id: str
    date: str
    title: str
    body: str          # summary 역할
    published_ts: int
    # why_it_matters 필드 없음
```

### 수정 방안

두 가지 선택지:

**A. 실제 파이프라인도 `why_it_matters` 없이 추론하도록 통일** — 가장 간단하지만 현재 운영 중인 점수가 바뀜

**B. 백필 소스에서도 `why_it_matters`를 생성** — CoinDesk/Alpaca 원본에 해당 필드가 없으므로 빈 문자열이 불가피. 대신 이 차이를 문서화하고, 백필 데이터에 `backfill_text_mismatch=True` 같은 메타데이터를 남김

현실적으로는 **B + 영향도 측정**이 적절합니다. 실제 파이프라인의 최근 뉴스에서 `why_it_matters` 유무에 따른 점수 차이를 샘플링하여, 차이가 무시할 수준인지 확인합니다.

---

## 3. 백필 `batch_size` 불일치 (32 vs 16)

### 현상

```python
# scripts/backfill/scorer.py:31-39
class _BackfillFinBertSettings:
    finbert_batch_size: int = 32      # ← 백필

# src/morning_brief/config.py:240-242
finbert_batch_size=_env_bounded_int(
    "FINBERT_BATCH_SIZE", default=16,  # ← 파이프라인
    minimum=1, maximum=64
)
```

### 문제

`batch_size`가 다르면 padding 길이가 달라지고, transformer의 attention mask가 변하면서 softmax 출력이 미세하게 달라질 수 있습니다. 대부분의 경우 차이는 소수점 4자리 이하이지만, 엄밀한 시계열 재현성을 요구하면 문제가 됩니다.

### 수정 방안

`_BackfillFinBertSettings`의 기본값을 16으로 변경:

```python
# scripts/backfill/scorer.py
class _BackfillFinBertSettings:
    finbert_batch_size: int = 16  # 파이프라인 기본값과 동일
```

---

## 수정 우선순위

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **1** | Lag-1 미적용 (§1) | 🔴 Granger 검정 결과 오염 | 중 (5개 파일 + 테스트) |
| **2** | why_it_matters 불일치 (§2) | 🟡 시계열 일관성 저하 | 저 (영향도 측정 후 판단) |
| **3** | batch_size 불일치 (§3) | 🟢 미세한 수치 차이 | 저 (1줄 변경) |

**§1은 백필 전에 반드시 해결해야 합니다.** §2, §3은 영향도를 측정한 뒤 판단할 수 있지만, 같이 처리하는 것이 깔끔합니다.
