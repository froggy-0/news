from __future__ import annotations

import pytest

from morning_brief.data.sources import stooq



def test_to_stooq_symbol_appends_us_suffix():
    assert stooq.to_stooq_symbol("AAPL") == "aapl.us"



def test_to_stooq_symbol_keeps_existing_suffix():
    assert stooq.to_stooq_symbol("msft.us") == "msft.us"



def test_fetch_close_change_and_volume_parses_csv(monkeypatch):
    csv_text = """Date,Open,High,Low,Close,Volume
2026-03-10,100,101,99,100,1000
2026-03-11,100,103,99,102,2000
"""

    monkeypatch.setattr(stooq, "get_text_with_retry", lambda *args, **kwargs: csv_text)

    close, change_pct, volume = stooq.fetch_close_change_and_volume("aapl.us")
    assert close == pytest.approx(102.0)
    assert change_pct == pytest.approx(2.0)
    assert volume == 2000
