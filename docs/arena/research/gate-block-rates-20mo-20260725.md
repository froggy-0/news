# 게이트 차단률 진단 (2026-07-25)

- frames: 3740 (2024-11-09 ~ 2026-07-25), forward_bars=6


## regime_trend

- long 신호: 16/3740 bars (0.4%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| donchian_breakout | 3542 |
| bullish_regime | 3015 |
| ema_aligned_up | 2362 |
| above_ema200_4h | 1791 |
| adx_trending | 1199 |
| taker_confirms | 963 |
| oi_not_diverged | 720 |
| funding_not_hot | 282 |
| rsi_below_long_max | 209 |
| lsr_not_crowded | 204 |
| etf_outflow_not_heavy | 126 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| donchian_breakout | 217 | +0.08 | 51 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 21 | +0.25 | 48 | dead weight 후보(알파 차단) |
| adx_trending | 20 | +0.03 | 65 | dead weight 후보(알파 차단) |
| oi_not_diverged | 6 | -1.37 | 17 | 유효 필터 |
| bullish_regime | 5 | +0.05 | 20 | dead weight 후보(알파 차단) |
| taker_confirms | 4 | -0.90 | 25 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -2.05 | 0 | 유효 필터 |
| lsr_not_crowded | 1 | +0.90 | 100 | dead weight 후보(알파 차단) |
| funding_not_hot | 1 | +0.62 | 100 | dead weight 후보(알파 차단) |

## macd_momentum

- long 신호: 47/3740 bars (1.3%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| macd_hist_increasing | 1867 |
| macd_hist_positive | 1855 |
| above_ema200_4h | 1791 |
| not_risk_off | 1124 |
| bb_width_sufficient | 979 |
| adx_sufficient | 871 |
| oi_not_diverged | 720 |
| rsi_below_long_max | 443 |
| funding_not_hot | 282 |
| lsr_not_crowded | 204 |
| etf_outflow_not_heavy | 126 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| macd_hist_increasing | 170 | -0.21 | 46 | 유효 필터 |
| above_ema200_4h | 142 | +0.03 | 51 | dead weight 후보(알파 차단) |
| macd_hist_positive | 104 | +0.18 | 53 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 83 | +0.58 | 64 | dead weight 후보(알파 차단) |
| adx_sufficient | 52 | +0.15 | 48 | dead weight 후보(알파 차단) |
| bb_width_sufficient | 34 | -0.15 | 44 | 유효 필터 |
| oi_not_diverged | 22 | -0.22 | 45 | 유효 필터 |
| not_risk_off | 14 | -1.08 | 21 | 유효 필터 |
| funding_not_hot | 5 | -1.97 | 20 | 유효 필터 |
| lsr_not_crowded | 4 | +0.30 | 50 | dead weight 후보(알파 차단) |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |

## multi_factor

- long 신호: 454/3740 bars (12.1%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| direction_regime_ok | 2366 |
| breadth_not_collapsed | 1230 |
| not_risk_off | 1124 |
| other_votes_sufficient | 1029 |
| stablecoin_not_contracting | 336 |
| lsr_not_crowded | 204 |
| etf_outflow_not_heavy | 126 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| direction_regime_ok | 634 | +0.09 | 50 | dead weight 후보(알파 차단) |
| other_votes_sufficient | 503 | +0.21 | 50 | dead weight 후보(알파 차단) |
| breadth_not_collapsed | 121 | +0.76 | 68 | dead weight 후보(알파 차단) |
| stablecoin_not_contracting | 19 | -1.52 | 16 | 유효 필터 |
| etf_outflow_not_heavy | 15 | +1.18 | 87 | dead weight 후보(알파 차단) |
| lsr_not_crowded | 14 | -0.36 | 43 | 유효 필터 |
