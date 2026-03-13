from __future__ import annotations

from morning_brief.data.sources import provider_runtime


def test_retry_delay_seconds_uses_exponential_backoff_with_midpoint_jitter(monkeypatch):
    monkeypatch.setattr(provider_runtime.random, "random", lambda: 0.5)

    first = provider_runtime.retry_delay_seconds(
        provider="perplexity",
        attempt=1,
        base_backoff_seconds=2.0,
    )
    second = provider_runtime.retry_delay_seconds(
        provider="perplexity",
        attempt=2,
        base_backoff_seconds=2.0,
    )

    assert round(first, 2) == 2.0
    assert round(second, 2) == 4.0


def test_execute_with_provider_retry_tracks_retries_and_success(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    monkeypatch.setattr(provider_runtime.random, "random", lambda: 0.5)
    monkeypatch.setattr(provider_runtime.time, "sleep", lambda seconds: sleeps.append(seconds))
    provider_runtime.reset_provider_runtime_state()

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary failure")
        return "ok"

    result = provider_runtime.execute_with_provider_retry(
        provider="test_provider",
        operation=operation,
        should_retry=lambda exc: True,
        max_attempts=3,
        base_backoff_seconds=2.0,
    )

    assert result == "ok"
    assert calls["count"] == 3
    assert sleeps == [2.0, 4.0]
    assert provider_runtime.provider_stats_snapshot()["test_provider"] == {
        "requests": 3,
        "successes": 1,
        "failures": 0,
        "retries": 2,
        "skips": 0,
        "circuit_opened": 0,
    }
