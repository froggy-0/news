from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "backfill_btc_futures.py"
SPEC = importlib.util.spec_from_file_location("backfill_btc_futures", SCRIPT_PATH)
assert SPEC is not None
backfill_btc_futures = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backfill_btc_futures)


def _ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def test_extract_coinalyze_oi_shifts_date_plus_one_day() -> None:
    rows = [
        {"t": _ts(2025, 4, 23), "c": 100.0},
        {"t": _ts(2025, 4, 24), "c": 200.0},
        {"t": _ts(2025, 4, 25), "c": 300.0},
    ]

    result = backfill_btc_futures._extract_coinalyze_oi(
        rows,
        start=date(2025, 4, 24),
        end=date(2025, 4, 25),
    )

    assert result == {
        "2025-04-24": 100.0,
        "2025-04-25": 200.0,
    }


def test_extract_coinalyze_lsr_keeps_same_utc_date() -> None:
    rows = [
        {"t": _ts(2025, 4, 23), "r": 0.9},
        {"t": _ts(2025, 4, 24), "r": 1.1},
        {"t": _ts(2025, 4, 25), "r": 1.2},
    ]

    result = backfill_btc_futures._extract_coinalyze_lsr(
        rows,
        start=date(2025, 4, 24),
        end=date(2025, 4, 25),
    )

    assert result == {
        "2025-04-24": 1.1,
        "2025-04-25": 1.2,
    }


def test_fetch_coinalyze_all_uses_oi_start_minus_one_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COINALYZE_API_KEY", "test-key")
    calls: list[tuple[str, date, date, dict[str, str] | None]] = []

    def fake_get_history(
        endpoint: str,
        *,
        api_key: str,
        start: date,
        end: date,
        extra_params: dict[str, str] | None = None,
    ) -> list[dict]:
        assert api_key == "test-key"
        calls.append((endpoint, start, end, extra_params))
        if endpoint == "open-interest-history":
            return [{"t": _ts(2025, 4, 23), "c": 100.0}]
        return [{"t": _ts(2025, 4, 24), "r": 1.1}]

    monkeypatch.setattr(backfill_btc_futures, "_coinalyze_get_history", fake_get_history)

    result = backfill_btc_futures._fetch_coinalyze_all(
        date(2025, 4, 24),
        date(2025, 4, 24),
    )

    assert calls == [
        (
            "open-interest-history",
            date(2025, 4, 23),
            date(2025, 4, 24),
            {"convert_to_usd": "true"},
        ),
        ("long-short-ratio-history", date(2025, 4, 24), date(2025, 4, 24), None),
    ]
    assert result == {
        "2025-04-24": {
            "funding_rate": None,
            "open_interest_usd": 100.0,
            "btc_long_short_ratio": 1.1,
        }
    }


def test_row_for_upsert_omits_none_metrics() -> None:
    row = backfill_btc_futures._row_for_upsert(
        "2025-04-24",
        {
            "funding_rate": None,
            "open_interest_usd": 100.0,
            "btc_long_short_ratio": 1.1,
        },
        source="coinalyze",
    )

    assert row == {
        "date": "2025-04-24",
        "symbol": "BTCUSDT",
        "source": "coinalyze",
        "open_interest_usd": 100.0,
        "btc_long_short_ratio": 1.1,
    }
