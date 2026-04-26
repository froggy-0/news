from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join import statistical_tests
from morning_brief.analysis.sentiment_join.statistical_tests import (
    TransferEntropy,
    _apply_bh_correction,
    _run_granger_all_lags,
    stationarity_check,
    walk_forward_validate,
)


def _sample_df(rows: int = 35) -> pd.DataFrame:
    """§0: GRANGER_PAIRS는 raw 컬럼을 사용한다 (double-lag 방지).
    _lag1 컬럼도 포함해 ADF_TARGETS 검정 및 기존 테스트와 공존한다.
    """
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-03-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            # raw (Granger + ADF 용)
            "news_sentiment_mean": [0.1] * rows,
            "fng_value": pd.array([55] * rows, dtype="Int64"),
            "funding_rate": [0.001] * rows,
            "btc_long_short_ratio": [0.9] * rows,
            "oi_change_pct": [0.01] * rows,
            "etf_net_inflow_usd": [1_000_000.0] * rows,
            "usdkrw_log_return": [0.001] * rows,
            "volume_change_pct": [0.02] * rows,
            "btc_log_return": [0.01] * rows,
            # _lag1 (PCA / correlation 용 — 기존 테스트 호환)
            "news_sentiment_mean_lag1": [0.1] * rows,
            "fng_value_lag1": [55.0] * rows,
            "funding_rate_lag1": [0.001] * rows,
            "btc_long_short_ratio_lag1": [0.9] * rows,
            "etf_net_inflow_usd_lag1": [1_000_000.0] * rows,
        }
    )


def test_run_statistical_tests_skips_when_rows_are_insufficient() -> None:
    results = statistical_tests.run_statistical_tests(_sample_df(rows=10))
    assert results == {}


_STATIONARY_RESULT = {
    "adf_statistic": -3.0,
    "adf_pvalue": 0.01,
    "kpss_statistic": 0.1,
    "kpss_pvalue": 0.10,
    "stationary": True,
    "conclusion": "stationary",
}


def test_run_statistical_tests_stationarity_runs_at_30_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADF+KPSS 공동검정은 30행 이상이면 실행된다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=35))

    assert "stationarity_results" in results
    assert "btc_log_return" in results["stationarity_results"]
    assert "adf" not in results  # 구 키 제거 확인


def test_run_statistical_tests_granger_skips_at_179_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 179행이면 Granger 미실행."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )
    pair_calls: list[tuple] = []

    def fake_granger_all_lags(df, predictor, target, max_lag=3, *, skip_collector=None):
        pair_calls.append((predictor, target))
        return None  # skip

    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", fake_granger_all_lags)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=179))

    assert results["granger"] == []
    assert pair_calls == []
    assert results["granger_executed"] is False
    assert results["granger_eligible_rows"] == 179


def test_run_statistical_tests_granger_runs_at_180_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 180행이면 Granger 실행. forward(18: TARGET 10 + CROSS 8) + reverse(5) = 23쌍, 각 3 lag → 69 entry."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )
    pair_calls: list[tuple] = []

    def fake_granger_all_lags(df, predictor, target, max_lag=3, *, skip_collector=None):
        pair_calls.append((predictor, target))
        return [
            {
                "predictor": predictor,
                "target": target,
                "lag": lag,
                "pvalue": 0.04,
                "pvalue_raw": 0.04,
            }
            for lag in range(1, max_lag + 1)
        ]

    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", fake_granger_all_lags)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    # forward(18: TARGET 10 + CROSS 8) + reverse(5) = 23쌍, 각 3 lag → 69 entry
    assert len(pair_calls) == 23
    assert len(results["granger"]) == 69
    assert results["granger_executed"] is True
    assert results["granger_eligible_rows"] == 180


def test_run_statistical_tests_records_granger_pair_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )

    def fake_granger_all_lags(df, predictor, target, max_lag=3, *, skip_collector=None):
        if skip_collector is not None:
            skip_collector.append(
                {"predictor": predictor, "target": target, "reason": "unit_test_skip"}
            )
        return None

    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", fake_granger_all_lags)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    assert len(results["granger_skips"]) == 23
    assert results["granger_skip_summary"] == {"unit_test_skip": 23}
    assert {row["direction"] for row in results["granger_skips"]} == {"forward", "reverse"}


def test_run_granger_all_lags_records_missing_column_skip() -> None:
    skips: list[dict] = []
    result = _run_granger_all_lags(
        _sample_df(rows=180),
        "missing_predictor",
        "btc_log_return",
        max_lag=3,
        skip_collector=skips,
    )

    assert result is None
    assert skips == [
        {
            "predictor": "missing_predictor",
            "target": "btc_log_return",
            "reason": "missing_column",
            "missing_columns": ["missing_predictor"],
        }
    ]


def test_run_statistical_tests_returns_stationarity_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """결과 dict에 stationarity_results 키가 존재하고 adf 키는 없어야 한다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )
    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert isinstance(results["stationarity_results"], dict)
    assert "btc_log_return" in results["stationarity_results"]
    assert "adf" not in results


def test_run_statistical_tests_skips_missing_stationarity_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = _sample_df().drop(columns=["btc_long_short_ratio"])
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )
    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(df)

    assert "btc_long_short_ratio" not in results["stationarity_results"]
    assert "btc_log_return" in results["stationarity_results"]


def test_run_statistical_tests_isolates_stationarity_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert results["granger"] == []


def test_adf_and_granger_thresholds_are_independent() -> None:
    """ADF 기준(30)과 Granger 기준(180)이 독립적인지 확인."""
    assert statistical_tests.MIN_ROWS_FOR_ADF == 30
    assert statistical_tests.MIN_ROWS_FOR_GRANGER == 180


def test_stationarity_check_reports_insufficient_rows() -> None:
    result = stationarity_check(pd.Series([0.1] * 3))

    assert result["conclusion"] == "insufficient_rows"
    assert result["stationary"] is False


def test_transfer_entropy_returns_warning_free_rows() -> None:
    rows = 60
    df = pd.DataFrame(
        {
            "x": np.sin(np.arange(rows) / 4),
            "y": np.sin((np.arange(rows) - 1) / 4),
        }
    )

    result = TransferEntropy(max_lag=2, bins=3, min_rows=20).fit(df, "x", "y")

    assert result
    assert all(row["warning"] is None for row in result)


def test_walk_forward_validate_expanding_window_metadata() -> None:
    rows = 220
    idx = np.arange(rows)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "news_sentiment_mean_lag1": np.sin(idx / 5),
            "fng_value_lag1": 50 + np.cos(idx / 4) * 20,
            "funding_rate_lag1": np.sin(idx / 7) * 0.001,
            "btc_long_short_ratio_lag1": 0.9 + np.cos(idx / 6) * 0.1,
            "etf_net_inflow_usd_lag1": np.sin(idx / 8) * 100000.0,
            "volume_change_pct_lag1": np.cos(idx / 9) * 0.05,
            "vix_lag1": 18 + np.sin(idx / 10) * 3,
            "btc_log_return": np.sin(idx / 6) * 0.01,
            "btc_direction_label": ["up" if v > 0 else "down" for v in np.sin(idx / 6)],
        }
    )

    result = walk_forward_validate(
        df,
        train_days=80,
        test_days=20,
        horizon_days=3,
        purged_kfold=True,
        expanding_window=True,
    )

    assert result is not None
    assert result.embargo_days == 5
    assert result.purged_kfold is True
    assert result.expanding_window is True

    purged_t1 = walk_forward_validate(
        df,
        train_days=80,
        test_days=20,
        horizon_days=1,
        purged_kfold=True,
    )
    assert purged_t1 is not None
    assert purged_t1.embargo_days == 5


# ── §4.2: BH 다중검정 보정 테스트 ──


def test_apply_bh_correction_adds_adjusted_pvalue() -> None:
    """§4.2: BH 보정 후 pvalue_adjusted 필드가 추가되어야 한다."""
    entries = [
        {
            "predictor": "a",
            "target": "b",
            "lag": 1,
            "pvalue": 0.01,
            "pvalue_raw": 0.01,
            "significant": True,
        },
        {
            "predictor": "c",
            "target": "b",
            "lag": 1,
            "pvalue": 0.20,
            "pvalue_raw": 0.20,
            "significant": False,
        },
        {
            "predictor": "d",
            "target": "b",
            "lag": 1,
            "pvalue": 0.50,
            "pvalue_raw": 0.50,
            "significant": False,
        },
    ]
    corrected = _apply_bh_correction(entries)

    assert all("pvalue_adjusted" in e for e in corrected)
    assert all("pvalue_raw" in e for e in corrected)


def test_apply_bh_correction_significant_uses_adjusted_pvalue() -> None:
    """§4.2: significant 플래그는 pvalue_adjusted < 0.05 기준으로 설정되어야 한다."""
    # p-value가 0.06이면 BH 보정 후 모두 0.06 → 0.05 초과 → significant=False
    # BH step-up: rank k에서 adj = 0.06 * 10/k, 최소값(rank 10) = 0.06 > 0.05
    entries = [
        {
            "predictor": f"x{i}",
            "target": "b",
            "lag": 1,
            "pvalue": 0.06,
            "pvalue_raw": 0.06,
            "significant": True,
        }
        for i in range(10)
    ]
    corrected = _apply_bh_correction(entries)

    # step-up 후 모두 pvalue_adjusted = 0.06 > 0.05 → significant=False
    assert not any(e["significant"] for e in corrected)


def test_apply_bh_correction_empty_returns_empty() -> None:
    """§4.2: 빈 입력에 대해 빈 리스트를 반환해야 한다."""
    assert _apply_bh_correction([]) == []


def test_apply_bh_correction_single_entry_preserves_significance() -> None:
    """§4.2: 단일 항목은 보정이 없으므로 원본 p-value = adjusted p-value."""
    entries = [
        {
            "predictor": "a",
            "target": "b",
            "lag": 1,
            "pvalue": 0.03,
            "pvalue_raw": 0.03,
            "significant": True,
        }
    ]
    corrected = _apply_bh_correction(entries)

    assert corrected[0]["pvalue_adjusted"] == pytest.approx(0.03)
    assert corrected[0]["significant"] is True


# ── §4.1: 정상성 gate 테스트 ──


def test_ensure_stationary_returns_series_when_stationary(monkeypatch: pytest.MonkeyPatch) -> None:
    """§4.1: ADF+KPSS 공동검정 통과 시계열은 원본을 그대로 반환해야 한다."""
    import numpy as np

    from morning_brief.analysis.sentiment_join.statistical_tests import _ensure_stationary

    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.statistical_tests.MIN_ROWS_FOR_ADF", 5
    )
    series = pd.Series(np.random.randn(30))
    # _run_stationarity를 monkeypatch로 정상 판정
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda s: _STATIONARY_RESULT,
    )

    result, is_stationary, was_differenced = _ensure_stationary(series)

    assert is_stationary is True
    assert was_differenced is False


# ── §1 KPSS 공동검정 신규 케이스 ──


def test_run_stationarity_stationary_when_adf_and_kpss_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property C-1 (정상): ADF p<0.05 + KPSS p>0.05 → conclusion='stationary', stationary=True."""
    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.1, 0.10, None, {}))

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_stationarity

    result = _run_stationarity(pd.Series([0.1] * 50))

    assert result["stationary"] is True
    assert result["conclusion"] == "stationary"


def test_run_stationarity_non_stationary_when_both_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADF p>=0.05 + KPSS p<=0.05 → conclusion='non_stationary', stationary=False."""
    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-1.0, 0.30, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.5, 0.01, None, {}))

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_stationarity

    result = _run_stationarity(pd.Series([float(i) for i in range(50)]))

    assert result["stationary"] is False
    assert result["conclusion"] == "non_stationary"


def test_run_stationarity_trend_stationary_on_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property C-1 (불일치): ADF p<0.05 + KPSS p<=0.05 → conclusion='trend_stationary', stationary=False."""
    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.5, 0.01, None, {}))

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_stationarity

    result = _run_stationarity(pd.Series([0.1] * 50))

    assert result["stationary"] is False
    assert result["conclusion"] == "trend_stationary"


def test_granger_skipped_when_stationarity_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property C-2: stationary=False인 predictor는 어떤 lag에도 Granger 결과를 생성하지 않아야 한다."""
    import statsmodels.tsa.stattools as _sts

    # ADF+KPSS 불일치 → stationary=False
    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.5, 0.01, None, {}))

    import numpy as np

    rng = np.random.default_rng(0)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_granger

    entry = _run_granger(df, "news_sentiment_mean_lag1", "btc_log_return", lag=1)

    # trend_stationary → stationary=False → Granger skip → None 반환
    assert entry is None


def test_granger_pairs_use_raw_predictors() -> None:
    """Property R-1: GRANGER_PAIRS의 모든 predictor는 raw(비-lag1) 컬럼이어야 한다.
    double-lag 방지: _lag1 버전을 투입하면 실제 검정 관계가 한 칸 더 밀린다.
    """
    for predictor, target in statistical_tests.GRANGER_PAIRS:
        assert not predictor.endswith("_lag1"), (
            f"predictor '{predictor}'가 raw가 아닙니다. double-lag 위험."
        )


def test_granger_pairs_count() -> None:
    """GRANGER_PAIRS = TARGET(10) + CROSS(8) = 18쌍."""
    assert len(statistical_tests.GRANGER_PAIRS_TARGET) == 10
    assert len(statistical_tests.GRANGER_PAIRS_CROSS) == 8
    assert len(statistical_tests.GRANGER_PAIRS) == 18


def test_granger_pairs_reverse_has_btc_as_predictor() -> None:
    """§4.3: GRANGER_PAIRS_REVERSE는 btc_log_return이 predictor, target은 raw여야 한다."""
    for predictor, target in statistical_tests.GRANGER_PAIRS_REVERSE:
        assert predictor == "btc_log_return"
        assert not target.endswith("_lag1"), (
            f"GRANGER_PAIRS_REVERSE target '{target}'이 raw가 아닙니다."
        )


def test_run_statistical_tests_granger_entries_have_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4.3: Granger 결과 각 항목에 direction 필드가 있어야 한다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_stationarity",
        lambda series: _STATIONARY_RESULT,
    )

    def fake_granger_all_lags(df, predictor, target, max_lag=3, *, skip_collector=None):
        return [
            {
                "predictor": predictor,
                "target": target,
                "lag": lag,
                "pvalue": 0.10,
                "pvalue_raw": 0.10,
            }
            for lag in range(1, max_lag + 1)
        ]

    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", fake_granger_all_lags)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    for entry in results["granger"]:
        assert "direction" in entry
        assert entry["direction"] in ("forward", "reverse")


# ── §5·§8: 쌍별 유효 행 수 + 달력 gap 진단 테스트 ──


def _sample_df_with_gap(rows: int = 200, gap_start: int = 50, gap_days: int = 3) -> pd.DataFrame:
    """중간에 달력 gap이 있는 샘플 DataFrame 생성."""
    import numpy as np

    dates_before = pd.date_range("2025-01-01", periods=gap_start, freq="D")
    dates_after = pd.date_range(
        dates_before[-1] + pd.Timedelta(days=gap_days + 1), periods=rows - gap_start, freq="D"
    )
    dates = list(dates_before.strftime("%Y-%m-%d")) + list(dates_after.strftime("%Y-%m-%d"))
    n = len(dates)
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "date": dates,
            # raw
            "news_sentiment_mean": rng.normal(0, 0.1, n),
            "fng_value": pd.array([55] * n, dtype="Int64"),
            "funding_rate": [0.001] * n,
            "btc_long_short_ratio": [0.9] * n,
            "oi_change_pct": [0.01] * n,
            "etf_net_inflow_usd": [1_000_000.0] * n,
            "usdkrw_log_return": [0.001] * n,
            "volume_change_pct": [0.02] * n,
            "btc_log_return": rng.normal(0, 0.02, n),
            # _lag1 (기존 테스트 호환)
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
            "fng_value_lag1": [55.0] * n,
            "funding_rate_lag1": [0.001] * n,
            "btc_long_short_ratio_lag1": [0.9] * n,
            "etf_net_inflow_usd_lag1": [1_000_000.0] * n,
        }
    )


def test_calendar_span_returns_correct_days() -> None:
    """_calendar_span이 날짜 시리즈의 max-min 일수를 반환해야 한다."""
    from morning_brief.analysis.sentiment_join.statistical_tests import _calendar_span

    dates = pd.Series(["2026-01-01", "2026-01-05", "2026-01-10"])
    assert _calendar_span(dates) == 9  # 10 - 1


def test_calendar_span_returns_zero_for_single_date() -> None:
    from morning_brief.analysis.sentiment_join.statistical_tests import _calendar_span

    assert _calendar_span(pd.Series(["2026-01-01"])) == 0


def test_max_consecutive_gap_detects_gap() -> None:
    """_max_consecutive_gap이 불연속 구간의 최대 갭 일수를 반환해야 한다."""
    from morning_brief.analysis.sentiment_join.statistical_tests import _max_consecutive_gap

    # 2026-01-01, 2026-01-02, 2026-01-05 → gap=3
    dates = pd.Series(["2026-01-01", "2026-01-02", "2026-01-05"])
    assert _max_consecutive_gap(dates) == 3


def test_max_consecutive_gap_returns_one_for_contiguous() -> None:
    """연속된 날짜에서는 최대 갭이 1이어야 한다."""
    from morning_brief.analysis.sentiment_join.statistical_tests import _max_consecutive_gap

    dates = pd.Series(pd.date_range("2026-01-01", periods=10, freq="D").strftime("%Y-%m-%d"))
    assert _max_consecutive_gap(dates) == 1


def test_run_granger_returns_effective_rows_and_gap_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property B-4: effective_rows, calendar_span_days, max_consecutive_gap_days 필드가 존재해야 한다."""
    import numpy as np

    rng = np.random.default_rng(0)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_granger

    entry = _run_granger(df, "news_sentiment_mean_lag1", "btc_log_return", lag=1)

    assert entry is not None
    assert "effective_rows" in entry
    assert "calendar_span_days" in entry
    assert "max_consecutive_gap_days" in entry
    assert entry["effective_rows"] > 0


def test_run_granger_adds_warning_for_non_contiguous_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property B-3: max_consecutive_gap_days > 1이면 warning='non_contiguous_dates'가 존재해야 한다."""
    import numpy as np

    rng = np.random.default_rng(1)
    # 중간에 5일 gap이 있는 날짜 시리즈
    dates_a = pd.date_range("2025-01-01", periods=100, freq="D")
    dates_b = pd.date_range("2025-05-01", periods=100, freq="D")  # gap ~100일
    dates = list(dates_a.strftime("%Y-%m-%d")) + list(dates_b.strftime("%Y-%m-%d"))
    n = len(dates)
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_granger

    entry = _run_granger(df, "news_sentiment_mean_lag1", "btc_log_return", lag=1)

    assert entry is not None
    assert entry["max_consecutive_gap_days"] > 1
    assert entry.get("warning") == "non_contiguous_dates"


# ── PR-D: _run_granger_all_lags / _select_optimal_lag / analytics_contract 테스트 ──


def test_run_granger_all_lags_returns_list_with_all_lags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property D-1: grangercausalitytests는 max_lag=3으로 단 1회만 호출되어야 한다."""
    import numpy as np

    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    import statsmodels.tsa.stattools as _sts

    gc_call_count = 0

    original_gc = _sts.grangercausalitytests

    def counting_gc(data, maxlag, verbose=False):
        nonlocal gc_call_count
        gc_call_count += 1
        return original_gc(data, maxlag=maxlag, verbose=False)

    monkeypatch.setattr(_sts, "grangercausalitytests", counting_gc)
    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.1, 0.10, None, {}))

    entries = _run_granger_all_lags(df, "news_sentiment_mean_lag1", "btc_log_return", max_lag=3)

    # Property D-1: grangercausalitytests 단 1회 호출
    assert gc_call_count == 1
    assert entries is not None
    assert len(entries) == 3
    assert [e["lag"] for e in entries] == [1, 2, 3]


def test_run_granger_all_lags_entries_have_f_statistic_and_df(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6·§7: 각 entry에 f_statistic, df_num, df_denom이 존재해야 한다."""
    import numpy as np

    rng = np.random.default_rng(7)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.1, 0.10, None, {}))

    entries = _run_granger_all_lags(df, "news_sentiment_mean_lag1", "btc_log_return", max_lag=3)

    assert entries is not None
    for entry in entries:
        assert "f_statistic" in entry
        assert "df_num" in entry
        assert "df_denom" in entry
        assert "optimal_lag" in entry
        assert "granger_primary" in entry
        assert "inference" in entry
        assert entry["inference"] == "ssr_ftest_ols"


def test_run_granger_all_lags_granger_primary_unique_per_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property D-2: granger_primary=True인 entry는 각 (predictor, target) 방향당 정확히 1개여야 한다."""
    import numpy as np

    rng = np.random.default_rng(99)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean_lag1": rng.normal(0, 0.1, n),
        }
    )

    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.1, 0.10, None, {}))

    entries = _run_granger_all_lags(df, "news_sentiment_mean_lag1", "btc_log_return", max_lag=3)

    assert entries is not None
    primary_count = sum(1 for e in entries if e["granger_primary"])
    # Property D-2: 한 쌍당 granger_primary=True는 정확히 1개
    assert primary_count == 1


# ── PR-D: analytics_contract _backfill 파라미터화 테스트 ──


def test_build_analytics_sentiment_payload_default_is_not_backfill() -> None:
    """build_analytics_sentiment_payload 기본값은 _backfill=False여야 한다."""
    from morning_brief.data.storage.analytics_contract import build_analytics_sentiment_payload

    payload = build_analytics_sentiment_payload(
        symbol="btc",
        run_date="2026-01-01",
        full_payload={
            "meta": {
                "sentimentStatus": "ok",
                "newsSentiment": {"mean": 0.1, "std": 0.05, "count": 5},
            }
        },
    )
    assert payload["_backfill"] is False


def test_build_analytics_sentiment_payload_is_backfill_true() -> None:
    """is_backfill=True를 전달하면 _backfill=True여야 한다."""
    from morning_brief.data.storage.analytics_contract import build_analytics_sentiment_payload

    payload = build_analytics_sentiment_payload(
        symbol="btc",
        run_date="2026-01-01",
        full_payload={
            "meta": {
                "sentimentStatus": "ok",
                "newsSentiment": {"mean": 0.1, "std": 0.05, "count": 5},
            }
        },
        is_backfill=True,
    )
    assert payload["_backfill"] is True


def test_validate_analytics_payload_passes_with_backfill_false() -> None:
    """Property D-3: _backfill=False여도 키가 존재하면 missing_backfill_marker 오류 없어야 한다."""
    from morning_brief.data.storage.analytics_contract import validate_analytics_sentiment_payload

    payload = {
        "schemaVersion": "v1",
        "producer": "public_site.publish_public_brief",
        "generatedAt": "2026-01-01T00:00:00Z",
        "date": "2026-01-01",
        "symbol": "btc",
        "sentimentStatus": "ok",
        "newsSentiment": {"mean": 0.1, "std": 0.05, "count": 5},
        "_backfill": False,
    }
    result = validate_analytics_sentiment_payload(payload)
    assert result["valid"] is True
    assert result["reason"] is None


def test_validate_analytics_payload_fails_without_backfill_key() -> None:
    """_backfill 키 자체가 없으면 missing_backfill_marker여야 한다."""
    from morning_brief.data.storage.analytics_contract import validate_analytics_sentiment_payload

    payload = {
        "schemaVersion": "v1",
        "producer": "public_site.publish_public_brief",
        "generatedAt": "2026-01-01T00:00:00Z",
        "date": "2026-01-01",
        "symbol": "btc",
        "sentimentStatus": "ok",
        "newsSentiment": {"mean": 0.1, "std": 0.05, "count": 5},
    }
    result = validate_analytics_sentiment_payload(payload)
    assert result["valid"] is False
    assert result["reason"] == "missing_backfill_marker"


# ── §0: double-lag 회귀 테스트 ──


def test_raw_and_lag1_predictor_produce_different_pvalues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property R-2: raw predictor와 _lag1 predictor는 Granger p-value가 달라야 한다.
    동일한 시리즈를 한 칸 밀면 검정되는 시간 관계가 달라지므로 결과도 달라야 한다.
    """
    import numpy as np
    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))
    monkeypatch.setattr(_sts, "kpss", lambda s, **kw: (0.1, 0.10, None, {}))

    rng = np.random.default_rng(7)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "btc_log_return": rng.normal(0, 0.02, n),
            "news_sentiment_mean": rng.normal(0, 0.1, n),
        }
    )
    df["news_sentiment_mean_lag1"] = df["news_sentiment_mean"].shift(1)

    from morning_brief.analysis.sentiment_join.statistical_tests import _run_granger

    entry_raw = _run_granger(df, "news_sentiment_mean", "btc_log_return", lag=1)
    entry_lag1 = _run_granger(df, "news_sentiment_mean_lag1", "btc_log_return", lag=1)

    assert entry_raw is not None
    assert entry_lag1 is not None
    assert entry_raw["pvalue"] != pytest.approx(entry_lag1["pvalue"]), (
        "raw와 _lag1 predictor의 p-value가 같습니다. double-lag 의심."
    )


# ── §3.D: power_warning 테스트 ──


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


# ── §10(b): fng_value Int64 target dtype 회귀 테스트 ──


def test_run_granger_all_lags_handles_fng_value_as_target_int64() -> None:
    """Property INT64: fng_value(Int64 nullable)가 cross pair TARGET일 때 오류 없이 완료된다.
    GRANGER_PAIRS_CROSS에 ("news_sentiment_mean", "fng_value")가 있으므로 반드시 동작해야 한다.
    _run_granger_all_lags 내부 pd.to_numeric(target, errors="coerce")가 이를 처리한다.
    """
    import numpy as np

    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame(
        {
            "date": dates,
            "news_sentiment_mean": rng.normal(0, 0.1, n),
            "fng_value": pd.array(rng.integers(20, 80, n).tolist(), dtype="Int64"),
        }
    )

    # 실제 통계 라이브러리 호출 — Int64 dtype이 문제 없이 float 변환되어야 한다
    entries = _run_granger_all_lags(df, "news_sentiment_mean", "fng_value", max_lag=3)

    # 정상성 gate를 통과하면 list, 미통과하면 None — 어떤 경우도 예외가 없어야 한다
    assert entries is None or isinstance(entries, list)


# ── §10(c): BH-FDR 보정 결과 스키마 테스트 ──


def test_granger_results_schema_has_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property BH-SCHEMA: cross pair 포함 전체 Granger 결과에 필수 스키마 필드가 존재해야 한다.
    pvalue_raw, pvalue_adjusted, significant, direction — §3.D 결과 구조.
    """
    monkeypatch.setattr(statistical_tests, "_run_stationarity", lambda s: _STATIONARY_RESULT)

    def fake_granger_all_lags(df, predictor, target, max_lag=3, *, skip_collector=None):
        return [
            {
                "predictor": predictor,
                "target": target,
                "lag": lag,
                "pvalue": 0.04,
                "pvalue_raw": 0.04,
            }
            for lag in range(1, max_lag + 1)
        ]

    monkeypatch.setattr(statistical_tests, "_run_granger_all_lags", fake_granger_all_lags)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    assert len(results["granger"]) > 0
    for entry in results["granger"]:
        assert "pvalue_raw" in entry, f"pvalue_raw 누락: {entry}"
        assert "pvalue_adjusted" in entry, f"pvalue_adjusted 누락: {entry}"
        assert "significant" in entry, f"significant 누락: {entry}"
        assert "direction" in entry, f"direction 누락: {entry}"
        assert isinstance(entry["significant"], bool)
        assert entry["direction"] in ("forward", "reverse")
