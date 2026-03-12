from __future__ import annotations

import socket

from morning_brief.data.sources import http_client


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
