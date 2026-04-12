# Design Document — binance-integration

## Overview

Binance Spot API를 BTC 현물 가격 1차 소스로 도입하고, 선물 Long/Short Ratio를 추가하여 마스터 데이터셋의 분석 Coverage를 확장한다. 기존 코드베이스 분석에서 `get_json_with_retry()`가 `dict`만 허용하나 Binance 공개 엔드포인트(`/fapi/v1/fundingRate`, `/api/v3/klines`)는 JSON 배열(list)을 반환한다는 잠재 버그를 확인했다. 이번 설계에서 함께 수정한다.

---

## ① 시스템 아키텍처 및 데이터 흐름

### Source Layer

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Source Layer                                  │
│                                                                        │
│  [binance.py] fetch_btc_close_binance(start, end, api_key)             │
│    ├─ PRIMARY:  GET api.binance.com/api/v3/klines                      │
│    │            symbol=BTCUSDT, interval=1d                            │
│    │            → {"date": str, "close": float64,                      │
│    │               "btc_quote_volume": float64}                        │
│    │            attrs["btc_source"] = "binance"                        │
│    └─ FALLBACK: btc_prices.fetch_btc_close(start, end)  [기존 유지]    │
│                 → CoinGecko → yfinance chain                           │
│                 attrs["btc_source"] = "coingecko" | "yfinance"         │
│                 btc_quote_volume = NaN                                 │
│                                                                        │
│  [futures.py] fetch_futures_data(lookback_days)  [기존 + 확장]         │
│    ├─ /fapi/v1/fundingRate       → funding_rate      (기존)            │
│    ├─ /futures/data/openInterestHist → open_interest_usd (기존)        │
│    └─ /futures/data/globalLongShortAccountRatio → btc_long_short_ratio │
│                                                        (신규)          │
│                                                                        │
│  [r2_sentiment.py] fetch_r2_sentiment()  [변경 없음]                   │
│    └─ R2 briefs/{date}.json → news_sentiment_mean, signal_sentiment    │
│                                                                        │
│  [fng.py] fetch_fng()  [변경 없음]                                     │
│    └─ alternative.me → fng_value                                       │
│                                                                        │
│  [usdkrw_prices.py] fetch_usdkrw_close()  [변경 없음]                  │
│    └─ KIS FHKST03030100 → yfinance KRW=X fallback                     │
└────────────────────────────────────────────────────────────────────────┘
```

**폴백 체인 상세 (`binance.py`):**

```
fetch_btc_close_binance(start, end, api_key)
    │
    ▼  [1차] GET /api/v3/klines (get_list_with_retry 사용)
    │        params: symbol=BTCUSDT, interval=1d, startTime={ms}, limit={n}
    │        ※ 응답이 JSON list임 — get_json_with_retry() 사용 불가
    │        ※ 모든 가격값은 str 타입 → float() 변환 필수
    │        parse: open_time(idx0) → date, close(idx4) str→float, 
    │               quote_asset_volume(idx7) str→float
    │  성공 → return df, attrs["btc_source"]="binance"
    │
    ▼  실패 (4xx/5xx/timeout, 최대 3회 지수 백오프)
    │  WARNING log: event=fallback.used | source=btc | reason
    │
    ▼  [2차] btc_prices.fetch_btc_close(start, end)
            │  (기존 CoinGecko → yfinance 체인 그대로 실행)
            │  btc_quote_volume = NaN 컬럼 추가
            └─ return df, attrs["btc_source"]="coingecko"|"yfinance"
```

**klines 파싱 구현 예시:**

```python
# 실측 API 응답 형식 (2026-04-12 기준 검증):
# row = [1775779200000, '71787.98', '73434.00', '71426.15', '72962.70',
#        '17372.63', 1775865599999, '1259195636.05', 3176308, ...]
# 인덱스:  0(open_time)                                      6(close_time)  7(quote_vol)

def _parse_kline_row(row: list) -> dict:
    open_time_ms = int(row[0])
    date = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    close = float(row[4])          # str → float
    quote_vol = float(row[7])      # str → float
    return {"date": date, "close": close, "btc_quote_volume": quote_vol}
```

### Transform Layer (변경 없음)

```
normalize_dates() → YYYY-MM-DD UTC 통일
forward_fill_prices(cols=["close"], max_periods=2) → BTC, USDKRW 주말/공휴일 gap 최대 2일 채움
compute_returns("close") → close_log_return, close_return
_rename_returns() → btc_log_return, btc_return
trim_to_date_range() → lookback window로 자름
```

`btc_quote_volume`은 수익률이 아니라 절대값이므로 `compute_returns()` 처리 대상에서 제외. `btc_quote_volume`은 close_df와 함께 전달되어 `btc_returns_df`에 컬럼으로 유지된다.

### Join Layer (join.py — 확장)

```
merge_sources(sentiment_df, fng_df, btc_df, usdkrw_df, futures_df)
    │
    ▼ Step 1: news_sentiment_mean NaN 행 제거 (rows.dropped warning)
    ▼ Step 2: sentiment ← inner join → fng  (date key)
    ▼ Step 3: ← inner join → btc_returns   (date key)
    │          btc_df는 close_log_return, close_return, btc_quote_volume 포함
    ▼ Step 4: ← inner join → usdkrw_returns (date key)
    ▼ Step 5: ← LEFT join  → futures        (date key)
    │          futures에 funding_rate, open_interest_usd, btc_long_short_ratio 포함
    │          futures 장애 시 NaN 컬럼으로 계속 진행
    ▼ Step 6: _add_futures_lag_columns()
    │          funding_rate_lag1     = funding_rate.shift(1)
    │          oi_change_pct_lag1    = open_interest_usd.pct_change().shift(1)
    │          btc_long_short_ratio_lag1 = btc_long_short_ratio.shift(1)  ← 신규
    ▼ Step 7: detect_outliers_rolling_iqr(
    │              cols=["btc_return", "usdkrw_return",
    │                    "funding_rate",          ← 신규
    │                    "open_interest_usd",     ← 신규
    │                    "btc_long_short_ratio"])  ← 신규
    ▼ → master_df (21 columns)
```

**설계 이유:** inner join을 sentiment 기준으로 사용하는 이유는 감성 데이터가 없는 날은 분석 의미가 없기 때문이다. futures는 LEFT join으로 사용해 데이터 수집 실패가 행 수를 줄이지 않도록 한다.

---

## ② 상세 데이터 스키마

### MASTER_SCHEMA 최종 컬럼 정의 (validate.py)

| # | 컬럼명 | 타입 | nullable | 범위 제약 | 출처 | 신규 |
|---|--------|------|----------|-----------|------|------|
| 1 | `date` | `str` | No | `^\d{4}-\d{2}-\d{2}$`, unique | 결합 키 | |
| 2 | `news_sentiment_mean` | `float64` | No | -1.0 ~ 1.0 | R2 FinBERT | |
| 3 | `news_sentiment_std` | `float64` | Yes | ≥ 0 | R2 FinBERT | |
| 4 | `n_articles` | `Int64` | Yes | ≥ 0 | R2 FinBERT | |
| 5 | `signal_sentiment_mean` | `float64` | Yes | -1.0 ~ 1.0 | R2 X signal | |
| 6 | `signal_sentiment_std` | `float64` | Yes | ≥ 0 | R2 X signal | |
| 7 | `n_signals` | `Int64` | Yes | ≥ 0 | R2 X signal | |
| 8 | `fng_value` | `Int64` | Yes | 0 ~ 100 | Alternative.me | |
| 9 | `btc_log_return` | `float64` | Yes | — | Binance/CG/YF | |
| 10 | `btc_return` | `float64` | Yes | — | Binance/CG/YF | |
| 11 | `btc_quote_volume` | `float64` | Yes | ≥ 0 | Binance Spot | **NEW** |
| 12 | `usdkrw_log_return` | `float64` | Yes | — | KIS/yfinance | |
| 13 | `usdkrw_return` | `float64` | Yes | — | KIS/yfinance | |
| 14 | `is_outlier` | `bool` | No | — | 롤링 IQR | |
| 15 | `funding_rate` | `float64` | Yes | — | Binance Futures | |
| 16 | `open_interest_usd` | `float64` | Yes | — | Binance Futures | |
| 17 | `funding_rate_lag1` | `float64` | Yes | — | shift(1) | |
| 18 | `oi_change_pct_lag1` | `float64` | Yes | — | pct_change().shift(1) | |
| 19 | `btc_long_short_ratio` | `float64` | Yes | ≥ 0 | Binance Futures | **NEW** |
| 20 | `btc_long_short_ratio_lag1` | `float64` | Yes | — | shift(1) | **NEW** |
| 21 | `hybrid_index` | `float64` | Yes | — | PCA | |

**타입 변환 규칙:**
- `Int64` (pandas nullable integer): `n_articles`, `fng_value`, `n_signals` — `pd.array(dtype="Int64")` 사용. pandera `strict=True` 모드에서 `str(dtype) != "Int64"` 체크 유지
- `btc_quote_volume`: klines 배열 인덱스 7, `float(row[7])` 변환, 음수 불가. **API는 str 반환** (예: `'1259195636.05566300'`)
- `btc_long_short_ratio`: `globalLongShortAccountRatio` 응답의 `longShortRatio` 필드, `float()` 변환. **API는 str 반환** (예: `'0.8829'`). 해석: < 1이면 숏 계정 우세

**Binance API 필드 타입 정리 (실측 검증):**

| 엔드포인트 | 필드 | API 반환 타입 | 변환 |
|-----------|------|-------------|------|
| klines | close (idx 4) | `str` | `float()` |
| klines | quote_asset_volume (idx 7) | `str` | `float()` |
| klines | open_time (idx 0) | `int` | ms → datetime |
| fundingRate | fundingRate | `str` | `float()` |
| fundingRate | fundingTime | `int` | ms → datetime |
| openInterestHist | sumOpenInterestValue | `str` | `float()` |
| openInterestHist | timestamp | `int` | ms → datetime |
| globalLongShortAccountRatio | longShortRatio | `str` | `float()` |
| globalLongShortAccountRatio | timestamp | `int` | ms → datetime |

### Parquet 커스텀 메타데이터 설계

`storage.py`의 `save_parquet()` 함수에 `btc_source: str` 파라미터를 추가한다.

```python
# storage.py — 변경 후 시그니처
def save_parquet(
    df: pd.DataFrame,
    output_dir: Path,
    run_date: str,
    *,
    ffill_days: int = 0,
    stats_metadata: bytes | None = None,
    btc_source: str = "unknown",   # ← 신규
) -> Path:
    ...
    metadata[b"ffill_days"] = str(ffill_days).encode()
    metadata[b"btc_source"] = btc_source.encode()        # ← 신규
    if stats_metadata is not None:
        metadata[b"sentiment_join_stats"] = stats_metadata
```

**이유:** `btc_source`는 통계 결과와 독립적인 수집 이력 정보이므로 `stats_metadata` JSON에 묻히지 않고 별도 최상위 키로 분리한다. PyArrow schema metadata는 바이트 키/값을 저장하므로 `b"btc_source"` 키 사용.

읽기 시: `pq.read_table(path).schema.metadata[b"btc_source"].decode()`

---

## ③ 통계 분석 엔진 설계

### 정상성 확보 — ADF 전처리 흐름

```
원시 데이터              전처리                    ADF 검정 대상
─────────────────────────────────────────────────────────────
BTC 종가 (비정상)   →  ln(P_t/P_{t-1})  →  btc_log_return  ✓
funding_rate        →  직접 사용 가능     →  funding_rate    (정상성 가정)
open_interest_usd   →  pct_change().shift →  oi_change_pct_lag1  ✓
btc_long_short_ratio →  직접 사용 가능    →  btc_long_short_ratio (유계 비율)
```

**현재 구현** (`statistical_tests.py:_run_adf()`):
- 대상: `btc_log_return` (단일 시계열)
- 라이브러리: `statsmodels.tsa.stattools.adfuller`
- 유의수준: `pvalue < 0.05` → `stationary=True`
- 비정상 시: `WARNING` 로그 출력, 파이프라인 중단 없음

**이번 변경:** ADF 검정 대상 컬럼 목록을 `GRANGER_PAIRS`와 독립적으로 관리하여 `btc_log_return` 외 `funding_rate`, `oi_change_pct_lag1`, `btc_long_short_ratio`의 정상성도 로그로 기록할 수 있도록 `run_statistical_tests()`에 다중 ADF 지원을 추가한다.

```python
# statistical_tests.py — 변경 방향 (현재 단일 → 다중)
# btc_log_return: 로그 수익률, 정상성 가정 ✓
# funding_rate: 8h 합산 일별 수익률 성격, 실측 예: [-0.000201, 0.000007, ...] → 정상성 가능
# oi_change_pct_lag1: pct_change 후 lag → 정상성 ✓
# btc_long_short_ratio: 유계 비율 [0, ∞), 정상성 가정 단계에서 검증 필요 ← 신규
ADF_TARGETS = [
    "btc_log_return",
    "funding_rate",
    "oi_change_pct_lag1",
    "btc_long_short_ratio",  # ← 신규: 유계 비율, 실측 약 0.8~1.2 범위
]

def run_statistical_tests(df):
    adf_results = {}
    for col in ADF_TARGETS:
        if col in df.columns and df[col].dropna().shape[0] >= MIN_ROWS_FOR_TESTS:
            adf_results[col] = _run_adf(df[col])
    results["adf"] = adf_results   # dict[str, dict] 구조로 변경 (기존 단일 dict → 다중)
```

**`btc_quote_volume` ADF 제외 이유:** 거래대금은 절대 USD 금액으로 장기 성장 추세를 가지는 비정상 시계열이다. 로그 차분(log difference) 처리 없이는 Granger 검정 투입이 부적절하다. 이번 범위에서는 ADF 대상에서 제외하고, 향후 `btc_quote_volume_log_return` 컬럼 추가 시 포함한다.

### Granger 인과성 검정 로직

**현재 구현:**
```python
GRANGER_LAGS = [1, 2, 3]
GRANGER_PAIRS = [
    ("news_sentiment_mean", "btc_log_return"),
    ("funding_rate_lag1",   "btc_log_return"),
    ("fng_value",           "btc_log_return"),
]
```

**이번 변경:** `btc_long_short_ratio_lag1` Granger 쌍 추가.

```python
GRANGER_PAIRS = [
    ("news_sentiment_mean",        "btc_log_return"),
    ("funding_rate_lag1",          "btc_log_return"),
    ("fng_value",                  "btc_log_return"),
    ("btc_long_short_ratio_lag1",  "btc_log_return"),  # ← 신규
]
```

**파라미터 설정 이유:**
- `maxlag=3`: 일별 데이터에서 3일 선행 효과까지 검정. 4일 이상은 시장 반응 속도 고려 시 실용성 낮음
- `p < 0.05`: 표준 유의수준. 현재 총 검정 수 = 4쌍 × 3 lag = 12회. Bonferroni 보정(`p < 0.05/12 ≈ 0.004`)은 탐색 단계에서 과도하게 보수적이므로 미적용. 대신 로그에 "다중비교 주의(uncorrected)" 명시 권고
- `ssr_ftest`: statsmodels `grangercausalitytests` 결과 dict의 `[lag][0]["ssr_ftest"][1]` 인덱스로 p-value 추출
- **구현 효율 주의:** 현재 코드는 `lag in [1,2,3]`을 반복하여 `grangercausalitytests(maxlag=lag)`를 3번 호출한다. `grangercausalitytests(maxlag=3)` 단일 호출로 lag 1~3 결과를 모두 얻을 수 있어 더 효율적이나, 기존 인터페이스 유지를 위해 현재 구조를 변경하지 않는다

### 하이브리드 지수 가중치 산출 — PCA 알고리즘

**현재 구현** (`hybrid_index.py`):

```
HYBRID_FEATURE_CANDIDATES = [
    "news_sentiment_mean",   # FinBERT 뉴스 감성
    "fng_value",             # Fear & Greed Index
    "funding_rate_lag1",     # 펀딩비 Lag-1
    "etf_net_inflow_usd",    # 미래 예정
]
```

**알고리즘 흐름:**
```
1. 후보 중 DataFrame에 실제 존재하는 컬럼 선별
2. 결측행 dropna → df_clean
3. StandardScaler → VIF 계산 (statsmodels.VIF)
4. VIF ≥ 10 인 변수 반복 제거 (최대 VIF 변수 우선 제거)
5. 잔여 변수 ≥ 2개 → PCA(n_all).fit() → cumvar ≥ 80% 달성 n_components 결정
6. PCA(n_components).fit_transform() → components[:,0] = hybrid_index
7. loadings (PC1 eigenvector) = 각 변수의 hybrid_index 기여 가중치
```

**이번 변경:** `btc_long_short_ratio_lag1`을 후보에 추가.

```python
HYBRID_FEATURE_CANDIDATES = [
    "news_sentiment_mean",
    "fng_value",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",  # ← 신규
    "etf_net_inflow_usd",
]
```

**설계 이유:** Long/Short Ratio는 레버리지 포지션 분포로 감성 지표와 독립적인 차원을 가질 가능성이 높다. VIF 필터가 자동으로 다중공선성을 제거하므로 후보에 추가해도 기존 결과가 degradation되지 않는다.

---

## ④ 하이브리드 감성 앙상블 로직

> **범위 명시:** LLM 감성 점수 수집은 이번 구현 범위에 포함되지 않는다. 아래는 향후 확장을 위한 데이터 계약 설계이다.

### FinBERT + LLM 앙상블 설계 (Future Extension)

**현황:** 현재 `news_sentiment_mean`은 ProsusAI/finbert가 뉴스 기사 원문(영문)에 부여한 점수의 일별 평균 (`meta.newsSentiment.mean`). X 시그널은 `signal_sentiment_mean`으로 별도 저장.

**앙상블 목표:** 전문 용어 분류에 강한 FinBERT + 문맥 해석에 강한 LLM을 결합하여 감성 신호 품질 향상.

**설계:**

```
Step 1: LLM 점수 수집 (모닝 브리핑 파이프라인에서 수행)
  - Gemini Flash / GPT-4o-mini에게 각 뉴스 기사 원문 전달
  - 프롬프트: "다음 기사의 BTC 가격에 대한 감성을 -1.0(부정)~1.0(긍정) 
              float JSON으로 응답: {\"score\": float}"
  - 클램핑: max(-1.0, min(1.0, raw_score))
  - 저장: R2 brief JSON의 meta.llmSentiment.mean, meta.llmSentiment.std

Step 2: R2 수집 (r2_sentiment.py 확장)
  - "meta.llmSentiment.mean" → llm_sentiment_mean (float64, nullable)
  - 스키마 컬럼 추가

Step 3: 앙상블 가중치 결정 — PCA-driven
  - 기존 hybrid_index PCA에서 PC1 loadings 추출:
    w_finbert = |loadings["news_sentiment_mean"]|
    w_llm     = |loadings["llm_sentiment_mean"]|  (존재 시)
  - 정규화: w_i / Σw_i
  - 앙상블 점수 = w_finbert * news_sentiment_mean + w_llm * llm_sentiment_mean
  - 저장: ensemble_sentiment (float64, nullable)

Step 4: Granger 검정 확장
  GRANGER_PAIRS += [("ensemble_sentiment", "btc_log_return")]
```

**스케일 정규화:** FinBERT는 이미 softmax 확률에서 [-1, 1]로 매핑됨. LLM 출력은 프롬프트 명세로 범위 강제, 수집 시 클램핑 적용. 두 소스 모두 `[-1, 1]` 범위이므로 가중 평균 후 클램핑 불필요.

---

## ⑤ 에러 처리 및 안정성 전략

### 핵심 문제: `get_json_with_retry()`의 list 응답 미지원

**현황:** `http_client.py`의 `get_json_with_retry()`는 JSON 응답이 `dict`가 아니면 `HttpFetchError`를 발생시킨다. **로컬 테스트 결과 확인**: Binance klines·fundingRate·openInterestHist·globalLongShortAccountRatio 엔드포인트 4개 모두 JSON 배열(list)을 반환한다. 기존 `futures.py`의 `_fetch_funding_rate_history()` 및 `_fetch_oi_history()`가 `get_json_with_retry()`를 사용 중이므로 실제 실행 시 `HttpFetchError("JSON 응답 구조가 예상과 달라요")`가 발생하는 버그다.

**해결:** `http_client.py`에 `get_list_with_retry()` 추가 (additive-only, 기존 함수 미변경).

```python
# http_client.py — 신규 추가
def get_list_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    provider: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF,
) -> list[Any]:
    response = _request_with_retry(
        url, params=params, headers=headers,
        provider=provider, timeout=timeout,
        retries=retries, backoff_seconds=backoff_seconds,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HttpFetchError(f"JSON 응답 형식을 확인하지 못했어요: {url}") from exc
    if not isinstance(payload, list):
        raise HttpFetchError(f"JSON 응답이 배열 형식이 아닙니다: {url}")
    return payload
```

`futures.py`의 `_fetch_funding_rate_history()`, `_fetch_oi_history()`와 신규 `_fetch_long_short_ratio()` 모두 `get_list_with_retry()` 사용.

### Rate Limit 대응 — 지수 백오프

**기존 인프라 활용:** `execute_with_provider_retry()`가 이미 지수 백오프를 구현하고 있다. `_request_with_retry()` → `execute_with_provider_retry()` 체인에 `base_backoff_seconds=1.2`, `max_attempts=3`으로 설정됨.

**신규 추가: 100ms 호출 간 지연**

Binance는 분당 가중치(weight) 한도를 IP 단위로 적용한다. 실측 엔드포인트별 weight: `klines`=2, `fundingRate`=5, `openInterestHist`=1, `globalLongShortAccountRatio`=1. 4개 엔드포인트 합산 weight=9 (기본 한도 1200/min의 0.75% 수준). 단일 실행에서 절대 한도를 초과하지 않으나, 반복 배치 또는 테스트 실행 시 IP 단위 누적을 방어하기 위해 100ms 지연 적용.

```python
# binance.py — 엔드포인트 순차 호출 시
import time

_BINANCE_CALL_INTERVAL_MS = 100  # 최소 호출 간격

def _sleep_between_calls() -> None:
    time.sleep(_BINANCE_CALL_INTERVAL_MS / 1000)
```

**HTTP 418 처리:** IP 차단 상태. `_is_retryable_status()`에서 `418`을 non-retryable로 유지 (기존 정책 준수). 418 수신 시 즉시 폴백 전환, `ERROR` 레벨 로그.

```python
# provider_runtime.py의 retryable_statuses에 418이 없음 → 재시도 없이 HttpFetchError 발생
# binance.py에서 HttpFetchError(status_code=418) catch → 폴백 진행
```

**Binance API Key 헤더 처리:**

```python
def _binance_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {}
    return {"X-MBX-APIKEY": api_key}
    # 키 값을 로그에 절대 포함시키지 않음
```

### 이상값 탐지 — 롤링 IQR

**현재 구현** (`join.py:detect_outliers_rolling_iqr()`):

```python
# 파라미터 (현재)
window = 30          # 30일 롤링 윈도우
iqr_multiplier = 3.0 # |value - median| > 3 × IQR
min_periods = 15     # 최소 15개 관측값 필요
```

**알고리즘:**
```
reference = series.shift(1)                    # 미래 오염 방지 (현재값 제외)
rolling = reference.rolling(window=30, min_periods=15)
median = rolling.median()
iqr = rolling.quantile(0.75) - rolling.quantile(0.25)
threshold = 3.0 * iqr
outlier = (|value - median| > threshold) AND value.notna() AND median.notna()
```

**이번 변경:** 파라미터 변경 없이 탐지 대상 컬럼만 확장.

```python
# join.py — merge_sources() 내부 호출
merged = detect_outliers_rolling_iqr(
    merged,
    cols=[
        "btc_return",
        "usdkrw_return",
        "funding_rate",           # ← 신규
        "open_interest_usd",      # ← 신규
        "btc_long_short_ratio",   # ← 신규
    ],
)
```

**NaN 처리:** 기존 코드의 `series.notna()` 마스크로 NaN 행 자동 제외됨. 추가 로직 불필요.

### 펀딩비 일별 집계 — sum vs mean 설계 결정

**실측 데이터 확인 (2026-04-10):**
```
2026-04-10 00:00 UTC  fundingRate= 0.000004
2026-04-10 08:00 UTC  fundingRate= 0.000025
2026-04-10 16:00 UTC  fundingRate=-0.000022
────────────────────────────────────────────
sum  = 0.000007   (일별 총 펀딩 비용 — P&L 영향)
mean = 0.000002   (8h 단위 평균 비율)
```

**기존 구현:** `futures.py:_aggregate_daily_funding()` → **`sum`** 사용.

**설계 이유 (sum 유지):** 
- `sum`은 해당일 레버리지 포지션 보유자가 실제로 납부/수취한 총 비용이다
- 시장 과열도 분석에서 "하루 동안 시장이 얼마나 한방향으로 치우쳤는가"를 측정하는 데 sum이 더 적합하다
- Granger 인과성 검정에서 `funding_rate_lag1`이 BTC 가격 변동의 선행 지표인지를 검증할 때, sum 기반 지표가 일별 체결 규모를 더 잘 반영한다
- `mean`으로 변경 시 3회 체결일(완전한 하루)과 2회 체결일(수집 시작일 첫날 등)의 값이 동등하게 정규화되어 오히려 비교 왜곡 발생

**이번 범위:** 기존 `sum` 방식 유지. 요구사항 원문 "평균 또는 특정 시점 종가"는 sum을 의도한 표현으로 해석한다.

### 결측치 처리 — Forward Fill

```
forward_fill_prices(cols=["close"], max_periods=2)
  ├─ BTC: 주말(토·일) 2일 연속 결측 → forward fill 허용
  └─ USDKRW: 공휴일 1~2일 결측 → forward fill 허용
  
  3일 이상 연속 결측: NaN 유지 (이상한 소스 중단 신호로 처리)
```

`btc_quote_volume`은 `forward_fill_prices()` 대상에 포함하지 않는다. 거래대금의 forward fill은 데이터 의미 왜곡 (거래가 없는 날의 거래대금이 이전 날과 같다는 의미가 됨). 결측 시 NaN 유지.

---

## 변경 파일 요약

| 파일 | 변경 유형 | 핵심 변경 내용 |
|------|-----------|---------------|
| `data/sources/http_client.py` | 확장 | `get_list_with_retry()` 추가 (기존 함수 미변경) |
| `sources/binance.py` | **신규** | `fetch_btc_close_binance()`: klines 수집, 폴백 체인, API Key 헤더 |
| `sources/futures.py` | 수정 | `get_list_with_retry()` 교체, Long/Short Ratio 수집 추가 |
| `join.py` | 수정 | 이상값 탐지 컬럼 확장, `_add_futures_lag_columns()`에 lag 추가 |
| `validate.py` | 수정 | `MASTER_SCHEMA`에 3개 컬럼 추가 |
| `config.py` | 수정 | `binance_api_key: str` 필드 추가 |
| `pipeline.py` | 수정 | `fetch_btc_close_binance()` 호출로 교체, `btc_source` 추출 및 전달 |
| `storage.py` | 수정 | `save_parquet(btc_source=)` 파라미터 추가, metadata 기록 |
| `statistical_tests.py` | 수정 | 다중 ADF 지원, Granger pairs에 `btc_long_short_ratio_lag1` 추가 |
| `hybrid_index.py` | 수정 | `HYBRID_FEATURE_CANDIDATES`에 `btc_long_short_ratio_lag1` 추가 |
