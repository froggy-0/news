from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/analysis"))

from daily_frequency_audit import resample_4h_bars_to_daily

from arena import frequency


def _bar(open_time: str, close_time: str, *, o: float, h: float, lo: float, c: float, v: float):
    return {
        "open_time": open_time,
        "close_time": close_time,
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": v,
    }


def _full_day(day: str, base: float) -> list[dict]:
    hours = ["00", "04", "08", "12", "16", "20"]
    rows = []
    for i, hh in enumerate(hours):
        close_hh = hours[i + 1] if i + 1 < len(hours) else "24"
        open_time = f"{day}T{hh}:00:00Z"
        close_time = f"{day}T{close_hh}:00:00Z" if close_hh != "24" else f"{day}T23:59:59Z"
        rows.append(
            _bar(
                open_time,
                close_time,
                o=base + i,
                h=base + i + 5,
                lo=base + i - 5,
                c=base + i + 1,
                v=10.0 + i,
            )
        )
    return rows


def test_resample_aggregates_complete_calendar_day_into_one_bar() -> None:
    rows = _full_day("2026-01-01", base=100.0)

    daily = resample_4h_bars_to_daily(rows)

    assert len(daily) == 1
    bar = daily[0]
    assert bar["open"] == rows[0]["open"]
    assert bar["close"] == rows[-1]["close"]
    assert bar["high"] == max(r["high"] for r in rows)
    assert bar["low"] == min(r["low"] for r in rows)
    assert bar["volume"] == sum(r["volume"] for r in rows)
    assert bar["open_time"] == rows[0]["open_time"]
    assert bar["close_time"] == rows[-1]["close_time"]


def test_resample_drops_incomplete_boundary_days() -> None:
    full = _full_day("2026-01-02", base=200.0)
    partial = _full_day("2026-01-03", base=300.0)[:3]  # 6개 중 3개만 (경계일)

    daily = resample_4h_bars_to_daily(full + partial)

    assert len(daily) == 1


def test_resample_handles_multiple_complete_days_in_order() -> None:
    day1 = _full_day("2026-01-01", base=100.0)
    day2 = _full_day("2026-01-02", base=200.0)

    daily = resample_4h_bars_to_daily(day2 + day1)  # 순서 뒤섞여 들어와도

    assert [row["open_time"] for row in daily] == [
        day1[0]["open_time"],
        day2[0]["open_time"],
    ]


def test_daily_research_profile_registered_for_all_multi_asset_symbols() -> None:
    from arena import parameters

    for symbol in parameters.MULTI_ASSET_SYMBOLS:
        profile_id = frequency.daily_research_profile_id(symbol)
        profile = frequency.get_frequency_profile(profile_id)
        assert profile.interval == "1d"
        assert profile.live_enabled is False
        assert profile.symbol == symbol
        cost = frequency.get_cost_scenario(profile_id, "base")
        assert (
            cost.fee_bps
            == frequency.get_cost_scenario(frequency.LIVE_4H_PROFILE_ID, "base").fee_bps
        )
