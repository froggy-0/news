# Sentiment-Join 파이프라인 — 선행 개선 사항

> 백필 데이터 생성 전에 반드시 해결해야 하는 항목입니다.
> 이 상태로 180일치를 백필하면 Granger 검정 결과가 오염됩니다.
>
> _2026-04-17 업데이트: data-engineer / data-scientist 관점의 추가 이슈(다중검정 보정, 정상성 gate, UTC 경계 의미론, 스키마 마이그레이션, 재현성)를 §4~§5로 확장했습니다._

---

## 1. `news_sentiment_mean`, `fng_value`에 Lag-1 미적용

### 현상

`_add_futures_lag_columns` ([src/morning_brief/analysis/sentiment_join/join.py:77-96](src/morning_brief/analysis/sentiment_join/join.py#L77-L96))에서 선물/ETF 지표에만 `.shift(1)`을 적용합니다.
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

"어제의 감성/공포지수가 오늘의 BTC 수익률을 예측하는가"를 검정하려면, predictor가 target보다 시간적으로 앞서야 합니다. 현재는 같은 날짜 데이터끼리 비교하므로 **look-ahead bias** 가능성이 큽니다.

### 시간 의미론(timezone/경계) 재확인 필요

Lag-1 적용만으로는 부족합니다. 다음 두 가지가 함께 명세되어야 합니다.

1. **`analytics/btc/{date}.json`의 `date`가 어떤 경계인지** — 수집 스케줄러는 KST 08:00에 돌지만, 집계 대상 기사의 컷오프는 어디인지? 백필(`scripts/backfill/sources/coindesk.py:42-44`)은 **UTC 자정** 기준으로 `date`를 부여합니다. 운영 파이프라인도 동일하게 UTC 자정 컷오프를 사용하는지 확인해야 두 소스 간 시계열 정의가 일치합니다. 불일치 시 백필/실시간 교차 구간에서 하루짜리 shift가 생깁니다.
2. **Alternative.me F&G Index는 UTC 자정 기준 일일 스냅샷** — `fng_value`가 해당 날짜 BTC 종가 이전 정보만 반영하는지 API 명세로 확인해야 합니다. 같은 날 0~24 UTC 구간을 이미 일부 반영한다면 lag1 처리조차 부분적으로만 선행을 보장합니다.
3. **BTC 종가는 UTC 자정 기준** ([btc_prices.py:29-30](src/morning_brief/analysis/sentiment_join/sources/btc_prices.py#L29-L30)) — 위 두 변수가 UTC 컷오프에 맞춰져 있다면 lag1 적용으로 선행 관계가 성립합니다.

결론: 시간 경계를 코드 주석/스펙으로 명시하고, 그 위에서 lag1 규칙을 적용해야 합니다.

### 수정 방안

`join.py`에 별도 헬퍼를 추가해 두 변수에도 shift를 적용하고, predictor명을 lag1 버전으로 변경합니다.

수정 대상 파일:

| 파일 | 변경 |
|---|---|
| `src/morning_brief/analysis/sentiment_join/join.py` | `news_sentiment_mean_lag1`, `fng_value_lag1` 컬럼 생성 (별도 `_add_sentiment_lag_columns` 헬퍼 권장) |
| `src/morning_brief/analysis/sentiment_join/statistical_tests.py` | `GRANGER_PAIRS`에서 predictor명 변경 |
| `src/morning_brief/analysis/sentiment_join/hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES`에서 `news_sentiment_mean` → `news_sentiment_mean_lag1`, `fng_value` → `fng_value_lag1` |
| `src/morning_brief/analysis/sentiment_join/validate.py` | `MASTER_SCHEMA`에 새 컬럼 추가 (§5의 마이그레이션 전략과 함께) |
| `tests/analysis/test_sentiment_join/test_join.py` | lag1 컬럼 존재 및 T-1 값 검증(첫 행 NaN, 둘째 행 = 이전 원본) |
| `tests/analysis/test_sentiment_join/test_statistical_tests.py` | GRANGER_PAIRS 업데이트에 따른 fixture 수정 |
| `tests/analysis/test_sentiment_join/test_hybrid_index.py` | feature 이름 변경 반영 |
| `tests/analysis/test_sentiment_join/test_validate.py` | 스키마 신규 컬럼 검증 |

**네이밍 일관성**: `funding_rate_lag1`, `btc_long_short_ratio_lag1`, `news_sentiment_mean_lag1`은 순수 `.shift(1)`이고 `oi_change_pct_lag1`, `etf_net_inflow_usd_lag1`만 변환 후 shift입니다. 혼동을 막으려면 docstring에 "lag1 = T-1 시점 값" 정의를 명시합니다.

---

## 2. 백필 `why_it_matters` 빈 문자열 고정

### 현상

백필 스코어러 ([scripts/backfill/scorer.py:99](scripts/backfill/scorer.py#L99)):

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

백필 데이터의 FinBERT 입력 텍스트가 실제 파이프라인과 달라집니다. 동일한 기사라도 `why_it_matters` 유무에 따라 감성 점수가 달라질 수 있으며, 이는 시계열의 일관성(structural break)을 깨뜨립니다. 백필과 실시간의 경계 일자에 분포가 점프하면 이후의 Granger/PCA 해석이 잘못된 단서를 포착하게 됩니다.

### 원인

백필 소스(CoinDesk, Alpaca)의 `RawArticle` 구조에 `why_it_matters` 필드가 없습니다 ([scripts/backfill/sources/coindesk.py:26-41](scripts/backfill/sources/coindesk.py#L26-L41)).

### 수정 방안

세 가지 선택지:

**A. 백필/실시간 모두 `why_it_matters` 없는 단일 빌더 사용** — 가장 단순. 실시간 파이프라인은 이미 `enrich_news_packet(..., text_builder=...)`로 빌더 주입을 지원하므로([finbert_sentiment.py:291](src/morning_brief/data/finbert_sentiment.py#L291)), `build_news_sentiment_text_minimal(title, summary)`를 추가하고 양쪽에 동일하게 적용. 단, 과거 실시간 점수가 바뀌므로 일회성 재집계 또는 dual-write 기간이 필요.

**B. 백필 데이터는 빈 `why_it_matters`로 진행하되 메타데이터로 표식** — 현재 가정. 대신 R2 payload 스키마와 parquet 모두에 `sentiment_text_schema ∈ {"title_summary", "title_summary_whyitmatters"}`를 기록해 downstream 분석에서 필터/덤미화 가능.

**C. 실시간 점수 재계산 없이 구간 덤미(dummy) 추가** — `is_backfill=True`를 기존 `is_backfill_valid` 외 별도 컬럼으로 노출하고, 회귀/그레인저 단계에서 회귀식에 regime dummy를 포함. 통계 모델 쪽에서 처리하는 방식.

### 권장 순서

1. **영향도 먼저 측정**: 실시간 파이프라인의 최근 30~60일 기사 샘플에 대해, 같은 기사에 `why_it_matters` 포함/미포함 두 번 스코어링 → `|Δscore|`의 p50/p95, 일별 mean 차이의 표준편차, Pearson corr 산출. `scripts/analysis/measure_text_schema_drift.py` 식의 일회성 배치로 정량화. 배치는 tests/fixtures 복사로도 구현 가능.
2. **|Δmean_daily| p95 < 0.03** 수준이면 **B안** (메타데이터만)으로 충분. 그 이상이면 **A안** 전환 + 재집계.
3. 어느 경우든 parquet과 R2 payload 양쪽에 `text_schema_version` 필드를 추가해 미래 변경도 추적 가능하게 합니다.

### 구현 팁

- `enrich_news_packet`의 `text_builder` 인자는 이미 존재하므로, 백필 쪽에 맞춘 `build_news_sentiment_text_minimal`을 양쪽에서 공유하면 이중 구현을 피할 수 있음.
- 단일 빌더 체계에서 `why_it_matters`만 누락된 dict를 넘기면 현행 `combine_fields`가 자연스럽게 빈 파트로 처리해 동작 — 경로 A를 낮은 리스크로 시도 가능.

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

### 문제와 영향 범위 재평가

`batch_size` 차이 자체는 dynamic padding(배치 내 max length padding)과 attention mask의 영향으로 softmax 출력에 극소 오차(일반적으로 ≤ 1e-4)를 만들 뿐입니다. 하지만 엄밀한 재현성을 노린다면 **batch_size 통일은 필요조건일 뿐 충분조건이 아닙니다**. 아래 요소가 함께 고정되어야 동일 입력 → 동일 출력이 보장됩니다.

| 요소 | 현재 상태 | 제안 |
|---|---|---|
| `finbert_batch_size` | 32 vs 16 | 16으로 통일 |
| `torch.manual_seed` | 미고정 | `FinBertScorer` 생성 시점에 고정 |
| `torch.use_deterministic_algorithms(True)` | 미설정 | 배치 추론 경로에서 설정 |
| `cudnn.deterministic` / `cudnn.benchmark` | 미설정 | CPU 추론이면 무관. GPU 실행 시 고정 필요 |
| `TOKENIZERS_PARALLELISM` | 미지정 | `false`로 고정 (토크나이저 스레드 경쟁 제거) |
| `PYTHONHASHSEED` | 미지정 | CI/백필 스크립트에서 고정 |
| 정렬 순서 | 백필은 `sorted(dates)` → 기사 순서가 안정 | 실시간은 `_select_items_for_scoring` 우선순위 할당 — 배치 구성은 시점 의존적 |

### 수정 방안

1. **최소 변경**: `_BackfillFinBertSettings.finbert_batch_size = 16`으로 통일.
2. **더 나은 접근**: `_BackfillFinBertSettings` duck-type을 제거하고 운영 파이프라인의 `Settings`를 직접 생성해 사용. `FINBERT_BATCH_SIZE` 환경변수 하나로 양쪽을 묶음. 현재 duck-type은 기본값 드리프트 위험의 원천입니다.
3. **회귀 방지 테스트**: 동일 fixture 20~50건에 대해 `batch_size ∈ {1, 4, 16, 32}`에서 `max |Δscore| < 1e-4`를 검증하는 단위 테스트를 `tests/test_finbert_sentiment.py`에 추가.

---

## 4. Granger 검정 전제 조건 및 다중검정 보정 (신규)

§1의 lag 정리만으로는 Granger 해석이 안전해지지 않습니다. 다음 3건을 함께 반영해야 결과를 신뢰할 수 있습니다.

### 4.1 정상성(stationarity) gate

`statistical_tests.py`는 ADF 검정을 실행하지만, 그 결과를 Granger 실행 여부와 **연결하지 않습니다**. 비정상 시계열에 Granger를 적용하면 spurious causality가 흔합니다.

**수정 방안**:
- `_run_granger` 진입 전에 `predictor`·`target` 모두 ADF p < 0.05인지 확인하는 gate 추가.
- 비정상일 경우 첫 차분(`.diff().dropna()`)을 적용한 뒤 재검정, 그래도 비정상이면 해당 페어를 skip하고 구조화 로그 기록.
- 또는 ADF 비정상 시 lag1이 아닌 **log-diff** 버전을 별도 컬럼으로 만들어 페어링.

### 4.2 다중검정 보정

현재 `GRANGER_PAIRS`(5개) × `GRANGER_LAGS`(3개) = **15회 검정**을 α=0.05로 판정하므로, 귀무가설이 모두 참이어도 최소 한 개 이상이 유의하게 나올 family-wise error rate는 약 `1 - 0.95^15 ≈ 0.54`입니다.

**수정 방안**:
- Benjamini–Hochberg(FDR) 또는 Bonferroni 보정 적용.
- `run_statistical_tests` 반환 dict에 `pvalue_raw`와 `pvalue_adjusted` 두 필드를 모두 남겨 downstream이 양쪽을 볼 수 있게 함.
- `significant` 플래그는 조정 후 기준으로만 True로 설정.

### 4.3 Reverse-causality 점검

현재 페어는 단방향(`predictor → btc_log_return`)뿐입니다. 데이터 과학 관점에서는 역방향(`btc_log_return → news_sentiment_mean_lag1` 등)도 함께 돌려야, 감성이 가격을 선행한 것인지 아니면 가격에 **반응**한 것인지 분리할 수 있습니다.

**수정 방안**:
- `GRANGER_PAIRS`에 symmetric 버전을 추가하거나 `GRANGER_PAIRS_REVERSE` 리스트를 별도로 두고 결과 JSON에 양방향 p-value를 저장.
- 보고서/프론트엔드 노출 시 "양방향 모두 유의"인 경우는 단순 선행으로 해석하지 않도록 표기.

### 4.4 (선택) 공적분 검정

`funding_rate`, `btc_long_short_ratio`, `open_interest_usd`, `etf_total_aum_usd`는 레벨 시계열로 non-stationary일 가능성이 있습니다. lag1 + diff로 정상화해도, 원본 간 장기 균형관계가 있다면 공적분(Engle–Granger, Johansen) 검정이 더 적합한 프레임입니다. 백필 완료 후 정책으로 논의.

---

## 5. 스키마 마이그레이션 · 재현성 (신규)

### 5.1 `MASTER_SCHEMA` strict 모드와의 충돌

`validate.py:46`의 `strict=True`는 스키마에 정의되지 않은 컬럼도 거부합니다. §1에서 `news_sentiment_mean_lag1`, `fng_value_lag1`을 추가하고 §2에서 `sentiment_text_schema` 같은 메타 컬럼을 더하면, **기존에 저장된 parquet(`data/sentiment_join/master_{YYYYMMDD}.parquet`)을 그대로 재검증하려 할 때 실패**합니다.

**수정 방안 중 하나 선택**:

| 방식 | 장점 | 단점 |
|---|---|---|
| (a) 기존 parquet 전량 폐기 후 재생성 | 단순·일관 | 비용 — 하지만 백필 직전이면 부담 작음 |
| (b) `storage.py` load 경로에서 누락 컬럼 NaN 채움 후 재검증 | 과거 데이터 보존 | 분기 코드 유지 부담 |
| (c) 버전 디렉터리 분리 (`master/v2/...`) | 정책적 명확함 | consumer 경로 업데이트 필요 |

백필을 곧 다시 돌릴 예정이므로 **(a) 재생성이 가장 깔끔합니다**. 단 파일 경로가 존재하지 않을 때도 파이프라인이 단절되지 않도록 `storage.py`의 upsert 로직을 확인해야 합니다.

### 5.2 Hybrid Index 연속성

`HYBRID_FEATURE_CANDIDATES`가 바뀌면 PCA loading과 PC1 방향이 재학습되어 이전 `hybrid_index`와 단위·부호 모두 불연속이 됩니다.

**수정 방안**:
- `hybrid_index_diagnostics.pca_summary`에 `feature_schema_version`을 기록 (이미 `loadings`는 있으나 버전 식별자는 없음).
- 부호 정렬(sign-flip) 규칙 추가: 예를 들어 `fng_value_lag1`의 loading이 양수가 되도록 강제해 일별 부호 반전을 방지.
- 리릴리즈 시점을 별도 로그 이벤트(`stats.pca_schema_changed`)로 남겨 downstream이 discontinuity 지점을 인지.

### 5.3 FinBERT 결정성 고정

§3의 연장선에서, 백필과 실시간 모두 동일한 결과를 얻으려면 다음을 CI와 백필 스크립트에서 고정:

```text
PYTHONHASHSEED=0
TOKENIZERS_PARALLELISM=false
TORCH_DETERMINISTIC=1
FINBERT_BATCH_SIZE=16
```

`FinBertScorer` 초기화 시 `torch.manual_seed(0)`, `torch.use_deterministic_algorithms(True)`를 호출하고, 실패 시(일부 CUDA 커널에서는 deterministic 모드 미지원) warning 로그 후 경고를 내면 됩니다.

---

## 수정 우선순위

| 순위 | 항목 | 영향도 | 난이도 | 블로커 |
|---|---|---|---|---|
| **1** | Lag-1 미적용 (§1) | 🔴 Granger 결과 오염 (look-ahead) | 중 (5개 파일 + 4개 테스트) | 백필 전 필수 |
| **2** | Granger 전제(정상성 gate + 다중검정 보정) (§4.1, §4.2) | 🔴 spurious 인과 / FWER 팽창 | 중 | 백필 후라도 필수 |
| **3** | 스키마 마이그레이션 (§5.1) | 🟠 기존 parquet 로드 실패 | 저 | §1과 묶어 처리 |
| **4** | `why_it_matters` 불일치 (§2) | 🟡 시계열 structural break | 저 (영향도 측정 우선) | 측정 후 판단 |
| **5** | 시간 경계 명세 (§1의 의미론 절) | 🟡 운영/백필 하루 shift 위험 | 저 | 백필 전 확인 |
| **6** | Reverse-causality 점검 (§4.3) | 🟢 해석 보조 | 저 | 리포팅 품질 향상 |
| **7** | Hybrid index 연속성 (§5.2) | 🟢 discontinuity 표식 | 저 | §1 반영 시 |
| **8** | `batch_size` 불일치 + 결정성 (§3, §5.3) | 🟢 미세 수치 / 재현성 | 저 | 회귀 테스트와 함께 |

**필수 블로커(1, 2, 3, 5)는 백필 실행 전에 해결**해야 합니다. 나머지는 백필과 병행 또는 직후 처리 가능하지만, §1과 §5.1은 논리적으로 한 PR에서 묶는 것이 스키마 깨짐을 피하는 데 유리합니다.
