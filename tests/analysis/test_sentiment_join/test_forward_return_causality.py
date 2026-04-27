"""Forward-return causality tests.

`btc_fwd_ret_Nd[t]` must depend ONLY on `btc_log_return[s]` for `s > t`.
Perturbing past or current returns must not change `btc_fwd_ret_Nd[t]`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.join import _add_forward_target_columns


def _make_df(n: int = 40, *, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "btc_log_return": rng.normal(0.0, 0.02, n),
        }
    )


@pytest.mark.parametrize("horizon", [1, 3, 7])
def test_perturbing_past_returns_does_not_change_forward_target(horizon: int) -> None:
    """t 시점 forward target 은 t-k(k≥0) 시점 수익률 변경에 영향받지 않아야 한다."""
    base = _make_df()
    perturbed = base.copy()
    target_idx = 25  # forward target 평가 시점 (마지막 horizon 행은 NaN 이라 안전 마진 확보)
    perturbed.loc[:target_idx, "btc_log_return"] += 0.10  # past + present 모두 흔들기

    base_out = _add_forward_target_columns(base)
    perturbed_out = _add_forward_target_columns(perturbed)

    col = f"btc_fwd_ret_{horizon}d"
    assert base_out[col].iloc[target_idx] == pytest.approx(perturbed_out[col].iloc[target_idx])


@pytest.mark.parametrize("horizon", [1, 3, 7])
def test_perturbing_future_returns_does_change_forward_target(horizon: int) -> None:
    """sanity: t+1..t+horizon 변경은 forward target 을 반드시 바꿔야 한다."""
    base = _make_df()
    perturbed = base.copy()
    target_idx = 25
    perturbed.loc[target_idx + 1 : target_idx + horizon, "btc_log_return"] += 0.10

    base_out = _add_forward_target_columns(base)
    perturbed_out = _add_forward_target_columns(perturbed)

    col = f"btc_fwd_ret_{horizon}d"
    assert not np.isclose(base_out[col].iloc[target_idx], perturbed_out[col].iloc[target_idx]), (
        f"{col}[{target_idx}] should reflect future return change"
    )


@pytest.mark.parametrize("horizon", [1, 3, 7])
def test_last_horizon_rows_are_nan(horizon: int) -> None:
    """마지막 horizon 행은 NaN 이어야 한다 (lookahead 차단)."""
    out = _add_forward_target_columns(_make_df())
    col = f"btc_fwd_ret_{horizon}d"
    assert out[col].iloc[-horizon:].isna().all()
    if horizon < len(out):
        assert out[col].iloc[-horizon - 1 : -horizon].notna().all()


def test_btc_fwd_ret_1d_equals_next_day_return() -> None:
    """btc_fwd_ret_1d[t] == btc_log_return[t+1]."""
    df = _make_df()
    out = _add_forward_target_columns(df)
    expected = df["btc_log_return"].shift(-1).reset_index(drop=True)
    actual = out["btc_fwd_ret_1d"].reset_index(drop=True)
    pd.testing.assert_series_equal(actual, expected, check_names=False, check_dtype=False)


@pytest.mark.parametrize("horizon", [3, 7])
def test_btc_fwd_ret_kd_equals_cumulative_log_return(horizon: int) -> None:
    """btc_fwd_ret_kd[t] == sum(btc_log_return[t+1..t+k])."""
    df = _make_df()
    out = _add_forward_target_columns(df)
    expected = (
        df["btc_log_return"]
        .shift(-1)
        .rolling(horizon, min_periods=horizon)
        .sum()
        .shift(-(horizon - 1))
        .reset_index(drop=True)
    )
    actual = out[f"btc_fwd_ret_{horizon}d"].reset_index(drop=True)
    pd.testing.assert_series_equal(
        actual.dropna().reset_index(drop=True),
        expected.dropna().reset_index(drop=True),
        check_names=False,
        check_dtype=False,
        atol=1e-12,
    )
