# Implementation Plan: Granger Cross-Pairs (Task 03)

## Overview

`docs/tasks/03-granger-cross-pairs.md` 설계를 구현한다. 세 핵심 변경: (1) Granger predictor를
`_lag1`→raw로 복원해 double-lag 제거, (2) 신규 raw 컬럼 생성 + `btc_quote_volume` 누락 방어,
(3) cross pair 16쌍 + 역방향 5쌍 구성 및 BH-FDR family 확장(63 검정).
`validate.py`의 `strict=True` 스키마가 모든 신규 컬럼을 강제하므로
**join → validate → statistical_tests → hybrid_index → pipeline** 순서로 진행한다.

**요구사항 출처**: `docs/tasks/03-granger-cross-pairs.md`  
**전제 조건**: task-01(pre-backfill-fixes), task-02(statistical-rigor-fixes) 완료  
**BH-FDR family 크기**: (16 TARGET+CROSS + 5 REVERSE) × 3 lag = **63 검정**  
**완료 일시**: 2026-04-17

---

## Tasks

### 묶음 A — double-lag 제거 + cross pair 재구성 (우선순위 3-1, 3-3)

- [x] 1. `statistical_tests.py` — GRANGER_PAIRS raw 복원 + cross pair 추가 + ADF_TARGETS 갱신

  - [x] 1.1 상수 재정의: `GRANGER_PAIRS_TARGET` / `GRANGER_PAIRS_CROSS` 선언

    현재 `GRANGER_PAIRS`는 5쌍이며 predictor가 전부 `_lag1`이다. 이를 아래로 교체한다.

    ```python
    # Before
    GRANGER_PAIRS = [
        ("news_sentiment_mean_lag1", "btc_log_return"),
        ("funding_rate_lag1",        "btc_log_return"),
        ("fng_value_lag1",           "btc_log_return"),
        ("btc_long_short_ratio_lag1","btc_log_return"),
        ("etf_net_inflow_usd_lag1",  "btc_log_return"),
    ]

    # After
    # Granger 내부에서 predictor[t-1..t-k]를 자체 처리하므로 raw 컬럼을 투입해야 한다.
    # _lag1 버전을 투입하면 실제 검정 관계가 한 칸 더 밀리는 double-lag이 발생한다.
    _TARGET = "btc_log_return"
    _PREDICTORS_RAW = [
        "news_sentiment_mean",
        "fng_value",
        "funding_rate",
        "btc_long_short_ratio",
        "oi_change_pct",
        "etf_net_inflow_usd",
        "usdkrw_log_return",
        "volume_change_pct",
    ]
    GRANGER_PAIRS_TARGET = [(p, _TARGET) for p in _PREDICTORS_RAW]  # 8쌍

    GRANGER_PAIRS_CROSS = [
        # 정보 전파 경로 — Granger lag=k: "k일 전 predictor → 오늘 target"
        ("news_sentiment_mean", "fng_value"),
        ("fng_value",           "news_sentiment_mean"),
        ("news_sentiment_mean", "funding_rate"),
        ("news_sentiment_mean", "etf_net_inflow_usd"),
        ("fng_value",           "btc_long_short_ratio"),
        ("fng_value",           "etf_net_inflow_usd"),
        ("usdkrw_log_return",   "volume_change_pct"),
        ("funding_rate",        "etf_net_inflow_usd"),
    ]  # 8쌍

    GRANGER_PAIRS = GRANGER_PAIRS_TARGET + GRANGER_PAIRS_CROSS  # 16쌍 × 3 lag = 48 검정
    ```

    _Requirements: §0, §3.A, §3.B_

  - [x] 1.2 `GRANGER_PAIRS_REVERSE` — target을 raw로 교체 (predictor `btc_log_return` 유지)

    ```python
    # Before
    GRANGER_PAIRS_REVERSE = [
        ("btc_log_return", "news_sentiment_mean_lag1"),
        ("btc_log_return", "funding_rate_lag1"),
        ("btc_log_return", "fng_value_lag1"),
        ("btc_log_return", "btc_long_short_ratio_lag1"),
        ("btc_log_return", "etf_net_inflow_usd_lag1"),
    ]

    # After
    GRANGER_PAIRS_REVERSE = [
        ("btc_log_return", "news_sentiment_mean"),
        ("btc_log_return", "funding_rate"),
        ("btc_log_return", "fng_value"),
        ("btc_log_return", "btc_long_short_ratio"),
        ("btc_log_return", "etf_net_inflow_usd"),
    ]  # 5쌍 — 가격이 지표를 선행하는지 확인 (단순 선행 해석 방지)
    ```

    _Requirements: §0_

  - [x] 1.3 `ADF_TARGETS` — raw 9개로 재작성

    ```python
    # Before (혼재)
    ADF_TARGETS = [
        "btc_log_return",
        "news_sentiment_mean_lag1",  # ← lag1 잔존
        "fng_value_lag1",            # ← lag1 잔존
        "funding_rate",
        "funding_rate_lag1",         # ← lag1 중복
        "oi_change_pct_lag1",        # ← raw 없이 lag1만
        "btc_long_short_ratio",
        "btc_long_short_ratio_lag1", # ← lag1 중복
        "etf_net_inflow_usd_lag1",   # ← raw 없이 lag1만
    ]

    # After
    ADF_TARGETS = [
        "btc_log_return",
        "news_sentiment_mean",
        "fng_value",
        "funding_rate",
        "btc_long_short_ratio",
        "oi_change_pct",
        "etf_net_inflow_usd",
        "usdkrw_log_return",
        "volume_change_pct",
    ]  # 9개 raw 변수
    ```

    _Requirements: §4_

  - [x] 1.4 `__all__` 업데이트 — `GRANGER_PAIRS_TARGET`, `GRANGER_PAIRS_CROSS` 추가 export

    _Requirements: §3.C_

- [x] 2. `test_statistical_tests.py` — 기존 깨지는 테스트 수정 + 신규 테스트 추가

  - [x] 2.1 `_sample_df` fixture에 raw 컬럼 추가

    기존 `_lag1` 위주 fixture에 raw 컬럼을 추가해 raw/lag1 양쪽 테스트가 모두 동작하게 한다.

    추가할 컬럼: `news_sentiment_mean`, `fng_value`(Int64), `funding_rate`,
    `btc_long_short_ratio`, `oi_change_pct`, `etf_net_inflow_usd`,
    `usdkrw_log_return`, `volume_change_pct`

    `_sample_df_with_gap`도 동일하게 raw 컬럼 추가.

  - [x] 2.2 `test_granger_pairs_use_lag1_predictors` 삭제 → `test_granger_pairs_use_raw_predictors`로 교체

    ```python
    # 삭제
    def test_granger_pairs_use_lag1_predictors() -> None: ...

    # 신규
    def test_granger_pairs_use_raw_predictors() -> None:
        """Property R-1: GRANGER_PAIRS의 모든 predictor는 raw(비-lag1) 컬럼이어야 한다."""
        for predictor, target in statistical_tests.GRANGER_PAIRS:
            assert not predictor.endswith("_lag1"), (
                f"predictor '{predictor}'가 raw가 아닙니다. double-lag 위험."
            )

    def test_granger_pairs_count() -> None:
        """GRANGER_PAIRS = TARGET(8) + CROSS(8) = 16쌍."""
        assert len(statistical_tests.GRANGER_PAIRS_TARGET) == 8
        assert len(statistical_tests.GRANGER_PAIRS_CROSS) == 8
        assert len(statistical_tests.GRANGER_PAIRS) == 16
    ```

    _Requirements: §0, §3_

  - [x] 2.3 `test_run_statistical_tests_granger_runs_at_180_rows` 업데이트

    ```python
    # Before
    assert len(pair_calls) == 10   # 순방향(5) + 역방향(5)
    assert len(results["granger"]) == 30

    # After
    assert len(pair_calls) == 21   # forward(16) + reverse(5)
    assert len(results["granger"]) == 63
    ```

    _Requirements: §3.C_

  - [x] 2.4 `test_granger_pairs_reverse_has_btc_as_predictor` — target raw 검증 추가

    기존 `predictor == "btc_log_return"` 확인 유지.  
    추가: `assert not target.endswith("_lag1")`

  - [x] 2.5 double-lag 회귀 테스트 신규 추가

    **Property R-2: double-lag 방지** — raw vs `_lag1` predictor를 같은 쌍에 투입했을 때
    p-value가 달라야 한다(같은 데이터를 한 칸씩 밀면 결과가 달라짐을 보장).

    ```python
    def test_raw_and_lag1_predictor_produce_different_pvalues(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Property R-2: raw predictor와 _lag1 predictor는 Granger p-value가 달라야 한다."""
        import statsmodels.tsa.stattools as _sts
        monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
        monkeypatch.setattr(_sts, "kpss",     lambda s, **kw: (0.1, 0.10, None, {}))

        rng = np.random.default_rng(7)
        n = 200
        dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
        df = pd.DataFrame({
            "date":                    dates,
            "btc_log_return":          rng.normal(0, 0.02, n),
            "news_sentiment_mean":     rng.normal(0, 0.1, n),
        })
        df["news_sentiment_mean_lag1"] = df["news_sentiment_mean"].shift(1)

        from morning_brief.analysis.sentiment_join.statistical_tests import _run_granger

        entry_raw  = _run_granger(df, "news_sentiment_mean",      "btc_log_return", lag=1)
        entry_lag1 = _run_granger(df, "news_sentiment_mean_lag1", "btc_log_return", lag=1)

        assert entry_raw  is not None
        assert entry_lag1 is not None
        assert entry_raw["pvalue"] != pytest.approx(entry_lag1["pvalue"]), (
            "raw와 _lag1 predictor의 p-value가 같습니다. double-lag 의심."
        )
    ```

    _Requirements: §0_

- [x] **Checkpoint 1** — `pytest tests/analysis/test_sentiment_join/test_statistical_tests.py -v`

  통과 기준: 전체 green, `test_granger_pairs_use_lag1_predictors` 삭제 확인.

---

### 묶음 B — raw 컬럼 생성 + 방어 로직 + 스키마 (우선순위 3-2)

- [x] 3. `join.py` — raw 컬럼 생성 + `btc_quote_volume` 방어 + outlier cols 확장

  - [x] 3.1 `_add_futures_lag_columns` — `oi_change_pct` raw 추가, `volume_change_pct` raw+lag1 추가

    ```python
    # Before (oi 부분)
    if "open_interest_usd" in result.columns:
        result["oi_change_pct_lag1"] = result["open_interest_usd"].pct_change().shift(1)
    else:
        result["oi_change_pct_lag1"] = float("nan")

    # After (oi 부분)
    if "open_interest_usd" in result.columns:
        oi = pd.to_numeric(result["open_interest_usd"], errors="coerce")
        result["oi_change_pct"]      = oi.pct_change()
        result["oi_change_pct_lag1"] = result["oi_change_pct"].shift(1)
    else:
        result["oi_change_pct"]      = float("nan")
        result["oi_change_pct_lag1"] = float("nan")
    ```

    ```python
    # After (volume 추가 — btc_quote_volume이 이미 merged에 존재한다고 가정)
    if "btc_quote_volume" in result.columns:
        vol = pd.to_numeric(result["btc_quote_volume"], errors="coerce")
        result["volume_change_pct"]      = vol.pct_change()
        result["volume_change_pct_lag1"] = result["volume_change_pct"].shift(1)
    else:
        result["volume_change_pct"]      = float("nan")
        result["volume_change_pct_lag1"] = float("nan")
    ```

    _Requirements: §7_

  - [x] 3.2 `_add_sentiment_lag_columns` — `usdkrw_log_return_lag1` 추가

    ```python
    # After (기존 블록 끝에 추가)
    if "usdkrw_log_return" in result.columns:
        result["usdkrw_log_return_lag1"] = result["usdkrw_log_return"].shift(1)
    else:
        result["usdkrw_log_return_lag1"] = float("nan")
    ```

    함수 docstring 갱신:
    > "PCA·correlation용 lag1 컬럼. Granger 검정에는 raw 컬럼을 사용한다(double-lag 방지)."

    _Requirements: §7_

  - [x] 3.3 `merge_sources` — `btc_quote_volume` 누락 방어

    `_add_futures_lag_columns(merged)` 호출 **직전**에 삽입:

    ```python
    # §7: btc_quote_volume 누락 방어 — _empty_return_frame fallback 경로에서 컬럼이 없을 수 있음
    if "btc_quote_volume" not in merged.columns:
        merged["btc_quote_volume"] = float("nan")
    ```

    _Requirements: §7 🔴 `_empty_return_frame` 누락 컬럼_

  - [x] 3.4 `detect_outliers_rolling_iqr` 호출 컬럼 확장

    ```python
    # Before
    merged = detect_outliers_rolling_iqr(
        merged,
        cols=[
            "btc_return",
            "usdkrw_return",
            "funding_rate",
            "open_interest_usd",
            "btc_long_short_ratio",
        ],
    )

    # After
    merged = detect_outliers_rolling_iqr(
        merged,
        cols=[
            "btc_return",
            "usdkrw_return",
            "funding_rate",
            "open_interest_usd",
            "btc_long_short_ratio",
            "news_sentiment_mean",
            "fng_value",
            "etf_net_inflow_usd",
            "btc_quote_volume",
        ],
    )
    # 이상치 처리: 값만 NaN 마스킹, 행 유지 (pipeline.py §8-A 정책과 일치)
    ```

    _Requirements: §7 이상치 감지 대상 확장_

- [x] 4. `test_join.py` — 신규 컬럼 + 방어 로직 테스트

  - [x] 4.1 `oi_change_pct` raw + lag1 일관성 테스트

    **Property J-1** — `oi_change_pct_lag1.iloc[k] == oi_change_pct.iloc[k-1]` (k≥1)

    ```python
    def test_add_futures_lag_columns_oi_raw_and_lag1_consistent() -> None:
        """Property J-1: oi_change_pct_lag1은 oi_change_pct를 1행 shift한 값이어야 한다."""
        df = pd.DataFrame({
            "open_interest_usd": [1000.0, 1100.0, 990.0, 1050.0, 1020.0],
            "funding_rate": [0.001] * 5,
            "btc_long_short_ratio": [0.9] * 5,
            "etf_net_inflow_usd": [0.0] * 5,
        })
        from morning_brief.analysis.sentiment_join.join import _add_futures_lag_columns
        result = _add_futures_lag_columns(df)

        assert "oi_change_pct" in result.columns
        assert "oi_change_pct_lag1" in result.columns
        # lag1[k] == raw[k-1]
        pd.testing.assert_series_equal(
            result["oi_change_pct_lag1"].iloc[2:].reset_index(drop=True),
            result["oi_change_pct"].iloc[1:-1].reset_index(drop=True),
            check_names=False,
        )
    ```

  - [x] 4.2 `volume_change_pct` 생성 테스트 + btc_quote_volume 없을 때 방어 테스트

    **Property J-2** — `btc_quote_volume` 없어도 KeyError 없이 NaN 컬럼 생성

    ```python
    def test_add_futures_lag_columns_volume_without_btc_quote_volume() -> None:
        """Property J-2: btc_quote_volume 없으면 volume_change_pct/lag1이 NaN으로 생성된다."""
        df = pd.DataFrame({
            "funding_rate": [0.001] * 5,
            "open_interest_usd": [1000.0] * 5,
            "btc_long_short_ratio": [0.9] * 5,
            "etf_net_inflow_usd": [0.0] * 5,
            # btc_quote_volume 없음
        })
        from morning_brief.analysis.sentiment_join.join import _add_futures_lag_columns
        result = _add_futures_lag_columns(df)

        assert "volume_change_pct" in result.columns
        assert "volume_change_pct_lag1" in result.columns
        assert result["volume_change_pct"].isna().all()
    ```

  - [x] 4.3 `usdkrw_log_return_lag1` 컬럼 테스트

    ```python
    def test_add_sentiment_lag_columns_includes_usdkrw_lag1() -> None:
        """usdkrw_log_return이 있으면 lag1 컬럼이 생성된다."""
        df = pd.DataFrame({
            "news_sentiment_mean": [0.1, 0.2, 0.3],
            "fng_value": pd.array([50, 60, 55], dtype="Int64"),
            "usdkrw_log_return": [0.001, -0.002, 0.003],
        })
        from morning_brief.analysis.sentiment_join.join import _add_sentiment_lag_columns
        result = _add_sentiment_lag_columns(df)

        assert "usdkrw_log_return_lag1" in result.columns
        assert pd.isna(result["usdkrw_log_return_lag1"].iloc[0])
        assert result["usdkrw_log_return_lag1"].iloc[1] == pytest.approx(0.001)
    ```

  - [x] 4.4 `merge_sources` btc_quote_volume 누락 방어 통합 테스트

    btc_returns_df에 `btc_quote_volume` 컬럼이 없는 상태로 `merge_sources`를 호출했을 때
    KeyError 없이 완료되고, 결과에 `volume_change_pct` 컬럼이 NaN으로 존재함을 확인.

- [x] 5. `validate.py` — MASTER_SCHEMA 신규 컬럼 4개 추가

  `strict=True` 스키마에 아래 컬럼을 추가한다. 추가하지 않으면 `validate_master` 호출 시
  `SchemaError`가 발생한다(unexpected column).

  ```python
  # §3: Granger raw predictors — Granger 내부에서 lag 처리, double-lag 방지
  "oi_change_pct":         pa.Column(float, nullable=True),
  "volume_change_pct":     pa.Column(float, nullable=True),
  # §5: PCA / correlation용 lag1 (Granger에는 미사용)
  "usdkrw_log_return_lag1":  pa.Column(float, nullable=True),
  "volume_change_pct_lag1":  pa.Column(float, nullable=True),
  ```

  배치 위치: 기존 `"oi_change_pct_lag1"` 바로 위에 `"oi_change_pct"` 삽입,
  `"etf_net_inflow_usd_lag1"` 아래에 나머지 3개 삽입.

  _Requirements: §10 validate.py_

- [x] 6. `test_validate.py` — 신규 컬럼 스키마 테스트

  - [x] 6.1 신규 4개 컬럼을 포함한 DataFrame이 `validate_master` 통과 확인
  - [x] 6.2 신규 4개 컬럼 중 하나라도 없으면 `SchemaError` 발생 확인 (`strict=True` 보장)

    ```python
    @pytest.mark.parametrize("missing_col", [
        "oi_change_pct", "volume_change_pct",
        "usdkrw_log_return_lag1", "volume_change_pct_lag1",
    ])
    def test_validate_master_fails_without_new_columns(
        missing_col: str, valid_master_df: pd.DataFrame
    ) -> None:
        """strict=True: task 03 신규 컬럼이 없으면 SchemaError가 발생해야 한다."""
        df = valid_master_df.drop(columns=[missing_col])
        with pytest.raises(SchemaError):
            validate_master(df)
    ```

    ※ `valid_master_df` fixture는 기존 테스트 fixture에 신규 4개 컬럼(NaN)을 추가해 재사용.

- [x] **Checkpoint 2** — `pytest tests/analysis/test_sentiment_join/test_join.py tests/analysis/test_sentiment_join/test_validate.py -v`

---

### 묶음 C — hybrid_index + pipeline 메타 (우선순위 3-5)

- [x] 7. `hybrid_index.py` — `volume_change_pct_lag1` PCA 추가 + schema v3

  - [x] 7.1 `HYBRID_FEATURE_CANDIDATES`에 `volume_change_pct_lag1` 추가

    ```python
    # Before (v2, 5개)
    HYBRID_FEATURE_CANDIDATES = [
        "news_sentiment_mean_lag1",
        "fng_value_lag1",
        "funding_rate_lag1",
        "btc_long_short_ratio_lag1",
        "etf_net_inflow_usd_lag1",
    ]

    # After (v3, 6개)
    HYBRID_FEATURE_CANDIDATES = [
        "news_sentiment_mean_lag1",
        "fng_value_lag1",
        "funding_rate_lag1",
        "btc_long_short_ratio_lag1",
        "etf_net_inflow_usd_lag1",
        "volume_change_pct_lag1",  # v3 신규: VIF gate가 funding_rate/OI와 공선성 시 자동 제거
    ]
    ```

    `usdkrw_log_return_lag1`은 PCA 미포함 (Granger 전용 채널, §5 참조).

  - [x] 7.2 `HYBRID_FEATURE_SCHEMA_VERSION` v2 → v3

    ```python
    # Before
    HYBRID_FEATURE_SCHEMA_VERSION = "v2"  # v1: 원본; v2: lag1 버전

    # After
    HYBRID_FEATURE_SCHEMA_VERSION = "v3"
    # v1: news_sentiment_mean/fng_value 원본
    # v2: _lag1 버전 (look-ahead bias 제거)
    # v3: volume_change_pct_lag1 추가. usdkrw_log_return_lag1은 Granger 전용으로 PCA 제외.
    ```

    _Requirements: §5_

- [x] 8. `test_hybrid_index.py` — HYBRID_FEATURE_CANDIDATES 변화 반영

  - [x] 8.1 `volume_change_pct_lag1` 포함 확인

    ```python
    def test_hybrid_feature_candidates_includes_volume() -> None:
        from morning_brief.analysis.sentiment_join.hybrid_index import HYBRID_FEATURE_CANDIDATES
        assert "volume_change_pct_lag1" in HYBRID_FEATURE_CANDIDATES
    ```

  - [x] 8.2 `HYBRID_FEATURE_SCHEMA_VERSION == "v3"` 확인

  - [x] 8.3 `volume_change_pct_lag1`이 전부 NaN일 때 VIF gate가 제거하고 나머지로 PCA 완료

    ```python
    def test_compute_hybrid_index_removes_all_nan_volume_feature() -> None:
        """volume_change_pct_lag1이 NaN만 있으면 VIF gate가 제거하고 PCA가 완료돼야 한다."""
        import numpy as np
        rng = np.random.default_rng(0)
        n = 30
        df = pd.DataFrame({
            "news_sentiment_mean_lag1":    rng.normal(0, 0.1, n),
            "fng_value_lag1":              rng.uniform(30, 70, n),
            "funding_rate_lag1":           rng.normal(0, 0.001, n),
            "btc_long_short_ratio_lag1":   rng.uniform(0.8, 1.2, n),
            "etf_net_inflow_usd_lag1":     rng.normal(0, 1e6, n),
            "volume_change_pct_lag1":      [float("nan")] * n,  # 전부 NaN
        })
        result = compute_hybrid_index(df)
        # NaN 컬럼은 dropna() 단계에서 제거 → 나머지로 PCA 완료
        assert result.attrs["hybrid_index_diagnostics"]["pca_summary"]["status"] in (
            "ok", "insufficient_rows", "insufficient_features"
        )
    ```

- [x] 9. `pipeline.py` — `_build_granger_correction`에 `granger_method` 필드 추가

  ```python
  # Before
  def _build_granger_correction(statistical_results: dict[str, object]) -> dict[str, object]:
      granger = statistical_results.get("granger")
      n_tests = len(granger) if isinstance(granger, list) else 0
      return {
          "method": "bh_fdr",
          "n_tests": n_tests,
          "bonferroni_threshold": round(0.05 / n_tests, 10) if n_tests > 0 else None,
      }

  # After
  def _build_granger_correction(statistical_results: dict[str, object]) -> dict[str, object]:
      granger = statistical_results.get("granger")
      n_tests = len(granger) if isinstance(granger, list) else 0
      return {
          "method": "bh_fdr",
          "granger_method": "pairwise_granger",  # §6: 후속 VAR 확장 시 구분 포인트
          "n_tests": n_tests,
          "bonferroni_threshold": round(0.05 / n_tests, 10) if n_tests > 0 else None,
      }
  ```

  _Requirements: §10 etf_storage.py_

- [x] **Checkpoint 3** — `pytest tests/analysis/test_sentiment_join/test_hybrid_index.py tests/analysis/test_sentiment_join/test_pipeline.py -v`

---

### 묶음 D — usdkrw 채널 근거 + 검정력 경고 (우선순위 3-4)

- [x] 10. `statistical_tests.py` — usdkrw 채널 근거 주석 + 검정력 경고 메타

  - [x] 10.1 `_PREDICTORS_RAW` 또는 `GRANGER_PAIRS_TARGET` 선언부 근처에 usdkrw 근거 주석 추가

    ```python
    # usdkrw_log_return: 두 채널로 btc_log_return 선행 가능 (한국 투자자 차별화 지표)
    # (1) KIMP 채널: 원달러 변동 → 업비트·빗썸 프리미엄(KIMP) → 국내 BTC 유동성 전가
    # (2) 글로벌 리스크온/오프: USD 강세 → 리스크자산 매도 연쇄 → BTC 하방 압력
    # 채널 근거가 약하다고 판단될 경우 GRANGER_PAIRS_EXPLORATORY로 이동 고려 (§8)
    ```

    _Requirements: §8_

  - [x] 10.2 `run_statistical_tests` 반환 dict에 `power_warning` 메타 추가

    ```python
    # 기존 results["granger_executed"] 할당 직후에 추가
    if len(df) >= MIN_ROWS_FOR_GRANGER:
        results["power_warning"] = (
            f"n≈{len(df)}, BH-FDR, {len(granger_results)} tests: "
            "작은 효과(f²≈0.02)의 검정력은 약 20~40% 수준. "
            "'유의하지 않음'이 효과 부재가 아닌 검정력 부족에서 기인할 수 있음. "
            "360일 이상 확보 권장."
        )
    ```

    _Requirements: §3.D ⚠️_

- [x] 11. `test_statistical_tests.py` — `power_warning` 필드 테스트

  ```python
  def test_run_statistical_tests_includes_power_warning_when_granger_executed(
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      """Property W-1: granger_executed=True이면 power_warning 키가 존재해야 한다."""
      monkeypatch.setattr(statistical_tests, "_run_stationarity", lambda s: _STATIONARY_RESULT)
      monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", lambda *a, **kw: None)

      results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

      assert "power_warning" in results
      assert isinstance(results["power_warning"], str)

  def test_run_statistical_tests_no_power_warning_when_insufficient_rows() -> None:
      """Property W-2: 180행 미만이면 power_warning 키가 없어야 한다 (empty dict 반환)."""
      results = statistical_tests.run_statistical_tests(_sample_df(rows=10))
      assert "power_warning" not in results
  ```

- [x] **Checkpoint 4 (최종)** — `make check`

  통과 기준:
  - `pytest tests/analysis/test_sentiment_join/ -v` 전체 green
  - `mypy src/morning_brief/analysis/sentiment_join/ --strict` 오류 없음
  - `ruff check src/ tests/` 오류 없음

---

## 미포함 항목 (PR-E 이후 별도 이슈)

| 항목 | 사유 |
|---|---|
| **§9 Regime 안정성 점검** | 180일 전/후 분할 Granger, `ruptures` breakpoint — 작업 비용 대비 효과 불확실 |
| **§6 VAR/IRF 확장** | `statsmodels.tsa.vector_ar` 다변량 조건부 Granger — `granger_method="pairwise_granger"` 기록으로 확장 포인트만 남김 |
| **GRANGER_PAIRS_EXPLORATORY** | `usdkrw_log_return` 채널 근거 검토 후 분리 여부 판단 — 현재는 CORE 유지 |
