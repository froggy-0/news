from __future__ import annotations

from pathlib import Path

import pytest

from morning_brief.analysis.sentiment_join.config import load_sentiment_join_settings


def test_load_sentiment_join_settings_rejects_below_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTIMENT_JOIN_LOOKBACK_DAYS", "0")

    with pytest.raises(ValueError):
        load_sentiment_join_settings()


def test_load_sentiment_join_settings_rejects_above_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTIMENT_JOIN_LOOKBACK_DAYS", "731")

    with pytest.raises(ValueError):
        load_sentiment_join_settings()


@pytest.mark.parametrize("value", ["1", "30", "730"])
def test_load_sentiment_join_settings_accepts_boundary_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SENTIMENT_JOIN_LOOKBACK_DAYS", value)

    settings = load_sentiment_join_settings()

    assert settings.lookback_days == int(value)


def test_load_sentiment_join_settings_uses_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTIMENT_JOIN_LOOKBACK_DAYS", "90")
    monkeypatch.setenv("SENTIMENT_JOIN_OUTPUT_DIR", "tmp/sentiment-output")
    monkeypatch.setenv("SENTIMENT_JOIN_R2_MAX_CONCURRENCY", "12")
    monkeypatch.setenv("SENTIMENT_JOIN_RETAIN_DAYS", "45")
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "https://example.invalid")
    monkeypatch.setenv("KIS_APP_KEY", "app-key")
    monkeypatch.setenv("KIS_APP_SECRET", "app-secret")

    settings = load_sentiment_join_settings()

    assert settings.lookback_days == 90
    assert settings.output_dir == Path("tmp/sentiment-output").resolve()
    assert settings.r2_max_concurrency == 12
    assert settings.retain_days == 45
    assert settings.r2_public_bucket == "https://example.invalid"
    assert settings.kis_app_key == "app-key"
    assert settings.kis_app_secret == "app-secret"


def test_load_sentiment_join_settings_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "SENTIMENT_JOIN_LOOKBACK_DAYS",
        "SENTIMENT_JOIN_OUTPUT_DIR",
        "SENTIMENT_JOIN_R2_MAX_CONCURRENCY",
        "SENTIMENT_JOIN_RETAIN_DAYS",
        "R2_PUBLIC_BUCKET",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_sentiment_join_settings()

    assert settings.lookback_days == 180
    assert settings.output_dir == Path("data/sentiment_join").resolve()
    assert settings.r2_max_concurrency == 10
    assert settings.retain_days == 30
    assert settings.r2_public_bucket == ""
    assert settings.kis_app_key == ""
    assert settings.kis_app_secret == ""
