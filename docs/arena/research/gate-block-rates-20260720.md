# 게이트 차단률 진단 (2026-07-20)

- frames: 1966 (2025-08-27 ~ 2026-07-20), forward_bars=6


## macd_momentum

- long 신호: 9/1966 bars (0.5%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| above_ema200_4h | 1114 |
| macd_hist_increasing | 975 |
| macd_hist_positive | 908 |
| not_risk_off | 702 |
| oi_not_diverged | 582 |
| bb_width_sufficient | 452 |
| adx_sufficient | 411 |
| rsi_below_long_max | 202 |
| funding_not_hot | 198 |
| lsr_not_crowded | 138 |
| etf_outflow_not_heavy | 108 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| macd_hist_increasing | 79 | -0.42 | 46 | 유효 필터 |
| above_ema200_4h | 71 | -0.34 | 52 | 유효 필터 |
| macd_hist_positive | 46 | +0.51 | 63 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 39 | +0.20 | 67 | dead weight 후보(알파 차단) |
| oi_not_diverged | 13 | -0.72 | 38 | 유효 필터 |
| bb_width_sufficient | 12 | -0.18 | 42 | 유효 필터 |
| adx_sufficient | 9 | -0.29 | 56 | 유효 필터 |
| not_risk_off | 5 | +0.18 | 40 | dead weight 후보(알파 차단) |
| funding_not_hot | 4 | -2.07 | 25 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |
