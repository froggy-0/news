# Granger 교차 쌍 설계

> 1·2순위 태스크(`01-pre-backfill-fixes.md`, `02-statistical-rigor-fixes.md`) 완료를 전제로 합니다.
>
> _2026-04-17 업데이트: 실코드 기반 리뷰에서 **pre-shift + Granger 내부 lag의 이중 적용(double-lag) 문제**, BH-FDR/태스크 02와의 정합성, `_empty_return_frame` 누락 컬럼, usdkrw 채널 근거 부재, PCA feature 결정, 검정력(power) 현실성, VAR 확장 대안 등을 추가했습니다._

---

## 🔴 0. 선결 쟁점: Granger에 투입하는 predictor는 **raw**여야 합니다 (double-lag 방지)

task 01은 "**look-ahead 방지를 위해 lag1로 pre-shift**"를 도입했습니다. 이는 **동시점 상관·회귀·PCA**에는 올바른 처치이지만, **Granger 검정에는 부적절**합니다. `statsmodels.grangercausalitytests(work, maxlag=k)`는 내부적으로 `predictor[t-1..t-k]`를 `target[t]`에 회귀하므로, 이미 `_lag1`로 한 칸 밀린 predictor를 넣으면 실제 검정되는 관계는 한 칸 더 밀립니다.

| 입력 predictor | Granger maxlag=1 | 실제 검정 관계 | 의도한 관계 |
|---|---|---|---|
| `news_sentiment_mean` (raw) | 내부에서 `[t-1]` 사용 | **어제 → 오늘** ✅ | 어제 → 오늘 |
| `news_sentiment_mean_lag1` | `predictor[t-1] = mean[t-2]` | **그저께 → 오늘** ❌ | 어제 → 오늘 |

결과적으로 현재 `GRANGER_PAIRS` 16쌍 × lag ∈ {1,2,3} = 48개 검정이 전부 **한 칸씩 더 먼 과거**를 보고 있습니다. 의도를 유지하려면 두 가지 중 하나:

**선택지 1 (권장) — Granger에는 raw를 투입**
- master에는 raw(`news_sentiment_mean`, `fng_value`, ...)와 `_lag1` 버전을 **둘 다** 보관.
- `GRANGER_PAIRS`의 predictor는 **raw 컬럼명**을 사용. Granger 내부 lag가 모든 시간 정렬을 처리.
- 동시점 상관 / PCA / hybrid_index / regression은 `_lag1` 컬럼을 사용 (task 01의 의도 보존).
- 해석 테이블(프론트·리포트)에 "Granger lag=k는 **k일 전 → 오늘**을 의미" 명시.

**선택지 2 — pre-shifted predictor를 Granger에 계속 사용하되 라벨을 교정**
- 결과 entry에 `effective_lag = lag + 1`을 함께 기록하고, `lag` 필드를 `grangercausalitytests_lag`으로 이름 변경.
- 가독성이 떨어지고 실수 유발이 잦으므로 권장하지 않음.

**적용 범위**: task 01에서 `GRANGER_PAIRS`를 `_lag1` 버전으로 치환한 부분을 **되돌리고 raw로 복원**. `ADF_TARGETS`, `HYBRID_FEATURE_CANDIDATES`, cross pair 설계 모두 여기에 맞춰 재정렬합니다. 이 쟁점이 해결되지 않으면 아래 §1~§4의 쌍 설계는 전부 "한 칸 어긋난" 상태로 들어갑니다.

---

## 1. 설계 원칙 (갱신)

1. **Target**: `btc_log_return` 단일 (§3 cross pair에서 일부 확장)
2. **Predictor**: 마스터 테이블의 **raw** 정상 시계열 변수. Granger 내부에서 lag 적용.
3. **교차 쌍**: predictor 간 상호 인과성도 검정하여 정보 전파 경로 파악. 단, omitted variable bias(§6) 인식.
4. **다중 검정 보정**: **BH-FDR 우선, Bonferroni는 참고용**. task 02 §4와 동일한 정책.
5. **정상성 게이트**: task 02 §1의 ADF+KPSS 합의 결과를 Granger 실행 분기와 연결.

---

## 2. Predictor 변수 목록 (raw 기준)

마스터 테이블에서 Granger predictor로 사용할 수 있는 시계열 변수 (raw 컬럼; `_lag1`은 PCA·correlation용으로만 유지):

| # | raw 컬럼 | 원본 의미 | 성격 | 정상성 기대 | 비고 |
|---|---|---|---|---|---|
| 1 | `news_sentiment_mean` | 뉴스 감성 평균 | 감성 | ✅ bounded (-1~1) | |
| 2 | `fng_value` | Fear & Greed Index | 심리 | ⚠️ bounded + 고도 persistent | task 02 §1.3의 KPSS gate 필수 |
| 3 | `funding_rate` | 선물 펀딩비 | 선물 | ✅ mean-reverting | |
| 4 | `btc_long_short_ratio` | Long/Short 비율 | 선물 | ✅ bounded ratio | |
| 5 | `oi_change_pct` | 미결제약정 일일 변화율 | 선물 | ✅ pct_change 변환 | 현재 저장 형태는 `oi_change_pct_lag1` — §7 참조 |
| 6 | `etf_net_inflow_usd` | ETF 일별 순유입 | ETF | ✅ 이미 flow 성격 | |
| 7 | `usdkrw_log_return` | 원/달러 로그 수익률 | 환율 | ✅ 수익률 | **채널 근거 필요** — §8 |
| 8 | `volume_change_pct` | BTC 거래량 변화율 | 거래량 | ✅ pct_change 변환 | 신규 컬럼 (§7) |

**제외 변수와 사유** (기존 표 유지):

| 변수 | 제외 사유 |
|---|---|
| `btc_return` | `btc_log_return`과 정보 중복 |
| `usdkrw_return` | `usdkrw_log_return`과 정보 중복 |
| `news_sentiment_std` | 분산 지표 — 우선순위 낮음 |
| `n_articles` | 양적 지표 — 감성 강도 아님 |
| `etf_total_btc` | 누적 레벨값 — 비정상, flow로 대표 |
| `etf_total_aum_usd` | 동일 사유 |
| `open_interest_usd` | 레벨값 — `oi_change_pct`로 대표 |
| `btc_quote_volume` | 레벨값 — `volume_change_pct`로 대표 |

---

## 3. Granger 쌍 설계 (raw 기준으로 재작성)

### A. predictor → `btc_log_return` (핵심, 8쌍)

```python
_TARGET = "btc_log_return"
_PREDICTORS_RAW = [
    "news_sentiment_mean",
    "fng_value",
    "funding_rate",
    "btc_long_short_ratio",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "usdkrw_log_return",
    "volume_change_pct",
]
GRANGER_PAIRS_TARGET = [(pred, _TARGET) for pred in _PREDICTORS_RAW]
```

### B. 교차 쌍 (정보 전파 경로, 선별 8쌍)

raw predictor와 raw target을 쌍으로 구성. Granger lag=k 해석은 "k일 전 predictor → 오늘 target":

```python
GRANGER_PAIRS_CROSS = [
    ("news_sentiment_mean", "fng_value"),            # 감성 → 심리
    ("fng_value", "news_sentiment_mean"),            # 심리 → 감성
    ("news_sentiment_mean", "funding_rate"),         # 감성 → 선물심리
    ("news_sentiment_mean", "etf_net_inflow_usd"),   # 감성 → ETF
    ("fng_value", "btc_long_short_ratio"),           # 심리 → 선물 포지션
    ("fng_value", "etf_net_inflow_usd"),             # 심리 → ETF
    ("usdkrw_log_return", "volume_change_pct"),      # 환율 → 거래량
    ("funding_rate", "etf_net_inflow_usd"),          # 선물 → ETF
]
```

### 🟡 dtype 주의 — target·predictor 모두 `pd.to_numeric`

`fng_value`는 `Int64`(nullable)입니다. 교차 쌍에서 target으로 올라올 수 있으므로 `_run_granger`에서 **두 컬럼 모두** 변환해야 합니다.

```python
work = df[[target, predictor]].copy()
work[target] = pd.to_numeric(work[target], errors="coerce")
work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
work = work.dropna()
```

### C. 최종 GRANGER_PAIRS

```python
GRANGER_PAIRS = GRANGER_PAIRS_TARGET + GRANGER_PAIRS_CROSS
# 8 + 8 = 16쌍 × 3 lags = 48 개별 검정
```

### D. 다중 검정 보정 (task 02와 정렬)

task 02 §4에 맞춰 BH-FDR을 1차 판정 기준, Bonferroni는 참고용 스레숄드로 기록:

```python
# pvalue list across 48 tests
from statsmodels.stats.multitest import multipletests
reject, pvalue_bh, _, _ = multipletests(pvalues, alpha=0.05, method="fdr_bh")

bonferroni_threshold = 0.05 / 48  # ≈ 0.00104
```

각 entry:

```python
{
    "predictor": ..., "target": ..., "lag": ...,
    "pvalue_raw": ...,
    "pvalue_bh": ...,
    "significant": bool(reject),  # BH 기준
    "bonferroni_threshold": 0.00104,
}
```

⚠️ **검정력 현실성 경고**: 180일 × BH-FDR × 48 검정으로 **작은 효과(F² ≈ 0.02)** 를 유의하게 잡을 확률은 낮습니다(대략 20~40% 수준). 백필을 180일로만 돌릴 경우 "유의하지 않음"이 실제 효과 부재가 아니라 검정력 부족에서 기인할 수 있음을 리포트에 명시해야 합니다. 확장 가능한 경우 360일 이상 확보 권장.

---

## 4. 정상성 게이트 (task 02 §1과 정합)

Granger에 투입되는 모든 raw 변수에 ADF+KPSS 합의 검정을 적용합니다. shift는 정상성을 바꾸지 않지만, `pct_change` 적용 여부에 따라 달라지므로 raw 형태 그대로 검정:

```python
ADF_TARGETS = [
    # target
    "btc_log_return",
    # predictor (raw)
    "news_sentiment_mean",
    "fng_value",
    "funding_rate",
    "btc_long_short_ratio",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "usdkrw_log_return",
    "volume_change_pct",
]
```

- ADF+KPSS 불일치: `label = "trend_stationary" | "difference_stationary"` 등으로 기록, **차분 재시도** 후에도 비정상이면 해당 페어 skip.
- `fng_value`는 persistent bounded 특성상 KPSS가 비정상으로 기울기 쉬움 → 차분 버전(`fng_value_diff`)을 sub-predictor로 별도 검정하는 경로를 메타에 남김.

---

## 5. PCA / hybrid_index 입력 (`_lag1`는 여기서 그대로 사용)

§0에서 정리한 대로 **PCA·correlation에는 `_lag1` 버전을 유지**합니다. Granger와 달리 hybrid_index의 목적은 "t 시점에서 가용한 정보로 t 시점의 종합 신호를 만드는" 것인데, t시점의 `news_sentiment_mean`은 같은 날 BTC 종가 움직임에 이미 영향을 받았을 수 있어 look-ahead 위험이 있습니다. 따라서 PCA 입력은 `_lag1` 버전이 적절.

`HYBRID_FEATURE_CANDIDATES`:

```python
HYBRID_FEATURE_CANDIDATES = [
    "news_sentiment_mean_lag1",
    "fng_value_lag1",
    "funding_rate_lag1",
    "btc_long_short_ratio_lag1",
    "etf_net_inflow_usd_lag1",
    # 신규 후보 — 초기엔 제외 권장, §7 참조
    # "volume_change_pct_lag1",
]
```

### 🟡 volume을 PCA에 넣을지 결정 필요

`volume_change_pct_lag1`은 `oi_change_pct_lag1`, `funding_rate_lag1`과 **선물·거래량 간 고상관**(VIF ≥ 10 예상)을 보일 가능성이 큽니다. VIF gate가 자동으로 제거할 수 있으나, 제거 순서에 따라 "무엇이 남느냐"가 달라져 PC1 방향이 불안정해질 수 있습니다.

**권장 단계**:
1. 백필 후 `volume_change_pct_lag1`을 포함·제외한 두 버전의 PCA 결과(누적 분산, loading 절댓값)를 한번씩 비교.
2. loading이 funding_rate·OI와 공선형이면 제외, 독립 정보가 보이면 포함.
3. 결정 결과를 `hybrid_index_diagnostics.pca_summary.feature_schema_version`에 기록 (task 01 §5.2 연계).

---

## 6. 🟡 Pairwise Granger의 omitted variable bias와 VAR 확장 (신규)

8개 predictor 간 상호 상관이 존재하면 pairwise Granger는 **교란변수 통제 없음**으로 spurious 신호를 내기 쉽습니다. 예: `Z → X`이고 `Z → Y`이면 pairwise Granger(X → Y)가 유의하게 나올 수 있으나 실제로는 공통 원인 Z 때문.

**단기 방어**: cross pair 결과 해석 시 "pairwise 결과는 직접 인과의 증거가 아니라 상관 구조의 지표"라고 리포트에 명시.

**중기 확장(PR-D 이후)**:
- `statsmodels.tsa.vector_ar.var_model.VAR`로 다변량 VAR(k*) 피팅 → `test_causality`로 조건부 Granger 검정을 구현. 타 변수를 통제한 "conditional Granger"가 pairwise의 omitted variable bias를 제거.
- IRF(impulse response function)로 변수 간 충격 전파 경로를 시각화.
- 12개 이상의 pairwise entry를 VAR 하나로 대체하여 해석 부담 감소.

본 태스크 범위에서는 pairwise 설계를 유지하되, 메타에 `method = "pairwise_granger"`를 기록해 후속 확장 포인트를 남김.

---

## 7. 새로 필요한 컬럼 (pipeline.py·join.py 수정)

task 01 완료 후 master에 이미 존재해야 하는 컬럼:

- `news_sentiment_mean_lag1`, `fng_value_lag1` (task 01 §1)
- `funding_rate_lag1`, `btc_long_short_ratio_lag1`, `oi_change_pct_lag1`, `etf_net_inflow_usd_lag1` (기존)

task 03에서 **추가로 생성**해야 하는 컬럼:

| 컬럼 | 원본 | 생성 방법 | 용도 |
|---|---|---|---|
| `oi_change_pct` | `open_interest_usd` | `.pct_change()` | Granger(raw) |
| `usdkrw_log_return_lag1` | `usdkrw_log_return` | `.shift(1)` | PCA / correlation |
| `volume_change_pct` | `btc_quote_volume` | `.pct_change()` | Granger(raw) |
| `volume_change_pct_lag1` | `volume_change_pct` | `.shift(1)` | PCA (§5 결정 시) |

**중요 — 기존 `oi_change_pct_lag1`과의 관계**:
현재 [join.py:85](src/morning_brief/analysis/sentiment_join/join.py#L85)는 `result["oi_change_pct_lag1"] = result["open_interest_usd"].pct_change().shift(1)`로 **raw 없이 lag1만** 생성합니다. §0에서 raw도 Granger에 필요하므로 두 컬럼을 모두 만들도록 수정:

```python
oi = pd.to_numeric(result["open_interest_usd"], errors="coerce")
result["oi_change_pct"] = oi.pct_change()
result["oi_change_pct_lag1"] = result["oi_change_pct"].shift(1)
```

`btc_quote_volume`도 동일 패턴 적용. `usdkrw_log_return`은 이미 raw가 존재하므로 lag1만 추가.

### 🔴 `_empty_return_frame` 누락 컬럼 (신규)

[pipeline.py:56-64](src/morning_brief/analysis/sentiment_join/pipeline.py#L56-L64)의 `_empty_return_frame`은 `btc_quote_volume`을 포함하지 않습니다.

```python
def _empty_return_frame(prefix: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = _date_strings(start_date, end_date)
    return pd.DataFrame({
        "date": dates,
        f"{prefix}_log_return": [np.nan] * len(dates),
        f"{prefix}_return": [np.nan] * len(dates),
    })
```

BTC 수집이 모두 실패해 fallback 프레임으로 대체되면 `btc_quote_volume`이 아예 없으므로 `volume_change_pct` 계산 단계에서 KeyError가 발생합니다.

**수정**: prefix가 "btc"인 경우에만 `btc_quote_volume=NaN` 컬럼을 추가하거나, merge_sources에서 `btc_quote_volume`이 없으면 NaN으로 채우는 방어 로직을 추가. 후자가 더 안전.

```python
if "btc_quote_volume" not in merged.columns:
    merged["btc_quote_volume"] = float("nan")
```

### 이상치 감지 대상 확장

`detect_outliers_rolling_iqr` 호출 시 `cols`에 `news_sentiment_mean`, `fng_value`, `etf_net_inflow_usd`, `btc_quote_volume`을 추가. **주의** — task 02 §8에서 합의된 이상치 처리 방식(값만 NaN 마스킹 vs 행 삭제)에 맞춰 구현해야 함. 행 삭제 방식이면 Granger의 time-index gap 문제가 다시 살아남.

---

## 8. 🟡 `usdkrw_log_return` predictor 근거 문서화

원/달러 환율이 BTC 수익률을 선행한다는 **이론 채널**이 명확하지 않으면 검정 부담만 늘립니다. 최소한 다음 중 하나를 문서화:

- **국내 투자자 차익거래 채널**: 업비트·빗썸 프리미엄과 연결된 KIMP가 USD-KRW 변동에 반응 → 국내 유동성이 BTC에 일부 전가.
- **글로벌 리스크온/오프 프록시**: USD 강세는 리스크자산 매도 연쇄로 BTC에 부정적.

이론 채널이 약하다고 판단되면 exploratory 섹션으로 분리해 `GRANGER_PAIRS_EXPLORATORY`로 옮기고 BH-FDR family를 분리 계산. core family의 검정력 손실을 줄일 수 있습니다.

---

## 9. 🟢 Regime 안정성 점검 (선택)

180~365일 구간은 BTC 사이클 전환(예: ETF 승인 전/후, 반감기 전/후)을 포함할 수 있습니다. Granger 파라미터가 구간 전반에 걸쳐 안정적이지 않으면 전체 기간 검정 결과가 두 체제의 평균일 뿐입니다.

**경량 체크**:
- `statsmodels.tsa.stattools` 직접 제공은 없으므로, 180일을 전/후 절반으로 나눠 Granger 재실행 → p-value 차이가 크면 "regime_unstable" 플래그.
- 또는 `ruptures` 라이브러리로 breakpoint 탐지.

작업 비용 대비 효과가 애매하므로 PR-D 이후 별도 이슈로 분리.

---

## 10. 수정 대상 파일 요약 (갱신)

| 파일 | 변경 |
|---|---|
| `join.py` | (a) raw predictor 컬럼 동시 생성(`oi_change_pct`, `volume_change_pct`). (b) `usdkrw_log_return_lag1`, `volume_change_pct_lag1` 추가 (PCA용). (c) `btc_quote_volume` 누락 시 NaN 방어. (d) `detect_outliers_rolling_iqr` 대상에 감성·F&G·ETF flow·volume 추가 (task 02 §8의 마스킹 방식으로) |
| `pipeline.py` | `_empty_return_frame`에서 prefix=="btc"일 때 `btc_quote_volume=NaN` 추가, 또는 merge_sources 단계에 방어 |
| `statistical_tests.py` | (a) `GRANGER_PAIRS`를 **raw predictor 기반**으로 재작성(§0). (b) `ADF_TARGETS` 9개 raw 변수로 갱신. (c) `_run_granger`에서 target·predictor 모두 `pd.to_numeric` 적용. (d) task 02 §4 BH-FDR 후처리와 task 02 §9 잔차 진단 호출 순서 정리 |
| `hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES`는 `_lag1` 버전 유지. `volume_change_pct_lag1` 포함 여부는 §5 실측 후 결정 |
| `validate.py` | `MASTER_SCHEMA`에 raw 컬럼(`oi_change_pct`, `volume_change_pct`) + `usdkrw_log_return_lag1` + `volume_change_pct_lag1` 추가 (nullable=True). task 01 §5.1 마이그레이션 전략 준수 |
| `etf_storage.py` | `build_stats_metadata_payload`에 `n_granger_tests=48`, `bonferroni_threshold=0.00104`, `correction_method="fdr_bh"`, `method="pairwise_granger"` 추가 |
| `tests/analysis/test_sentiment_join/test_join.py` | 새 컬럼 존재·NaN 방어·이상치 마스킹 검증 |
| `tests/analysis/test_sentiment_join/test_statistical_tests.py` | (a) `GRANGER_PAIRS` 16쌍 & raw 기반 검증. (b) `fng_value` target dtype 회귀 테스트. (c) BH-FDR 보정 결과 스키마 테스트. (d) double-lag 회귀: raw predictor와 `_lag1` predictor의 p-value가 서로 다름을 확인 |
| `tests/analysis/test_sentiment_join/test_validate.py` | 스키마 신규 컬럼 |
| `tests/analysis/test_sentiment_join/test_hybrid_index.py` | `HYBRID_FEATURE_CANDIDATES` 변화 반영 |

---

## 11. 체크리스트 (백필 전)

> _2026-04-17 task-03 구현 완료_

- [x] §0: `GRANGER_PAIRS`를 raw 기반으로 복원 (task 01의 pre-shift는 PCA 전용으로만 유지)
- [x] §3.D: BH-FDR을 1차 판정 기준으로 삼고 Bonferroni 임계값은 참고 기록
- [x] §4: ADF+KPSS 합의 gate가 실제 Granger 실행 분기와 연결됨
- [x] §5: `volume_change_pct_lag1` PCA 포함 여부 후처리 결정 프로세스 문서화 (VIF gate 자동 처리, `HYBRID_FEATURE_SCHEMA_VERSION=v3`)
- [x] §7: `oi_change_pct`, `volume_change_pct` raw 컬럼 추가 & `btc_quote_volume` 누락 방어
- [x] §7: 이상치 처리는 task 02 §8 마스킹 방식과 일치
- [x] §8: `usdkrw_log_return` 채널 근거 주석 추가 (KIMP + 글로벌 리스크 채널) — CORE 유지
- [x] master 스키마 마이그레이션 (task 01 §5.1) & hybrid feature schema 버전 기록 (v3)
- [x] 검정력 경고를 리포트 메타(`power_warning`)에 포함 (§3.D ⚠️)
- [x] regime 안정성 추적을 PR-E 이슈로 분리 기록 (§9) — `tasks.md` 미포함 항목에 명시

---

## 12. 수정 우선순위 (3순위 내, task 01·02 완료 전제)

| 순위 | 항목 | 영향도 | 난이도 |
|---|---|---|---|
| **3-1** | §0 Granger predictor를 raw로 복원 (double-lag 제거) | 🔴 16×3=48 검정 전체가 의도와 어긋남 | 저 (컬럼 참조만 교체) |
| **3-2** | §7 raw 변환 컬럼 추가 + `btc_quote_volume` 누락 방어 + fallback frame | 🔴 파이프라인 KeyError / raw 부재 | 저~중 |
| **3-3** | §3.A/B/C/D raw 기반 cross pair 재구성 & BH-FDR 정렬 | 🟡 task 02와 일관성 | 저 |
| **3-4** | §8 `usdkrw_log_return` 채널 근거 문서화 또는 family 분리 | 🟡 불필요한 다중검정 부담 | 저 |
| **3-5** | §5 volume PCA feature 결정 프로세스 | 🟡 PC1 안정성 | 저 |
| **3-6** | §6 VAR/IRF 확장 경로 메모 | 🟢 중기 로드맵 | 중 |
| **3-7** | §9 regime 안정성 별도 이슈 분리 | 🟢 해석 신뢰도 | 중 |

**3-1과 3-2는 반드시 한 PR에 묶어 처리**해야 raw/lag1 컬럼이 양쪽 모두 master에 존재하고 Granger·PCA가 각자 올바른 버전을 참조합니다. 3-3은 3-1 적용 후 자동으로 따라오는 정리 작업입니다.
