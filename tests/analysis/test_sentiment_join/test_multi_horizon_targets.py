from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.join import (
    FORWARD_TARGET_COLUMNS,
    FWD_LARGE_MOVE_3D_THRESHOLD,
    _add_forward_target_columns,
)


def _frame(rets: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(rets), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "btc_log_return": rets})


# ─────────────────────────────────────────────────────────────────────────────
# 정확성: T+1 shift 및 cumulative 계산
# ─────────────────────────────────────────────────────────────────────────────


def test_fwd_ret_1d_equals_negative_shift_of_log_return() -> None:
    df = _frame([0.01, -0.02, 0.015, 0.0, 0.03, -0.005, 0.012, -0.008, 0.004, 0.001])
    res = _add_forward_target_columns(df)
    expected = df["btc_log_return"].shift(-1)
    pd.testing.assert_series_equal(
        res["btc_fwd_ret_1d"].reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
    )


def test_fwd_ret_3d_matches_hand_computed_sum() -> None:
    """연속 1% 상승 10일 시퀀스: fwd_ret_3d 는 일정하게 0.03 이어야 한다."""
    df = _frame([0.01] * 10)
    res = _add_forward_target_columns(df)
    # t=0..6 은 T+1..T+3 합 = 0.03 (마지막 3개는 NaN)
    valid = res["btc_fwd_ret_3d"].dropna()
    assert len(valid) == 7
    np.testing.assert_allclose(valid.to_numpy(), 0.03, atol=1e-12)


def test_fwd_ret_7d_matches_hand_computed_sum() -> None:
    df = _frame([0.01] * 20)
    res = _add_forward_target_columns(df)
    valid = res["btc_fwd_ret_7d"].dropna()
    assert len(valid) == 13  # 20 - 7
    np.testing.assert_allclose(valid.to_numpy(), 0.07, atol=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# Forward-leak 방지: 마지막 k개 행이 NaN
# ─────────────────────────────────────────────────────────────────────────────


def test_last_k_rows_are_nan_per_target() -> None:
    df = _frame([0.001 * i for i in range(30)])
    res = _add_forward_target_columns(df)

    assert res["btc_fwd_ret_1d"].iloc[-1:].isna().all()
    assert res["btc_fwd_ret_1d"].iloc[-2:-1].notna().all()

    assert res["btc_fwd_ret_3d"].iloc[-3:].isna().all()
    assert res["btc_fwd_ret_3d"].iloc[-4:-3].notna().all()

    assert res["btc_fwd_ret_7d"].iloc[-7:].isna().all()
    assert res["btc_fwd_ret_7d"].iloc[-8:-7].notna().all()

    assert res["btc_fwd_vol_5d"].iloc[-5:].isna().all()
    assert res["btc_fwd_vol_5d"].iloc[-6:-5].notna().all()

    assert res["btc_large_move_3d"].iloc[-3:].isna().all()
    assert res["btc_large_move_3d"].iloc[-4:-3].notna().all()


# ─────────────────────────────────────────────────────────────────────────────
# btc_large_move_3d 이진 + dtype
# ─────────────────────────────────────────────────────────────────────────────


def test_large_move_3d_is_binary_int64_with_na() -> None:
    df = _frame([0.02, 0.02, 0.02, -0.005, -0.002, 0.001, 0.0, 0.0, 0.0, 0.0])
    res = _add_forward_target_columns(df)

    assert str(res["btc_large_move_3d"].dtype) == "Int64"
    valid = res["btc_large_move_3d"].dropna()
    # 모든 유효값이 0/1 이어야 한다
    assert set(valid.unique().tolist()).issubset({0, 1})


def test_large_move_3d_threshold_respected() -> None:
    """fwd_ret_3d = 0.04 (>3%) → 1, fwd_ret_3d = 0.01 (<3%) → 0."""
    # t=0 기준 fwd_ret_3d = r1+r2+r3. 설계: 앞 3 일은 큰 상승, 뒤는 잠잠.
    df = _frame([0.0, 0.02, 0.02, 0.02, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001])
    res = _add_forward_target_columns(df)

    # t=0: r1+r2+r3 = 0.06 > 0.03 → 1
    assert res.loc[0, "btc_large_move_3d"] == 1
    # t=4: r5+r6+r7 = 0.003 < 0.03 → 0
    assert res.loc[4, "btc_large_move_3d"] == 0
    # threshold 값이 실제로 0.03 인지 회귀 방지
    assert FWD_LARGE_MOVE_3D_THRESHOLD == 0.03


# ─────────────────────────────────────────────────────────────────────────────
# fwd_vol_5d: skipna=False, 중간 NaN 이 포함되면 전파
# ─────────────────────────────────────────────────────────────────────────────


def test_fwd_vol_5d_propagates_nan_from_future_window() -> None:
    rets = [0.01] * 15
    df = _frame(rets)
    df.loc[5, "btc_log_return"] = np.nan
    res = _add_forward_target_columns(df)

    # t=0..4 는 T+1..T+5 중 하나가 NaN (t=5 위치) → 전파
    for t in range(1, 5):
        assert pd.isna(res.loc[t, "btc_fwd_vol_5d"]), f"row {t} should propagate NaN"


def test_fwd_vol_5d_equals_numpy_std() -> None:
    rng = np.random.default_rng(42)
    rets = rng.normal(0, 0.01, 30).tolist()
    df = _frame(rets)
    res = _add_forward_target_columns(df)

    t = 3
    expected = np.std(rets[t + 1 : t + 6], ddof=1)
    np.testing.assert_allclose(res.loc[t, "btc_fwd_vol_5d"], expected, atol=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# btc_log_return 컬럼 부재 방어
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_btc_log_return_fills_all_nan() -> None:
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-02"]})
    res = _add_forward_target_columns(df)
    for col in FORWARD_TARGET_COLUMNS:
        assert col in res.columns
        # 전부 NaN / <NA>
        assert res[col].isna().all()


# ─────────────────────────────────────────────────────────────────────────────
# 스키마: FORWARD_TARGET_COLUMNS 튜플 안정성 (다운스트림이 이 상수에 의존)
# ─────────────────────────────────────────────────────────────────────────────


def test_forward_target_columns_constant_is_stable() -> None:
    assert FORWARD_TARGET_COLUMNS == (
        "btc_fwd_ret_1d",
        "btc_fwd_ret_3d",
        "btc_fwd_ret_7d",
        "btc_fwd_vol_5d",
        "btc_large_move_3d",
    )
