"""CoinDesk 수집기 단위 테스트."""

from __future__ import annotations

from unittest.mock import patch

from backfill.sources.coindesk import (
    _date_to_ts,
    _ts_to_utc_date,
    fetch_coindesk_articles,
)


def _make_item(id_: int, pub_ts: int, title: str = "BTC News", body: str = "body") -> dict:
    return {"ID": id_, "PUBLISHED_ON": pub_ts, "TITLE": title, "BODY": body}


# ──────────────────────────────────────────────
# 날짜 변환 UTC 경계값
# ──────────────────────────────────────────────


def test_ts_to_utc_date_just_before_midnight() -> None:
    # 1704067199 = 2023-12-31 23:59:59 UTC
    assert _ts_to_utc_date(1704067199) == "2023-12-31"


def test_ts_to_utc_date_at_midnight() -> None:
    # 1704067200 = 2024-01-01 00:00:00 UTC
    assert _ts_to_utc_date(1704067200) == "2024-01-01"


# ──────────────────────────────────────────────
# 루프 종료: Data=[] 응답
# ──────────────────────────────────────────────


def test_loop_stops_on_empty_data() -> None:
    """Data=[] 응답이 오면 즉시 루프 종료."""
    responses = [
        {"Data": [_make_item(1, 1704100000), _make_item(2, 1704099000)]},
        {"Data": []},
    ]
    call_count = 0

    def mock_get(url, params):
        nonlocal call_count
        call_count += 1
        return responses[call_count - 1]

    with patch("backfill.sources.coindesk._get_with_retry", side_effect=mock_get):
        with patch("backfill.sources.coindesk.time.sleep"):
            result = fetch_coindesk_articles("2024-01-01", "2024-01-02", delay_seconds=0)

    assert call_count == 2
    assert len(result) == 2


# ──────────────────────────────────────────────
# 루프 종료: start_ts 이전 기사 포함 → 필터링
# ──────────────────────────────────────────────


def test_loop_stops_and_filters_old_articles() -> None:
    """배치에 start_ts 이전 기사 포함 시 루프 종료, 초과 기사 필터."""
    start_ts = _date_to_ts("2024-01-01")
    new_ts = start_ts + 3600  # 2024-01-01 01:00 UTC (포함)
    old_ts = start_ts - 86400  # 2023-12-31 UTC (제외)

    responses = [
        {"Data": [_make_item(1, new_ts), _make_item(2, old_ts)]},
    ]

    with patch("backfill.sources.coindesk._get_with_retry", return_value=responses[0]):
        with patch("backfill.sources.coindesk.time.sleep"):
            result = fetch_coindesk_articles("2024-01-01", "2024-01-02", delay_seconds=0)

    # old_ts 기사는 필터링되어 1개만 반환
    assert len(result) == 1
    assert result[0].article_id == "1"


# ──────────────────────────────────────────────
# to_ts 커서 계산
# ──────────────────────────────────────────────


def test_cursor_advances_with_min_published_on_minus_one() -> None:
    """다음 커서 = min(PUBLISHED_ON) - 1."""
    ts_a = 1704100000
    ts_b = 1704090000  # min

    first_batch = {"Data": [_make_item(1, ts_a), _make_item(2, ts_b)]}
    second_batch = {"Data": []}

    captured_cursors: list[int] = []

    def mock_get(url, params):
        captured_cursors.append(params["to_ts"])
        if len(captured_cursors) == 1:
            return first_batch
        return second_batch

    with patch("backfill.sources.coindesk._get_with_retry", side_effect=mock_get):
        with patch("backfill.sources.coindesk.time.sleep"):
            fetch_coindesk_articles("2024-01-01", "2024-01-02", delay_seconds=0)

    assert len(captured_cursors) == 2
    assert captured_cursors[1] == ts_b - 1


# ──────────────────────────────────────────────
# ID 중복 제거
# ──────────────────────────────────────────────


def test_dedup_same_id_across_pages() -> None:
    """동일 ID가 두 페이지에서 반환되면 1개만 보존."""
    ts_a = 1704100000
    ts_b = 1704090000

    batch1 = {"Data": [_make_item(99, ts_a)]}
    batch2 = {"Data": [_make_item(99, ts_b)]}  # 동일 ID, 다른 ts
    batch3 = {"Data": []}

    responses = [batch1, batch2, batch3]
    idx = 0

    def mock_get(url, params):
        nonlocal idx
        r = responses[idx]
        idx += 1
        return r

    with patch("backfill.sources.coindesk._get_with_retry", side_effect=mock_get):
        with patch("backfill.sources.coindesk.time.sleep"):
            result = fetch_coindesk_articles("2024-01-01", "2024-01-03", delay_seconds=0)

    assert len(result) == 1
    assert result[0].article_id == "99"


# ──────────────────────────────────────────────
# BODY=null 처리
# ──────────────────────────────────────────────


def test_body_null_sets_empty_string() -> None:
    """BODY가 None이면 body="" 설정."""
    ts = _date_to_ts("2024-01-01") + 3600
    item = {"ID": 1, "PUBLISHED_ON": ts, "TITLE": "title", "BODY": None}

    with patch(
        "backfill.sources.coindesk._get_with_retry",
        side_effect=[
            {"Data": [item]},
            {"Data": []},
        ],
    ):
        with patch("backfill.sources.coindesk.time.sleep"):
            result = fetch_coindesk_articles("2024-01-01", "2024-01-02", delay_seconds=0)

    assert result[0].body == ""


def test_body_empty_string_sets_empty_string() -> None:
    """BODY가 빈 문자열이면 body="" 설정."""
    ts = _date_to_ts("2024-01-01") + 3600
    item = {"ID": 2, "PUBLISHED_ON": ts, "TITLE": "title", "BODY": ""}

    with patch(
        "backfill.sources.coindesk._get_with_retry",
        side_effect=[
            {"Data": [item]},
            {"Data": []},
        ],
    ):
        with patch("backfill.sources.coindesk.time.sleep"):
            result = fetch_coindesk_articles("2024-01-01", "2024-01-02", delay_seconds=0)

    assert result[0].body == ""


def test_progress_callback_reports_pages_and_completion() -> None:
    ts = _date_to_ts("2024-01-01") + 3600
    events: list[dict[str, object]] = []

    with patch(
        "backfill.sources.coindesk._get_with_retry",
        side_effect=[
            {"Data": [_make_item(1, ts), _make_item(2, ts - 60)]},
            {"Data": []},
        ],
    ):
        with patch("backfill.sources.coindesk.time.sleep"):
            fetch_coindesk_articles(
                "2024-01-01",
                "2024-01-02",
                delay_seconds=0,
                progress_callback=events.append,
            )

    assert events[0]["source"] == "coindesk"
    assert events[0]["status"] == "running"
    assert events[0]["pages_fetched"] == 1
    assert events[0]["collected"] == 2
    assert events[-1]["status"] == "completed"
    assert events[-1]["collected"] == 2
