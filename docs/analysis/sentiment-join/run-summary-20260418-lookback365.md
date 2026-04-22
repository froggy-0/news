# Sentiment Join Run Summary (2026-04-18, lookback=365)

## 실행 요약
- **파이프라인**: `SENTIMENT_JOIN_LOOKBACK_DAYS=365 make sentiment-join`
- **주요 단계**:
  - 소스 수집 완료
  - 로컬 Binance FAPI 선물 데이터 수집 전략 선택
  - ETF 공식 보유량 피처 준비 완료
  - 감성 품질 게이트 적용 완료
  - 소스 결합 완료 및 outlier 마스킹 수행
  - 결과 Parquet 파일을 R2에 업로드

## 경고/이슈 핵심
1. **outlier.detected**
   - `롤링 IQR 기준 이상값을 감지했습니다.`
   - `detect_outliers_rolling_iqr()`가 이전 30일 rolling IQR × 3 기준을 초과하는 값을 감지함
   - 이상값 발생 시 `stats.outlier_filter_applied` 이벤트에 따라 해당 수치 칼럼은 `NaN`으로 마스킹됨

2. **KPSS 보간 경고**
   - `InterpolationWarning: The test statistic is outside of the range of p-values available in the look-up table.`
   - `statsmodels` KPSS 검정의 p-value lookup table 범위를 벗어남
   - 실행은 계속되지만 통계 검정 입력이 극단값 또는 분포 특이 상태임을 의미함

3. **정상성 비통과**
   - `stats.stationarity_non_stationary` 경고 발생
   - ADF+KPSS 공동검정에서 시계열이 `stationary`로 판정되지 않음
   - 이 경우 해당 변수는 Granger 검정 gate에서 제외될 수 있음

4. **Granger 건너뜀**
   - `stats.granger_skipped | reason=insufficient_rows_for_granger`
   - `Granger` 최소 행 수 `180` 미달로 실행되지 않음
   - 현재 분석 데이터는 충분한 기간 또는 유효 행이 부족하다는 의미

5. **PCA 실행 미충족**
   - `stats.pca_insufficient_features` 경고 발생
   - PCA에 필요한 최소 feature/row 조건을 만족하지 못함

## 해석 포인트
- 이 로그는 `오류`가 아니라 통계 분석 파이프라인에서 데이터 상태를 평가하며 발생한 경고들임
- 핵심 문제는 `데이터 수/행 수 부족`, `정상성 미충족`, `극단값 존재`로 요약됨
- 이상값은 마스킹으로 처리되었고, 결과 파일 업로드는 정상 완료됨

## 참고
- 관련 코드 위치:
  - `src/morning_brief/analysis/sentiment_join/join.py`
  - `src/morning_brief/analysis/sentiment_join/statistical_tests.py`
