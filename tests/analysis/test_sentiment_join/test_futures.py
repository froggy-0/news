from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from morning_brief.analysis.sentiment_join.sources import futures


@pytest.fixture(autouse=True)
def _isolate_futures_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(futures, "_read_futures_from_supabase", lambda *args, **kwargs: {})
    monkeypatch.setattr(futures, "_write_futures_to_supabase", lambda *args, **kwargs: None)


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def test_aggregate_daily_funding_sums_three_intraday_rows() -> None:
    rows = [
        {"fundingTime": _ms(2026, 4, 10, 0), "fundingRate": "0.001"},
        {"fundingTime": _ms(2026, 4, 10, 8), "fundingRate": "0.002"},
        {"fundingTime": _ms(2026, 4, 10, 16), "fundingRate": "0.003"},
    ]

    assert futures._aggregate_daily_funding(rows) == {"2026-04-10": 0.006}


def test_extract_daily_oi_uses_sum_open_interest_value() -> None:
    rows = [{"timestamp": _ms(2026, 4, 10), "sumOpenInterestValue": "123456.7"}]

    assert futures._extract_daily_oi(rows) == {"2026-04-10": 123456.7}


def test_fetch_futures_data_returns_nan_grid_when_all_requests_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Binance fapi 전부 실패
    monkeypatch.setattr(futures, "_fetch_funding_rate_history", lambda start_ms, end_ms: [])
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda limit_days: [])
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda limit_days: [])
    # Lambda ARN 미설정 → Lambda 경로 skip
    monkeypatch.delenv("FUTURES_LAMBDA_ARN", raising=False)
    # Bybit도 전부 실패
    monkeypatch.setattr(futures, "_fetch_bybit_funding_rows", lambda *a, **kw: [])
    monkeypatch.setattr(futures, "_fetch_bybit_oi_rows", lambda *a, **kw: [])
    monkeypatch.setattr(futures, "_fetch_bybit_lsr_rows", lambda *a, **kw: [])

    df = futures.fetch_futures_data(lookback_days=2)

    assert list(df.columns) == ["date", "funding_rate", "open_interest_usd", "btc_long_short_ratio"]
    assert df["funding_rate"].isna().all()
    assert df["open_interest_usd"].isna().all()
    assert df["btc_long_short_ratio"].isna().all()


def test_extract_daily_long_short_ratio_parses_str_fields() -> None:
    rows = [
        {"timestamp": _ms(2026, 4, 10), "longShortRatio": "0.8829"},
        {"timestamp": _ms(2026, 4, 11), "longShortRatio": "1.0305"},
    ]

    result = futures._extract_daily_long_short_ratio(rows)

    assert result["2026-04-10"] == pytest.approx(0.8829)
    assert result["2026-04-11"] == pytest.approx(1.0305)


def test_extract_daily_long_short_ratio_value_above_one_is_valid() -> None:
    rows = [{"timestamp": _ms(2026, 4, 10), "longShortRatio": "2.5"}]

    result = futures._extract_daily_long_short_ratio(rows)

    assert result["2026-04-10"] == pytest.approx(2.5)


def test_fetch_futures_data_lsr_failure_does_not_block_funding_oi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    target_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    funding_rows = [
        {
            "fundingTime": _ms(target_day.year, target_day.month, target_day.day, 0),
            "fundingRate": "0.001",
        },
    ]
    oi_rows = [
        {
            "timestamp": _ms(target_day.year, target_day.month, target_day.day),
            "sumOpenInterestValue": "1000.0",
        }
    ]

    # GitHub Actions 환경 감지를 비활성화 (로컬 Binance 직접 호출 사용)
    # os.getenv를 monkeypatch하여 GITHUB_ACTIONS를 "false"로 반환하도록 함
    original_getenv = os.getenv

    def mock_getenv(key: str, default: str = "") -> str:
        if key == "GITHUB_ACTIONS":
            return ""  # Empty string → not github actions
        return original_getenv(key, default)

    monkeypatch.setattr(os, "getenv", mock_getenv)
    monkeypatch.setattr(
        futures, "_fetch_funding_rate_history", lambda start_ms, end_ms: funding_rows
    )
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda limit_days: oi_rows)
    monkeypatch.setattr(
        futures,
        "_fetch_long_short_ratio",
        lambda limit_days: (_ for _ in ()).throw(RuntimeError("LSR network error")),
    )

    df = futures.fetch_futures_data(lookback_days=2)

    assert df["funding_rate"].notna().any()
    assert df["open_interest_usd"].notna().any()
    assert "btc_long_short_ratio" in df.columns


def test_oi_and_lsr_requests_use_limit_without_start_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get_list_with_retry(url: str, *, params: dict[str, str], **kwargs):
        calls.append((url, params))
        return []

    monkeypatch.setattr(futures, "get_list_with_retry", fake_get_list_with_retry)

    futures._fetch_oi_history(32)
    futures._fetch_long_short_ratio(32)

    assert calls[0][0] == futures.BINANCE_OI_URL
    assert calls[0][1] == {"symbol": "BTCUSDT", "period": "1d", "limit": "32"}
    assert calls[1][0] == futures.BINANCE_LSR_URL
    assert calls[1][1] == {"symbol": "BTCUSDT", "period": "1d", "limit": "32"}


def test_fetch_futures_data_records_sparse_oi_and_lsr_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = datetime.now(timezone.utc).date()
    target_day = today - timedelta(days=1)
    monkeypatch.setenv("GITHUB_ACTIONS", "")

    monkeypatch.setattr(
        futures,
        "_fetch_funding_rate_history",
        lambda start_ms, end_ms: [
            {
                "fundingTime": _ms(target_day.year, target_day.month, target_day.day, 0),
                "fundingRate": "0.001",
            }
        ],
    )
    monkeypatch.setattr(
        futures,
        "_fetch_oi_history",
        lambda limit_days: [
            {
                "timestamp": _ms(target_day.year, target_day.month, target_day.day),
                "sumOpenInterestValue": "1000.0",
            }
        ],
    )
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda limit_days: [])

    df = futures.fetch_futures_data(lookback_days=5)

    assert df.attrs["funding_quality_status"] == "degraded"
    assert df.attrs["oi_quality_status"] == "degraded"
    assert df.attrs["lsr_quality_status"] == "degraded"
    assert "coverage_below_threshold" in df.attrs["oi_quality_reasons"]
    assert "no_history" in df.attrs["lsr_quality_reasons"]


def test_fetch_futures_data_records_full_coverage_as_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    monkeypatch.setenv("GITHUB_ACTIONS", "")

    funding_rows = []
    oi_rows = []
    lsr_rows = []
    for day in dates:
        funding_rows.append(
            {
                "fundingTime": _ms(day.year, day.month, day.day, 0),
                "fundingRate": "0.001",
            }
        )
        oi_rows.append(
            {
                "timestamp": _ms(day.year, day.month, day.day),
                "sumOpenInterestValue": "1000.0",
            }
        )
        lsr_rows.append(
            {
                "timestamp": _ms(day.year, day.month, day.day),
                "longShortRatio": "1.1",
            }
        )

    monkeypatch.setattr(
        futures, "_fetch_funding_rate_history", lambda start_ms, end_ms: funding_rows
    )
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda limit_days: oi_rows)
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda limit_days: lsr_rows)

    df = futures.fetch_futures_data(lookback_days=5)

    assert df.attrs["quality_status"] == "ok"
    assert df.attrs["oi_quality_status"] == "ok"
    assert df.attrs["lsr_quality_status"] == "ok"


def test_fetch_funding_rate_history_paginates_until_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """limit=1000 가득 찬 페이지가 반환되면 커서를 이동해 다음 페이지를 요청합니다."""
    calls: list[dict] = []

    page1 = [
        {"fundingTime": _ms(2025, 1, 1, hour) + i * 8 * 3600 * 1000, "fundingRate": "0.001"}
        for i, hour in enumerate([0, 8, 16] * 333 + [0])  # 1000건
    ]
    page2 = [
        {"fundingTime": _ms(2025, 12, 1, 0), "fundingRate": "0.002"},
    ]

    def fake_get_list(url: str, *, params: dict, **kwargs) -> list:
        calls.append(dict(params))
        if len(calls) == 1:
            return page1
        return page2

    monkeypatch.setattr(futures, "get_list_with_retry", fake_get_list)

    start_ms = _ms(2025, 1, 1)
    end_ms = _ms(2025, 12, 31)
    rows = futures._fetch_funding_rate_history(start_ms, end_ms)

    # 두 페이지 합산
    assert len(rows) == len(page1) + len(page2)
    assert len(calls) == 2
    # 두 번째 요청의 startTime은 page1 마지막 fundingTime + 1
    expected_cursor = str(page1[-1]["fundingTime"] + 1)
    assert calls[1]["startTime"] == expected_cursor
    # 두 요청 모두 endTime이 전달됨
    assert calls[0]["endTime"] == str(end_ms)
    assert calls[1]["endTime"] == str(end_ms)


def test_is_cache_complete_returns_false_when_oi_values_are_null() -> None:
    """행이 존재해도 OI/LSR 값이 None이면 완전 히트 아님."""
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    cached = {
        d: {"funding_rate": 0.001, "open_interest_usd": None, "btc_long_short_ratio": None}
        for d in dates
    }
    assert futures._is_cache_complete(cached, dates) is False


def test_is_cache_complete_returns_true_when_recent_window_filled() -> None:
    """최근 30일 OI/LSR이 채워지고 펀딩비 60% 이상이면 True."""
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(179, -1, -1)]
    cached: dict = {}
    for d in dates:
        cached[d] = {
            "funding_rate": 0.001,
            "open_interest_usd": None,
            "btc_long_short_ratio": None,
        }
    # 최근 30일만 OI/LSR 채움
    for d in dates[-30:]:
        cached[d]["open_interest_usd"] = 1000.0
        cached[d]["btc_long_short_ratio"] = 1.1
    assert futures._is_cache_complete(cached, dates) is True


def test_merge_with_cache_api_overwrites_stale_cache() -> None:
    """동일 날짜에 대해 API 값이 캐시보다 우선."""
    merged_f, merged_oi, merged_lsr = futures._merge_with_cache(
        {"2026-04-10": 0.002},
        {"2026-04-10": 2000.0},
        {"2026-04-10": 1.2},
        {"2026-04-10": 0.001, "2026-04-09": 0.0005},
        {"2026-04-10": 999.0, "2026-04-09": 800.0},
        {"2026-04-10": 0.9, "2026-04-09": 1.0},
    )
    assert merged_f["2026-04-10"] == 0.002    # API wins
    assert merged_f["2026-04-09"] == 0.0005   # cache 보완
    assert merged_oi["2026-04-10"] == 2000.0
    assert merged_oi["2026-04-09"] == 800.0
    assert merged_lsr["2026-04-10"] == 1.2


def test_fetch_futures_data_partial_cache_merged_with_binance_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """부분 캐시 히트: Supabase에 과거 OI가 있고 Binance가 최근 OI를 반환하면 전체가 채워짐."""
    today = datetime.now(timezone.utc).date()
    monkeypatch.setenv("GITHUB_ACTIONS", "")

    old_day = today - timedelta(days=5)
    recent_day = today - timedelta(days=1)

    # Supabase 캐시: old_day OI만 있음 (최근 30일 미충족 → _is_cache_complete = False)
    monkeypatch.setattr(
        futures,
        "_read_futures_from_supabase",
        lambda *a, **kw: {
            old_day.isoformat(): {
                "funding_rate": 0.001,
                "open_interest_usd": 500.0,
                "btc_long_short_ratio": 1.0,
            }
        },
    )
    # Binance: recent_day OI만 반환
    monkeypatch.setattr(
        futures,
        "_fetch_funding_rate_history",
        lambda s, e: [
            {
                "fundingTime": int(
                    datetime(
                        recent_day.year, recent_day.month, recent_day.day, tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                ),
                "fundingRate": "0.002",
            }
        ],
    )
    monkeypatch.setattr(
        futures,
        "_fetch_oi_history",
        lambda l: [
            {
                "timestamp": int(
                    datetime(
                        recent_day.year, recent_day.month, recent_day.day, tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                ),
                "sumOpenInterestValue": "1000.0",
            }
        ],
    )
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda l: [])

    df = futures.fetch_futures_data(lookback_days=6)

    old_row = df[df["date"] == old_day.isoformat()]
    recent_row = df[df["date"] == recent_day.isoformat()]
    assert old_row["open_interest_usd"].notna().any()
    assert recent_row["open_interest_usd"].notna().any()


def test_fetch_funding_rate_history_stops_when_page_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1000건 미만 페이지가 반환되면 추가 요청 없이 종료합니다."""
    calls: list[dict] = []

    def fake_get_list(url: str, *, params: dict, **kwargs) -> list:
        calls.append(dict(params))
        return [{"fundingTime": _ms(2025, 6, 1, 0), "fundingRate": "0.001"}]  # 1건 = 마지막 페이지

    monkeypatch.setattr(futures, "get_list_with_retry", fake_get_list)

    rows = futures._fetch_funding_rate_history(_ms(2025, 6, 1), _ms(2025, 6, 2))

    assert len(rows) == 1
    assert len(calls) == 1  # 단일 요청으로 종료


def test_fetch_futures_data_api_capped_oi_lsr_passes_gate_when_recent_window_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binance API 30일 보존 제약 시나리오: lookback=90일이지만 최근 30일치만 존재해도
    oi_recent_quality_status / lsr_recent_quality_status가 ok가 되어 게이트를 통과합니다.
    전체 커버리지(oi_quality_status)는 여전히 degraded로 진단됩니다."""
    today = datetime.now(timezone.utc).date()
    monkeypatch.setenv("GITHUB_ACTIONS", "")

    # 펀딩비: 90일 전체 제공 (API 제약 없음)
    all_90 = [today - timedelta(days=i) for i in range(89, -1, -1)]
    funding_rows = [
        {
            "fundingTime": _ms(d.year, d.month, d.day, 0),
            "fundingRate": "0.001",
        }
        for d in all_90
    ]
    # OI / LSR: Binance API 30일 보존 제약 시뮬레이션 — 최근 30일치만 존재
    recent_30 = [today - timedelta(days=i) for i in range(29, -1, -1)]
    oi_rows = [
        {
            "timestamp": _ms(d.year, d.month, d.day),
            "sumOpenInterestValue": "1000.0",
        }
        for d in recent_30
    ]
    lsr_rows = [
        {
            "timestamp": _ms(d.year, d.month, d.day),
            "longShortRatio": "1.1",
        }
        for d in recent_30
    ]

    monkeypatch.setattr(
        futures, "_fetch_funding_rate_history", lambda start_ms, end_ms: funding_rows
    )
    monkeypatch.setattr(futures, "_fetch_oi_history", lambda limit_days: oi_rows)
    monkeypatch.setattr(futures, "_fetch_long_short_ratio", lambda limit_days: lsr_rows)

    df = futures.fetch_futures_data(lookback_days=90)

    # 최근 30일 윈도우 커버리지 → ok (게이트 판단 기준)
    assert df.attrs["oi_recent_quality_status"] == "ok"
    assert df.attrs["lsr_recent_quality_status"] == "ok"
    # 전체 lookback 커버리지 → degraded (30/90 ≈ 33%, 진단용)
    assert df.attrs["oi_quality_status"] == "degraded"
    assert df.attrs["lsr_quality_status"] == "degraded"
    # api_capped 플래그 설정
    assert df.attrs["oi_api_capped"] is True
    assert df.attrs["lsr_api_capped"] is True
    # 전체 quality_status는 최근 윈도우 기준 → ok
    assert df.attrs["quality_status"] == "ok"
