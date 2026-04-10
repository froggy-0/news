from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import fng


def test_fetch_fng_parses_value_and_date(monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.now(timezone.utc).date()
    payload = {
        "data": [
            {"timestamp": today.strftime("%m-%d-%Y"), "value": "75"},
            {"timestamp": (today - timedelta(days=1)).strftime("%m-%d-%Y"), "value": "63"},
        ]
    }
    monkeypatch.setattr(fng, "get_json_with_retry", lambda *args, **kwargs: payload)

    df = fng.fetch_fng(1)

    assert list(df["date"]) == [
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
    ]
    assert df["fng_value"].dtype == pd.Int64Dtype()
    assert df.loc[df["date"] == today.isoformat(), "fng_value"].iloc[0] == 75


def test_fetch_fng_sets_nan_for_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.now(timezone.utc).date()
    payload = {"data": [{"timestamp": today.strftime("%m-%d-%Y"), "value": "N/A"}]}
    monkeypatch.setattr(fng, "get_json_with_retry", lambda *args, **kwargs: payload)

    df = fng.fetch_fng(0)

    assert pd.isna(df.loc[0, "fng_value"])


def test_fetch_fng_returns_nan_frame_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_get_json(*args, **kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr(fng, "get_json_with_retry", fake_get_json)

    with caplog.at_level(logging.WARNING):
        df = fng.fetch_fng(2)

    assert df["fng_value"].isna().all()
    assert any(getattr(record, "event", None) == "source.failed" for record in caplog.records)
