# Sentiment Join Payoff Review - 2026-04-27

## Summary

이번 스프린트 변경은 새 alpha를 추가하지 않고, T+7 기준 수익화 실패 원인을 설명하는 metadata 계약을 보강했다.

- 기준 artifact: `master_20260427.parquet`
- 검증 방식: 기존 parquet를 다운로드한 뒤, 변경된 `run_alpha_validation()`으로 재평가
- 주의: 기준 artifact에는 predictor별 outlier flags가 저장되어 있지 않아 manual verification은 global mask fallback으로 확인했다. 새 pipeline run부터는 source column 기준 mask summary가 metadata까지 전달된다.

## Contract Changes

`horizon_metrics["7"]["hit_rates"]` 각 predictor row에 다음 필드가 추가된다.

- `payoff_diagnostics`: correct/wrong return, payoff ratio, exposure, turnover, strategy/B&H 평균 수익
- `masked_cells`, `masked_denominator`, `masked_source_columns`, `masked_ratio_source`
- `vol_regime_hit_rate_lift`, `vol_regime_sharpe_lift`

Top-level alpha metadata에는 다음 요약이 추가된다.

- `baseline_gap_summary["7"]`
- `next_research_candidates["7"]`
- 확장된 `feature_group_summary["7"]`
- `outlier_mask_summary`

Frontend artifact는 alpha block에서 다음 camelCase 필드를 통과시킨다.

- `baselineGapSummary`
- `nextResearchCandidates`

## Baseline Gap

2026-04-27 기준 primary benchmark는 여전히 `vol_regime`이다.

| metric | value |
|---|---:|
| best baseline | `vol_regime` |
| vol_regime hit rate | 0.5803 |
| vol_regime sharpe | 4.1020 |
| top signal by hit rate | `full_hybrid_index_score_lag1` |
| top signal hit rate | 0.5382 |
| top signal hit-rate gap vs vol_regime | -0.0420 |
| top signal by sharpe | `btc_bear_regime_lag1` |
| top signal sharpe | 0.8673 |
| top signal sharpe gap vs vol_regime | -3.2347 |
| signals beating vol_regime count | 0 |
| strict promote count | 0 |

해석: 일부 signal은 50% 초반 hit rate를 만들지만, `vol_regime` 대비 hit-rate와 Sharpe를 동시에 넘는 후보는 없다. 현 단계에서 promote가 아니라 research-only로 남는 것이 정상이다.

## Payoff Diagnostics

Payoff ratio 상위 predictor는 다음과 같다.

| predictor | hit rate | sharpe | payoff ratio | vol hit lift |
|---|---:|---:|---:|---:|
| `fng_change_5d_lag1` | 0.5170 | -0.8306 | 53.4295 | -0.0632 |
| `full_hybrid_index_score_lag1` | 0.5382 | 0.5530 | 40.8755 | -0.0420 |
| `sentiment_momentum_lag1` | 0.5113 | -1.6557 | 17.9442 | -0.0690 |
| `fng_change_1d_lag1` | 0.4663 | -1.8414 | 6.6932 | -0.1140 |
| `btc_bear_regime_lag1` | 0.5322 | 0.8673 | 5.8482 | -0.0481 |

Payoff ratio 하위 predictor는 다음과 같다.

| predictor | hit rate | sharpe | payoff ratio | vol hit lift |
|---|---:|---:|---:|---:|
| `sentiment_accel_lag1` | 0.5140 | -1.1416 | 0.5112 | -0.0662 |
| `news_sentiment_mean_lag1` | 0.5042 | -0.6710 | 0.6514 | -0.0761 |
| `vix_lag1` | 0.4930 | -2.1670 | 0.7874 | -0.0873 |
| `sentiment_momentum_x_bear_lag1` | 0.4972 | -1.3329 | 1.5524 | -0.0831 |
| `fng_change_1d_x_bear_lag1` | 0.4775 | -1.8068 | 1.5788 | -0.1028 |

해석: payoff ratio가 높아 보여도 `vol_regime` 대비 hit-rate lift가 음수이고 Sharpe 격차가 크다. 즉 "맞을 때의 평균 수익"만으로는 수익화 실패를 설명할 수 없고, 노출/회전/틀린 구간의 손익 및 benchmark gap을 함께 봐야 한다.

## Feature Groups

| group | predictors | avg hit | avg sharpe | avg payoff | positive payoff | candidates |
|---|---:|---:|---:|---:|---:|---:|
| level | 3 | 0.4958 | -0.9956 | 1.1448 | 1 | 0 |
| stationary | 4 | 0.5022 | -1.3673 | 19.6445 | 3 | 0 |
| regime | 4 | 0.4853 | -1.4446 | 3.4515 | 4 | 0 |
| hybrid | 2 | 0.5353 | 0.4095 | 21.3749 | 2 | 0 |

후보 선정 규칙은 `payoff_ratio > 1.0`, `vol_regime_hit_rate_lift > -0.05`, `masked_ratio <= 0.10`, `paired_rows_vs_vol_regime >= 180`이다.

이번 manual verification에서는 `next_research_candidates["7"]`가 비어 있다. 주요 이유는 기존 artifact에 predictor별 mask 정보가 없어 global fallback mask ratio가 적용되었고, 동시에 `vol_regime` 대비 lift가 충분하지 않았기 때문이다.

## Next Experiments

다음 alpha 실험은 promote가 아니라 "버릴 수 있는 후보를 더 빨리 버리는" 방향으로 잡는 것이 좋다.

1. `full_hybrid_index_score_lag1`: top hit-rate signal이며 payoff ratio도 높다. 단, `vol_regime` 대비 Sharpe gap이 커서 regime-aware exposure cap부터 확인한다.
2. `btc_bear_regime_lag1`: top Sharpe signal이지만 benchmark gap은 여전히 크다. bear-only cash/long rule보다 vol filter 결합 여부를 본다.
3. `fng_change_5d_lag1`: payoff ratio는 가장 높지만 Sharpe가 음수다. tail winner에 의존하는지 fold별 payoff를 분해한다.
4. `sentiment_momentum_lag1`: stationary 후보지만 Sharpe가 낮다. transaction cost와 turnover 민감도를 먼저 확인한다.

다음 스프린트 후보는 utility-based gate 또는 sparse regime rule 최적화다. 이번 변경으로 그 전에 필요한 실패 원인 metadata는 artifact에 남는다.
