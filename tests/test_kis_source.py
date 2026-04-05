from __future__ import annotations

import logging

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
