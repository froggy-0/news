# Sentiment Join 파이프라인 진단 리뷰
> 작성일: 2026-04-27  
> 관점: `data-scientist` + `senior-data-engineer`  
> 대상 산출물: `master_20260427.parquet`  
> 참고 문서: `docs/analysis/sentiment-join/sentiment_join_pipeline_changes.md`, `docs/analysis/sentiment-join/parquet-status-report-20260424.md`

## 1. 결론 요약

현재 파이프라인은 **데이터 수집/결합 파이프라인으로는 꽤 안정화**되어 있습니다. 실제 산출물 기준으로 날짜 중복은 없고, `BTC ETF`와 `futures` coverage도 사실상 정상 수준입니다. `full/core hybrid index`도 생성되고 있으며 메타데이터까지 parquet 안에 일관되게 저장됩니다.

반면 **알파 검증 관점에서는 아직 운영 승격 단계가 아닙니다**. 단순 상관, hit rate, backtest, walk-forward를 종합하면 주요 predictor 대부분이 랜덤에 가깝고, hybrid index 역시 “국면 설명력”은 보여도 “수익 예측력”은 아직 약합니다. 특히 `7D` 기준에서 hit rate가 일부 개선되어 보여도 실제 누적수익은 여전히 음수여서, 현재 상태를 “좋은 regime dashboard”에 더 가깝고 “실전 alpha engine”으로 보기는 어렵습니다.

또 하나 중요한 점은 **문서와 실제 산출물 계약(contract) 사이에 일부 불일치가 남아 있다**는 것입니다. 변경 요약 문서에는 `decision_strict`, baseline separation, FDR 기반 승격 게이트가 산출물 셀에 포함되는 것처럼 적혀 있지만, 실제 `master_20260427.parquet` 메타데이터의 `horizon_metrics`에는 그 필드가 아직 들어가지 않습니다. 이건 연구 품질 문제이면서 동시에 운영/데이터 계약 문제입니다.

---

## 2. 분석 대상과 확인 방법

이번 리뷰는 아래 두 축으로 봤습니다.

1. **데이터 과학 관점**
   - 피처 분포
   - 결측/이상치
   - 정상성
   - predictor 간 다중공선성
   - target 대비 상관
   - baseline 대비 hit rate / backtest / walk-forward

2. **데이터 엔지니어링 관점**
   - 소스 커버리지
   - 산출물 메타데이터 구조
   - 평가 결과의 재현성/추적성
   - 코드와 문서의 계약 일치 여부
   - 향후 운영 자동화 포인트

코드상 주요 연결 지점:

- Alpha validation 실행 및 parquet 메타데이터 주입: `src/morning_brief/analysis/sentiment_join/pipeline.py:598`
- horizon별 metric 계산: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1583`
- walk-forward 기본 horizon 설정: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1187`
- parquet 메타데이터 payload 직렬화: `src/morning_brief/data/etf_storage.py:266`

---

## 3. 현재 산출물 상태

## 3.1 데이터 볼륨과 스키마

`master_20260427.parquet` 기준:

- 기간: `2025-04-27 ~ 2026-04-27`
- 행 수: `365`
- 컬럼 수: `68`
- `date` 중복: `0`

4월 24일 리포트의 `358행 / 50컬럼` 대비 데이터 길이와 피처 폭이 모두 늘었습니다. 즉, 파이프라인은 단순 유지가 아니라 실제로 **실험용 feature space를 확장**한 상태입니다.

## 3.2 소스 커버리지

메타데이터 기준:

- `btc_etf.coverage.ratio = 0.9973`
- `futures funding/oi/lsr coverage = 1.0`
- `futures mode = lambda`
- `btc_etf mode = gold_history`

이건 운영 관점에서 좋은 신호입니다. 적어도 이번 산출물은 “특정 소스가 비어 있는데 downstream이 조용히 돌아간 케이스”가 아닙니다.

## 3.3 결측치

주요 결측:

- `ingest_validation_reason`: 365행 전부 null
  - 정상 해석 가능. 실패 이유가 없다는 뜻에 가깝습니다.
- `usdkrw_log_return`, `usdkrw_return`, `usdkrw_log_return_lag1`: 12~13행
  - 외환 시장 휴장/forward fill 경계 영향
- `btc_fwd_ret_7d`: 7행
  - horizon target 특성상 자연 결측
- `full/core_hybrid_index*`: 2~5행
  - warm-up / lag / PCA 입력 결측 영향

치명적인 결측 패턴은 보이지 않습니다. 현재 문제는 “결측 때문에 분석이 불가능”한 상태가 아니라 “데이터는 충분한데 predictive edge가 약한 상태”에 더 가깝습니다.

## 3.4 이상치

여기서는 숫자 해석을 두 층으로 나눠야 합니다.

- row-level `is_outlier=True`: `46 / 365 = 12.6%`
- 메타데이터 `outlier_filtered_count = 83`, `outlier_filtered_ratio = 0.2274`

즉, 현재 정책은 “행 전체 제거”가 아니라 **셀 단위 마스킹(column policy)** 이므로, `is_outlier` 행 비율과 실제 분석용 마스킹 셀 수는 다릅니다. 이 구분은 문서와 대시보드에서 계속 분리해 보여주는 게 맞습니다.

월별 row outlier 비율은 아래 구간에서 높았습니다.

- `2026-01`: 32.3%
- `2026-02`: 32.1%
- `2026-03`: 22.6%
- `2026-04`: 15.4%

즉, 최근 급변동 구간에 이상치가 몰린 패턴은 여전히 유지됩니다.

---

## 4. 데이터 과학 관점 평가

## 4.1 최근 30일 국면 해석은 일관적이다

전체 평균 대비 최근 30일 평균:

| 지표 | 전체 | 최근 30일 | 해석 |
|---|---:|---:|---|
| `news_sentiment_mean` | `0.0173` | `-0.0282` | 감성 약화 |
| `fng_value` | `39.82` | `20.13` | 극단적 공포 구간 |
| `btc_return` | `-0.0003` | `0.0050` | 단기 반등 |
| `funding_rate` | `0.0001` | `-0.0001` | 과열 완화 |
| `vix` | `18.48` | `21.55` | 변동성 확대 |
| `full_hybrid_index_score` | `50.16` | `37.87` | risk-off 쪽 |
| `core_hybrid_index_score` | `53.26` | `32.47` | risk-off 쪽 |

이건 파이프라인이 **시장 상태를 설명하는 regime sensor**로서는 꽤 자연스럽게 동작하고 있다는 뜻입니다.

## 4.2 하지만 단순 예측력은 여전히 약하다

`lag1 predictor -> btc_return` 피어슨 상관:

- `news_sentiment_mean_lag1`: `r=-0.0158`, `p=0.7643`
- `fng_value_lag1`: `r=-0.0089`, `p=0.8659`
- `funding_rate_lag1`: `r=-0.0407`, `p=0.4393`
- `oi_change_pct_lag1`: `r=-0.0618`, `p=0.2404`
- `btc_long_short_ratio_lag1`: `r=-0.0559`, `p=0.2871`
- `etf_net_inflow_usd_lag1`: `r=-0.0512`, `p=0.3310`
- `vix_lag1`: `r=0.0638`, `p=0.2258`
- `full_hybrid_index_score_lag1`: `r=-0.0223`, `p=0.6731`
- `core_hybrid_index_score_lag1`: `r=-0.0434`, `p=0.4101`

핵심은 간단합니다.

- 절대 상관이 대부분 `0.07` 이하
- p-value 전부 비유의

즉, **선형 단기 예측 신호로는 아직 설득력이 약합니다.**

## 4.3 정상성은 개선 대상이 분명하다

ADF 기준:

- 비정상(non-stationary)
  - `news_sentiment_mean`
  - `fng_value`
  - `full_hybrid_index_score`
  - `core_hybrid_index_score`
- 정상(stationary)
  - `funding_rate`
  - `oi_change_pct`
  - `btc_long_short_ratio`
  - `etf_net_inflow_usd`
  - `vix`
  - `sentiment_momentum`
  - `sentiment_accel`

이 결과는 매우 중요합니다. 지금 파이프라인은 **레벨(level) 피처와 변화율(change) 피처를 함께 쓰고 있는데**, 실제로 stationary한 쪽은 `momentum/accel/change` 계열이고, 비정상인 쪽은 `raw sentiment / raw F&G / hybrid score` 계열입니다.

즉, 다음 단계는 자연스럽게:

- raw level 기반 threshold 전략 비중 축소
- stationary transform 기반 실험 확대

로 가는 게 맞습니다.

## 4.4 predictor 간 중복 정보가 크다

상관이 높은 조합:

- `news_sentiment_mean_lag1` ↔ `sentiment_momentum_lag1`: `0.976`
- `full_hybrid_index_score_lag1` ↔ `core_hybrid_index_score_lag1`: `0.944`
- `btc_bear_regime_lag1` ↔ `core_hybrid_index_score_lag1`: `-0.770`
- `news_sentiment_mean_lag1` ↔ `sentiment_accel_lag1`: `0.759`

이건 두 가지를 뜻합니다.

1. feature 확장은 되었지만 실제 정보 다양성은 기대보다 작다
2. full/core index를 둘 다 계속 돌려도 독립 실험 수가 생각보다 적다

데이터 과학적으로는 **feature count가 아니라 effective independent signals 수를 관리**해야 하는 단계입니다.

## 4.5 7일 horizon hit rate는 일부 개선되지만, 통계적 설득력은 약하다

`horizon_metrics["7"]["hit_rates"]` 기준 상위권:

- `full_hybrid_index_score_lag1`: `53.8%`, CI `44.8% ~ 63.2%`, `fdr_q=0.999`
- `core_hybrid_index_score_lag1`: `53.2%`, CI `44.2% ~ 62.5%`, `fdr_q=0.999`
- `btc_bear_regime_lag1`: `53.2%`, CI `43.7% ~ 63.3%`, `fdr_q=0.999`

문제는:

- CI 폭이 넓고
- baseline 대비 p-value가 높고
- BH-FDR 후 `q=0.999`

즉, “53%대 hit rate”만 보면 좋아 보일 수 있지만 **다중검정과 불확실성을 반영하면 실질적 우위라고 보기 어렵습니다.**

## 4.6 baseline을 못 이긴다

`baseline_metrics["7"]` 기준:

- `always_up`: hit rate `51.4%`
- `btc_momo_20d`: `47.3%`
- `fng_contrarian`: `50.7%`
- `vol_regime`: `58.0%`, Sharpe `4.10`

가장 중요한 기준은 `vol_regime`입니다. 현재 signal 후보들 대부분이 이 baseline을 안정적으로 넘지 못합니다.  
즉, 지금의 질문은 “53%가 넘는가?”가 아니라 **“vol_regime보다 유의하게 좋은가?”** 여야 합니다.

## 4.7 backtest는 더 냉정하다

대표 backtest:

- `full_hybrid_index_score_lag1`
  - alpha `+0.0053`
  - cumulative return `-24.35%`
  - Sharpe `-1.01`
- `core_hybrid_index_score_lag1`
  - alpha `+0.0242`
  - cumulative return `-18.19%`
  - Sharpe `-0.74`
- `btc_bear_regime_lag1`
  - alpha `+0.2665`
  - cumulative return `+6.59%`
  - Sharpe `+0.28`
  - 단, `n_trades=7`
- `fng_change_5d_lag1`
  - alpha `+0.2488`
  - cumulative return `+1.52%`
  - Sharpe `+0.06`

여기서 보이는 패턴:

- hybrid score는 설명력은 있어도 수익화가 약함
- 일부 interaction / regime형 신호가 상대적으로 낫지만 거래 수가 적고 CI가 넓음

즉, **research 방향은 raw sentiment보다 regime-conditioned sparse signal 쪽이 더 유망**합니다.

## 4.8 walk-forward 결과는 “맞추는 것”과 “버는 것”이 다르다는 걸 보여준다

top-level `walk_forward`는 기본값이 `btc_log_return`, `horizon_days=1`입니다.

- full: avg hit rate `43.75%`, avg cumulative return `-5.83%`
- core: avg hit rate `44.40%`, avg cumulative return `-4.50%`

반면 `walk_forward_horizons["full"]["7"]`, `["core"]["7"]`는:

- avg hit rate `56.16%`
- stability 약 `0.75`
- avg cumulative return 약 `-9.4% ~ -9.7%`

이건 매우 중요한 시사점입니다.

- 방향은 어느 정도 맞출 수 있음
- 하지만 수익률 크기와 손익 비대칭을 못 잡음
- 거래 규칙이 hit rate 최적화에 치우쳐 있을 가능성 큼

즉, 다음 단계의 목표함수는 `hit rate` 단독이 아니라:

- expected return
- downside capture
- drawdown-aware utility

로 바뀌어야 합니다.

## 4.9 Granger 결과는 “alpha 근거”보다 “시장 구조 설명”에 가깝다

이번 산출물은 `granger_executed=True`, `eligible_rows=365`로 충분히 실행됐습니다. 다만 유의 결과를 보면:

- `news_sentiment_mean -> fng_value`
- `news_sentiment_mean -> etf_net_inflow_usd`
- `btc_log_return -> news_sentiment_mean`
- `btc_log_return -> funding_rate`
- `btc_log_return -> fng_value`
- `btc_log_return -> btc_long_short_ratio`

같은 식의 관계가 많습니다.

즉, 현재 Granger 결과는 “감성이 직접 수익률을 예측한다”보다

- 감성이 다른 risk sentiment variable과 연결된다
- 혹은 BTC 움직임이 후행 sentiment/positioning을 만든다

는 해석이 더 자연스럽습니다.  
따라서 Granger significance를 alpha 승격 근거로 쓰는 건 지금 단계에서는 과하게 낙관적일 수 있습니다.

---

## 5. 데이터 엔지니어링 관점 평가

## 5.1 파이프라인 본체는 안정화되고 있다

좋은 점:

- Alpha validation 결과를 parquet metadata에 함께 저장함  
  `src/morning_brief/analysis/sentiment_join/pipeline.py:739`
- hybrid diagnostics, structured source coverage, target diagnostics까지 한 payload에 포함
- futures/ETF coverage를 별도 structured metadata로 남김

이 구조는 이후 dashboard, monitoring, replay에 유리합니다.

## 5.2 하지만 산출물 계약이 아직 완전히 닫히지 않았다

문서 `sentiment_join_pipeline_changes.md`에는 각 셀에 다음 필드가 포함된다고 적혀 있습니다.

- `decision`
- `decision_strict`
- `best_baseline`
- baseline separation 관련 필드

그런데 실제 `horizon_metrics` 생성 코드는 현재:

- `pvalue_vs_baselines`
- `fdr_q`

만 추가하고 있습니다.  
근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1650`

그리고 payload는 받은 내용을 그대로 직렬화합니다.  
근거: `src/morning_brief/data/etf_storage.py:266`

즉, **문서상 계약과 실제 parquet 계약이 다릅니다.**

이건 운영상 왜 중요하냐면:

- 프론트엔드/리포트가 문서를 믿고 필드를 기대할 수 있음
- 리서치 문서와 실제 artifact가 다른 말을 하게 됨
- “승격 게이트가 있다”는 사실이 데이터 수준에서 재현되지 않음

이건 개선 우선순위를 높게 둬야 합니다.

## 5.3 paired bootstrap 비교 구현은 방법론 리스크가 있다

`_horizon_metrics()`에서 signal hit array와 baseline hit array를 만든 뒤:

- 날짜 인덱스를 정확히 맞춰 merge하지 않고
- `min(length)` 기준으로 앞에서 잘라 paired bootstrap을 수행합니다  
  `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1665`

이 방식은 엄밀한 의미의 paired comparison이라고 보기 어렵습니다.  
signal과 baseline의 active row 집합이 다를 수 있기 때문입니다.

데이터 엔지니어링 관점에서는 이게 단순 코드 스타일 문제가 아니라:

- 평가 재현성
- 통계 해석 일관성
- 승격 게이트 신뢰도

에 직접 영향을 주는 **measurement contract bug risk**입니다.

## 5.4 top-level walk_forward와 7D 전략의 대표 지표가 분리되어 있다

현재 `run_alpha_validation()`은:

- top-level `walk_forward`: 기본 `return_col="btc_log_return"`, `horizon_days=1`
- `walk_forward_horizons`: 각 horizon 별 별도 결과

로 저장합니다.  
근거: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:1187`, `1709`

변경 문서는 “T+7 단일 운영”을 강조하지만, 실제 artifact의 대표 위치는 아직 `1D walk_forward`입니다.  
이건 소비자 입장에서 혼란을 만듭니다.

정리하면:

- 연구 코드상으론 7D를 지원
- artifact 요약 구조상으론 1D가 아직 메인처럼 보임

이 불일치를 정리해야 합니다.

---

## 6. 무엇을 더 개선해야 하나

아래는 우선순위 기준입니다.

## 6.1 P0: 평가 계약부터 바로잡기

### P0-1. `decision_strict`를 실제 artifact에 넣기

문서에만 있고 parquet에 없으면 안 됩니다.

필요한 것:

- `horizon_metrics["7"]` 각 predictor 셀에
  - `decision`
  - `decision_strict`
  - `best_baseline`
  - `hit_rate_lift_vs_best_baseline`
  - `sharpe_lift_vs_best_baseline`
  를 실제로 채우기

이건 “좋아 보이는 실험”과 “승격 가능한 실험”을 구분하는 최소 단위입니다.

### P0-2. paired bootstrap 정렬 로직 수정

현재의 `min(length)` truncation 대신:

- signal/baseline 각각 날짜 인덱스를 보존
- 공통 날짜 집합으로 inner join
- 같은 row에서 paired statistic 계산

으로 바꿔야 합니다.

이건 분석 품질 관점에서도 가장 시급합니다.

### P0-3. top-level 대표 metric을 7D 기준으로 재정렬

지금처럼 `walk_forward`는 1D, `walk_forward_horizons`는 7D인 구조는 혼란스럽습니다.

선택지는 둘 중 하나입니다.

1. top-level도 7D만 남기기
2. top-level 이름을 `walk_forward_1d_legacy`처럼 명시적으로 바꾸기

현재 운영 문서 방향을 보면 1번이 더 자연스럽습니다.

## 6.2 P1: feature engineering 방향 수정

### P1-1. level feature보다 stationary feature 중심으로 재편

우선순위:

- `sentiment_momentum`
- `sentiment_accel`
- `fng_change_1d`
- `fng_change_5d`
- `rolling z-score`
- `regime-conditioned transforms`

반대로 raw level만으로 threshold를 거는 전략은 비중을 낮추는 게 맞습니다.

### P1-2. regime-aware model로 분기

현재 결과상 `btc_bear_regime_lag1`와 interaction 계열이 상대적으로 낫습니다.

추천 실험:

- bull / bear 분리 모델
- high vol / low vol 분리 모델
- sentiment extreme zone 에서만 활성화되는 sparse rule

즉, “항상 예측”보다 “특정 국면에서만 예측”이 더 유망합니다.

### P1-3. 목표함수를 hit rate 중심에서 utility 중심으로 바꾸기

다음 지표를 승격 게이트 후보로 올리는 게 좋습니다.

- net cumulative return
- downside deviation
- max drawdown
- turnover-adjusted Sharpe
- precision on large-move days

지금 7D hit rate 56%와 음수 cumulative return이 동시에 나오는 건, hit rate가 메인 KPI로는 부족하다는 뜻입니다.

## 6.3 P2: 연구 설계와 데이터 플랫폼 강화

### P2-1. 독립 신호 수 기준으로 실험 수를 줄이기

현재 predictor 간 상관이 매우 높습니다.

- 사실상 같은 정보의 다른 표현이 많음
- 다중검정 부담만 늘어남

추천:

- correlation clustering
- VIF / redundancy pruning
- “대표 feature set” 고정 후 실험

### P2-2. outlier 해석 레이어 분리

현재는 row-level outlier flag와 cell masking count가 함께 존재합니다.

향후에는 아래를 별도로 저장하는 게 좋습니다.

- `row_outlier_ratio`
- `masked_cell_count`
- `masked_feature_counts`
- `regime_stress_rows`

그래야 “시장 충격을 제거한 결과가 좋아졌다” 같은 해석이 덜 모호해집니다.

### P2-3. 데이터 품질 대시보드 자동화

현재 parquet metadata는 이미 충분히 풍부합니다.  
이제 필요한 건 자동 surfaced view입니다.

권장 모니터링 항목:

- source coverage ratio
- null ratio by column
- outlier row ratio / masked cell ratio
- stationarity pass count
- top baseline vs top signal gap
- walk-forward 7D cumulative return trend

이 정도면 매일 build 이후 “이번 run이 연구 가치가 있는지”를 바로 판단할 수 있습니다.

---

## 7. 추천 실행 순서

가장 현실적인 다음 순서는 아래입니다.

1. `P0`부터 처리
   - artifact contract 정합화
   - paired bootstrap row alignment 수정
   - top-level walk-forward를 7D 중심으로 정리

2. 그 다음 `P1`
   - level feature 축소
   - stationary / regime-conditioned feature 실험 강화
   - utility 기반 승격 게이트 추가

3. 마지막으로 `P2`
   - 실험 수 축소
   - 자동 품질 대시보드
   - 리서치/운영 문서 일치 자동 검증

---

## 8. 최종 판단

현재 상태를 한 줄로 정리하면:

**“데이터 파이프라인은 운영 가능한 수준까지 많이 안정화됐지만, alpha pipeline은 아직 연구 단계이며, 특히 평가 계약과 측정 방법론을 먼저 정리해야 한다.”**

더 구체적으로는:

- 데이터 품질: `좋음`
- 메타데이터 설계: `좋아지는 중`
- regime 설명력: `있음`
- 단순 수익 예측력: `약함`
- 승격 게이트 신뢰도: `보강 필요`

즉, 다음 개선의 핵심은 더 많은 피처를 넣는 것이 아니라:

- **평가를 더 정확하게 만들고**
- **regime-conditioned signal만 남기고**
- **수익화 기준으로 게이트를 다시 설계하는 것**

입니다.
