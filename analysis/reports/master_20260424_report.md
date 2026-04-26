# master_20260424.parquet 데이터 상태 보고서

## 1. 데이터 개요
- 파일: `analysis/data/master_20260424.parquet`
- 행/열: 178행, 50열
- 날짜 범위: 2025-10-26 ~ 2026-04-24
- 날짜 중복 건수: 0
- 전체 완전중복 행 수: 0
- 수치형 컬럼 수: 38, 불리언: 2, 범주/문자열: 10

## 2. 컬럼 목록과 타입
- `date`: `str`
- `news_sentiment_mean`: `float64`
- `news_sentiment_std`: `float64`
- `n_articles`: `Int64`
- `sentiment_status`: `str`
- `is_backfill_valid`: `bool`
- `ingest_validation_reason`: `object`
- `text_schema_version`: `str`
- `fng_value`: `Int64`
- `btc_quote_volume`: `float64`
- `btc_log_return`: `float64`
- `btc_return`: `float64`
- `usdkrw_log_return`: `float64`
- `usdkrw_return`: `float64`
- `funding_rate`: `float64`
- `open_interest_usd`: `float64`
- `btc_long_short_ratio`: `float64`
- `etf_total_btc`: `float64`
- `etf_total_aum_usd`: `float64`
- `etf_net_inflow_usd`: `float64`
- `vix`: `float64`
- `funding_source`: `str`
- `oi_source`: `str`
- `lsr_source`: `str`
- `etf_source`: `str`
- `vix_source`: `str`
- `funding_rate_lag1`: `float64`
- `oi_change_pct`: `float64`
- `oi_change_pct_lag1`: `float64`
- `btc_long_short_ratio_lag1`: `float64`
- `etf_net_inflow_usd_lag1`: `float64`
- `volume_change_pct`: `float64`
- `volume_change_pct_lag1`: `float64`
- `vix_lag1`: `float64`
- `news_sentiment_mean_lag1`: `float64`
- `fng_value_lag1`: `float64`
- `usdkrw_log_return_lag1`: `float64`
- `btc_direction_label`: `str`
- `btc_fwd_ret_1d`: `float64`
- `btc_fwd_ret_3d`: `float64`
- `btc_fwd_ret_7d`: `float64`
- `btc_fwd_vol_5d`: `float64`
- `btc_large_move_3d`: `Int64`
- `is_outlier`: `bool`
- `full_hybrid_index`: `float64`
- `core_hybrid_index`: `float64`
- `full_hybrid_index_score`: `float64`
- `core_hybrid_index_score`: `float64`
- `full_hybrid_index_score_lag1`: `float64`
- `core_hybrid_index_score_lag1`: `float64`

## 3. 샘플 레코드
```text
      date  news_sentiment_mean  news_sentiment_std  n_articles sentiment_status  fng_value  btc_return  usdkrw_return  funding_rate  open_interest_usd  btc_long_short_ratio  etf_net_inflow_usd   vix btc_direction_label  btc_fwd_ret_1d  btc_fwd_ret_3d  btc_fwd_ret_7d  full_hybrid_index  core_hybrid_index  full_hybrid_index_score  core_hybrid_index_score
2025-10-26             0.160033            0.657419         116               ok         40    0.026092            NaN      0.000093       8.849273e+09                1.4540                 NaN   NaN                  up       -0.003951       -0.040420       -0.035710                NaN                NaN                      NaN                      NaN
2025-10-27             0.329648            0.609266         311               ok         51   -0.003943            NaN      0.000273       9.358640e+09                1.2748                 NaN 15.79                down       -0.010654       -0.052026       -0.068218                NaN                NaN                      NaN                      NaN
2025-10-28             0.123816            0.627537         313               ok         50   -0.010597      -0.000488      0.000169       8.898620e+09                1.1744        6.398970e+07 16.42                down       -0.025815       -0.029578       -0.106457                NaN           4.445710                      NaN               100.000000
2025-10-29             0.033791            0.622345         297               ok         51   -0.025484      -0.008166      0.000086       8.554678e+09                1.4420        5.737024e+07 16.92                down       -0.015557        0.000698       -0.057388           3.317544           3.087026                79.789614                81.760685
2025-10-30            -0.079740            0.687760         299               ok         34   -0.015437       0.009852      0.000081       8.613584e+09                2.0423       -1.491580e+08 16.91                down        0.011794        0.020267       -0.066576           2.717696           2.606498                72.894977                75.309946
2025-10-31            -0.024986            0.679453         274               ok         29    0.011864      -0.001394      0.000202       8.433260e+09                2.6350       -3.084311e+08 17.44                  up        0.004461       -0.027986       -0.058895           0.735015           1.044316                50.106062                54.338826
2025-11-01             0.043385            0.665969         167               ok         33    0.004471       0.000000      0.000298       8.584262e+09                1.9709        0.000000e+00 17.44                  up        0.004012       -0.081340       -0.073336           0.116932           1.305523                43.001820                57.845331
2025-11-02             0.095660            0.677794         122               ok         37    0.004020       0.000000      0.000220       8.438022e+09                1.8752        0.000000e+00 17.44                  up       -0.036459       -0.062098       -0.054065           1.534883           2.087964                59.299731                68.349013
2025-11-03            -0.127482            0.693641         266               ok         42   -0.035803      -0.001186      0.000183       8.399510e+09                1.9189       -1.383511e+08 17.17                down       -0.048893       -0.050384       -0.005380           1.860166           2.467056                63.038528                73.438050
2025-11-04            -0.229559            0.704145         365               ok         21   -0.047717       0.006498      0.000221       8.247951e+09                2.2206       -1.771850e+08 19.00                down        0.023255        0.017984        0.015270           1.024060           1.903930                53.428340                65.878497
2025-11-05            -0.171366            0.693837         373               ok         23    0.023527       0.000833      0.000128       8.217528e+09                2.7566       -5.010747e+07 18.01                  up       -0.024745       -0.015250       -0.021708          -0.765268           0.208069                32.861821                43.112834
2025-11-06            -0.073638            0.672294         295               ok         27   -0.024442       0.005202      0.000164       8.710304e+09                2.3887       -3.653305e+08 19.50                down        0.019475        0.032778       -0.016455          -0.539504           0.071067                35.456753                41.273675
```

## 4. 데이터 품질 점검
- 결측치 비율 상위 20개
  - ingest_validation_reason: 100.00%
  - btc_fwd_ret_7d: 3.93%
  - usdkrw_log_return_lag1: 3.37%
  - usdkrw_log_return: 2.81%
  - full_hybrid_index_score_lag1: 2.81%
  - usdkrw_return: 2.81%
  - btc_fwd_vol_5d: 2.81%
  - full_hybrid_index_score: 2.25%
  - full_hybrid_index: 2.25%
  - core_hybrid_index_score_lag1: 1.69%
  - vix_lag1: 1.69%
  - btc_fwd_ret_3d: 1.69%
  - etf_net_inflow_usd_lag1: 1.69%
  - btc_large_move_3d: 1.69%
  - core_hybrid_index_score: 1.12%
  - oi_change_pct_lag1: 1.12%
  - etf_net_inflow_usd: 1.12%
  - vix: 1.12%
  - core_hybrid_index: 1.12%
  - volume_change_pct_lag1: 1.12%
- 고유값 수 하위 20개
  - etf_source: 1
  - vix_source: 1
  - sentiment_status: 1
  - is_backfill_valid: 1
  - ingest_validation_reason: 1
  - lsr_source: 1
  - oi_source: 1
  - funding_source: 1
  - text_schema_version: 2
  - is_outlier: 2
  - btc_direction_label: 2
  - btc_large_move_3d: 3
  - fng_value_lag1: 38
  - fng_value: 38
  - usdkrw_log_return_lag1: 118
  - etf_net_inflow_usd: 119
  - etf_net_inflow_usd_lag1: 119
  - usdkrw_return: 119
  - usdkrw_log_return: 119
  - vix_lag1: 120
- 불리언 컬럼 분포
  - is_backfill_valid: True=178
  - is_outlier: False=135, True=43

## 5. 주요 변수 분포
- `news_sentiment_mean`: count=178, mean=-0.101603, std=0.157301, min=-0.503306, p25=-0.214764, median=-0.099496, p75=0.00727692, max=0.329648
- `news_sentiment_std`: count=178, mean=0.61564, std=0.0545183, min=0.2271, p25=0.597743, median=0.620444, p75=0.645379, max=0.714748
- `n_articles`: count=178, mean=212.809, std=86.6905, min=12, p25=139.5, median=219.5, p75=267.5, max=424
- `fng_value`: count=178, mean=20.427, std=10.6446, min=5, p25=12, median=20, p75=26, max=61
- `btc_quote_volume`: count=178, mean=1.73008e+09, std=1.03307e+09, min=2.81321e+08, p25=1.12152e+09, median=1.53826e+09, p75=2.05781e+09, max=7.19875e+09
- `btc_return`: count=178, mean=-0.00193841, std=0.0264037, min=-0.140174, p25=-0.0154847, median=-0.00111719, p75=0.0114741, max=0.121927
- `usdkrw_return`: count=173, mean=0.000126324, std=0.00525528, min=-0.0238352, p25=-0.000973913, median=0, p75=0.00225464, max=0.0317361
- `funding_rate`: count=178, mean=6.48507e-05, std=0.000123561, min=-0.00028763, p25=-3.4725e-06, median=8.1065e-05, p75=0.000155572, max=0.00029782
- `open_interest_usd`: count=178, mean=7.4211e+09, std=1.34925e+09, min=5.10949e+09, p25=6.05883e+09, median=7.88032e+09, p75=8.617e+09, max=9.35864e+09
- `btc_long_short_ratio`: count=178, mean=1.90106, std=0.654172, min=0.601, p25=1.44725, median=1.8927, p75=2.32725, max=3.9925
- `etf_net_inflow_usd`: count=176, mean=-1.34885e+07, std=2.42942e+08, min=-1.54047e+09, p25=-6.90788e+07, median=0, p75=2.67708e+07, max=1.83449e+09
- `vix`: count=176, mean=19.302, std=4.25007, min=13.47, p25=16.09, median=17.935, p75=21.1625, max=31.05
- `btc_fwd_ret_1d`: count=177, mean=-0.00244858, std=0.0265634, min=-0.151026, p25=-0.0156197, median=-0.00119121, p75=0.0109913, max=0.115048
- `btc_fwd_ret_3d`: count=175, mean=-0.0073586, std=0.0429711, min=-0.224431, p25=-0.0334637, median=-0.0015169, p75=0.0248933, max=0.111501
- `btc_fwd_ret_7d`: count=171, mean=-0.016175, std=0.0611765, min=-0.296824, p25=-0.055483, median=-0.00799669, p75=0.0269667, max=0.098707
- `btc_fwd_vol_5d`: count=173, mean=0.0234212, std=0.0145883, min=0.00392234, p25=0.0157432, median=0.0212584, p75=0.0282516, max=0.0971604
- `full_hybrid_index_score`: count=174, mean=41.6578, std=16.9687, min=0, p25=30.0122, median=42.0729, p75=51.3571, max=100
- `core_hybrid_index_score`: count=176, mean=40.3197, std=17.4377, min=0, p25=26.7124, median=41.1782, p75=50.5299, max=100

## 6. 범주형 변수 분포
- `sentiment_status` top values
  - ok: 178
- `text_schema_version` top values
  - title_summary: 174
  - title_summary_whyitmatters: 4
- `funding_source` top values
  - supabase: 178
- `oi_source` top values
  - supabase: 178
- `lsr_source` top values
  - supabase: 178
- `etf_source` top values
  - unknown: 178
- `vix_source` top values
  - fred: 178
- `btc_direction_label` top values
  - down: 97
  - up: 81
- `ingest_validation_reason` top values
  - <NA>: 178

## 7. 상관관계 스냅샷
- `btc_fwd_ret_1d` 양의 상관 상위 5
  - btc_fwd_ret_3d: 0.560
  - btc_fwd_ret_7d: 0.387
  - volume_change_pct: 0.140
  - vix: 0.084
  - volume_change_pct_lag1: 0.076
- `btc_fwd_ret_1d` 음의 상관 상위 5
  - btc_fwd_vol_5d: -0.206
  - core_hybrid_index: -0.158
  - core_hybrid_index_score: -0.158
  - etf_total_aum_usd: -0.150
  - fng_value: -0.145
- `btc_fwd_ret_3d` 양의 상관 상위 5
  - btc_fwd_ret_7d: 0.626
  - btc_fwd_ret_1d: 0.560
  - vix: 0.151
  - vix_lag1: 0.126
  - volume_change_pct: 0.090
- `btc_fwd_ret_3d` 음의 상관 상위 5
  - btc_fwd_vol_5d: -0.287
  - etf_total_aum_usd: -0.258
  - open_interest_usd: -0.225
  - fng_value: -0.212
  - n_articles: -0.190
- `btc_fwd_ret_7d` 양의 상관 상위 5
  - btc_fwd_ret_3d: 0.626
  - btc_fwd_ret_1d: 0.387
  - vix_lag1: 0.227
  - vix: 0.212
  - etf_net_inflow_usd_lag1: 0.053
- `btc_fwd_ret_7d` 음의 상관 상위 5
  - etf_total_aum_usd: -0.402
  - open_interest_usd: -0.373
  - etf_total_btc: -0.300
  - btc_fwd_vol_5d: -0.295
  - fng_value: -0.293
- `full_hybrid_index_score` 양의 상관 상위 5
  - full_hybrid_index: 1.000
  - news_sentiment_mean_lag1: 0.827
  - core_hybrid_index: 0.819
  - core_hybrid_index_score: 0.819
  - fng_value_lag1: 0.784
- `full_hybrid_index_score` 음의 상관 상위 5
  - btc_long_short_ratio_lag1: -0.649
  - btc_long_short_ratio: -0.536
  - vix_lag1: -0.444
  - vix: -0.405
  - btc_quote_volume: -0.231
- `core_hybrid_index_score` 양의 상관 상위 5
  - core_hybrid_index: 1.000
  - fng_value_lag1: 0.872
  - fng_value: 0.851
  - full_hybrid_index: 0.819
  - full_hybrid_index_score: 0.819
- `core_hybrid_index_score` 음의 상관 상위 5
  - vix_lag1: -0.488
  - vix: -0.455
  - btc_fwd_ret_7d: -0.232
  - btc_long_short_ratio_lag1: -0.230
  - btc_fwd_vol_5d: -0.222

## 8. 데이터사이언티스트 관점 진단
- 표본 수가 178행으로 작아서 복잡한 예측 모델보다 규칙 기반/선형 모델/강한 정규화 모델이 적합합니다.
- 5% 초과 결측 컬럼이 1개 있으며, 주로 lag/forward 파생변수의 경계 결측일 가능성이 높습니다. 학습 시 누락 구간 처리 규칙을 고정해야 합니다.
- 날짜가 단조 증가라 시계열 분할에 유리합니다. 랜덤 셔플 검증보다 time-based split이 필요합니다.
- 미래 수익률(`btc_fwd_ret_*`)과 방향 라벨이 함께 있어 예측 타깃 정의는 명확합니다. 다만 feature 생성 시 미래값 누수 여부를 별도로 점검해야 합니다.
- 하이브리드 지수와 score/lags가 함께 저장돼 있어 신호 품질 모니터링과 백테스트에 적합한 구조입니다.
- `is_outlier` 비중은 24.16%입니다. 이상치 정의가 레이블 기반인지 feature 기반인지 문서화가 필요합니다.

## 9. 권장 후속 작업
- 학습용 feature set에서 미래정보(`btc_fwd_*`)를 완전히 제외한 baseline 테이블을 별도로 만들기
- lag 결측이 있는 첫 구간과 forward return 결측이 있는 마지막 구간을 명시적으로 분리하기
- 날짜 기준 rolling backtest(예: expanding window)로 신호 안정성 평가하기
- target별 상관이 높은 변수는 단순 상관 외에 시차(cross-correlation)와 regime별 성능으로 재검증하기
- 감성값과 시장변수 결합 지표(full/core hybrid index)의 산식 버전 관리 문서 추가하기