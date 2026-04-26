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
    monkeypatch.setenv("SENTIMENT_JOIN_REGIME_WARMUP_DAYS", "180")
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "brief-public")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("NEXT_PUBLIC_R2_BASE_URL", "https://public.example.com")
    monkeypatch.setenv("KIS_APP_KEY", "app-key")
    monkeypatch.setenv("KIS_APP_SECRET", "app-secret")

    settings = load_sentiment_join_settings()

    assert settings.lookback_days == 90
    assert settings.output_dir == Path("tmp/sentiment-output").resolve()
    assert settings.r2_max_concurrency == 12
    assert settings.retain_days == 45
    assert settings.regime_warmup_days == 180
    assert settings.r2_public_bucket == "brief-public"
    assert settings.r2_s3_endpoint == "https://example.r2.cloudflarestorage.com"
    assert settings.r2_access_key_id == "key-id"
    assert settings.r2_secret_access_key == "secret"
    assert settings.r2_base_url == "https://public.example.com"
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
        "SENTIMENT_JOIN_REGIME_WARMUP_DAYS",
        "R2_PUBLIC_BUCKET",
        "R2_BUCKET_NAME",
        "R2_S3_ENDPOINT",
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "NEXT_PUBLIC_R2_BASE_URL",
        "R2_BASE_URL",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "SENTIMENT_JOIN_BINANCE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_sentiment_join_settings()

    assert settings.lookback_days == 365
    assert settings.output_dir == Path("data/sentiment_join").resolve()
    assert settings.r2_max_concurrency == 10
    assert settings.retain_days == 90
    assert settings.regime_warmup_days == 220
    assert settings.r2_public_bucket == ""
    assert settings.r2_s3_endpoint == ""
    assert settings.r2_access_key_id == ""
    assert settings.r2_secret_access_key == ""
    assert settings.r2_base_url == ""
    assert settings.kis_app_key == ""
    assert settings.kis_app_secret == ""
    assert settings.binance_api_key == ""


def test_load_sentiment_join_settings_binance_key_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SENTIMENT_JOIN_BINANCE_KEY", raising=False)

    settings = load_sentiment_join_settings()

    assert settings.binance_api_key == ""


def test_load_sentiment_join_settings_binance_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTIMENT_JOIN_BINANCE_KEY", "test-key-123")

    settings = load_sentiment_join_settings()

    assert settings.binance_api_key == "test-key-123"


def test_load_sentiment_join_settings_accepts_legacy_r2_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("R2_PUBLIC_BUCKET", raising=False)
    monkeypatch.delenv("R2_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_R2_BASE_URL", raising=False)
    monkeypatch.setenv("R2_BUCKET_NAME", "legacy-bucket")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://legacy.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BASE_URL", "https://legacy.example.com")

    settings = load_sentiment_join_settings()

    assert settings.r2_public_bucket == "legacy-bucket"
    assert settings.r2_s3_endpoint == "https://legacy.r2.cloudflarestorage.com"
    assert settings.r2_base_url == "https://legacy.example.com"
