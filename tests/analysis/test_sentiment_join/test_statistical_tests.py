from __future__ import annotations

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join import statistical_tests
from morning_brief.analysis.sentiment_join.statistical_tests import _apply_bh_correction


def _sample_df(rows: int = 35) -> pd.DataFrame:
    """§1: GRANGER_PAIRS가 lag1 컬럼을 사용하므로 news_sentiment_mean_lag1, fng_value_lag1 포함."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-03-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "news_sentiment_mean": [0.1] * rows,
            "news_sentiment_mean_lag1": [0.1] * rows,
            "fng_value": pd.array([55] * rows, dtype="Int64"),
            "fng_value_lag1": [55.0] * rows,
            "funding_rate_lag1": [0.001] * rows,
            "btc_log_return": [0.01] * rows,
            "btc_long_short_ratio": [0.9] * rows,
            "btc_long_short_ratio_lag1": [0.9] * rows,
            "etf_net_inflow_usd_lag1": [1000000.0] * rows,
        }
    )


def test_run_statistical_tests_skips_when_rows_are_insufficient() -> None:
    results = statistical_tests.run_statistical_tests(_sample_df(rows=10))
    assert results == {}


def test_run_statistical_tests_adf_runs_at_30_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADF는 30행 이상이면 실행된다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=35))

    assert "adf" in results
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_granger_skips_at_179_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 179행이면 Granger 미실행."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    granger_calls: list[tuple] = []

    def fake_granger(df, predictor, target, lag):
        granger_calls.append((predictor, target, lag))
        return {"predictor": predictor, "target": target, "lag": lag, "pvalue": 0.04}

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=179))

    assert results["granger"] == []
    assert granger_calls == []
    assert results["granger_executed"] is False
    assert results["granger_eligible_rows"] == 179


def test_run_statistical_tests_granger_runs_at_180_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6: 180행이면 Granger 실행. §4.3 역방향 포함 → 10쌍 × 3 lags = 30 호출."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    granger_calls: list[tuple] = []

    def fake_granger(df, predictor, target, lag):
        granger_calls.append((predictor, target, lag))
        return {
            "predictor": predictor,
            "target": target,
            "lag": lag,
            "pvalue": 0.04,
            "pvalue_raw": 0.04,
        }

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    # §4.3: 순방향(5) + 역방향(5) × 3 lags = 30 호출
    assert len(granger_calls) == 30
    assert len(results["granger"]) == 30
    assert results["granger_executed"] is True
    assert results["granger_eligible_rows"] == 180


def test_run_statistical_tests_returns_multi_adf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert isinstance(results["adf"], dict)
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_skips_missing_adf_column(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _sample_df().drop(columns=["btc_long_short_ratio"])
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(df)

    assert "btc_long_short_ratio" not in results["adf"]
    assert "btc_log_return" in results["adf"]


def test_run_statistical_tests_isolates_adf_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(statistical_tests, "_run_granger", lambda *args, **kwargs: None)

    results = statistical_tests.run_statistical_tests(_sample_df())

    assert results["granger"] == []


def test_adf_and_granger_thresholds_are_independent() -> None:
    """ADF 기준(30)과 Granger 기준(180)이 독립적인지 확인."""
    assert statistical_tests.MIN_ROWS_FOR_ADF == 30
    assert statistical_tests.MIN_ROWS_FOR_GRANGER == 180


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
    """§4.1: ADF p<0.05인 시계열은 원본을 그대로 반환해야 한다."""
    import numpy as np

    from morning_brief.analysis.sentiment_join.statistical_tests import _ensure_stationary

    monkeypatch.setattr(
        "morning_brief.analysis.sentiment_join.statistical_tests.MIN_ROWS_FOR_ADF", 5
    )
    series = pd.Series(np.random.randn(30))
    # ADF를 monkeypatch
    import statsmodels.tsa.stattools as _sts

    monkeypatch.setattr(_sts, "adfuller", lambda s, **kw: (-5.0, 0.001, None, None, {}, None))

    result, is_stationary, was_differenced = _ensure_stationary(series)

    assert is_stationary is True
    assert was_differenced is False


def test_granger_pairs_use_lag1_predictors() -> None:
    """§1: 모든 GRANGER_PAIRS predictor는 lag1 버전이어야 한다."""
    for predictor, target in statistical_tests.GRANGER_PAIRS:
        assert predictor.endswith("_lag1") or predictor == "btc_log_return", (
            f"predictor '{predictor}'가 lag1 버전이 아닙니다."
        )


def test_granger_pairs_reverse_has_btc_as_predictor() -> None:
    """§4.3: GRANGER_PAIRS_REVERSE는 btc_log_return이 predictor여야 한다."""
    for predictor, target in statistical_tests.GRANGER_PAIRS_REVERSE:
        assert predictor == "btc_log_return"


def test_run_statistical_tests_granger_entries_have_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4.3: Granger 결과 각 항목에 direction 필드가 있어야 한다."""
    monkeypatch.setattr(
        statistical_tests,
        "_run_adf",
        lambda series: {"statistic": -3.0, "pvalue": 0.01, "stationary": True},
    )

    def fake_granger(df, predictor, target, lag):
        return {
            "predictor": predictor,
            "target": target,
            "lag": lag,
            "pvalue": 0.10,
            "pvalue_raw": 0.10,
        }

    monkeypatch.setattr(statistical_tests, "_run_granger", fake_granger)

    results = statistical_tests.run_statistical_tests(_sample_df(rows=180))

    for entry in results["granger"]:
        assert "direction" in entry
        assert entry["direction"] in ("forward", "reverse")
