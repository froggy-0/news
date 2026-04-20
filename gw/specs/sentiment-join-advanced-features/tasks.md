# Implementation Plan: Sentiment-Join Advanced Features

## Overview

이 계획은 `design.md`의 순서를 그대로 따라간다. 먼저 sub-index와 supervised model의 공통 입력 계약을 만들고, 그 다음에 statistical validation과 baseline 비교를 확장한다. 마지막으로 feature store, lineage, tracking, sample size, reporting을 묶어서 연구 결과가 재현 가능한 형태로 남도록 정리한다.

기존 `sentiment-join-outlier-rework`에서 이미 안정화된 `merge_sources`, `compute_hybrid_indices`, `walk_forward_validate`, `bootstrap_ci`, `run_anova`는 유지하고, 새 작업은 그 위의 확장으로만 붙인다.

## Tasks

### Phase 1 — Sub-index and model foundation

- [x] 1. Sub-index feature architecture
  - [x] 1.1 `src/morning_brief/analysis/sentiment_join/subindices.py`를 생성한다.
    - `SubIndexSpec`, `SubIndexBundle` 또는 이에 준하는 데이터 구조를 정의한다.
    - `sentiment`, `positioning`, `flow`, `vol` 네 축의 feature group을 명시한다.
    - `funding * lsr`, `sentiment * vix` interaction feature를 생성하는 헬퍼를 추가한다.
    - _Requirements: R1, R6_
  - [x] 1.2 서브 인덱스 계산 함수 `compute_subindices`를 구현한다.
    - 각 서브 인덱스가 독립적인 feature selection, scaling, PCA를 수행하게 한다.
    - score/raw component/diagnostic 정보를 분리해서 반환한다.
    - `hybrid_index.py`의 full/core 경로는 그대로 보존한다.
    - _Requirements: R1_

- [x] 2. Sub-index regression tests
  - [x] 2.1 `tests/analysis/test_sentiment_join/test_subindices.py`를 생성한다.
    - 출력 DataFrame shape, score 범위, interaction feature 계산 여부를 검증한다.
    - 입력 컬럼 일부가 NaN일 때의 degradation 경로를 확인한다.
    - _Requirements: R1_
  - [x] 2.2 서브 인덱스와 기존 full/core hybrid index가 공존할 때 컬럼 충돌이 없는지 검증한다.
    - full/core 기존 컬럼과 새 서브 인덱스 컬럼이 서로 독립적으로 유지되는지 확인한다.
    - _Requirements: R1, R6_

- [x] 3. Supervised model wrappers
  - [x] 3.1 `src/morning_brief/analysis/sentiment_join/models.py`를 생성한다.
    - `L1LogisticModel`, `ElasticNetRegressorModel`, `LightGBMModel` wrapper를 정의한다.
    - pandas `DataFrame`/`Series` 입력 계약을 통일한다.
    - `LightGBMModel`에 대해 SHAP 해석 보조를 노출하되, SHAP 실패가 fit/predict 경로를 깨지 않도록 한다.
    - feature importance 또는 coefficient export를 위한 공통 인터페이스를 추가한다.
    - _Requirements: R2_
  - [x] 3.2 시계열 CV splitter를 추가한다.
    - `TimeSeriesSplit` 계열 분할과 embargo-aware split을 제공한다.
    - training/test 분리 경계가 누출을 만들지 않도록 한다.
    - _Requirements: R2, R4_

- [x] 4. Supervised model tests
  - [x] 4.1 `tests/analysis/test_sentiment_join/test_models.py`를 생성한다.
    - 세 wrapper의 fit/predict contract를 검증한다.
    - seeded 실행에서 예측이 재현 가능한지 확인한다.
    - _Requirements: R2_
  - [x] 4.2 CV splitter가 embargo와 split 경계를 지키는지 검증한다.
    - purged split 전제에서 train/test overlap이 없음을 확인한다.
    - _Requirements: R4_

- [x] 5. Checkpoint 1
  - [x] 5.1 `make fmt && make lint && make typecheck`를 수행한다.
  - [x] 5.2 `pytest tests/analysis/test_sentiment_join/test_subindices.py -v`와 `pytest tests/analysis/test_sentiment_join/test_models.py -v`를 수행한다.

### Phase 2 — Statistical validation and baselines

- [x] 6. Granger and stationarity redesign
  - [x] 6.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py`에 `stationarity_check`를 추가한다.
    - 기존 `_run_stationarity`의 판정 의미를 보존하면서 외부에서 호출 가능한 진입점을 만든다.
    - ADF/KPSS 결과와 판정 사유를 구조화해서 반환한다.
    - _Requirements: R3_
  - [x] 6.2 `TransferEntropy` 진입점을 추가한다.
    - Granger와 별도 경로로 비선형 의존성을 평가한다.
    - 경고가 없는 윈도우만 통과시키는 필터를 추가한다.
    - _Requirements: R3_

- [x] 7. Statistical tests regression coverage
  - [x] 7.1 `tests/analysis/test_sentiment_join/test_statistical_tests.py`를 확장한다.
    - stationarity dispatch, transfer entropy entry, warning-free window 선택을 검증한다.
    - 비정상 시계열은 계속 Granger를 건너뛰는지 회귀를 확인한다.
    - _Requirements: R3_

- [x] 8. Walk-forward enhancement
  - [x] 8.1 `walk_forward_validate`에 `purged_kfold`, `expanding_window`, horizon-aware embargo 옵션을 추가한다.
    - 기본 동작은 현재 T+1 결과와 호환되도록 유지한다.
    - `WalkForwardResult`에 purged/embargo 메타데이터를 노출한다.
    - _Requirements: R4_
  - [x] 8.2 horizon > 1일 때 `max(horizon, 5)` embargo 규칙을 명시적으로 적용한다.
    - multi-horizon 타겟별 overlap 위험을 차단한다.
    - _Requirements: R4_

- [x] 9. Walk-forward regression tests
  - [x] 9.1 `tests/analysis/test_sentiment_join/test_statistical_tests.py`에 walk-forward 케이스를 추가한다.
    - embargo 길이, purged split, expanding-window 동작을 확인한다.
    - default path가 기존 결과를 깨지 않는지 검증한다.
    - _Requirements: R4_

- [x] 10. Baseline strategies
  - [x] 10.1 `src/morning_brief/analysis/sentiment_join/baselines.py`를 생성한다.
    - `always_up`, `fng_contrarian`, `btc_momo_20d`, `vol_regime`을 구현한다.
    - 공통 평가 유틸로 hit rate, sharpe, return alignment를 계산한다.
    - _Requirements: R5_

- [x] 11. Baseline tests
  - [x] 11.1 `tests/analysis/test_sentiment_join/test_baselines.py`를 생성한다.
    - 네 baseline의 신호 방향과 metric 계산을 검증한다.
    - 입력 컬럼이 부족할 때의 skip/degrade 경로를 확인한다.
    - _Requirements: R5_

- [x] 12. Checkpoint 2
  - [x] 12.1 `make fmt && make lint && make typecheck`를 수행한다.
  - [x] 12.2 `pytest tests/analysis/test_sentiment_join/test_statistical_tests.py -v`와 `pytest tests/analysis/test_sentiment_join/test_baselines.py -v`를 수행한다.

### Phase 3 — Feature store, lineage, and tracking

- [x] 13. Feature store layer
  - [x] 13.1 `src/morning_brief/analysis/sentiment_join/feature_store.py`를 생성한다.
    - `raw`, `clean`, `model` 레이어를 담는 bundle을 정의한다.
    - manifest에 rules version, cache key, provenance를 저장한다.
    - 각 레이어를 재생성 가능한 스냅샷 파일로 저장하는 경로를 정의한다.
    - _Requirements: R6, R7_
  - [x] 13.2 cache invalidation 규칙을 추가한다.
    - outlier policy 또는 feature rule이 바뀌면 clean/model 재계산을 강제한다.
    - raw 레이어는 가능한 한 보존한다.
    - _Requirements: R6_

- [x] 14. Feature store tests
  - [x] 14.1 `tests/analysis/test_sentiment_join/test_feature_store.py`를 생성한다.
    - 레이어 분리, cache invalidation, raw row/order 보존을 검증한다.
    - _Requirements: R6_

- [x] 15. Lineage capture
  - [x] 15.1 `join.py` / `pipeline.py`에 per-column source metadata를 추가한다.
    - `funding_source`, `oi_source`, `lsr_source` 같은 provenance 필드를 보존한다.
    - _Requirements: R7_
  - [x] 15.2 `backfill_manifest.json` 생성 로직을 추가한다.
    - source mode, quality status, fallback 경로를 기록한다.
    - 기존 `save_parquet` metadata 계약(`btc_source`, `ffill_days`, stats payload)은 유지한다.
    - _Requirements: R7_

- [x] 16. Lineage tests
  - [x] 16.1 `tests/analysis/test_sentiment_join/test_join.py`와 `tests/analysis/test_sentiment_join/test_storage.py`를 확장한다.
    - source metadata, manifest 내용, Parquet metadata 호환성을 검증한다.
    - _Requirements: R7_

- [x] 17. Experiment tracking
  - [x] 17.1 `experiments.py`에 JSON tracking artifact를 추가한다.
    - `run_id`, `spec`, metrics, lineage를 함께 저장한다.
    - `ExperimentRunner`의 fold-level schema는 유지한다.
    - _Requirements: R8_
  - [x] 17.2 tracking snapshot을 재현 가능하게 만든다.
    - 동일 입력과 동일 spec이면 동일한 artifact 구조를 생성한다.
    - MLflow 연동은 이번 단계의 필수 범위에 넣지 않는다.
    - _Requirements: R8, R6_

- [x] 18. Tracking tests
  - [x] 18.1 `tests/test_experiment_tracking.py`를 생성한다.
    - snapshot 구조, run_id 규칙, schema 안정성을 검증한다.
    - _Requirements: R8_

- [x] 19. Checkpoint 3
  - [x] 19.1 `make fmt && make lint && make typecheck`를 수행한다.
  - [x] 19.2 `pytest tests/analysis/test_sentiment_join/test_feature_store.py -v`와 `pytest tests/test_experiment_tracking.py -v`를 수행한다.

### Phase 4 — Validation and report

- [x] 20. Sample size validation
  - [x] 20.1 `src/morning_brief/analysis/sentiment_join/variance.py`에 power analysis 및 minimum-sample 추정 유틸을 추가한다.
    - 기존 `bootstrap_ci`와 `run_anova`는 변경하지 않고 확장만 한다.
    - _Requirements: R9_
  - [x] 20.2 sample size 판단을 report gate에서 사용할 수 있도록 결과 포맷을 정리한다.
    - CI 하한과 보수적 판정이 함께 남도록 한다.
    - _Requirements: R9_

- [x] 21. Validation tests
  - [x] 21.1 `tests/test_variance_decomposition.py`를 확장한다.
    - bootstrap CI bounds, power estimate, conservative gating을 검증한다.
    - _Requirements: R9_

- [x] 22. Comprehensive report
  - [x] 22.1 reporting script를 업데이트한다.
    - sub-index vs full/core, baseline vs model, promotion gate, lineage summary를 한 번에 비교한다.
    - _Requirements: R1, R2, R5, R6, R7, R8, R9_
  - [x] 22.2 결과 artifact 이름과 저장 위치는 가능한 한 기존 규칙을 유지한다.
    - 새 artifact가 필요하면 기존 variance report와 충돌하지 않도록 분리한다.
    - _Requirements: R8, R9_

- [x] 23. Report tests
  - [x] 23.1 report 내용과 gate 평가를 검증하는 테스트를 추가한다.
    - 모델/베이스라인 셀이 일부 비어 있어도 report가 생성되는지 확인한다.
    - _Requirements: R1, R2, R5, R9_

- [x] 24. Checkpoint 4
  - [x] 24.1 `make fmt && make lint && make typecheck`를 수행한다.
  - [x] 24.2 `pytest tests/test_variance_decomposition.py -v`와 `pytest tests/test_variance_report.py -v`를 수행한다.

## Regression Test Summary

| 테스트 파일 | 검증 | Phase |
|---|---|---|
| `tests/analysis/test_sentiment_join/test_subindices.py` | 4개 서브 인덱스 출력, interaction feature, degradation | 1 |
| `tests/analysis/test_sentiment_join/test_models.py` | supervised wrapper fit/predict, CV split, 재현성 | 1 |
| `tests/analysis/test_sentiment_join/test_statistical_tests.py` | stationarity, transfer entropy, purged walk-forward | 2 |
| `tests/analysis/test_sentiment_join/test_baselines.py` | 4개 baseline metric, skip/degrade | 2 |
| `tests/analysis/test_sentiment_join/test_feature_store.py` | raw/clean/model 레이어 분리, cache invalidation | 3 |
| `tests/analysis/test_sentiment_join/test_join.py` | lineage/source metadata, manifest 생성 | 3 |
| `tests/analysis/test_sentiment_join/test_storage.py` | Parquet metadata 호환성 | 3 |
| `tests/test_experiment_tracking.py` | JSON tracking artifact, run_id, schema 안정성 | 3 |
| `tests/test_variance_decomposition.py` | bootstrap CI, power analysis, sample size gate | 4 |
| `tests/test_variance_report.py` | report sections, lineage summary, baseline/model comparison | 4 |

## Rollback Plan

- feature store 도입이 불안정하면 `raw -> clean -> model` 분리를 끄고 기존 단일 결합 흐름으로 되돌린다.
- sub-index 계산이 불안정하면 full/core hybrid index만 유지하고 서브 인덱스 컬럼은 저장하지 않는다.
- 모델 wrapper가 불안정하면 baseline과 walk-forward만 유지하고 supervised 경로는 비활성화한다.
- transfer entropy/CCM 경로가 불안정하면 기존 Granger + stationarity만 유지한다.
- tracking 또는 manifest 생성이 문제를 만들면 결과 계산은 유지하고 artifact 저장만 중단한다.
