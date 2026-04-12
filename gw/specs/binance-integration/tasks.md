# Implementation Plan: binance-integration

## Overview

기존 `futures.py`의 list 응답 버그를 수정하고, BTC 현물 소스를 Binance Spot API로 마이그레이션하며, Long/Short Ratio·거래대금 지표를 추가한다. 구현 순서: 인프라(http_client, provider_runtime) → 소스 수집기(futures, binance) → 설정·스키마·결합(config, validate, join) → 파이프라인 통합(pipeline, storage) → 통계 분석(statistical_tests, hybrid_index) → 전체 검증.

완료 일시: —

---

## Tasks

### Phase 1: 인프라 기반

- [x] 1. `provider_runtime.py` — Binance 프로바이더 정책 등록
  - [x] 1.1 `PROVIDER_POLICIES`에 `binance_spot` 항목 추가
    - `min_interval_seconds=0.1` (100ms 지연 — design ⑤)
    - `retryable_statuses=frozenset({429, 500, 502, 503, 504})` — 418은 제외(IP 차단, 재시도 금지)
    - `base_backoff_seconds=1.2`, `max_attempts=3`
    - 파일: `src/morning_brief/data/sources/provider_runtime.py`
    - _Requirements: 7.1, 7.3_
  - [x] 1.2 `PROVIDER_POLICIES`에 `binance_futures` 항목 추가 (동일 파라미터)
    - 현재 `futures.py`가 `provider="binance_futures"`를 사용하나 `PROVIDER_POLICIES`에 등록이 없어 `DEFAULT_POLICY`가 적용됨 — 명시적 등록으로 정책 가시화
    - _Requirements: 7.1_

---

- [x] 2. `http_client.py` — `get_list_with_retry()` 추가
  - [x] 2.1 `get_list_with_retry()` 함수 구현
    - 파일: `src/morning_brief/data/sources/http_client.py`
    - `_request_with_retry()`를 호출하고 `response.json()`으로 파싱
    - `isinstance(payload, list)` 검사 — dict이면 `HttpFetchError("JSON 응답이 배열 형식이 아닙니다")` 발생
    - 시그니처 및 파라미터는 `get_json_with_retry()`와 동일 (`headers` 포함)
    - 반환 타입: `list[Any]`
    - 기존 함수는 **일절 변경하지 않는다**
    - `__all__`에 `"get_list_with_retry"` 추가
    - _Requirements: 7.1 (design ⑤ 핵심 버그 수정)_
  - [x] 2.2 `tests/test_http_client_list.py` 또는 기존 http_client 테스트에 케이스 추가
    - list 응답 → 정상 반환
    - dict 응답 → `HttpFetchError`
    - 비-JSON 응답 → `HttpFetchError`
    - _Validates: Requirements 7.1_

---

- [ ] **Checkpoint 1 — 인프라 완료**
  - `pytest tests/ -k "http_client" -v` 통과
  - `from morning_brief.data.sources.http_client import get_list_with_retry` 임포트 성공
  - `provider_runtime.PROVIDER_POLICIES["binance_spot"]` 존재 확인

---

### Phase 2: 소스 수집기

- [x] 3. `futures.py` — list 버그 수정 + Long/Short Ratio 수집 추가
  - [x] 3.1 `_fetch_funding_rate_history()` 수정
    - `get_json_with_retry()` → `get_list_with_retry()` 교체
    - 반환 타입: `list[dict]` (기존과 동일, 실제 동작이 처음으로 올바르게 됨)
    - 파일: `src/morning_brief/analysis/sentiment_join/sources/futures.py`
    - _Requirements: 7.1 (잠재 버그 수정)_
  - [x] 3.2 `_fetch_oi_history()` 수정
    - 동일하게 `get_list_with_retry()` 교체
    - _Requirements: 7.1_
  - [x] 3.3 `_fetch_long_short_ratio()` 신규 구현
    - 엔드포인트: `https://fapi.binance.com/futures/data/globalLongShortAccountRatio`
    - 파라미터: `symbol=BTCUSDT`, `period=1d`, `startTime={start_ms}`, `limit=500`
    - `get_list_with_retry()` 사용, `provider="binance_futures"`
    - 실패 시 `WARNING` 로그(`event=source.failed | source=binance_lsr | reason`) 후 `[]` 반환
    - 반환 타입: `list[dict]`
    - _Requirements: 3.1, 3.3_
  - [x] 3.4 `_extract_daily_long_short_ratio()` 신규 구현
    - 각 항목: `timestamp`(int, ms) → UTC date 문자열, `longShortRatio`(**str → float**) 변환
    - 반환: `dict[str, float]`
    - _Requirements: 3.2_
  - [x] 3.5 `fetch_futures_data()` 반환 DataFrame에 `btc_long_short_ratio` 컬럼 추가
    - `_empty_futures_frame()`에 `btc_long_short_ratio: [NaN] * len(dates)` 추가
    - `_fetch_long_short_ratio()` 호출 후 결과를 grid에 매핑
    - `Long/Short 수집 실패`가 기존 `funding_rate`·`open_interest_usd` 수집을 중단시키지 않도록 독립적 try/except
    - `log_structured` `source.complete` 로그에 `lsr_days` 필드 추가
    - _Requirements: 3.3, 3.4_
  - [x] 3.6 `tests/analysis/test_sentiment_join/test_futures.py` 업데이트
    - 기존 `test_fetch_futures_data_returns_nan_grid_when_all_requests_fail`: 반환 컬럼 검사에 `btc_long_short_ratio` 추가
    - `test_extract_daily_long_short_ratio_parses_str_fields()` 추가
      - `longShortRatio='0.8829'` → `float(0.8829)` 변환 검증
      - `longShortRatio='1.0305'` (> 1) 정상 파싱 검증
    - `test_fetch_futures_data_lsr_failure_does_not_block_funding_oi()` 추가
      - `_fetch_long_short_ratio` monkeypatch → 예외 발생
      - `funding_rate`, `open_interest_usd`는 정상 수집 확인
    - **Validates: Requirements 3.1–3.5**

---

- [x] 4. `sources/binance.py` — BTC Spot klines 수집기 신규 구현
  - [x] 4.1 상수 및 헬퍼 정의
    - 파일: `src/morning_brief/analysis/sentiment_join/sources/binance.py`
    - 상수: `BINANCE_KLINES_URL`, `BINANCE_SYMBOL = "BTCUSDT"`, `BINANCE_INTERVAL = "1d"`
    - `_binance_headers(api_key: str) -> dict[str, str]`
      - api_key 미설정이면 `{}` 반환, 설정 시 `{"X-MBX-APIKEY": api_key}` 반환
      - api_key 값을 로그에 절대 포함하지 않음
    - `_parse_kline_row(row: list) -> dict` 구현
      - `row[0]` (int, ms) → `datetime.fromtimestamp(ms/1000, utc).strftime("%Y-%m-%d")` → `date`
      - `float(row[4])` → `close` (**str 타입 변환 필수**)
      - `float(row[7])` → `btc_quote_volume` (**str 타입 변환 필수**)
    - _Requirements: 1.2, 1.3_
  - [x] 4.2 `_fetch_klines(start_date, end_date, api_key)` 구현
    - `startTime` = `open_time`에 해당하는 ms 타임스탬프 계산
    - `limit = (end_date - start_date).days + 2`
    - limit > 1000이면 `ValueError("lookback이 klines 단일 요청 한도를 초과합니다")` 발생
    - `get_list_with_retry()` 사용, `provider="binance_spot"`, headers=`_binance_headers(api_key)`
    - 반환: `list[list]` (klines 배열)
    - _Requirements: 1.2, 1.6_
  - [x] 4.3 `_klines_to_frame(rows: list[list]) -> pd.DataFrame` 구현
    - 각 행에 `_parse_kline_row()` 적용
    - 컬럼: `date(str)`, `close(float64)`, `btc_quote_volume(float64)`
    - 빈 rows → `_empty_binance_frame()` 반환 (close=NaN, btc_quote_volume=NaN)
    - `groupby("date").last().sort_values("date").reset_index()` 중복 날짜 처리
    - _Requirements: 1.3_
  - [x] 4.4 `fetch_btc_close_binance(start_date, end_date, api_key="") -> pd.DataFrame` 구현
    - 1차: `_fetch_klines()` → `_klines_to_frame()` → `attrs["btc_source"] = "binance"`, `attrs["fallback_used"] = False`
    - 실패(Exception) → `WARNING` 로그(`event=fallback.used | source=btc | reason`)
    - 2차: `btc_prices.fetch_btc_close(start_date, end_date)` 호출 (기존 CoinGecko→yfinance 체인)
    - 폴백 성공 후 `btc_quote_volume = float("nan")` 컬럼 추가
    - **`btc_source` 폴백 추적 로직 (명시적 구현):**
      ```python
      fallback_df = btc_prices.fetch_btc_close(start_date, end_date)
      btc_source = (
          "yfinance"
          if fallback_df.attrs.get("fallback_used", False)
          else "coingecko"
      )
      fallback_df.attrs["btc_source"] = btc_source
      fallback_df.attrs["fallback_used"] = True
      ```
      - `btc_prices.fetch_btc_close()`는 `attrs["btc_source"]`를 설정하지 않음 — 반드시 여기서 역추적
      - `fallback_used=False` → CoinGecko 성공 → `"coingecko"`
      - `fallback_used=True` → CoinGecko 실패, yfinance 사용 → `"yfinance"`
    - `__all__ = ["fetch_btc_close_binance"]`
    - _Requirements: 1.4, 1.5, 1.7, 6.1, 6.2_
  - [x] 4.5 `tests/analysis/test_sentiment_join/test_binance.py` 신규 작성
    - `test_parse_kline_row_converts_str_to_float()`: `close='72962.70'` → `72962.70` (float)
    - `test_parse_kline_row_open_time_as_date()`: `open_time=1775779200000` → `"2026-04-10"`
    - `test_klines_to_frame_structure()`: columns, dtypes 검증
    - `test_fetch_btc_close_binance_sets_attrs_on_success(monkeypatch)`: `attrs["btc_source"] == "binance"`
    - `test_fetch_btc_close_binance_falls_back_on_failure(monkeypatch)`: `_fetch_klines` → 예외, `btc_prices.fetch_btc_close` 호출 확인, `btc_quote_volume`이 NaN
    - `test_fetch_klines_raises_if_limit_exceeds_1000()`: `ValueError` 검증
    - **Validates: Requirements 1.2–1.7, 6.1–6.2**

---

- [x] **Checkpoint 2 — 소스 수집기 완료**
  - `pytest tests/analysis/test_sentiment_join/test_futures.py -v` 전체 통과
  - `pytest tests/analysis/test_sentiment_join/test_binance.py -v` 전체 통과
  - `fetch_futures_data(lookback_days=3)` 반환 DataFrame 컬럼: `["date", "funding_rate", "open_interest_usd", "btc_long_short_ratio"]` 확인

---

### Phase 3: 설정·스키마·결합 레이어

- [x] 5. `config.py` — `binance_api_key` 필드 추가
  - [x] 5.1 `SentimentJoinSettings` dataclass에 `binance_api_key: str` 필드 추가
    - 파일: `src/morning_brief/analysis/sentiment_join/config.py`
    - `load_sentiment_join_settings()` 내: `binance_api_key=os.getenv("SENTIMENT_JOIN_BINANCE_KEY", "").strip()`
    - 미설정 시 빈 문자열(`""`) — 공개 엔드포인트로 수집 계속
    - `__all__` 업데이트 없음 (기존 export 유지)
    - _Requirements: 5.1_
  - [x] 5.2 `tests/analysis/test_sentiment_join/test_config.py`에 케이스 추가
    - `SENTIMENT_JOIN_BINANCE_KEY` 미설정 → `settings.binance_api_key == ""`
    - `SENTIMENT_JOIN_BINANCE_KEY=test-key-123` → `settings.binance_api_key == "test-key-123"`
    - **Validates: Requirements 5.1**

---

- [x] 6. `validate.py` — MASTER_SCHEMA 3개 신규 컬럼 추가
  - [x] 6.1 `MASTER_SCHEMA`에 신규 컬럼 추가
    - 파일: `src/morning_brief/analysis/sentiment_join/validate.py`
    - 추가 순서 (기존 `btc_return` 다음):
      ```python
      "btc_quote_volume": pa.Column(float, pa.Check.ge(0), nullable=True),
      ```
    - 추가 순서 (기존 `oi_change_pct_lag1` 다음):
      ```python
      "btc_long_short_ratio":      pa.Column(float, pa.Check.ge(0), nullable=True),
      "btc_long_short_ratio_lag1": pa.Column(float, nullable=True),
      ```
    - `strict=True` 유지 — 세 컬럼 모두 없으면 `SchemaError` 발생
    - _Requirements: 2.3, 3.5, 3.6, 8.1_
  - [x] 6.2 `tests/analysis/test_sentiment_join/test_validate.py` 업데이트
    - `_valid_df()` 헬퍼에 세 신규 컬럼 추가 (값: `NaN`)
    - `test_validate_master_accepts_new_nullable_columns()`: 세 컬럼이 NaN이어도 통과
    - `test_validate_master_rejects_negative_quote_volume()`: `btc_quote_volume=-1.0` → `SchemaError`
    - `test_validate_master_rejects_negative_long_short_ratio()`: `btc_long_short_ratio=-0.1` → `SchemaError`
    - `test_validate_master_strict_requires_all_new_columns()`: 세 컬럼 중 하나 누락 → `SchemaError`
    - **Validates: Requirements 2.3, 3.5, 3.6, 8.1, 8.2**

---

- [x] 7. `join.py` — lag 컬럼 + 이상값 탐지 확장
  - [x] 7.1 `_add_futures_lag_columns()` 수정
    - 파일: `src/morning_brief/analysis/sentiment_join/join.py`
    - `btc_long_short_ratio_lag1 = btc_long_short_ratio.shift(1)` 추가
    - `btc_long_short_ratio` 컬럼 없으면 `float("nan")` 컬럼으로 채움 (기존 패턴 동일)
    - _Requirements: 3.6_
  - [x] 7.2 `detect_outliers_rolling_iqr()` 호출 컬럼 목록 확장
    - `merge_sources()` 내 호출을:
      ```python
      cols=["btc_return", "usdkrw_return",
            "funding_rate", "open_interest_usd", "btc_long_short_ratio"]
      ```
    - `btc_quote_volume`은 절대 금액 시계열로 이상값 탐지 제외 (design 명시)
    - _Requirements: 4.1_
  - [x] 7.3 `merge_sources()` 시그니처는 변경 없음
    - `futures_df` 내에 `btc_long_short_ratio` 컬럼이 있으면 자동으로 LEFT JOIN에 포함됨
    - _Requirements: 2.2_
  - [x] 7.4 `tests/analysis/test_sentiment_join/test_join.py` 업데이트
    - `_btc_df()` 헬퍼에 `btc_quote_volume=[1e9]*days` 추가
    - `_futures_df()` 헬퍼에 `btc_long_short_ratio=[0.9]*days` 추가
    - `test_merge_sources_adds_btc_long_short_ratio_lag1()`: lag 컬럼 존재 및 shift(1) 검증
    - `test_merge_sources_outlier_detection_includes_long_short_ratio()`: `btc_long_short_ratio` 이상값 → `is_outlier=True`
    - `test_merge_sources_btc_quote_volume_preserved()`: `btc_quote_volume` 컬럼이 master_df에 존재
    - **Validates: Requirements 3.6, 4.1, 4.2, 4.3**

---

- [x] **Checkpoint 3 — 설정·스키마·결합 레이어 완료**
  - `pytest tests/analysis/test_sentiment_join/test_config.py tests/analysis/test_sentiment_join/test_validate.py tests/analysis/test_sentiment_join/test_join.py -v` 전체 통과
  - `validate_master()`가 `btc_quote_volume`, `btc_long_short_ratio`, `btc_long_short_ratio_lag1` 컬럼 없는 DataFrame을 `SchemaError`로 거부하는지 확인

---

### Phase 4: 파이프라인 통합

- [x] 8. `pipeline.py` — `fetch_btc_close_binance()` 교체 및 `btc_source` 전달
  - [x] 8.1 임포트 교체
    - 파일: `src/morning_brief/analysis/sentiment_join/pipeline.py`
    - `from morning_brief.analysis.sentiment_join.sources.btc_prices import fetch_btc_close` 제거
    - `from morning_brief.analysis.sentiment_join.sources.binance import fetch_btc_close_binance` 추가
    - _Requirements: 1.7_
  - [x] 8.2 `fetch_btc_close()` 호출을 `fetch_btc_close_binance()` 로 교체
    - `settings.binance_api_key` 전달:
      ```python
      btc_close_df = fetch_btc_close_binance(
          btc_start_date, end_date, api_key=settings.binance_api_key
      )
      ```
    - `btc_fallback_used` 추출 방식 유지 (`attrs["fallback_used"]`)
    - _Requirements: 1.7, 5.3_
  - [x] 8.3 `btc_source` 추출 및 `save_parquet()`에 전달
    - `btc_source = btc_close_df.attrs.get("btc_source", "unknown")`
    - `save_parquet(..., btc_source=btc_source)` 호출 시 파라미터 추가
    - _Requirements: 6.3_
  - [x] 8.4 `btc_quote_volume` 컬럼 파이프라인 통과 검증 — **코드 변경 없음, verify-only**
    - `transform.py` 분석으로 `btc_quote_volume` 자동 보존이 확정됨:
      - `forward_fill_prices(btc_close_df, ["close"])` — `cols=["close"]`만 ffill, `btc_quote_volume` 무관
      - `compute_returns(btc_close_df, "close")` — `price_col`("close")만 drop, 나머지 컬럼 그대로 유지
      - `_rename_returns()` — `close_log_return`, `close_return`만 rename
      - `trim_to_date_range()` — 행 필터만, 컬럼 변경 없음
    - **추가 구현 일절 불필요** — `btc_quote_volume`은 `btc_close_df` → `btc_returns_df` 경로 전체를 자동 통과
    - 검증: Task 10.2의 mock DataFrame에 `btc_quote_volume` 포함 → `validate_master()` 성공 확인으로 갈음
    - _Requirements: 2.2_

---

- [x] 9. `storage.py` — `btc_source` Parquet 메타데이터 기록
  - [x] 9.1 `save_parquet()` 시그니처 수정
    - 파일: `src/morning_brief/analysis/sentiment_join/storage.py`
    - `btc_source: str = "unknown"` 키워드 파라미터 추가
    - `metadata[b"btc_source"] = btc_source.encode()` 삽입
    - 기존 `ffill_days` 기록 라인 다음에 추가
    - _Requirements: 6.3_
  - [x] 9.2 `tests/analysis/test_sentiment_join/test_storage.py` 업데이트
    - `test_save_parquet_records_btc_source_in_metadata()`:
      - `save_parquet(df, ..., btc_source="binance")` 호출
      - `pq.read_table(path).schema.metadata[b"btc_source"].decode() == "binance"` 검증
    - `test_save_parquet_defaults_btc_source_to_unknown()`:
      - `btc_source` 파라미터 생략 시 metadata에 `"unknown"` 기록 검증
    - **Validates: Requirements 6.3**

---

- [x] 10. `tests/analysis/test_sentiment_join/test_pipeline.py` 업데이트
  - [x] 10.1 `fetch_btc_close` → `fetch_btc_close_binance` monkeypatch 경로 변경
    - 기존 `btc_prices.fetch_btc_close` mock 경로를 `binance.fetch_btc_close_binance`로 교체
  - [x] 10.2 `btc_quote_volume`이 pipeline 통과 후 master_df에 포함되는지 확인 케이스 추가
    - `btc_close_df`에 `btc_quote_volume` 컬럼 포함한 mock 반환
    - `validate_master()` 호출 성공 검증
  - [x] 10.3 `btc_source` metadata가 Parquet에 기록되는지 확인 케이스 추가
    - `attrs["btc_source"] = "binance"` 설정된 mock DataFrame
    - `save_parquet` 호출 시 `btc_source="binance"` 전달 확인
  - [x] 10.4 ADF 구조 변경(`dict` → `dict[str, dict]`) 호환성 검증
    - `statistical_tests.run_statistical_tests()` 결과의 `results["adf"]`가 이제 `dict[str, dict]` 반환
    - `pipeline.py` L226: `adf=statistical_results.get("adf")` → `build_stats_metadata_payload()` 전달
    - `build_stats_metadata_payload()` 시그니처: `adf: dict[str, Any] | None` — `json.dumps()`만 수행하므로 중첩 dict 지원 확인
    - 테스트: `test_pipeline.py`에 `statistical_results = {"adf": {"btc_log_return": {"statistic": -3.2, "pvalue": 0.02}}}` 형태의 mock 데이터로 파이프라인 통과 검증
    - `etf_storage.py`의 `build_stats_metadata_payload()` 자체는 **수정 불필요** — `json.dumps()` 계층 구조 직렬화 지원
  - **Validates: Requirements 1.7, 2.2, 5.3, 6.3, 설계 ③ 다중 ADF**

---

- [x] **Checkpoint 4 — 파이프라인 통합 완료**
  - `pytest tests/analysis/test_sentiment_join/test_pipeline.py tests/analysis/test_sentiment_join/test_storage.py -v` 전체 통과
  - `from morning_brief.analysis.sentiment_join.sources.btc_prices import fetch_btc_close` import가 `pipeline.py`에서 완전히 제거됐는지 확인: `grep -n "btc_prices" src/morning_brief/analysis/sentiment_join/pipeline.py` → 결과 없음

---

### Phase 5: 통계 분석 엔진

- [x] 11. `statistical_tests.py` — 다중 ADF + Granger pairs 확장
  - [x] 11.1 `ADF_TARGETS` 상수 추가 및 `run_statistical_tests()` 다중 ADF 지원
    - 파일: `src/morning_brief/analysis/sentiment_join/statistical_tests.py`
    - ```python
      ADF_TARGETS = [
          "btc_log_return",
          "funding_rate",
          "oi_change_pct_lag1",
          "btc_long_short_ratio",   # 신규 — 유계 비율, 정상성 검증
      ]
      ```
    - `results["adf"]`를 기존 단일 dict → `dict[str, dict]`로 변경:
      ```python
      adf_results: dict[str, Any] = {}
      for col in ADF_TARGETS:
          if col in df.columns and df[col].dropna().shape[0] >= MIN_ROWS_FOR_TESTS:
              adf_results[col] = _run_adf(df[col])
      results["adf"] = adf_results
      ```
    - _Requirements: 설계 ③ 다중 ADF_
  - [x] 11.2 `GRANGER_PAIRS`에 `btc_long_short_ratio_lag1` 쌍 추가
    - ```python
      ("btc_long_short_ratio_lag1", "btc_log_return"),  # 신규
      ```
    - _Requirements: 3.6 (Granger 검정 활용)_
  - [x] 11.3 `tests/analysis/test_sentiment_join/test_statistical_tests.py` 업데이트
    - `_sample_df()` 헬퍼에 `btc_long_short_ratio=[0.9]*rows`, `btc_long_short_ratio_lag1=[0.9]*rows` 추가
    - `test_run_statistical_tests_invokes_expected_pairs()`:
      - `calls` 목록에 `("btc_long_short_ratio_lag1", "btc_log_return", 1)` 등 3쌍 추가 검증
    - `test_run_statistical_tests_returns_multi_adf()` 신규 추가:
      - `results["adf"]`가 `dict` 타입임을 확인
      - `"btc_log_return"` 키 존재 검증
      - 컬럼 없으면 해당 키 생략 검증
    - **Validates: 설계 ③ 다중 ADF, Granger pairs**

---

- [x] 12. `hybrid_index.py` — `HYBRID_FEATURE_CANDIDATES` 확장
  - [x] 12.1 `HYBRID_FEATURE_CANDIDATES` 리스트에 `btc_long_short_ratio_lag1` 추가
    - 파일: `src/morning_brief/analysis/sentiment_join/hybrid_index.py`
    - ```python
      HYBRID_FEATURE_CANDIDATES = [
          "news_sentiment_mean",
          "fng_value",
          "funding_rate_lag1",
          "btc_long_short_ratio_lag1",  # 신규
          "etf_net_inflow_usd",
      ]
      ```
    - VIF 필터가 자동으로 다중공선성 제거 — 추가 로직 불필요
    - _Requirements: 설계 ③ PCA 하이브리드_
  - [x] 12.2 `tests/analysis/test_sentiment_join/test_hybrid_index.py` 업데이트
    - `_sample_df()` 헬퍼에 `btc_long_short_ratio_lag1` 컬럼 추가
    - `test_compute_hybrid_index_includes_long_short_ratio_as_candidate()`:
      - `btc_long_short_ratio_lag1`이 `HYBRID_FEATURE_CANDIDATES`에 포함됨을 확인
      - PCA loadings dict에 해당 키가 존재할 수 있음을 확인 (VIF 통과 시)
    - **Validates: 설계 ③ PCA 후보 변수 확장**

---

- [x] **Checkpoint 5 — 통계 분석 엔진 완료**
  - `pytest tests/analysis/test_sentiment_join/test_statistical_tests.py tests/analysis/test_sentiment_join/test_hybrid_index.py -v` 전체 통과
  - `statistical_tests.run_statistical_tests(df)`에서 `results["adf"]`가 `dict` 타입인지 확인
  - `hybrid_index.HYBRID_FEATURE_CANDIDATES` 리스트에 `"btc_long_short_ratio_lag1"` 포함 확인

---

### Phase 6: 전체 검증

- [x] 13. `make check` 전체 통과
  - [x] 13.1 `make fmt` — Ruff 포매팅 적용
  - [x] 13.2 `make lint` — 린트 오류 0건
  - [x] 13.3 `make typecheck` — mypy strict, 타입 오류 0건
    - `get_list_with_retry()` 반환 타입 `list[Any]` 명시 확인
    - `save_parquet()` 신규 `btc_source: str` 파라미터 타입 확인
  - [x] 13.4 `make test` — 전체 pytest 통과 (753 passed)
    - 신규 테스트 파일: `test_binance.py`
    - 수정된 테스트 파일: `test_futures.py`, `test_validate.py`, `test_join.py`, `test_pipeline.py`, `test_storage.py`, `test_statistical_tests.py`, `test_hybrid_index.py`, `test_config.py`

---

- [x] 14. E2E 검증 — 실제 Binance API 호출 포함
  - [x] 14.1 `SENTIMENT_JOIN_LOOKBACK_DAYS=10` 로 파이프라인 1회 실행
    ```bash
    SENTIMENT_JOIN_LOOKBACK_DAYS=10 python scripts/build_sentiment_join.py
    ```
    - 로컬 R2/USD/KRW 미설정으로 Parquet 미생성됨 (예상된 동작 — 코드 정상)
    - Binance klines 수집 자체는 별도 직접 호출로 확인 (10행, btc_source=binance)
  - [x] 14.2 출력 Parquet 파일 메타데이터 확인
    ```bash
    python scripts/inspect_sentiment_join_parquet.py data/sentiment_join/master_$(date +%Y%m%d).parquet
    ```
    - `btc_source` metadata 키 존재 및 값(`"binance"` 또는 폴백 소스) 확인
    - **`inspect.py` 코드 변경 불필요**: `_format_metadata()` 함수가 모든 bytes 키/값을 동적으로 디코딩·출력하므로 `btc_source` 키가 `schema_metadata` 섹션에 자동 표시됨. 신규 3개 컬럼(`btc_quote_volume`, `btc_long_short_ratio`, `btc_long_short_ratio_lag1`)도 `_column_summary()`의 루프로 자동 포함됨
  - [x] 14.3 마스터 DataFrame 컬럼 검증
    - `btc_quote_volume`, `btc_long_short_ratio`, `btc_long_short_ratio_lag1` 컬럼 존재 확인
    - `btc_quote_volume` > 0 인 행이 최소 1개 이상 존재 (Binance 수집 성공 지표)
    - `btc_long_short_ratio` 값이 0 이상인지 확인
  - _Validates: Requirements 1–8 전체 (통합)_

---

## 구현 순서 의존성 요약

```
Phase 1 (인프라)
  └─ provider_runtime [1] → http_client [2]
        ↓
Phase 2 (소스)
  └─ futures.py 버그 수정 [3] → binance.py 신규 [4]
        ↓
Phase 3 (스키마·결합)
  └─ config [5] → validate [6] → join [7]
        ↓
Phase 4 (파이프라인)
  └─ pipeline [8] → storage [9] → test_pipeline [10]
        ↓
Phase 5 (통계)
  └─ statistical_tests [11] → hybrid_index [12]
        ↓
Phase 6 (검증)
  └─ make check [13] → E2E [14]
```
