# 게이트 차단률 진단 (2026-07-11)

- frames: 1966 (2025-08-17 ~ 2026-07-11), forward_bars=6


## regime_trend

- long 신호: 7/1966 bars (0.4%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| donchian_breakout | 1868 |
| bullish_regime | 1625 |
| ema_aligned_up | 1350 |
| above_ema200_4h | 1114 |
| taker_confirms | 652 |
| oi_not_diverged | 600 |
| adx_trending | 549 |
| funding_not_hot | 198 |
| lsr_not_crowded | 144 |
| etf_outflow_not_heavy | 114 |
| rsi_below_long_max | 81 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| donchian_breakout | 86 | -0.27 | 48 | 유효 필터 |
| adx_trending | 8 | +0.56 | 88 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 6 | -0.50 | 33 | 유효 필터 |
| oi_not_diverged | 5 | -1.66 | 0 | 유효 필터 |
| bullish_regime | 4 | -0.61 | 0 | 유효 필터 |
| taker_confirms | 2 | -0.78 | 50 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -2.05 | 0 | 유효 필터 |
| lsr_not_crowded | 1 | +0.90 | 100 | dead weight 후보(알파 차단) |
| funding_not_hot | 1 | +0.62 | 100 | dead weight 후보(알파 차단) |

## macd_momentum

- long 신호: 11/1966 bars (0.6%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| above_ema200_4h | 1114 |
| macd_hist_increasing | 974 |
| macd_hist_positive | 911 |
| not_risk_off | 719 |
| oi_not_diverged | 600 |
| bb_width_sufficient | 442 |
| adx_sufficient | 403 |
| rsi_below_long_max | 199 |
| funding_not_hot | 198 |
| lsr_not_crowded | 144 |
| etf_outflow_not_heavy | 114 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| above_ema200_4h | 75 | -0.46 | 49 | 유효 필터 |
| macd_hist_increasing | 64 | -0.34 | 52 | 유효 필터 |
| macd_hist_positive | 41 | +0.45 | 59 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 38 | +0.23 | 68 | dead weight 후보(알파 차단) |
| oi_not_diverged | 13 | -0.72 | 38 | 유효 필터 |
| bb_width_sufficient | 11 | -0.05 | 45 | 유효 필터 |
| adx_sufficient | 9 | -0.29 | 56 | 유효 필터 |
| not_risk_off | 5 | -0.16 | 20 | 유효 필터 |
| funding_not_hot | 4 | -2.07 | 25 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |
