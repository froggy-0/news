from __future__ import annotations

import logging

import pandas as pd
import pytest

from morning_brief.analysis.sentiment_join.sources import usdkrw_prices


def test_fetch_usdkrw_close_skips_kis_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"kis": False}

    def fake_kis(*args, **kwargs):
        called["kis"] = True
        return pd.DataFrame()

    expected = pd.DataFrame({"date": ["2026-04-10"], "close": [1400.0]})
    monkeypatch.setattr(usdkrw_prices, "_kis_chartprice", fake_kis)
    monkeypatch.setattr(usdkrw_prices, "_download_with_yfinance", lambda *args, **kwargs: expected)

    df = usdkrw_prices.fetch_usdkrw_close("2026-04-09", "2026-04-10", "", "")

    assert called["kis"] is False
    assert df.equals(expected)
    assert df.attrs["fallback_used"] is True


def test_fetch_usdkrw_close_falls_back_when_kis_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        usdkrw_prices,
        "_kis_chartprice",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kis down")),
    )
    expected = pd.DataFrame({"date": ["2026-04-10"], "close": [1410.0]})
    monkeypatch.setattr(usdkrw_prices, "_download_with_yfinance", lambda *args, **kwargs: expected)

    with caplog.at_level(logging.WARNING):
        df = usdkrw_prices.fetch_usdkrw_close("2026-04-09", "2026-04-10", "key", "secret")

    assert df.equals(expected)
    assert any(getattr(record, "event", None) == "fallback.used" for record in caplog.records)


def test_fetch_usdkrw_close_returns_empty_frame_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        usdkrw_prices,
        "_kis_chartprice",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kis down")),
    )
    monkeypatch.setattr(
        usdkrw_prices,
        "_download_with_yfinance",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("yfinance down")),
    )

    df = usdkrw_prices.fetch_usdkrw_close("2026-04-09", "2026-04-10", "key", "secret")

    assert df.empty
