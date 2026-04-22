# Sentiment Join Run Issues

- **Date:** 2026-04-18
- **File:** `data/sentiment_join/master_20260417.parquet`
- **Rows:** 100
- **Columns:** 33
- **Problem summary:** 현재 실행에서 발견된 모든 주요 경고/문제 사항을 핵심만 추렸습니다.

## 1. Rolling IQR 이상값 감지 (`outlier.detected`)
- 발생 경고: `롤링 IQR 기준 이상값을 감지했습니다.`
- 원인: `src/morning_brief/analysis/sentiment_join/join.py`의 `detect_outliers_rolling_iqr()`가 이전 30개 행 기준 rolling IQR × 3을 초과하는 값을 발견함.
- 감지된 컬럼과 행 수:
  - `usdkrw_return`: 4개
  - `open_interest_usd`: 4개
  - `fng_value`: 4개
  - `btc_return`: 2개
  - `etf_net_inflow_usd`: 2개
  - `btc_quote_volume`: 2개
  - `funding_rate`: 1개
- 대표 날짜: `2025-12-24`, `2026-01-14`, `2026-01-15`, `2026-01-16`, `2026-01-19`, `2026-01-26`, `2026-02-05`, `2026-02-06`, `2026-03-03`, `2026-04-14`, `2026-04-15`, `2026-04-16`, `2026-04-17`

## 2. 이상값 마스킹 완료 (`stats.outlier_filter_applied`)
- 로그: `통계 분석용 이상값을 NaN으로 마스킹했습니다. (행은 유지)`
- 의미: 감지된 이상값 행은 제거되지 않았고, 분석용 수치 컬럼만 `NaN` 처리되었음.
- 대상: `analysis_df`에서 `is_outlier=True`인 행 전체에 대해 수치 컬럼이 마스킹됨.

## 3. KPSS 보간 경고 (`InterpolationWarning`)
- 발생 위치: `src/morning_brief/analysis/sentiment_join/statistical_tests.py:111`
- 경고 내용: `test statistic is outside of the range of p-values available in the look-up table.`
- 원인: `statsmodels` KPSS 검정이 극단적인 통계량 값을 얻었고, 내부 p-value 테이블 범위를 벗어났음.
- 영향: p-value 계산에 대한 경고일 뿐, 파이프라인 자체 오류는 아님.

## 4. 정상성 비통과 경고 (`stats.stationarity_non_stationary`)
- 로그: `시계열이 정상성 조건을 만족하지 않습니다.`
- 원인: ADF+KPSS 공동검정에서 다음 중 하나 이상이 성립하지 않음.
  - `adf_p < 0.05` and `kpss_p > 0.05`
- 결과: 해당 시계열은 `stationary=False`로 간주되어 이후 Granger 검정 gate에서 차단될 수 있음.

## 5. Granger 검정 건너뜀 (`stats.granger_skipped`)
- 로그: `reason=insufficient_rows_for_granger`
- 원인: Granger 검정에 필요한 최소 행 수 `180`에 미달함.
- 실제: 현재 파일은 `100`행.
- 의미: Granger 검정은 설계대로 실행되지 않았으며, 이는 데이터 수 제한으로 인한 정상적 건너뛰기임.

## 6. Statsmodels 내부 수치 경고
- 경고: `invalid value encountered in scalar divide`
- 발생 위치: `statsmodels/regression/linear_model.py`
- 원인: Granger 분석 중 분모가 0 또는 NaN에 가까운 경우가 발생.
- 영향: 수치적 한계 경고이며, 데이터 특성 또는 결측/동일 값 때문에 생김.

## 7. 파케이 파일 상태
- 출력 파일: `data/sentiment_join/master_20260417.parquet`
- 메타: `btc_source=binance`, `ffill_days=0`
- `sentiment_join_stats`에 `outlier_filtered_count=13`, `granger_eligible_rows=100`, `granger_executed=false` 기록됨.
- 특이 사항: `hybrid_index` 컬럼은 null이 많은 상태(`82` null)이며, 일부 선물/ETF 컬럼에 결측이 많음.

## 8. 핵심 결론
- 현재 가장 명확한 문제는 `데이터 행 수 부족으로 Granger 검정이 실행되지 않은 점`과 `여러 시계열이 정상성 검정을 통과하지 못한 점`.
- `outlier.detected`와 `stats.outlier_filter_applied`는 파이프라인 동작에 따른 정상 경고/처리이다.
- `InterpolationWarning`과 `invalid value encountered in scalar divide`는 통계 라이브러리의 수치적 한계 경고로, 입력 데이터가 극단값 또는 결측에 가까울 때 발생함.
