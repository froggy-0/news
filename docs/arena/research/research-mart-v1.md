# Arena Research Mart v1

작성일: 2026-06-19

## 목적

아레나 봇의 전략 버전, 피처 정의, decision 단위 분석 mart를 묶어 이후 백테스트/모델 실험을 재현 가능하게 만든다.

## 설계 원칙

- `strategy_version`은 코드/파라미터/피처셋/리스크모델 조합을 뜻한다.
- `feature_set_version`은 모델 입력 후보의 schema 버전이다.
- feature는 현재 run의 closed candle과 해당 시점 macro snapshot만 사용한다.
- forward return은 label이다. 모델 입력으로 쓰면 안 된다.
- gross forward return은 mart에서 제공하고, 실현 수익/수수료 반영은 `paper_positions`를 기준으로 본다.

## 신규 객체

| Object | Grain | Role |
| --- | --- | --- |
| `arena_strategy_versions` | strategy_version | 전략/파라미터/피처/리스크 모델 registry |
| `arena_feature_registry` | feature_set_version/feature_name | 피처 단위, lag, 누수 안전성, 리스크 영향 |
| `arena_decision_mart_v1` | run_id/algo_id | decision + features + forward labels |

## Mart Columns

Feature columns:

- `rsi`, `macd_hist`, `bb_pos`, `atr`
- `regime_state`, `fng`, `vix_now`, `vix_q40`
- `signal_open/high/low/close/volume`

Label columns:

- `forward_return_1bar`, `forward_return_3bar`, `forward_return_6bar`
- `signal_return_1bar`, `signal_return_3bar`, `signal_return_6bar`

`signal_return_*`는 `long`이면 forward return 그대로, `short`이면 부호 반전, flat이면 null이다.

## 운영 순서

1. Supabase SQL Editor에서 `/Users/giwon/code/news/supabase/migrations/20260619_arena_strategy_feature_mart.sql` 실행.
2. 실행 결과 `arena_strategy_feature_mart_ready`의 `has_*` 값이 true인지 확인.
3. `registered_features`가 8 이상인지 확인.
4. EC2에 최신 `src/arena` 배포.
5. `arena.service` 재시작.
6. 다음 run 후 `arena_runs.capture_status = ok`인지 확인.

## 검증 SQL

```sql
SELECT
    strategy_version,
    params_version,
    feature_set_version,
    risk_model_version,
    status
FROM arena_strategy_versions;
```

```sql
SELECT
    feature_name,
    layer,
    dtype,
    unit,
    lookback_bars,
    lag_bars,
    leakage_safe,
    risk_impact
FROM arena_feature_registry
WHERE feature_set_version = 'arena-features-v4'
ORDER BY layer, feature_name;
```

```sql
SELECT
    run_id,
    algo_id,
    signal,
    action,
    signal_close,
    rsi,
    macd_hist,
    atr,
    regime_state,
    fng,
    forward_return_1bar,
    signal_return_1bar
FROM arena_decision_mart_v1
ORDER BY started_at DESC, algo_id
LIMIT 20;
```

## 다음 확장

- walk-forward split table과 report mart는 구현되어 있으므로, sample size가 쌓이면 split별 결과를 누적 검증한다.
- frequency research v1에서는 `arena_frequency_backtest_mart_v1`로 빈도별 비용/회전율을 비교한다.
- realized PnL과 forward label을 같이 보는 `arena_position_outcome_mart_v1` 추가.
- feature importance/ablation 결과를 저장하는 `arena_experiment_runs` 계층 추가.
