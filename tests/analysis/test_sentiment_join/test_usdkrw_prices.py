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


def test_kis_chartprice_paginates_over_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KIS 단일 호출 응답 cap(≈100영업일)을 회피하기 위해 페이지네이션이 동작하는지 검증."""
    monkeypatch.setattr(usdkrw_prices, "_kis_token", lambda *a, **k: "tok")

    chunks_seen: list[tuple[str, str]] = []

    def fake_page(token, app_key, app_secret, start, end):
        chunks_seen.append((start, end))
        # 각 chunk 경계 내부의 2일치를 돌려준다 (실제 KIS와 유사하게 cap된 응답 가정)
        return pd.DataFrame({"date": [start, end], "close": [1400.0, 1410.0]})

    monkeypatch.setattr(usdkrw_prices, "_kis_chartprice_page", fake_page)

    frame = usdkrw_prices._kis_chartprice("k", "s", "2025-10-01", "2026-04-17")

    # 200일 구간을 120일 단위로 잘랐으면 chunk가 2개 이상이어야 한다.
    assert len(chunks_seen) >= 2
    # 마지막 chunk는 요청 end_date에서 시작
    assert chunks_seen[0][1] == "2026-04-17"
    # 가장 이른 chunk는 start_date를 커버해야 한다
    assert chunks_seen[-1][0] == "2025-10-01"
    # 중복 날짜는 groupby.last로 제거돼 고유해야 한다
    assert frame["date"].is_unique


def test_kis_chartprice_tolerates_single_chunk_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 chunk가 실패해도 다른 chunk 데이터는 유지돼야 한다."""
    from morning_brief.data.sources.http_client import HttpFetchError

    monkeypatch.setattr(usdkrw_prices, "_kis_token", lambda *a, **k: "tok")

    call_count = {"n": 0}

    def flaky_page(token, app_key, app_secret, start, end):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise HttpFetchError("transient", provider="kis")
        return pd.DataFrame({"date": [start], "close": [1400.0]})

    monkeypatch.setattr(usdkrw_prices, "_kis_chartprice_page", flaky_page)

    frame = usdkrw_prices._kis_chartprice("k", "s", "2025-10-01", "2026-04-17")

    # 전부 실패는 아니므로 DataFrame이 반환돼야 한다
    assert not frame.empty
    assert frame["date"].is_unique


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
