# 게이트 차단률 진단 (2026-07-13)

- frames: 1966 (2025-08-19 ~ 2026-07-13), forward_bars=6


## regime_trend

- long 신호: 14/1966 bars (0.7%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| donchian_breakout | 1868 |
| bullish_regime | 1359 |
| ema_aligned_up | 1342 |
| above_ema200_4h | 1117 |
| adx_trending | 551 |
| oi_not_diverged | 523 |
| taker_confirms | 463 |
| etf_outflow_not_heavy | 96 |
| rsi_below_long_max | 81 |
| lsr_not_crowded | 66 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| donchian_breakout | 153 | -0.13 | 52 | 유효 필터 |
| rsi_below_long_max | 11 | -0.51 | 27 | 유효 필터 |
| adx_trending | 11 | +0.88 | 82 | dead weight 후보(알파 차단) |
| oi_not_diverged | 5 | -1.66 | 0 | 유효 필터 |
| bullish_regime | 3 | -0.65 | 0 | 유효 필터 |
| taker_confirms | 1 | -2.42 | 0 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -2.05 | 0 | 유효 필터 |

## macd_momentum

- long 신호: 11/1966 bars (0.6%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| above_ema200_4h | 1117 |
| macd_hist_increasing | 977 |
| macd_hist_positive | 909 |
| not_risk_off | 713 |
| oi_not_diverged | 523 |
| bb_width_sufficient | 442 |
| adx_sufficient | 399 |
| rsi_below_long_max | 199 |
| etf_outflow_not_heavy | 96 |
| lsr_not_crowded | 66 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| above_ema200_4h | 102 | -0.33 | 49 | 유효 필터 |
| macd_hist_increasing | 94 | -0.38 | 49 | 유효 필터 |
| rsi_below_long_max | 44 | +0.15 | 61 | dead weight 후보(알파 차단) |
| macd_hist_positive | 42 | +0.38 | 57 | dead weight 후보(알파 차단) |
| bb_width_sufficient | 19 | -0.27 | 37 | 유효 필터 |
| adx_sufficient | 14 | -0.45 | 50 | 유효 필터 |
| oi_not_diverged | 8 | -1.75 | 0 | 유효 필터 |
| not_risk_off | 6 | -0.33 | 17 | 유효 필터 |
| etf_outflow_not_heavy | 1 | -1.42 | 0 | 유효 필터 |

## omnibus

- long 신호: 236/1966 bars (12.0%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| bb_not_extended | 484 |
| rsi_pullback_range | 455 |
| oversold_rebound_1of4votes | 307 |
| above_ema200_4h | 291 |
| regime_not_risk_off | 258 |
| range_near_low | 222 |
| oversold_rebound_2of4votes | 212 |
| rsi_below_range_max | 211 |
| adx_low_range | 114 |
| ema_aligned | 67 |
| etf_outflow_not_heavy | 65 |
| oversold_rebound_0of4votes | 45 |
| lsr_not_crowded | 14 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| oversold_rebound_1of4votes | 299 | -0.13 | 52 | 유효 필터 |
| regime_not_risk_off | 258 | +0.24 | 53 | dead weight 후보(알파 차단) |
| oversold_rebound_2of4votes | 203 | -0.30 | 46 | 유효 필터 |
| above_ema200_4h | 42 | -0.58 | 38 | 유효 필터 |
| oversold_rebound_0of4votes | 41 | -0.35 | 49 | 유효 필터 |
| rsi_pullback_range | 23 | -0.28 | 30 | 유효 필터 |
| adx_low_range | 19 | -0.25 | 47 | 유효 필터 |
| etf_outflow_not_heavy | 19 | -2.12 | 26 | 유효 필터 |
| rsi_below_range_max | 14 | -0.20 | 57 | 유효 필터 |
| bb_not_extended | 6 | +0.42 | 67 | dead weight 후보(알파 차단) |
| lsr_not_crowded | 4 | -2.44 | 0 | 유효 필터 |
| range_near_low | 1 | +1.52 | 100 | dead weight 후보(알파 차단) |
