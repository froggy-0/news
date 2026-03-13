from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from morning_brief.data.sources import http_client, provider_runtime


def test_is_host_resolvable_uses_ttl_cache(monkeypatch):
    calls: list[str] = []
    now = {"value": 100.0}

    def fake_gethostbyname(host: str) -> str:
        calls.append(host)
        return "127.0.0.1"

    monkeypatch.setattr(http_client.socket, "gethostbyname", fake_gethostbyname)
    monkeypatch.setattr(http_client.time, "monotonic", lambda: now["value"])
    http_client._host_resolution_cache.clear()

    assert http_client.is_host_resolvable("https://api.example.com/data")
    assert http_client.is_host_resolvable("https://api.example.com/data")
    assert calls == ["api.example.com"]

    now["value"] += http_client.HOST_RESOLUTION_CACHE_TTL_SECONDS + 1
    assert http_client.is_host_resolvable("https://api.example.com/data")
    assert calls == ["api.example.com", "api.example.com"]


def test_is_host_resolvable_refreshes_failed_dns_after_ttl(monkeypatch):
    calls: list[str] = []
    now = {"value": 200.0}

    def fake_gethostbyname(host: str) -> str:
        calls.append(host)
        if len(calls) == 1:
            raise socket.gaierror("temporary failure")
        return "127.0.0.1"

    monkeypatch.setattr(http_client.socket, "gethostbyname", fake_gethostbyname)
    monkeypatch.setattr(http_client.time, "monotonic", lambda: now["value"])
    http_client._host_resolution_cache.clear()

    assert not http_client.is_host_resolvable("query2.finance.yahoo.com")
    assert not http_client.is_host_resolvable("query2.finance.yahoo.com")
    assert calls == ["query2.finance.yahoo.com"]

    now["value"] += http_client.HOST_RESOLUTION_CACHE_TTL_SECONDS + 1
    assert http_client.is_host_resolvable("query2.finance.yahoo.com")
    assert calls == ["query2.finance.yahoo.com", "query2.finance.yahoo.com"]


def test_get_text_with_retry_does_not_retry_non_retryable_404(monkeypatch):
    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return SimpleNamespace(status_code=404, headers={}, text="not found")

    monkeypatch.setattr(http_client, "is_host_resolvable", lambda *_: True)
    monkeypatch.setattr(http_client.requests, "get", fake_get)
    provider_runtime.reset_provider_runtime_state()

    with pytest.raises(http_client.HttpFetchError) as exc_info:
        http_client.get_text_with_retry("https://example.com/missing", provider="btc_etf_official")

    assert calls["count"] == 1
    assert exc_info.value.status_code == 404
    assert exc_info.value.retryable is False


def test_get_text_with_retry_retries_429_and_uses_retry_after(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []
    now = {"value": 100.0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(status_code=429, headers={"Retry-After": "7"}, text="")
        return SimpleNamespace(status_code=200, headers={}, text="ok")

    monkeypatch.setattr(http_client, "is_host_resolvable", lambda *_: True)
    monkeypatch.setattr(http_client.requests, "get", fake_get)
    monkeypatch.setattr(provider_runtime.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        provider_runtime.time,
        "sleep",
        lambda seconds: sleeps.append(seconds) or now.__setitem__("value", now["value"] + seconds),
    )
    provider_runtime.reset_provider_runtime_state()

    text = http_client.get_text_with_retry(
        "https://example.com/rate-limited", provider="alpha_vantage"
    )

    assert text == "ok"
    assert calls["count"] == 2
    assert 7.0 in sleeps


def test_get_text_with_retry_parses_http_date_retry_after(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []
    now = {"value": 200.0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(
                status_code=429,
                headers={"Retry-After": "Fri, 13 Mar 2026 08:00:05 GMT"},
                text="",
            )
        return SimpleNamespace(status_code=200, headers={}, text="ok")

    monkeypatch.setattr(http_client, "is_host_resolvable", lambda *_: True)
    monkeypatch.setattr(http_client.requests, "get", fake_get)
    monkeypatch.setattr(provider_runtime.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        provider_runtime.time,
        "sleep",
        lambda seconds: sleeps.append(seconds) or now.__setitem__("value", now["value"] + seconds),
    )
    monkeypatch.setattr(provider_runtime.time, "time", lambda: 1773388800.0)
    provider_runtime.reset_provider_runtime_state()

    text = http_client.get_text_with_retry(
        "https://example.com/retry-after-date", provider="alpha_vantage"
    )

    assert text == "ok"
    assert calls["count"] == 2
    assert sleeps and round(sleeps[0], 2) == 5.0


def test_get_text_with_retry_uses_exponential_backoff_without_retry_after(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []
    now = {"value": 300.0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(status_code=503, headers={}, text="")
        return SimpleNamespace(status_code=200, headers={}, text="ok")

    monkeypatch.setattr(http_client, "is_host_resolvable", lambda *_: True)
    monkeypatch.setattr(http_client.requests, "get", fake_get)
    monkeypatch.setattr(provider_runtime.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(
        provider_runtime.time,
        "sleep",
        lambda seconds: sleeps.append(seconds) or now.__setitem__("value", now["value"] + seconds),
    )
    monkeypatch.setattr(provider_runtime.random, "random", lambda: 0.5)
    provider_runtime.reset_provider_runtime_state()

    text = http_client.get_text_with_retry("https://example.com/transient", provider="fred")

    assert text == "ok"
    assert calls["count"] == 2
    assert sleeps and round(sleeps[0], 2) == http_client.DEFAULT_BACKOFF


def test_get_text_with_retry_skips_provider_with_open_circuit(monkeypatch):
    monkeypatch.setattr(http_client, "is_host_resolvable", lambda *_: True)
    provider_runtime.reset_provider_runtime_state()
    provider_runtime.open_circuit("alpha_vantage", "quota exhausted")

    with pytest.raises(http_client.HttpFetchError) as exc_info:
        http_client.get_text_with_retry("https://example.com/data", provider="alpha_vantage")

    assert "quota exhausted" in str(exc_info.value)
