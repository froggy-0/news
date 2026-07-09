# 게이트 차단률 진단 (2026-07-09)

- frames: 1966 (2025-08-15 ~ 2026-07-08), forward_bars=6


## regime_trend

- long 신호: 14/1966 bars (0.7%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| donchian_breakout | 1869 |
| bullish_regime | 1379 |
| ema_aligned_up | 1359 |
| above_ema200_4h | 1109 |
| oi_not_diverged | 534 |
| adx_trending | 534 |
| taker_confirms | 480 |
| etf_outflow_not_heavy | 96 |
| rsi_below_long_max | 81 |
| lsr_not_crowded | 66 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| donchian_breakout | 145 | -0.12 | 53 | 유효 필터 |
| rsi_below_long_max | 11 | -0.51 | 27 | 유효 필터 |
| adx_trending | 10 | +1.00 | 90 | dead weight 후보(알파 차단) |
| oi_not_diverged | 5 | -1.66 | 0 | 유효 필터 |
| bullish_regime | 3 | -0.65 | 0 | 유효 필터 |
| taker_confirms | 1 | -2.42 | 0 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -2.05 | 0 | 유효 필터 |

## macd_momentum

- long 신호: 10/1966 bars (0.5%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| above_ema200_4h | 1109 |
| macd_hist_increasing | 971 |
| macd_hist_positive | 923 |
| not_risk_off | 724 |
| oi_not_diverged | 534 |
| bb_width_sufficient | 442 |
| adx_sufficient | 392 |
| rsi_below_long_max | 199 |
| etf_outflow_not_heavy | 96 |
| lsr_not_crowded | 66 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| above_ema200_4h | 102 | -0.33 | 49 | 유효 필터 |
| macd_hist_increasing | 84 | -0.39 | 50 | 유효 필터 |
| macd_hist_positive | 50 | +0.12 | 52 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 44 | +0.15 | 61 | dead weight 후보(알파 차단) |
| bb_width_sufficient | 20 | -0.35 | 35 | 유효 필터 |
| adx_sufficient | 11 | -0.60 | 45 | 유효 필터 |
| oi_not_diverged | 8 | -1.75 | 0 | 유효 필터 |
| not_risk_off | 6 | -0.33 | 17 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |

## multi_factor

- long 신호: 691/1966 bars (35.1%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| factor_score_at_least_4 | 973 |
| not_risk_off | 724 |
| etf_outflow_not_heavy | 96 |
| lsr_not_crowded | 66 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| factor_score_at_least_4 | 466 | -0.41 | 44 | 유효 필터 |
| not_risk_off | 239 | -0.12 | 51 | 유효 필터 |
| etf_outflow_not_heavy | 42 | -0.03 | 48 | 유효 필터 |
| lsr_not_crowded | 10 | -0.28 | 60 | 유효 필터 |
