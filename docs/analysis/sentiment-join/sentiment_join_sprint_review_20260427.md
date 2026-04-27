# Sentiment Join 스프린트 구현 검증 리포트
> 작성일: 2026-04-27  
> 범위: P0 운영 신뢰도 회복 + P1 연구 기반 일부 착수

## 1. 구현 요약

이번 변경으로 `horizon_metrics["7"]["hit_rates"]`가 문서에 적힌 운영 판단 계약을 실제 artifact에 포함하게 되었다.

추가된 핵심 필드:

- `decision`
- `decision_strict`
- `best_baseline`
- `best_hit_rate_baseline`
- `best_sharpe_baseline`
- `hit_rate_lift_vs_best_baseline`
- `sharpe_lift_vs_best_baseline`
- `baseline_hit_rate_ci_upper`
- `baseline_sharpe_ci_upper`
- `paired_baseline_alignment`

또한 baseline 대비 paired bootstrap 비교는 기존 길이 절단 방식이 아니라, signal/baseline의 공통 index 기준으로 정렬한 뒤 계산하도록 바뀌었다.

## 2. 계약 변경 전/후

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| `decision` / `decision_strict` | 문서에는 있으나 artifact 셀에는 없음 | `horizon_metrics["7"]["hit_rates"]` 각 셀에 포함 |
| baseline 비교 | signal/baseline 길이를 `min(length)`로 절단 | 공통 index/date 기반 paired sample만 사용 |
| top-level `walk_forward` | 1D 결과처럼 보임 | T+7 대표 결과로 정렬 |
| 1D walk-forward | top-level에 섞임 | `walk_forward_legacy_1d`로 명시 보존 |
| feature group 비교 | 없음 | `feature_group_summary` 추가 |

## 3. `master_20260427.parquet` 기준 수동 검증

검증 입력:

- `master_20260427.parquet`
- 원본: `https://pub-b507110be38b42808d6f82b517b123f1.r2.dev/sentiment_join/master_20260427.parquet`
- `BootstrapConfig(n_bootstrap=50, block_length=14, seed=0)`

검증 결과:

- `horizon_metrics["7"]["hit_rates"]`: 13개 predictor
- `decision` count: `research_only = 13`
- `decision_strict` count: `research_only = 13`
- top-level `walk_forward`: `full/core` 모두 `horizon_days = 7`
- `walk_forward_legacy_1d`: `full/core` 모두 `horizon_days = 1`
- `feature_group_summary`: horizon key `7` 생성

현재 데이터에서 전부 `research_only`가 나온 것은 정상이다. baseline 대비 유의한 승격 근거가 없고, strict gate는 CI hard separation과 FDR 조건을 요구하기 때문이다.

## 4. Paired Bootstrap 정렬 검증

테스트 fixture에서 signal valid row와 baseline active row를 일부러 어긋나게 만들었다.

예상 결과:

- signal rows: 19
- baseline rows: 3
- paired rows: 2

이 결과가 통과했으므로, 이제 paired bootstrap은 길이만 맞춰 앞에서 자르는 방식이 아니라 같은 index에 존재하는 관측치만 비교한다.

## 5. T+7 대표 Walk-Forward 검증

`run_alpha_validation()`의 top-level `walk_forward`는 이제 T+7 결과를 대표한다.

기존 1D 결과는 제거하지 않고 `walk_forward_legacy_1d`에 보존했다. 따라서 downstream consumer는 다음 기준으로 읽으면 된다.

- 운영/리서치 대표값: `walk_forward`
- 과거 1D 비교용 값: `walk_forward_legacy_1d`
- 전체 horizon 확장 결과: `walk_forward_horizons`

## 6. Feature Group Summary

새 `feature_group_summary`는 predictor를 아래 그룹으로 나눠 성능을 비교한다.

- `level`
- `stationary`
- `regime`
- `hybrid`
- `other`

이번 스프린트에서는 신규 ML 모델을 추가하지 않고, 기존 threshold/backtest 평가 결과를 group 단위로 요약하는 기반만 추가했다.

## 7. 검증 명령

```bash
./.venv/bin/python -m pytest tests/analysis/test_sentiment_join/test_alpha_validation.py tests/analysis/test_sentiment_join/test_frontend_artifact.py tests/test_btc_etf_storage.py -q
```

결과:

- `67 passed`

```bash
./.venv/bin/python -m ruff check src/morning_brief/analysis/sentiment_join/statistical_tests.py src/morning_brief/analysis/sentiment_join/pipeline.py src/morning_brief/data/etf_storage.py src/morning_brief/analysis/sentiment_join/frontend_artifact.py tests/analysis/test_sentiment_join/test_alpha_validation.py tests/test_btc_etf_storage.py tests/analysis/test_sentiment_join/test_frontend_artifact.py
```

결과:

- `All checks passed`

## 8. 다음 스프린트 후보

추천 우선순위:

1. `masked_ratio`를 horizon metric 셀 단위로 더 정확히 연결한다.
2. `feature_group_summary`를 daily frontend artifact에서 더 보기 좋은 카드/표 형태로 노출한다.
3. stationary/regime 그룹만 대상으로 sparse rule 또는 utility-based gate를 실험한다.
4. `decision_strict` count와 top baseline gap을 매일 자동 리포트에 포함한다.
