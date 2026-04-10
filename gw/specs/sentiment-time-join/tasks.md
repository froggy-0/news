# Implementation Plan: Sentiment Time Join

## Overview

`src/morning_brief/analysis/sentiment_join/` 신규 모듈을 레이어 순서대로 구현한다: 설정 → 소스 수집기 → 변환/정제 → 결합/이상값 탐지 → 검증 → 저장 → 파이프라인 오케스트레이터 → CLI 진입점. 각 레이어 구현 직후 단위 테스트를 작성하고, 4~5개 레이어마다 Checkpoint를 삽입한다. `pipeline.py`·`main.py`는 수정하지 않는다.

완료 일시: —

---

## Tasks

### Phase 1: 기반 설정

- [ ] 1. 모듈 디렉토리 및 의존성 세팅
  - [ ] 1.1 디렉토리 구조 생성
    - `src/morning_brief/analysis/__init__.py`
    - `src/morning_brief/analysis/sentiment_join/__init__.py` — `run_sentiment_join` export 포함
    - `src/morning_brief/analysis/sentiment_join/sources/__init__.py`
    - `tests/analysis/__init__.py`
    - `tests/analysis/test_sentiment_join/__init__.py`
    - _Requirements: 1.3_
  - [ ] 1.2 `requirements-analysis.txt` 신규 파일 생성 및 CI 등록
    - `pandera>=0.18`
    - `numpy`, `pandas` (기존 `requirements.txt`에 이미 있으면 생략)
    - FinBERT(`requirements-ml.txt`)와 분리 — 성격 상이
    - `.github/workflows` 또는 CI 설정에 `pip install -r requirements-analysis.txt` 단계 추가
    - _Requirements: 8.1_
  - [ ] 1.3 `tests/analysis/conftest.py` 생성
    - `reset_provider_runtime_state()` autouse fixture 적용 — ThreadPool 병렬 테스트에서 circuit breaker 상태 격리
    - `sys.path`에 `src/` 추가 (기존 `tests/conftest.py` 참조)
    - _Requirements: 1.1_
  - [ ] 1.4 `Makefile`에 `sentiment-join` 타겟 추가
    ```makefile
    sentiment-join:
        $(PYTHON) scripts/build_sentiment_join.py
    ```
    - _Requirements: 1.3_

---

- [ ] 2. `analysis/sentiment_join/config.py` 구현
  - [ ] 2.1 `SentimentJoinSettings` dataclass 구현
    - `lookback_days: int` — `SENTIMENT_JOIN_LOOKBACK_DAYS`, default=180
    - `output_dir: Path` — `SENTIMENT_JOIN_OUTPUT_DIR`, default=`data/sentiment_join`
    - `r2_public_bucket: str` — `R2_PUBLIC_BUCKET` (기존 env 재사용)
    - `r2_max_concurrency: int` — `SENTIMENT_JOIN_R2_MAX_CONCURRENCY`, default=10
    - `retain_days: int` — `SENTIMENT_JOIN_RETAIN_DAYS`, default=30
    - `kis_app_key: str` — `KIS_APP_KEY`
    - `kis_app_secret: str` — `KIS_APP_SECRET`
    - `_env_bounded_int`, `_env_bool` 패턴 — 기존 `config.py` 방식 그대로 복제, import 없이 독립 구현
    - _Requirements: 10.1, 10.3_
  - [ ] 2.2 `load_sentiment_join_settings()` 구현
    - `lookback_days` 범위 검증: 30 미만 또는 730 초과 시 `ValueError`
    - `dotenv` 로드 (기존 `config.py` 동일 방식)
    - _Requirements: 10.2_
  - [ ] 2.3 `tests/analysis/test_sentiment_join/test_config.py` 작성
    - `SENTIMENT_JOIN_LOOKBACK_DAYS=29` → `ValueError`
    - `SENTIMENT_JOIN_LOOKBACK_DAYS=731` → `ValueError`
    - `SENTIMENT_JOIN_LOOKBACK_DAYS=30`, `730` → 경계값 통과
    - `SENTIMENT_JOIN_LOOKBACK_DAYS=90` → `lookback_days=90`
    - 기본값 검증: 환경변수 미설정 시 default 사용
    - **Validates: Requirements 10.1, 10.2, 10.3**

---

- [ ] 3. Checkpoint 1 — 설정 레이어
  - `pytest tests/analysis/test_sentiment_join/test_config.py -v` 통과
  - 파일 임포트 시 `morning_brief.pipeline` / `morning_brief.config.Settings` 참조 없음 확인

---

### Phase 2: 소스 수집기

- [ ] 4. `sources/r2_sentiment.py` 구현
  - [ ] 4.1 `fetch_r2_sentiment(dates, r2_public_bucket, max_concurrency=10)` 구현
    - `ThreadPoolExecutor(max_workers=max_concurrency)`로 병렬 GET
    - 각 날짜: `{r2_public_bucket}/briefs/{YYYY-MM-DD}.json`
    - 파싱 필드: `meta.newsSentiment.{mean, std, count}` + `meta.sentimentStatus`
      - `count` → `n_articles` 컬럼명 매핑
    - NaN 처리 조건:
      - `sentimentStatus == "skipped"` → 해당 날짜 mean/std/n_articles 모두 NaN
      - `sentimentStatus == "degraded"` → mean/std/count 값이 있으면 그대로 사용 (NaN 처리 안 함)
      - `mean is None` → NaN
    - 404 → NaN 행, 재시도 없음; 429/5xx/timeout → `get_json_with_retry` 재시도 3회
    - 전체 실패 시 `WARNING` 로그: `event=source.failed | source=r2 | reason`
    - `n_articles` 컬럼: `pd.array(values, dtype="Int64")` — nullable integer 캐스팅 필수
    - Returns: `DataFrame[date, news_sentiment_mean, news_sentiment_std, n_articles]`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [ ] 4.2 `tests/analysis/test_sentiment_join/test_r2_sentiment.py` 작성
    - 정상 응답 파싱 — `count` → `n_articles` 매핑 확인, dtype이 `pd.Int64Dtype()` 확인
    - `sentimentStatus="skipped"` → mean/std/n_articles 모두 NaN
    - `sentimentStatus="degraded"` + mean 값 있음 → NaN 처리하지 않고 값 보존
    - `sentimentStatus="ok"` + `mean=null` → NaN
    - 개별 날짜 404 → NaN 행, 나머지 정상 수집 (부분 실패 허용)
    - 전체 실패(모의 네트워크 오류) → 전 컬럼 NaN DataFrame
    - `reset_provider_runtime_state()` fixture 적용 확인
    - **Validates: Requirements 2.1–2.5**

---

- [ ] 5. `sources/fng.py` 구현
  - [ ] 5.1 `fetch_fng(lookback_days)` 구현
    - `GET https://api.alternative.me/fng/?limit={lookback_days+7}&date_format=us`
    - `get_json_with_retry` 재사용 (`DEFAULT_RETRIES=3`, `DEFAULT_BACKOFF=1.2`)
    - 날짜 변환: `MM/DD/YYYY` → UTC `YYYY-MM-DD` string
    - `value` 필드: `"75"` (string) → `int()` 변환; 변환 실패 시 NaN
    - `fng_value` 컬럼: `pd.array(values, dtype="Int64")` — nullable integer 캐스팅 필수
    - 실패 시 `WARNING` 로그, `fng_value` 전체 NaN DataFrame 반환
    - Returns: `DataFrame[date, fng_value]`
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ] 5.2 `tests/analysis/test_sentiment_join/test_fng.py` 작성
    - 정상 응답 — `"value": "75"` → `fng_value=75`, dtype `pd.Int64Dtype()` 확인
    - 날짜 변환 — `"04/10/2026"` → `"2026-04-10"`
    - `value` 파싱 실패 (`"N/A"` 등) → 해당 날짜 NaN
    - API 실패 → NaN DataFrame, WARNING 로그
    - **Validates: Requirements 3.1–3.3**

---

- [ ] 6. `sources/btc_prices.py` 구현
  - [ ] 6.1 `_fetch_coingecko_range(unix_start, unix_end)` 구현 (내부 함수)
    - `GET /api/v3/coins/bitcoin/market_chart/range?vs_currency=usd&from={unix_start}&to={unix_end}` — **단일 요청**
    - CoinGecko 응답 granularity 처리:
      - 범위 ≤ 90일: 시간별 데이터(`prices` 배열에 hourly 항목) → 일별 리샘플링 필요
      - 범위 > 90일: 일별 데이터 (그대로 사용)
      - 공통 처리: `timestamp_ms → UTC date`, 동일 날짜 중 **마지막 값(일별 종가)**으로 resample
    - Returns: `DataFrame[date, close]`
    - _Requirements: 4.1_
  - [ ] 6.2 `fetch_btc_close(start_date, end_date)` 구현 (공개 함수)
    - 1차: `_fetch_coingecko_range()` 호출
    - 2차 fallback: yfinance `BTC-USD` historical (`yf.download("BTC-USD", start, end)`)
    - `fallback.used` WARNING 로그: `event=fallback.used | source=btc | reason`
    - 두 소스 모두 실패 시 빈 DataFrame 반환 (btc 컬럼 전체 NaN은 pipeline에서 처리)
    - 수익률 계산은 `transform.compute_returns()` 위임
    - Returns: `DataFrame[date, close]`
    - _Requirements: 4.1, 4.2_
  - [ ] 6.3 `tests/analysis/test_sentiment_join/test_btc_prices.py` 작성
    - CoinGecko 시간별 응답(≤90일 range) → 일별 리샘플 후 행수 확인 (시간별 ≠ 일별)
    - CoinGecko 일별 응답(>90일 range) → 그대로 통과
    - `timestamp_ms` → `YYYY-MM-DD` 변환 정확성 확인
    - CoinGecko 실패 → yfinance fallback 호출, WARNING 로그
    - 두 소스 모두 실패 → 빈 DataFrame
    - **Validates: Requirements 4.1, 4.2**

---

- [ ] 7. `sources/usdkrw_prices.py` 구현
  - [ ] 7.1 `fetch_usdkrw_close(start_date, end_date, kis_app_key, kis_app_secret)` 구현
    - 1차: KIS `FHKST03030100` TR ID — `kis_app_key` 빈 문자열이면 즉시 yfinance로 전환
    - 2차 fallback: yfinance `KRW=X`
    - `fallback.used` WARNING 로그: `event=fallback.used | source=usdkrw | reason`
    - 두 소스 모두 실패 시 빈 DataFrame 반환
    - Returns: `DataFrame[date, close]`
    - 기존 `market.py` KIS 패턴 참조 (import 없이 독립 구현)
    - _Requirements: 5.1, 5.2_
  - [ ] 7.2 `tests/analysis/test_sentiment_join/test_usdkrw_prices.py` 작성
    - `kis_app_key=""` → 즉시 yfinance 전환 (KIS 미호출)
    - KIS 실패 → yfinance fallback, WARNING 로그
    - 두 소스 모두 실패 → 빈 DataFrame
    - **Validates: Requirements 5.1, 5.2**

---

- [ ] 8. Checkpoint 2 — 소스 수집기 레이어
  - `pytest tests/analysis/test_sentiment_join/test_r2_sentiment.py tests/analysis/test_sentiment_join/test_fng.py tests/analysis/test_sentiment_join/test_btc_prices.py tests/analysis/test_sentiment_join/test_usdkrw_prices.py -v` 통과
  - 각 소스 모듈이 `morning_brief.pipeline` / `morning_brief.config.Settings` import 없음 확인
  - `n_articles` dtype `pd.Int64Dtype()`, `fng_value` dtype `pd.Int64Dtype()` 확인

---

### Phase 3: 변환 및 정제

- [ ] 9. `transform.py` 구현
  - [ ] 9.1 `normalize_dates(df, date_col="date")` 구현
    - 타임존 포함 → UTC 변환 후 `YYYY-MM-DD` string 통일
    - 이미 string인 경우 포맷만 검증
    - _Requirements: 6.1_
  - [ ] 9.2 `forward_fill_prices(df, cols, max_periods=2)` 구현
    - 지정 컬럼에 `ffill(limit=2)` 적용
    - 2일 초과 연속 결측은 NaN 유지
    - **반환값 변경: `tuple[pd.DataFrame, int]`** — (채워진 DataFrame, fill된 행 수 합계)
      - `ffill_days` 카운트: fill 전후 NaN 수 차이로 계산
      - pipeline → save_parquet에 전달하기 위한 집계 경로
    - _Requirements: 6.2_
  - [ ] 9.3 `compute_returns(df, price_col)` 구현
    - `price_col` 값이 0 이하인 경우 NaN 처리 후 계산 (`where(close > 0)`)
    - `{price_col}_log_return = ln(close / close.shift(1))` — 첫 행은 항상 NaN, `ln(0)` → NaN not `-inf`
    - `{price_col}_return = close.pct_change()` — 첫 행은 항상 NaN
    - `price_col` 원본 컬럼 **삭제** (close → log_return + return만 유지) — 마스터 스키마 외 컬럼 방지
    - _Requirements: 4.3, 5.3_
  - [ ] 9.4 `trim_to_date_range(df, start_date, end_date)` 구현
    - `btc_start = start_date - 1일`로 수집한 extra row를 수익률 계산 후 제거
    - `df[df["date"] >= start_date]` 필터링
    - _Requirements: 4.1, 5.1_
  - [ ] 9.5 `tests/analysis/test_sentiment_join/test_transform.py` 작성
    - `normalize_dates`: UTC 타임존 포함 datetime → `"2026-04-10"` 변환
    - `forward_fill_prices` — 반환값 `(df, ffill_count)` 구조 확인:
      - **Property (hypothesis):** 연속 결측이 ≤2이면 fill 후 해당 컬럼 NaN 없음; ≥3이면 여전히 NaN 존재
      - fill 수 카운트 정확성: 1개 갭 → ffill_count=1, 2개 갭 → ffill_count=2
    - `compute_returns`:
      - 0 가격 → log_return=NaN (not `-inf`), `math.isinf()` 확인
      - 정상 가격 시퀀스 → 첫 행 log_return=NaN, return=NaN (shift 결과)
      - `close` 컬럼이 결과 DataFrame에 없음 확인 (삭제됨)
    - `trim_to_date_range`: extra row(start_date -1일)가 제거됨 확인
    - **edge case:** 상수 시계열 (가격 변화 없음) → log_return=0.0, return=0.0
    - **Validates: Requirements 4.3, 5.3, 6.1, 6.2**

---

- [ ] 10. Checkpoint 3 — 변환 레이어
  - `pytest tests/analysis/test_sentiment_join/test_transform.py -v` 통과
  - hypothesis property-based 테스트 최소 100 example 통과

---

### Phase 4: 결합 및 이상값 탐지

- [ ] 11. `join.py` 구현
  - [ ] 11.1 `_compute_sources_used(dfs: dict[str, pd.DataFrame])` 구현 (내부 유틸)
    - 소스별 핵심 컬럼이 모두 NaN이면 `sources_used`에서 제외
    - e.g., `"r2"`: `news_sentiment_mean` 비-NaN 행 존재 여부로 판단
    - Returns: `list[str]` — 유효 데이터가 있는 소스명 목록
    - _Requirements: 13.1 (join.complete 로그 필드)_
  - [ ] 11.2 `detect_outliers_rolling_iqr(df, cols, window=30, iqr_multiplier=3.0, min_periods=15)` 구현
    - 마스터 DataFrame에서 `btc_return`·`usdkrw_return` 컬럼 대상 롤링 IQR 탐지
    - `|value - rolling_median| > iqr_multiplier × rolling_IQR` → `is_outlier=True`
    - cold start (`min_periods` 미만 구간): IQR=NaN → `is_outlier=False`
    - `is_outlier` 컬럼 기본값 `False`, dtype `bool`
    - WARNING 로그: `event=outlier.detected | date | column | value | threshold`
    - _Requirements: 6.3_
  - [ ] 11.3 `merge_sources(sentiment_df, fng_df, btc_df, usdkrw_df)` 구현
    - join 전: `news_sentiment_mean` NaN 행 dropna
      - WARNING 로그: `event=rows.dropped | reason=no_sentiment | count`
    - `pd.merge(on='date', how='inner')` 순차 실행: sentiment → fng → btc → usdkrw
    - `detect_outliers_rolling_iqr()` 호출 → `is_outlier` 컬럼 추가
    - 결합 후 행수 < 30: WARNING 로그 `event=join.insufficient_rows | rows | min_required=30`
    - 완료 INFO 로그: `event=join.complete | rows | date_range_start | date_range_end | sources_used | outlier_count | dropped_no_sentiment`
      - `sources_used`: `_compute_sources_used()` 결과
    - _Requirements: 6.4, 7.1, 7.2, 7.3_
  - [ ] 11.4 `tests/analysis/test_sentiment_join/test_join.py` 작성
    - inner join — 날짜 교집합만 포함됨 확인
    - `news_sentiment_mean=NaN` 행 제거 + WARNING 로그 확인
    - `is_outlier`: 롤링 IQR 극단값(10× median) → True, 정상값 → False
    - cold start 구간 (`len < min_periods=15`) → `is_outlier=False` 전체
    - **edge case:** `lookback_days=30`이고 `window=30` → 전체 구간이 cold start → `is_outlier` 모두 False
    - 결합 후 10개 컬럼 스키마 확인 (date, mean, std, n_articles, fng, btc_log, btc, fx_log, fx, is_outlier), `close` 컬럼 없음
    - 행수 < 30 → WARNING 로그 발생
    - `sources_used`: btc 소스 전체 NaN이면 `"btc"` 목록에서 제외됨 확인
    - **Property (hypothesis):** 상수 시계열 → `detect_outliers_rolling_iqr()` 결과 `is_outlier` 모두 False (IQR=0)
    - **Property (hypothesis):** `merge_sources()` 결과에 `news_sentiment_mean=NaN` 행은 존재하지 않는다
    - **Validates: Requirements 6.3, 6.4, 7.1–7.3**

---

- [ ] 12. Checkpoint 4 — 결합 레이어
  - `pytest tests/analysis/test_sentiment_join/test_join.py -v` 통과
  - `is_outlier` 컬럼 dtype이 `bool`임을 확인

---

### Phase 5: 검증 및 저장

- [ ] 13. `validate.py` 구현
  - [ ] 13.1 `MASTER_SCHEMA` pandera DataFrameSchema 정의
    - `date`: str, `r"^\d{4}-\d{2}-\d{2}$"` 패턴, unique=True
    - `news_sentiment_mean`: float, -1.0~1.0, nullable=False
    - `news_sentiment_std`: float, ≥0, nullable=True
    - `n_articles`: `"Int64"` (대문자 — `pd.Int64Dtype()` 인식), ≥0, nullable=True
    - `fng_value`: `"Int64"`, 0~100, nullable=True
    - `btc_log_return`, `btc_return`, `usdkrw_log_return`, `usdkrw_return`: float, nullable=True
    - `is_outlier`: bool, nullable=False
    - _Requirements: 8.1_
  - [ ] 13.2 `validate_master(df)` 구현
    - `MASTER_SCHEMA.validate(df)` 호출
    - `SchemaError` → `ERROR` 로그 출력 후 re-raise (파이프라인이 종료 코드 1로 처리)
    - _Requirements: 8.2_
  - [ ] 13.3 `tests/analysis/test_sentiment_join/test_validate.py` 작성
    - 정상 DataFrame → 검증 통과
    - `news_sentiment_mean=1.5` → SchemaError
    - `fng_value=101` → SchemaError
    - `n_articles=-1` → SchemaError
    - `date` 중복 → SchemaError
    - `is_outlier=None` → SchemaError
    - `n_articles` dtype이 `pd.Int64Dtype()`일 때 정상 통과, Python `int` dtype이면 실패 확인 (`"Int64"` 인식 검증)
    - 마스터 스키마에 없는 여분 컬럼(`close`)이 있으면 SchemaError 또는 경고 확인 (strict 모드)
    - **Validates: Requirements 8.1, 8.2**

---

- [ ] 14. `storage.py` 구현
  - [ ] 14.1 `save_parquet(df, output_dir, run_date, *, ffill_days=0)` 구현
    - `output_dir / f"master_{run_date}.parquet"` 경로로 저장
    - `compression="snappy"` 명시
    - `output_dir.mkdir(parents=True, exist_ok=True)` — 디렉토리 자동 생성
    - 동일 날짜 파일 존재 시 덮어씀 (idempotency)
    - `ffill_days` 수를 Parquet custom metadata에 기록:
      ```python
      table = pa.Table.from_pandas(df)
      existing_meta = table.schema.metadata or {}
      table = table.replace_schema_metadata({**existing_meta, b"ffill_days": str(ffill_days).encode()})
      pq.write_table(table, path, compression="snappy")
      ```
    - _Requirements: 7.4, 7.5, 9.1_
  - [ ] 14.2 `cleanup_old_files(output_dir, retain_days)` 구현
    - `retain_days=0` → 무동작
    - `output_dir.glob("master_*.parquet")` 순회 → 파일명에서 날짜 파싱 (`master_YYYYMMDD.parquet`)
    - 오늘 기준 `retain_days` 초과 파일 삭제
    - _Requirements: 9.2_
  - [ ] 14.3 `upload_to_r2(local_path, r2_key, *, r2_s3_endpoint, r2_access_key_id, r2_secret_access_key, r2_public_bucket)` stub 구현
    - 함수 본체: `return` 한 줄 (no-op)
    - 시그니처에 접속 정보 파라미터 포함 — 향후 확장 시 시그니처 변경 불필요
    - _Requirements: 14.1_
  - [ ] 14.4 `tests/analysis/test_sentiment_join/test_storage.py` 작성
    - `save_parquet()` — 파일 생성 확인, snappy 압축 확인
    - idempotency: 동일 날짜로 2회 호출 → 파일 1개만 존재, 내용은 두 번째 호출 기준
    - **Parquet round-trip dtype 검증:**
      ```python
      df_read = pd.read_parquet(path)
      assert df_read["n_articles"].dtype == pd.Int64Dtype()
      assert df_read["fng_value"].dtype == pd.Int64Dtype()
      assert df_read["is_outlier"].dtype == bool
      ```
    - `ffill_days` Parquet 메타데이터 기록 확인:
      ```python
      import pyarrow.parquet as pq
      meta = pq.read_metadata(path).metadata
      assert meta[b"ffill_days"] == b"3"
      ```
    - `cleanup_old_files()`: `retain_days=30` → 31일 이전 파일 삭제, 최근 파일 보존
    - `cleanup_old_files(retain_days=0)` → 삭제 없음
    - `upload_to_r2()` — 호출 시 예외 없이 반환됨 (stub 확인)
    - **Validates: Requirements 7.4, 7.5, 9.1, 9.2, 14.1**

---

- [ ] 15. Checkpoint 5 — 검증·저장 레이어
  - `pytest tests/analysis/test_sentiment_join/test_validate.py tests/analysis/test_sentiment_join/test_storage.py -v` 통과
  - Parquet round-trip 후 `Int64`·`bool` dtype 보존 확인

---

### Phase 6: 파이프라인 오케스트레이터 및 CLI

- [ ] 16. `pipeline.py` 구현
  - [ ] 16.1 `run_sentiment_join(settings)` 구현
    - **단계 순서:**
      1. 날짜 범위 계산
         - `end_date = today`
         - `start_date = today - lookback_days`
         - `btc_start = start_date - 1일` (수익률 계산용 extra row)
      2. 4개 소스 수집 (순차, 각 소스 독립 실패 허용)
         - `event=source.complete | source | rows | fallback_used` INFO 로그
      3. 각 소스 DataFrame에 `transform.normalize_dates()` 적용
      4. 가격 DataFrame(btc, usdkrw)에 `transform.forward_fill_prices()` 적용
         - 반환된 `ffill_count` 누적 → `total_ffill_days`
      5. `transform.compute_returns()` — btc·usdkrw `close` → `log_return`+`return` (close 삭제)
      6. `transform.trim_to_date_range()` — btc·usdkrw DataFrame에서 `btc_start` extra row 제거
      7. `join.merge_sources()` — inner join + outlier 탐지
      8. 마스터 빈 DataFrame 확인 (모든 소스 실패) → `ERROR` 로그, Parquet 미저장, `return 1`
      9. `validate.validate_master()` — SchemaError → `ERROR` 로그, `return 1`
      10. `storage.save_parquet(df, ..., ffill_days=total_ffill_days)`
      11. `storage.cleanup_old_files()`
      12. `storage.upload_to_r2()` stub 호출
    - 반환값: `int` (0=성공, 1=실패)
    - _Requirements: 1.1, 1.2, 1.3, 10.1, 11.1, 11.2, 12.1, 12.2, 13.1–13.3_
  - [ ] 16.2 `tests/analysis/test_sentiment_join/test_pipeline.py` 작성
    - **통합 테스트** (소스 mock): 정상 흐름 → 종료 코드 0, Parquet 파일 생성
    - 소스 1개 실패 → 종료 코드 0, 해당 컬럼 NaN Parquet 생성
    - 모든 소스 실패 → 종료 코드 1, Parquet 미생성
    - pandera 검증 실패 (mock으로 범위 위반 주입) → 종료 코드 1, Parquet 미생성
    - `total_ffill_days`가 Parquet 메타데이터에 기록됨 확인
    - 독립성 검증:
      ```python
      def test_pipeline_does_not_import_main_pipeline():
          import inspect, importlib
          mod = importlib.import_module("morning_brief.analysis.sentiment_join.pipeline")
          source = inspect.getsource(mod)
          assert "from morning_brief.pipeline" not in source
          assert "from morning_brief.config import Settings" not in source
      ```
    - **Validates: Requirements 1.1–1.3, 10.1, 12.1, 12.2**

---

- [ ] 17. `scripts/build_sentiment_join.py` 구현
  - [ ] 17.1 CLI 진입점 작성
    ```python
    #!/usr/bin/env python3
    import sys
    from morning_brief.analysis.sentiment_join.config import load_sentiment_join_settings
    from morning_brief.analysis.sentiment_join.pipeline import run_sentiment_join

    if __name__ == "__main__":
        settings = load_sentiment_join_settings()
        sys.exit(run_sentiment_join(settings))
    ```
    - _Requirements: 1.3_
  - [ ] 17.2 실행 가능 권한 설정: `chmod +x scripts/build_sentiment_join.py`
  - [ ] 17.3 dry-run 확인: 환경변수 미설정 상태에서 `ValueError` 없이 설정 로드 후 소스 수집 시작 여부만 확인

---

- [ ] 18. Checkpoint 6 — 파이프라인 통합
  - `pytest tests/analysis/ -v` 전체 통과
  - `make lint` 통과 (Ruff)
  - `make typecheck` 통과 (mypy strict)

---

### Phase 7: 품질 검사 및 마무리

- [ ] 19. `make check` 전체 통과
  - [ ] 19.1 `make fmt` — Ruff 자동 포매팅
  - [ ] 19.2 `make lint` — Ruff 린트 검사
  - [ ] 19.3 `make test` — 전체 pytest (기존 테스트 회귀 없음 확인)
  - [ ] 19.4 `make typecheck` — mypy strict (신규 모듈 타입 오류 없음)
  - _Requirements: 전체_

- [ ] 20. 기존 파이프라인 회귀 없음 확인
  - [ ] 20.1 `pytest tests/ -v --ignore=tests/analysis` — 기존 테스트 전체 통과
  - [ ] 20.2 `pipeline.py`, `main.py`, `config.py`, `public_site.py` diff 없음 확인
    ```bash
    git diff src/morning_brief/pipeline.py src/morning_brief/main.py \
              src/morning_brief/config.py src/morning_brief/public_site.py
    # → 출력 없음이어야 함
    ```
  - _Requirements: 1.1, 1.2_

- [ ] 21. `CLAUDE.md` 및 `Makefile` 문서 갱신
  - [ ] 21.1 `CLAUDE.md` Architecture 표에 Sentiment Join 파이프라인 항목 추가
    - `scripts/build_sentiment_join.py` 실행법 (`make sentiment-join`)
    - 환경변수 목록: `SENTIMENT_JOIN_LOOKBACK_DAYS`, `SENTIMENT_JOIN_OUTPUT_DIR`, `SENTIMENT_JOIN_R2_MAX_CONCURRENCY`, `SENTIMENT_JOIN_RETAIN_DAYS`
    - 출력물: `data/sentiment_join/master_{YYYYMMDD}.parquet`
    - 의존성: `requirements-analysis.txt` (`pandera`)
  - [ ] 21.2 `Makefile` `sentiment-join` 타겟 추가 (Task 1.4에서 선행 추가했으면 확인만)
  - _Requirements: 전체 (CLAUDE.md 정책: 동작·설정 변경 시 문서 갱신)_

---

- [ ] 22. Checkpoint 7 — 최종
  - `make check` 통과
  - 기존 테스트 회귀 없음
  - `gw/specs/sentiment-time-join/tasks.md` Overview 완료 일시 기록
