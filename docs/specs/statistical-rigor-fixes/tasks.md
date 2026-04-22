# Implementation Plan: 02 Statistical Rigor Fixes

## Overview

`docs/tasks/02-statistical-rigor-fixes.md` 기반. Task 01 완료(main 병합) 이후 진행하며
PR-A → PR-B → PR-C → PR-D 순서로 병합한다.

> **이미 완료 (main 기준)**: 2-4(ADF non-stationary gate + 차분 재시도), 2-5(BH-FDR 다중검정 보정),
> GRANGER_PAIRS lag1 전환, ADF_TARGETS lag1 추가, GRANGER_PAIRS_REVERSE + direction 필드.
> PR-C의 2-3(KPSS)만 미완료.

| PR | 항목 | 핵심 파일 |
|---|---|---|
| **PR-A** | 2-1 §3 백필 JSON 계약 정합성 + `_is_pipeline_file` | `scripts/backfill/uploader.py` |
| **PR-B** | 2-2 §8 이상치 NaN 마스킹 + 2-6 §5 쌍별 진단 기록 | `pipeline.py`, `statistical_tests.py` |
| **PR-C** | 2-3 §1 KPSS 공동검정 | `statistical_tests.py` |
| **PR-D** | 2-10 §6·7 효과크기·중복제거, 2-9 §2 lag 자동선택, 2-11 §10 의미론 | `statistical_tests.py`, `analytics_contract.py` |
| **PR-D*** | *2-7 §2 HAC 추론, *2-8 §9 잔차진단 (선택) | `statistical_tests.py` |

---

## Tasks

### PR-A: 백필 JSON 계약 정합성 (2-1 §3)

- [ ] 1. `build_minimal_brief_json` extra 필드 제거
  - [ ] 1.1 `scripts/backfill/uploader.py` — `build_minimal_brief_json` 반환 dict 정리
    - 제거: `signalSentimentStatus`, `signalSentiment`, `_backfillSource`,
      `_backfillGeneratedAt`, `textSchemaVersion`
    - `producer` 값: `"backfill/finbert"` → `"backfill.finbert"` (점 구분자, `startswith("backfill.")` 판별 기반)
    - 결과 JSON이 정확히 `_ANALYTICS_ALLOWED_KEYS` 8개 키만 포함해야 함
    - _Requirements: §3_
  - [ ] 1.2 `scripts/backfill/uploader.py` — 사이드카 업로드 스텝 추가 (진단 정보 보존)
    - `upload_brief` 내 본체 `put_object` 성공 후, `{key}.backfill-meta.json`에
      `_backfillSource`, `_backfillGeneratedAt`, `textSchemaVersion` 포함 dict를 별도 업로드
    - 사이드카 업로드 실패는 WARNING 로그만 남기고 반환값에 영향 없음 (본체 성공이 우선)
    - `UploadResults`에는 사이드카 카운트 미포함 (진단 전용)
    - _Requirements: §3 사이드카 권장_

- [ ] 2. `_is_pipeline_file` — producer 기반으로 전환
  - [ ] 2.1 `scripts/backfill/uploader.py` — `_is_pipeline_file` 로직 교체
    ```python
    def _is_pipeline_file(existing_json: dict) -> bool:
        # flat format (현행 및 신규 백필): producer 접두사로 판별
        producer = str(existing_json.get("producer", ""))
        if producer:
            return not producer.startswith("backfill.")
        # legacy meta-wrapped 백필: _backfillSource 존재 여부로 폴백
        if "_backfillSource" in existing_json.get("meta", {}):
            return False
        return True
    ```
    - 라이브 파이프라인 `producer="public_site.publish_public_brief"` → `True` (보호)
    - 신규 백필 `producer="backfill.finbert"` → `False` (덮어쓰기 허용)
    - 레거시 meta 래퍼 백필 (`meta._backfillSource` 존재) → `False` (폴백)
    - _Requirements: §3_

- [ ] 3. uploader 테스트 갱신
  - [ ] 3.1 `tests/backfill/test_uploader.py` 수정
    - `test_build_minimal_brief_json_schema`:
      - `signalSentimentStatus`, `signalSentiment`, `_backfillSource`, `textSchemaVersion` assert 제거
      - 8개 허용 키만 검증: `{"schemaVersion","producer","generatedAt","date","symbol","sentimentStatus","newsSentiment","_backfill"}`
      - **핵심 추가**: `validate_analytics_sentiment_payload(payload)["valid"] is True` 직접 검증
    - `test_is_pipeline_file_*`: `_backfillSource` 기반 → `producer` 기반 케이스로 교체
      - `{"producer": "public_site.publish_public_brief"}` → `True`
      - `{"producer": "backfill.finbert"}` → `False`
      - 레거시 `{"meta": {"_backfillSource": "..."}}` → `False` (폴백 검증 유지)
    - **Property A-1: `build_minimal_brief_json` 결과는 `validate_analytics_sentiment_payload`를 반드시 통과해야 한다**
    - _Requirements: §3_

- [ ] 4. Checkpoint — PR-A
  - `pytest -q tests/backfill/test_uploader.py`
  - 실패 시: extra 필드 누출, producer 값 오기재, 레거시 폴백 여부 순서로 점검

---

### PR-B: 이상치 time-index gap 처리 + 쌍별 진단 기록 (2-2 §8, 2-6 §5)

- [ ] 5. `pipeline.py:246` NaN 마스킹으로 전환
  - [ ] 5.1 `src/morning_brief/analysis/sentiment_join/pipeline.py` 수정
    - 기존: `analysis_df = master_df.loc[~master_df["is_outlier"]].reset_index(drop=True)`
    - 변경:
      ```python
      _NON_MASK_COLS = frozenset({
          "date", "is_outlier", "sentiment_status", "is_backfill_valid",
          "ingest_validation_reason", "btc_direction_label", "text_schema_version",
      })
      analysis_df = master_df.copy()
      _mask_cols = [c for c in analysis_df.columns if c not in _NON_MASK_COLS]
      analysis_df.loc[analysis_df["is_outlier"], _mask_cols] = np.nan
      ```
    - `masked_count = analysis_df["is_outlier"].sum()` (기존 `outlier_filtered_count`)
    - 로그 이벤트 `stats.outlier_filter_applied` 필드: `rows_before/rows_after` 대신
      `total_rows`, `masked_count`, `masked_ratio`로 변경
    - `validate_master`는 수치 컬럼에 `nullable=True`이므로 스키마 위반 없음
    - _Requirements: §8-A_

- [ ] 6. `_calendar_span` + `_max_consecutive_gap` 헬퍼 추가
  - [ ] 6.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py`에 헬퍼 추가
    ```python
    def _calendar_span(date_series: pd.Series) -> int:
        """날짜 시계열의 달력 span 일수 (max - min)."""
        dates = pd.to_datetime(date_series.dropna(), errors="coerce").dropna()
        return int((dates.max() - dates.min()).days) if len(dates) >= 2 else 0

    def _max_consecutive_gap(date_series: pd.Series) -> int:
        """연속 날짜 간 최대 갭 일수."""
        dates = pd.to_datetime(date_series.dropna(), errors="coerce").dropna().sort_values()
        if len(dates) < 2:
            return 0
        return int((dates.diff().dropna().dt.days).max())
    ```
    - _Requirements: §8_

- [ ] 7. `_run_granger` 진단 필드 추가
  - [ ] 7.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py` — `_run_granger` 반환 dict 확장
    ```python
    if "date" in df.columns:
        span_dates = df.loc[work.index, "date"]
        calendar_span = _calendar_span(span_dates)
        gap_days = _max_consecutive_gap(span_dates)
    else:
        calendar_span, gap_days = 0, 0

    entry: dict[str, Any] = {
        # 기존 필드 유지
        "predictor": predictor, "target": target, "lag": lag,
        "pvalue": pvalue, "pvalue_raw": pvalue, "significant": pvalue < 0.05,
        # 신규 진단 필드
        "effective_rows": len(work),
        "calendar_span_days": calendar_span,
        "max_consecutive_gap_days": gap_days,
    }
    if gap_days > 1:
        entry["warning"] = "non_contiguous_dates"
    ```
    - _Requirements: §5, §8_

- [ ] 8. gap 처리·진단 테스트 추가
  - [ ] 8.1 `tests/analysis/test_sentiment_join/test_join.py` — NaN 마스킹 동작 검증
    - outlier 행이 DataFrame에서 제거되지 않고 수치 컬럼만 NaN이 되는지 검증
    - **Property B-1: NaN 마스킹 후 `len(analysis_df) == len(master_df)`이어야 한다**
    - **Property B-2: is_outlier=True인 행의 `btc_log_return`은 NaN이어야 한다**
    - _Requirements: §8-A_
  - [ ] 8.2 `tests/analysis/test_sentiment_join/test_statistical_tests.py` — 진단 필드 검증
    - 불연속 날짜(gap > 1일) DataFrame에서 `warning: "non_contiguous_dates"` 플래그 검증
    - `effective_rows`, `calendar_span_days`, `max_consecutive_gap_days` 필드 존재 검증
    - **Property B-3: max_consecutive_gap_days > 1이면 `warning="non_contiguous_dates"`가 존재해야 한다**
    - **Property B-4: effective_rows는 dropna 이후 실제 검정에 투입된 행 수와 일치해야 한다**
    - _Requirements: §5, §8_

- [ ] 9. Checkpoint — PR-B
  - `pytest -q tests/analysis/test_sentiment_join/test_join.py tests/analysis/test_sentiment_join/test_statistical_tests.py`
  - 실패 시: NaN 마스킹 컬럼 범위, `date` 컬럼 인덱싱, `_max_consecutive_gap` 엣지케이스 순서로 점검

---

### PR-C: KPSS 공동검정 (2-3 §1)

> 2-4(ADF gate), 2-5(BH-FDR)은 이미 main 완료. PR-C는 KPSS 추가에 집중.

- [ ] 10. `_run_adf` → `_run_stationarity` 공동검정으로 교체
  - [ ] 10.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py` 수정
    - `_run_adf` 제거, `_run_stationarity` 신규 추가:
      ```python
      def _run_stationarity(series: pd.Series) -> dict[str, Any]:
          from statsmodels.tsa.stattools import adfuller, kpss
          s = series.dropna()
          adf_stat, adf_p, *_ = adfuller(s)
          kpss_stat, kpss_p, *_ = kpss(s, regression="c", nlags="auto")

          # 공동 판정 로직
          if adf_p < 0.05 and kpss_p > 0.05:
              conclusion = "stationary"
          elif adf_p >= 0.05 and kpss_p <= 0.05:
              conclusion = "non_stationary"
          elif adf_p < 0.05 and kpss_p <= 0.05:
              conclusion = "trend_stationary"   # 불일치: ADF만 통과
          else:
              conclusion = "difference_stationary"  # 불일치: KPSS만 통과

          return {
              "adf_statistic": float(adf_stat), "adf_pvalue": float(adf_p),
              "kpss_statistic": float(kpss_stat), "kpss_pvalue": float(kpss_p),
              "stationary": conclusion == "stationary",
              "conclusion": conclusion,
          }
      ```
    - `run_statistical_tests`의 ADF 루프: `_run_adf` → `_run_stationarity`, 결과 키를 `stationarity_results`로 rename
    - `_ensure_stationary` 내부: ADF 단독 호출 → `_run_stationarity` 호출, `stationary` 필드로 gate
    - 비정상 결론(`non_stationary`, `trend_stationary`, `difference_stationary`)은 차분 재시도 대상
    - _Requirements: §1 KPSS_
  - [ ] 10.2 `__all__` 에 `_run_stationarity` 추가, `_run_adf` 제거
    - _Requirements: §1 KPSS_

- [ ] 11. KPSS 공동검정 테스트 추가·갱신
  - [ ] 11.1 `tests/analysis/test_sentiment_join/test_statistical_tests.py` 수정
    - `_run_adf` monkeypatch 대상을 `_run_stationarity`로 전환 (기존 테스트 시그니처 교체)
    - 신규 케이스:
      - ADF p<0.05 + KPSS p>0.05 → `conclusion="stationary"`, `stationary=True`
      - ADF p>=0.05 + KPSS p<=0.05 → `conclusion="non_stationary"`, Granger skip 확인
      - 불일치(trend_stationary) → `stationary=False`, Granger 차단
    - `run_statistical_tests` 반환 dict에 `stationarity_results` 키 존재 검증 (`adf` 키 제거 확인)
    - **Property C-1: ADF와 KPSS가 불일치하면 `stationary=False`이어야 한다**
    - **Property C-2: `stationary=False`인 predictor는 어떤 lag에도 Granger 결과를 생성하지 않아야 한다**
    - _Requirements: §1 KPSS_

- [ ] 12. Checkpoint — PR-C
  - `pytest -q tests/analysis/test_sentiment_join/test_statistical_tests.py`
  - 실패 시: `statsmodels kpss` 임포트 경로, `nlags="auto"` 버전 호환성, 기존 monkeypatch 시그니처 불일치 순서로 점검

---

### PR-D: 효과 크기·재현성·의미론 (2-10, 2-9, 2-11)

- [ ] 13. `_run_granger_all_lags` 리팩토링 (2-10 §6·§7)
  - [ ] 13.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py` 수정
    - `_run_granger` 기존 단일 lag 함수를 `_run_granger_all_lags` 로 교체:
      ```python
      def _run_granger_all_lags(
          df: pd.DataFrame,
          predictor: str,
          target: str,
          max_lag: int = 3,
      ) -> list[dict[str, Any]] | None:
          """grangercausalitytests 단 1회 호출 → lag 1…max_lag 전체 결과 반환."""
          # ... 정상성 gate (_ensure_stationary) 유지 ...
          result = grangercausalitytests(work, maxlag=max_lag, verbose=False)
          return [
              {
                  "predictor": predictor, "target": target, "lag": lag,
                  "pvalue": float(result[lag][0]["ssr_ftest"][1]),
                  "pvalue_raw": float(result[lag][0]["ssr_ftest"][1]),
                  "f_statistic": float(result[lag][0]["ssr_ftest"][0]),
                  "df_num": int(result[lag][0]["ssr_ftest"][2]),
                  "df_denom": int(result[lag][0]["ssr_ftest"][3]),
                  "effective_rows": len(work),
                  "significant": float(result[lag][0]["ssr_ftest"][1]) < 0.05,
              }
              for lag in range(1, max_lag + 1)
          ]
      ```
    - `run_statistical_tests` 내부 루프를 `_run_granger` 반복 호출 → `_run_granger_all_lags` 단일 호출로 교체
    - 반환 리스트를 `extend`로 누적 (기존 `append` 대신)
    - 결과 메타데이터에 `"inference": "ssr_ftest_ols"` 추가
    - _Requirements: §6, §7_

- [ ] 14. VAR 기반 최적 lag 선택 추가 (2-9 §2)
  - [ ] 14.1 `src/morning_brief/analysis/sentiment_join/statistical_tests.py`에 `_select_optimal_lag` 추가
    ```python
    def _select_optimal_lag(work: pd.DataFrame, max_lag: int = 5) -> int:
        from statsmodels.tsa.vector_ar.var_model import VAR
        try:
            model = VAR(work.astype(float))
            res = model.select_order(maxlags=min(max_lag, len(work) // 10))
            return max(int(res.aic), 1)
        except Exception:
            return 1  # 실패 시 lag-1 폴백
    ```
    - `_run_granger_all_lags` 내부에서 `optimal_lag = _select_optimal_lag(work)` 호출
    - 각 lag entry에 `"optimal_lag": optimal_lag`, `"granger_primary": lag == optimal_lag` 필드 추가
    - 전체 lag 결과를 `granger_all_lags`로 보관하되, 메인 `granger` 리스트에도 함께 포함
    - _Requirements: §2 lag auto-select_

- [ ] 15. `build_analytics_sentiment_payload` `_backfill` 파라미터화 (2-11 §10)
  - [ ] 15.1 `src/morning_brief/data/storage/analytics_contract.py` 수정
    - 함수 시그니처 변경:
      ```python
      def build_analytics_sentiment_payload(
          *, symbol: str, run_date: str, full_payload: dict[str, Any],
          is_backfill: bool = False,  # 라이브 파이프라인 기본값 False
      ) -> AnalyticsSentimentPayload:
      ```
    - 내부: `_backfill=True` 하드코딩 → `_backfill=is_backfill`
    - `validate_analytics_sentiment_payload` 검증부 수정:
      ```python
      # 기존: if not payload.get("_backfill"):
      if "_backfill" not in payload:  # bool 값에 무관하게 키 존재 여부만 확인
          return AnalyticsValidationResult(valid=False, reason="missing_backfill_marker")
      ```
    - 호출부(`public_site.py` 등)는 기본값(`is_backfill=False`)이므로 코드 변경 불필요
    - _Requirements: §10_

- [x] 16. PR-D 테스트 추가·갱신
  - [x] 16.1 `tests/analysis/test_sentiment_join/test_statistical_tests.py` 수정
    - `_run_granger_all_lags` 단일 호출이 lag 1·2·3 결과 모두 반환하는지 검증
    - 각 entry에 `f_statistic`, `df_num`, `df_denom`, `optimal_lag`, `granger_primary` 존재 확인
    - `run_statistical_tests` 결과 메타에 `inference: "ssr_ftest_ols"` 존재 확인
    - **Property D-1: 동일 (predictor, target) 쌍의 `grangercausalitytests`는 `maxlag=3`으로 단 1회만 호출되어야 한다**
    - **Property D-2: `granger_primary=True`인 entry는 각 (predictor, target) 방향당 정확히 1개여야 한다**
    - _Requirements: §6, §7, §2_
  - [x] 16.2 `tests/data/test_analytics_contract.py`에 `_backfill` 파라미터화 테스트 추가
    - `build_analytics_sentiment_payload(is_backfill=False)` → `payload["_backfill"] is False` 검증
    - `build_analytics_sentiment_payload(is_backfill=True)` → `payload["_backfill"] is True` 검증
    - `validate_analytics_sentiment_payload` 가 `_backfill=False`도 통과하는지 검증
    - **Property D-3: `_backfill` 필드가 존재하면 값에 무관하게 `missing_backfill_marker` 오류가 발생하지 않아야 한다**
    - _Requirements: §10_

- [ ] 17. *HAC/로버스트 추론 메타데이터 기록 (2-7, 선택)
  - [ ] 17.1 `_run_granger_all_lags` 결과 메타에 추론 방식 라벨 기록
    - 각 entry에 `"inference": "ssr_ftest_ols"` 추가 (task 13에서 이미 부분 포함)
    - VAR 수동 피팅 + `wald_test(..., cov_type="HAC")` 는 후속 PR로 분리
    - _Requirements: §2 HAC_

- [ ] 18. *잔차 진단 요약 (2-8, 선택)
  - [ ] 18.1 `run_statistical_tests` 반환 dict에 `residual_diagnostics` 추가
    ```python
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
    btc_series = df["btc_log_return"].dropna()
    results["residual_diagnostics"] = {
        "ljung_box_lag10_p": float(acorr_ljungbox(btc_series, lags=[10])["lb_pvalue"].iloc[0]),
        "arch_lm_lag5_p": float(het_arch(btc_series, nlags=5)[1]),
    }
    ```
    - Granger 결과가 존재하는 경우에만 계산 (btc_log_return 30행 이상 전제)
    - _Requirements: §9_

- [x] 19. Checkpoint — PR-D (최종)
  - `make check` (fmt + lint + test + typecheck)
  - 수동 검증: Granger entry에 `f_statistic`, `optimal_lag`, `granger_primary`, `pvalue_adjusted` 모두 존재
  - 실패 시: `VAR.select_order` 버전 호환(`maxlags` 하한), `_backfill=False` validator 통과, KPSS 임포트 순서로 점검
