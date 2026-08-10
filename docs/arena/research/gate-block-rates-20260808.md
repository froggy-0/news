# 게이트 차단률 진단 (2026-08-08)

- frames: 3966 (2024-07-13 ~ 2026-08-07), forward_bars=6


## macd_momentum

- long 신호: 390/3966 bars (9.8%)


### 조건별 차단 빈도 (flat bar 기준)

| 조건 | 실패(veto) 횟수 |
|---|---|
| macd_hist_increasing | 1988 |
| macd_hist_positive | 1941 |
| not_risk_off | 1171 |
| bb_width_sufficient | 1030 |
| adx_sufficient | 884 |
| rsi_below_long_max | 94 |

### near-miss 분석 (유일 차단자 → 이후 수익 분포)

| 유일 차단 조건 | near-miss 수 | 평균 이후수익% | 승률% | 판정 |
|---|---|---|---|---|
| macd_hist_increasing | 524 | +0.02 | 46 | dead weight 후보(알파 차단) |
| macd_hist_positive | 253 | +0.03 | 53 | dead weight 후보(알파 차단) |
| not_risk_off | 175 | -0.39 | 49 | 유효 필터 |
| bb_width_sufficient | 155 | -0.06 | 49 | 유효 필터 |
| adx_sufficient | 106 | +0.13 | 55 | dead weight 후보(알파 차단) |
| rsi_below_long_max | 14 | -0.04 | 36 | 유효 필터 |
