from __future__ import annotations

import math
import os
from typing import Callable

import pytest

from morning_brief.data.sources import kis

pytestmark = pytest.mark.live_kis


def _live_kis_enabled() -> bool:
    return (
        os.getenv("RUN_LIVE_KIS_TESTS", "").strip() == "1"
        and bool(os.getenv("KIS_APP_KEY", "").strip())
        and bool(os.getenv("KIS_APP_SECRET", "").strip())
    )


def _require_live_kis() -> None:
    if not _live_kis_enabled():
        pytest.skip("RUN_LIVE_KIS_TESTS=1 and KIS_APP_KEY/KIS_APP_SECRET are required")


def _assert_finite_positive(value: float) -> None:
    assert math.isfinite(value)
    assert value > 0


def test_live_usdkrw_contract_returns_latest_point() -> None:
    price, change_pct = kis.fetch_usdkrw_point()

    _assert_finite_positive(price)
    assert math.isfinite(change_pct)


def test_live_dow30_contract_returns_latest_point() -> None:
    price, change_pct = kis.fetch_dow30_point()

    _assert_finite_positive(price)
    assert math.isfinite(change_pct)


@pytest.mark.parametrize(
    ("label", "fetcher"),
    [
        ("kospi", kis.fetch_kospi_point),
        ("kosdaq", kis.fetch_kosdaq_point),
    ],
)
def test_live_domestic_index_current_price_contract(
    label: str,
    fetcher: Callable[[], tuple[float, float]],
) -> None:
    price, change_pct = fetcher()

    _assert_finite_positive(price)
    assert math.isfinite(change_pct), label
