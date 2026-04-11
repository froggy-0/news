from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from morning_brief.data.sources import kis
from morning_brief.data.sources.http_client import HttpFetchError


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _CapturePost:
    def __init__(self, response: _Response):
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.response


def test_is_available_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIS_APP_KEY", "key")
    monkeypatch.setenv("KIS_APP_SECRET", "secret")
    assert kis.is_available() is True

    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    assert kis.is_available() is False


def test_fetch_close_change_and_volume_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {
            "rt_cd": "0",
            "output": {"last": "612.34", "base": "600.00", "tvol": "123456"},
        },
    )

    close, change_pct, volume = kis.fetch_close_change_and_volume("NVDA")

    assert close == 612.34
    assert change_pct == 2.06
    assert volume == 123456


def test_fetch_close_change_and_volume_success_logs_quote(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {
            "rt_cd": "0",
            "output": {"last": "612.34", "base": "600.00", "tvol": "123456"},
        },
    )

    with caplog.at_level(logging.INFO, logger="morning_brief.data.sources.kis"):
        kis.fetch_close_change_and_volume("NVDA")

    assert any("KIS 시세: NVDA=612.34 (+2.06%)" in record.message for record in caplog.records)


def test_fetch_close_change_and_volume_rt_cd_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {"rt_cd": "1", "output": {"last": "612.34"}},
    )

    with pytest.raises(HttpFetchError):
        kis.fetch_close_change_and_volume("NVDA")


@pytest.mark.parametrize("last_value", ["", "0"])
def test_fetch_close_change_and_volume_empty_last(monkeypatch, last_value: str) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {"rt_cd": "0", "output": {"last": last_value}},
    )

    with pytest.raises(HttpFetchError):
        kis.fetch_close_change_and_volume("NVDA")


def test_fetch_close_change_and_volume_retries_on_egw00201(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    calls = {"count": 0}

    def fake_get(path, params, headers):
        calls["count"] += 1
        if calls["count"] == 1:
            raise kis._KisRateLimitError()
        return {"rt_cd": "0", "output": {"last": "101", "base": "100", "tvol": "7"}}

    monkeypatch.setattr(kis, "_kis_get", fake_get)

    close, change_pct, volume = kis.fetch_close_change_and_volume("SPY")

    assert calls["count"] == 2
    assert (close, change_pct, volume) == (101.0, 1.0, 7)


def test_fetch_close_change_and_volume_raises_after_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: (_ for _ in ()).throw(kis._KisRateLimitError()),
    )

    with pytest.raises(HttpFetchError):
        kis.fetch_close_change_and_volume("SPY")


def test_fetch_close_change_and_volume_unmapped_excd() -> None:
    with pytest.raises(HttpFetchError):
        kis.fetch_close_change_and_volume("UNKNOWN")


def test_fetch_usdkrw_point_uses_output1_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {
            "rt_cd": "0",
            "output1": {
                "ovrs_nmix_prpr": "1478.20",
                "ovrs_nmix_prdy_clpr": "1477.00",
            },
            "output2": [],
        },
    )

    price, change_pct = kis.fetch_usdkrw_point()

    assert price == 1478.2
    assert change_pct == 0.08


def test_fetch_usdkrw_point_logs_quote(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {
            "rt_cd": "0",
            "output1": {
                "ovrs_nmix_prpr": "1478.20",
                "ovrs_nmix_prdy_clpr": "1477.00",
            },
            "output2": [],
        },
    )

    with caplog.at_level(logging.INFO, logger="morning_brief.data.sources.kis"):
        kis.fetch_usdkrw_point()

    assert any("KIS 시세: USDKRW=1,478.2 (+0.08%)" in record.message for record in caplog.records)


def test_fetch_usdkrw_point_falls_back_to_output2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {
            "rt_cd": "0",
            "output1": {"ovrs_nmix_prpr": ""},
            "output2": [
                {"stck_bsop_date": "20260405", "ovrs_nmix_prpr": "1480.00"},
                {"stck_bsop_date": "20260404", "ovrs_nmix_prpr": "1475.00"},
            ],
        },
    )

    price, change_pct = kis.fetch_usdkrw_point()

    assert price == 1480.0
    assert change_pct == 0.34


def test_fetch_usdkrw_point_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis, "_ensure_token", lambda: "token")
    monkeypatch.setattr(
        kis,
        "_kis_get",
        lambda path, params, headers: {"rt_cd": "1", "msg1": "bad request"},
    )

    with pytest.raises(HttpFetchError):
        kis.fetch_usdkrw_point()


def test_kis_get_raises_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kis.requests,
        "get",
        lambda *args, **kwargs: _Response(500, {"message": "EGW00201"}),
    )

    with pytest.raises(kis._KisRateLimitError):
        kis._kis_get("/path", {}, {})


def test_kis_get_wraps_request_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_request_exception(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(kis.requests, "get", raise_request_exception)

    with pytest.raises(HttpFetchError):
        kis._kis_get("/path", {}, {})


def test_get_token_uses_documented_client_credentials_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _CapturePost(
        _Response(
            200,
            {
                "access_token": "token",
                "access_token_token_expired": "2099-01-01 00:00:00",
            },
        )
    )
    monkeypatch.setattr(kis.requests, "post", capture)

    record = kis._get_token("app-key", "app-secret")

    assert record.token == "token"
    assert isinstance(record.expires_at, datetime)
    # KIS 만료 필드 "2099-01-01 00:00:00" (KST) → UTC로 정상 변환됐는지 확인
    assert record.expires_at.year == 2098 or record.expires_at.year == 2099
    assert len(capture.calls) == 1
    kwargs = capture.calls[0]["kwargs"]
    assert kwargs["data"] == (
        '{"grant_type": "client_credentials", "appkey": "app-key", "appsecret": "app-secret"}'
    )
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Accept"] == "text/plain"
    assert kwargs["headers"]["charset"] == "UTF-8"


def test_get_token_surfaces_error_description(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kis.requests,
        "post",
        lambda *args, **kwargs: _Response(
            403,
            {
                "error_code": "EGW00102",
                "error_description": "AppKey는 필수입니다.",
            },
        ),
    )

    with pytest.raises(HttpFetchError, match="AppKey는 필수입니다."):
        kis._get_token("app-key", "app-secret")


def test_authorized_kis_get_refreshes_token_once_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = iter(["expired-token", "fresh-token"])
    calls: list[str] = []

    monkeypatch.setattr(kis, "_ensure_token", lambda: next(tokens))

    def fake_get_with_retry(
        *, path: str, params: dict[str, str], headers: dict[str, str], target: str
    ):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            raise HttpFetchError("expired", status_code=401, provider="kis")
        return {"rt_cd": "0", "target": target, "path": path, "params": params}

    monkeypatch.setattr(kis, "_kis_get_with_retry", fake_get_with_retry)

    payload = kis._authorized_kis_get(
        path="/path",
        params={"foo": "bar"},
        tr_id="TR123",
        target="dow30",
    )

    assert payload["rt_cd"] == "0"
    assert calls == ["Bearer expired-token", "Bearer fresh-token"]


def test_latest_chart_price_from_payload_prefers_output1() -> None:
    price, source = kis._latest_chart_price_from_payload(
        {
            "output1": {"ovrs_nmix_prpr": "6123.45"},
            "output2": [{"ovrs_nmix_prpr": "6000.00"}],
        }
    )

    assert price == 6123.45
    assert source == "output1"


def test_latest_chart_price_from_payload_falls_back_to_output2() -> None:
    price, source = kis._latest_chart_price_from_payload(
        {
            "output1": {"ovrs_nmix_prpr": ""},
            "output2": [
                {"stck_bsop_date": "20260406", "ovrs_nmix_prpr": "5300.12"},
                {"stck_bsop_date": "20260405", "ovrs_nmix_prpr": "5200.00"},
            ],
        }
    )

    assert price == 5300.12
    assert source == "output2"


def test_summarize_chart_payload_returns_debuggable_shape() -> None:
    summary = kis.summarize_chart_payload(
        {
            "rt_cd": "0",
            "output1": {
                "ovrs_nmix_prpr": "6123.45",
                "foo": "bar",
            },
            "output2": [
                {
                    "stck_bsop_date": "20260406",
                    "ovrs_nmix_prpr": "6100.00",
                }
            ],
        }
    )

    assert summary["rt_cd"] == "0"
    assert summary["output1_price"] == 6123.45
    assert summary["output2_len"] == 1
    assert summary["output2_first_date"] == "20260406"


def test_fetch_dow30_point_uses_verified_chartprice_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_authorized_kis_get(*, path: str, params: dict[str, str], tr_id: str, target: str):
        captured.update(
            {
                "path": path,
                "params": params,
                "tr_id": tr_id,
                "target": target,
            }
        )
        return {
            "rt_cd": "0",
            "output1": {
                "ovrs_nmix_prpr": "46504.67",
                "prdy_ctrt": "-0.13",
            },
            "output2": [],
        }

    monkeypatch.setattr(kis, "_authorized_kis_get", fake_authorized_kis_get)

    price, change_pct = kis.fetch_dow30_point()

    assert price == 46504.67
    assert change_pct == -0.13
    assert captured["path"] == "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
    assert captured["tr_id"] == "FHKST03030100"
    assert captured["target"] == "dow30"
    assert captured["params"] == {
        "FID_COND_MRKT_DIV_CODE": "N",
        "FID_INPUT_ISCD": ".DJI",
        "FID_INPUT_DATE_1": captured["params"]["FID_INPUT_DATE_1"],
        "FID_INPUT_DATE_2": captured["params"]["FID_INPUT_DATE_2"],
        "FID_PERIOD_DIV_CODE": "D",
    }


@pytest.mark.parametrize(
    ("fetcher_name", "code", "expected_price", "expected_change_pct"),
    [
        ("fetch_kospi_point", "0001", 5450.33, 1.36),
        ("fetch_kosdaq_point", "1001", 1047.37, -1.54),
    ],
)
def test_fetch_domestic_index_point_parses_verified_contract(
    monkeypatch: pytest.MonkeyPatch,
    fetcher_name: str,
    code: str,
    expected_price: float,
    expected_change_pct: float,
) -> None:
    captured: dict[str, object] = {}

    def fake_authorized_kis_get(*, path: str, params: dict[str, str], tr_id: str, target: str):
        captured.update(
            {
                "path": path,
                "params": params,
                "tr_id": tr_id,
                "target": target,
            }
        )
        return {
            "rt_cd": "0",
            "output": {
                "bstp_nmix_prpr": str(expected_price),
                "bstp_nmix_prdy_ctrt": str(expected_change_pct),
            },
        }

    monkeypatch.setattr(kis, "_authorized_kis_get", fake_authorized_kis_get)

    fetcher = getattr(kis, fetcher_name)
    price, change_pct = fetcher()

    assert price == expected_price
    assert change_pct == expected_change_pct
    assert captured["path"] == "/uapi/domestic-stock/v1/quotations/inquire-index-price"
    assert captured["tr_id"] == "FHPUP02100000"
    assert captured["params"] == {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": code,
    }


# ---------------------------------------------------------------------------
# 파일 캐시 헬퍼 단위 테스트
# ---------------------------------------------------------------------------


def test_load_cached_token_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert kis._load_cached_token(tmp_path / "nonexistent.json") is None


def test_load_cached_token_returns_none_on_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("not valid json", encoding="utf-8")
    assert kis._load_cached_token(path) is None


def test_load_cached_token_returns_none_when_expired(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    expires = datetime.now(UTC) - timedelta(hours=1)
    path.write_text(
        json.dumps({"access_token": "tok", "expires_at": expires.isoformat()}),
        encoding="utf-8",
    )
    assert kis._load_cached_token(path) is None


def test_load_cached_token_returns_none_when_expiring_soon(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    # _TOKEN_EXPIRY_MARGIN(5분) 이내 만료 → 유효하지 않아야 함
    expires = datetime.now(UTC) + timedelta(minutes=3)
    path.write_text(
        json.dumps({"access_token": "tok", "expires_at": expires.isoformat()}),
        encoding="utf-8",
    )
    assert kis._load_cached_token(path) is None


def test_load_cached_token_returns_record_when_valid(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    expires = datetime.now(UTC) + timedelta(hours=12)
    path.write_text(
        json.dumps({"access_token": "mytoken", "expires_at": expires.isoformat()}),
        encoding="utf-8",
    )
    record = kis._load_cached_token(path)
    assert record is not None
    assert record.token == "mytoken"
    assert record.expires_at.tzinfo is not None


def test_save_token_creates_file_with_correct_content(tmp_path: Path) -> None:
    path = tmp_path / "subdir" / "token.json"
    expires = datetime.now(UTC) + timedelta(hours=12)
    record = kis._TokenRecord(token="saved-token", expires_at=expires)

    kis._save_token(path, record)

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["access_token"] == "saved-token"
    loaded_expires = datetime.fromisoformat(data["expires_at"])
    assert abs((loaded_expires - expires).total_seconds()) < 1


def test_save_token_sets_restrictive_permissions(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    record = kis._TokenRecord(token="tok", expires_at=datetime.now(UTC) + timedelta(hours=12))

    kis._save_token(path, record)

    assert (path.stat().st_mode & 0o777) == 0o600


def test_save_token_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "c" / "token.json"
    record = kis._TokenRecord(token="tok", expires_at=datetime.now(UTC) + timedelta(hours=12))

    kis._save_token(path, record)

    assert path.exists()


def test_ensure_token_uses_file_cache_without_api_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kis, "_TOKEN_RECORD", None)
    cache_path = tmp_path / "token.json"
    expires = datetime.now(UTC) + timedelta(hours=12)
    cache_path.write_text(
        json.dumps({"access_token": "cached-token", "expires_at": expires.isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(kis, "_token_cache_path", lambda: cache_path)

    api_called: list[bool] = []
    monkeypatch.setattr(kis, "_get_token", lambda *_: api_called.append(True))

    token = kis._ensure_token()

    assert token == "cached-token"
    assert not api_called


def test_ensure_token_skips_expired_file_and_fetches_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kis, "_TOKEN_RECORD", None)
    cache_path = tmp_path / "token.json"
    # 만료된 토큰 파일 준비
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "old-token",
                "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(kis, "_token_cache_path", lambda: cache_path)
    monkeypatch.setattr(kis, "_credentials", lambda: ("key", "secret"))

    new_record = kis._TokenRecord(
        token="new-token", expires_at=datetime.now(UTC) + timedelta(hours=23)
    )
    monkeypatch.setattr(kis, "_get_token", lambda _k, _s: new_record)

    token = kis._ensure_token()

    assert token == "new-token"
    # 새 토큰이 파일에 저장됐는지 확인
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-token"


def test_authorized_kis_get_invalidates_file_cache_on_401(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "token.json"
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "stale",
                "expires_at": (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(kis, "_token_cache_path", lambda: cache_path)

    tokens = iter(["stale", "fresh"])
    monkeypatch.setattr(kis, "_ensure_token", lambda: next(tokens))

    def fake_get_with_retry(*, path: str, params: dict, headers: dict, target: str) -> dict:
        if headers["Authorization"] == "Bearer stale":
            raise HttpFetchError("expired", status_code=401, provider="kis")
        return {"rt_cd": "0"}

    monkeypatch.setattr(kis, "_kis_get_with_retry", fake_get_with_retry)

    result = kis._authorized_kis_get(path="/p", params={}, tr_id="TR", target="test")

    assert result["rt_cd"] == "0"
    assert not cache_path.exists()


def test_fetch_domestic_index_point_falls_back_to_delta_for_change_pct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kis,
        "_authorized_kis_get",
        lambda **_: {
            "rt_cd": "0",
            "output": {
                "bstp_nmix_prpr": "5450.33",
                "bstp_nmix_prdy_vrss": "73.03",
            },
        },
    )

    price, change_pct = kis.fetch_kospi_point()

    assert price == 5450.33
    assert change_pct == 1.36


def test_fetch_dow30_point_raises_on_zero_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kis,
        "_authorized_kis_get",
        lambda **_: {
            "rt_cd": "0",
            "output1": {"ovrs_nmix_prpr": "0.00"},
            "output2": [],
        },
    )

    with pytest.raises(HttpFetchError, match="유효 값을 찾지 못했어요"):
        kis.fetch_dow30_point()
