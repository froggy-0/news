"""Alpaca 수집기 단위 테스트."""

from __future__ import annotations

from unittest.mock import patch

from backfill.sources.alpaca import _iso_to_utc_date, _strip_html, fetch_alpaca_articles


def _make_item(
    id_: str,
    created_at: str = "2024-01-01T12:00:00Z",
    headline: str = "BTC news",
    summary: str = "summary text",
    content: str = "",
) -> dict:
    return {
        "id": id_,
        "headline": headline,
        "created_at": created_at,
        "summary": summary,
        "content": content,
    }


# ──────────────────────────────────────────────
# HTML 태그 제거
# ──────────────────────────────────────────────


def test_strip_html_removes_tags() -> None:
    assert _strip_html("<p>Bitcoin <b>surges</b></p>") == "Bitcoin surges"


def test_strip_html_no_tags_unchanged() -> None:
    assert _strip_html("plain text") == "plain text"


# ──────────────────────────────────────────────
# ISO → UTC 날짜 변환
# ──────────────────────────────────────────────


def test_iso_to_utc_date_basic() -> None:
    assert _iso_to_utc_date("2024-01-15T10:30:00Z") == "2024-01-15"


def test_iso_to_utc_date_midnight_boundary() -> None:
    # 2023-12-31 23:59:59 UTC → 2023-12-31
    assert _iso_to_utc_date("2023-12-31T23:59:59Z") == "2023-12-31"
    # 2024-01-01 00:00:00 UTC → 2024-01-01
    assert _iso_to_utc_date("2024-01-01T00:00:00Z") == "2024-01-01"


# ──────────────────────────────────────────────
# 페이지네이션
# ──────────────────────────────────────────────


def test_loop_stops_on_null_next_page_token() -> None:
    """next_page_token=null → 1회 호출로 종료."""
    response = {"news": [_make_item("1")], "next_page_token": None}

    with patch("backfill.sources.alpaca._get_with_retry", return_value=response):
        result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "key", "secret", delay_seconds=0)

    assert len(result) == 1


def test_loop_continues_with_non_null_next_page_token() -> None:
    """next_page_token non-null → 2회 호출."""
    call_count = 0
    responses = [
        {"news": [_make_item("1")], "next_page_token": "token_abc"},
        {"news": [_make_item("2")], "next_page_token": None},
    ]

    def mock_get(url, headers, params):
        nonlocal call_count
        r = responses[call_count]
        call_count += 1
        return r

    with patch("backfill.sources.alpaca._get_with_retry", side_effect=mock_get):
        with patch("backfill.sources.alpaca.time.sleep"):
            result = fetch_alpaca_articles(
                "2024-01-01", "2024-01-31", "key", "secret", delay_seconds=0
            )

    assert call_count == 2
    assert len(result) == 2


# ──────────────────────────────────────────────
# body 우선순위
# ──────────────────────────────────────────────


def test_content_html_stripped_takes_priority_over_summary() -> None:
    item = _make_item("1", content="<p>Full body</p>", summary="short summary")
    with patch(
        "backfill.sources.alpaca._get_with_retry",
        return_value={"news": [item], "next_page_token": None},
    ):
        result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "key", "secret")

    assert result[0].body == "Full body"


def test_empty_content_falls_back_to_summary() -> None:
    item = _make_item("1", content="", summary="fallback summary")
    with patch(
        "backfill.sources.alpaca._get_with_retry",
        return_value={"news": [item], "next_page_token": None},
    ):
        result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "key", "secret")

    assert result[0].body == "fallback summary"


def test_both_empty_sets_empty_body() -> None:
    item = _make_item("1", content="", summary="")
    with patch(
        "backfill.sources.alpaca._get_with_retry",
        return_value={"news": [item], "next_page_token": None},
    ):
        result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "key", "secret")

    assert result[0].body == ""


# ──────────────────────────────────────────────
# 자격증명 누락
# ──────────────────────────────────────────────


def test_missing_credentials_returns_empty_list(caplog) -> None:
    """자격증명 없으면 빈 리스트 반환, INFO 로그."""
    import logging

    with caplog.at_level(logging.INFO, logger="backfill.sources.alpaca"):
        result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "", "")

    assert result == []
    assert any(
        "source.skip" in r.getMessage() or "missing_credentials" in str(r.__dict__)
        for r in caplog.records
    )


def test_missing_key_id_only_returns_empty_list() -> None:
    result = fetch_alpaca_articles("2024-01-01", "2024-01-31", "", "secret")
    assert result == []
