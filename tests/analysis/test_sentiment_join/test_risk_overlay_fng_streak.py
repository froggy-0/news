from __future__ import annotations

import pandas as pd

from morning_brief.analysis.sentiment_join.risk_overlay import (
    _fng_streak_below,
    compute_regime_state,
)


def test_fng_streak_below_counts_consecutive_days_from_end() -> None:
    # 최근 3일 연속 <30 (공포 지속), 그 전은 무관.
    series = pd.Series([50.0, 45.0, 35.0, 25.0, 20.0, 15.0])
    assert _fng_streak_below(series, 30.0) == 3


def test_fng_streak_below_zero_when_last_value_at_or_above_threshold() -> None:
    series = pd.Series([10.0, 15.0, 35.0])
    assert _fng_streak_below(series, 30.0) == 0


def test_fng_streak_below_stops_at_nan() -> None:
    # 결측은 스트릭 중단(보수적) — NaN 이전 값은 세지 않는다.
    series = pd.Series([10.0, float("nan"), 20.0, 15.0])
    assert _fng_streak_below(series, 30.0) == 2


def test_fng_streak_below_empty_series_returns_none() -> None:
    assert _fng_streak_below(pd.Series(dtype=float), 30.0) is None


def test_fng_streak_below_all_below_threshold() -> None:
    series = pd.Series([25.0, 20.0, 15.0, 10.0])
    assert _fng_streak_below(series, 30.0) == 4


def test_compute_regime_state_exposes_fng_days_below_30_in_raw() -> None:
    df = pd.DataFrame(
        {
            "fng_value": [50.0, 40.0, 28.0, 22.0, 18.0],
            "vix": [15.0] * 5,
            "btc_realized_vol_20d_lag1": [0.4] * 5,
        }
    )
    state = compute_regime_state(df)
    assert state.raw["fng_days_below_30"] == 3
