# 게이트 차단률 진단 (2026-07-24)

- frames: 1966 (2025-08-30 ~ 2026-07-24), forward_bars=6


## regime_trend

- long 신호: 7/1966 bars (0.4%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| donchian_breakout | 1862 |
| bullish_regime | 1614 |
| ema_aligned_up | 1310 |
| above_ema200_4h | 1096 |
| taker_confirms | 676 |
| oi_not_diverged | 570 |
| adx_trending | 567 |
| funding_not_hot | 198 |
| lsr_not_crowded | 132 |
| etf_outflow_not_heavy | 108 |
| rsi_below_long_max | 81 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| donchian_breakout | 86 | -0.27 | 48 | 유효 필터 |
| adx_trending | 8 | +0.56 | 88 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 6 | -0.50 | 33 | 유효 필터 |
| oi_not_diverged | 5 | -1.66 | 0 | 유효 필터 |
| bullish_regime | 4 | -0.61 | 0 | 유효 필터 |
| taker_confirms | 3 | -0.40 | 33 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -2.05 | 0 | 유효 필터 |
| lsr_not_crowded | 1 | +0.90 | 100 | dead weight 후보(알파 차단) |
| funding_not_hot | 1 | +0.62 | 100 | dead weight 후보(알파 차단) |

## macd_momentum

- long 신호: 4/1966 bars (0.2%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| above_ema200_4h | 1096 |
| macd_hist_increasing | 978 |
| macd_hist_positive | 917 |
| not_risk_off | 694 |
| oi_not_diverged | 570 |
| bb_width_sufficient | 460 |
| adx_sufficient | 411 |
| rsi_below_long_max | 207 |
| funding_not_hot | 198 |
| lsr_not_crowded | 132 |
| etf_outflow_not_heavy | 108 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| macd_hist_increasing | 81 | -0.46 | 43 | 유효 필터 |
| above_ema200_4h | 71 | -0.34 | 52 | 유효 필터 |
| macd_hist_positive | 48 | +0.51 | 65 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 40 | +0.22 | 65 | dead weight 후보(알파 차단) |
| bb_width_sufficient | 16 | +0.17 | 56 | dead weight 후보(알파 차단) |
| oi_not_diverged | 13 | -0.72 | 38 | 유효 필터 |
| adx_sufficient | 9 | -0.29 | 56 | 유효 필터 |
| not_risk_off | 4 | +0.23 | 50 | dead weight 후보(알파 차단) |
| funding_not_hot | 4 | -2.07 | 25 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |

## multi_factor

- long 신호: 246/1966 bars (12.5%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| direction_regime_ok | 1331 |
| breadth_not_collapsed | 942 |
| not_risk_off | 694 |
| other_votes_sufficient | 324 |
| stablecoin_not_contracting | 300 |
| lsr_not_crowded | 132 |
| etf_outflow_not_heavy | 108 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| direction_regime_ok | 276 | -0.04 | 49 | 유효 필터 |
| other_votes_sufficient | 118 | +0.08 | 52 | dead weight 후보(알파 차단) |
| breadth_not_collapsed | 93 | +0.87 | 69 | dead weight 후보(알파 차단) |
| stablecoin_not_contracting | 19 | -1.52 | 16 | 유효 필터 |
| etf_outflow_not_heavy | 15 | +1.18 | 87 | dead weight 후보(알파 차단) |
| lsr_not_crowded | 6 | +1.38 | 100 | dead weight 후보(알파 차단) |

## vix_rsi

- long 신호: 54/1966 bars (2.7%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| momentum_not_worsening | 978 |
| breadth_not_collapsed | 942 |
| rsi_below_long_max | 924 |
| vix_calm | 858 |
| not_risk_off | 694 |
| stablecoin_not_contracting | 300 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| rsi_below_long_max | 187 | -0.20 | 53 | 유효 필터 |
| momentum_not_worsening | 88 | +0.03 | 56 | dead weight 후보(알파 차단) |
| breadth_not_collapsed | 63 | +0.15 | 62 | dead weight 후보(알파 차단) |
| not_risk_off | 37 | +0.26 | 51 | dead weight 후보(알파 차단) |
| vix_calm | 9 | -1.59 | 44 | 유효 필터 |
| stablecoin_not_contracting | 3 | -1.28 | 0 | 유효 필터 |

## omnibus

- long 신호: 202/1966 bars (10.3%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| bb_not_extended | 497 |
| rsi_pullback_range | 475 |
| oversold_rebound_1of4votes | 300 |
| above_ema200_4h | 294 |
| regime_not_risk_off | 260 |
| range_near_low | 233 |
| rsi_below_range_max | 224 |
| oversold_rebound_2of4votes | 209 |
| funding_not_hot | 190 |
| adx_low_range | 109 |
| etf_outflow_not_heavy | 76 |
| ema_aligned | 60 |
| oversold_rebound_0of4votes | 42 |
| lsr_not_crowded | 21 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| oversold_rebound_1of4votes | 262 | -0.09 | 52 | 유효 필터 |
| regime_not_risk_off | 260 | +0.25 | 54 | dead weight 후보(알파 차단) |
| oversold_rebound_2of4votes | 178 | -0.25 | 48 | 유효 필터 |
| above_ema200_4h | 43 | -0.73 | 40 | 유효 필터 |
| oversold_rebound_0of4votes | 35 | -0.02 | 54 | 유효 필터 |
| rsi_pullback_range | 24 | -0.46 | 25 | 유효 필터 |
| etf_outflow_not_heavy | 22 | -1.82 | 36 | 유효 필터 |
| rsi_below_range_max | 13 | -0.23 | 54 | 유효 필터 |
| funding_not_hot | 13 | -0.03 | 62 | 유효 필터 |
| adx_low_range | 12 | -0.97 | 25 | 유효 필터 |
| bb_not_extended | 4 | +2.07 | 100 | dead weight 후보(알파 차단) |
| range_near_low | 2 | +1.70 | 100 | dead weight 후보(알파 차단) |
