from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from morning_brief.config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_TEMPLATE_VERSION,
    DEFAULT_SES_REGION,
    DEFAULT_SES_SENDER,
    DEFAULT_SUBSCRIPTION_NEWSLETTER_KEY,
    DEFAULT_SUBSCRIPTION_UNSUBSCRIBE_PATH,
    load_settings,
)
from morning_brief.data.news_policy import (
    _load_domain_policy,
    _parse_domain_policy,
    _resolve_domain_policy_path,
    domain_score,
)


def test_max_news_items_lower_bound(monkeypatch):
    monkeypatch.setenv("MAX_NEWS_ITEMS", "1")
    settings = load_settings()
    assert settings.max_news_items == 3


def test_max_news_items_upper_bound(monkeypatch):
    monkeypatch.setenv("MAX_NEWS_ITEMS", "99")
    settings = load_settings()
    assert settings.max_news_items == 5


def test_fred_api_key_loaded(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "fred-test-key")
    settings = load_settings()
    assert settings.fred_api_key == "fred-test-key"


def test_kis_settings_loaded(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "kis-app-key")
    monkeypatch.setenv("KIS_APP_SECRET", "kis-app-secret")
    settings = load_settings()
    assert settings.kis_app_key == "kis-app-key"
    assert settings.kis_app_secret == "kis-app-secret"


def test_kis_settings_default_to_empty(monkeypatch):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    settings = load_settings()
    assert settings.kis_app_key == ""
    assert settings.kis_app_secret == ""


def test_kis_token_cache_path_default(monkeypatch):
    monkeypatch.delenv("KIS_TOKEN_CACHE_PATH", raising=False)
    settings = load_settings()
    assert settings.kis_token_cache_path.name == "kis_token.json"
    assert settings.kis_token_cache_path.is_absolute()


def test_kis_token_cache_path_custom(monkeypatch, tmp_path):
    custom = tmp_path / "custom" / "token.json"
    monkeypatch.setenv("KIS_TOKEN_CACHE_PATH", str(custom))
    settings = load_settings()
    assert settings.kis_token_cache_path == custom


def test_perplexity_settings_loaded(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("COINDESK_NEWS_ENABLED", "true")
    monkeypatch.setenv("COINDESK_NEWS_LOOKBACK_HOURS", "48")
    monkeypatch.setenv("COINDESK_NEWS_WEEKEND_LOOKBACK_HOURS", "96")
    monkeypatch.setenv("COINDESK_NEWS_MAX_ITEMS", "18")
    monkeypatch.setenv("COINDESK_NEWS_CATEGORIES", "BTC,ETH")
    monkeypatch.setenv("GROK_API_KEY", "grok-test-key")
    monkeypatch.setenv("GROK_MODEL", "grok-test-model")
    monkeypatch.setenv("RESEARCH_PROVIDER", "legacy")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("ENABLE_OFFICIAL_X_SIGNALS", "false")
    monkeypatch.setenv("OFFICIAL_X_LOOKBACK_HOURS", "36")
    monkeypatch.setenv("OFFICIAL_X_MAX_ITEMS", "2")
    settings = load_settings()
    assert settings.perplexity_api_key == "pplx-test-key"
    assert settings.coindesk_news_enabled is True
    assert settings.coindesk_news_lookback_hours == 48
    assert settings.coindesk_news_weekend_lookback_hours == 96
    assert settings.coindesk_news_max_items == 18
    assert settings.coindesk_news_categories == "BTC,ETH"
    assert settings.grok_api_key == "grok-test-key"
    assert settings.grok_model == "grok-test-model"
    assert settings.research_provider == "legacy"
    assert settings.enable_legacy_news_fallback is False
    assert settings.enable_official_x_signals is False
    assert settings.official_x_lookback_hours == 36
    assert settings.official_x_max_items == 2


def test_research_provider_invalid_defaults_to_perplexity(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER", "unknown")
    settings = load_settings()
    assert settings.research_provider == "perplexity"


def test_cache_dir_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    settings = load_settings()
    assert settings.cache_dir == (tmp_path / "cache").resolve()


def test_openai_web_search_flags_loaded(monkeypatch):
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "false")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_MODEL", "gpt-5")
    monkeypatch.setenv("OPENAI_PUBLIC_TRANSLATION_MODEL", "gpt-5-nano")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_MAX_RESULTS", "4")
    settings = load_settings()
    assert settings.openai_web_search_enabled is False
    assert settings.openai_web_search_model == "gpt-5"
    assert settings.openai_public_translation_model == "gpt-5-nano"
    assert settings.openai_web_search_max_results == 4


def test_openai_brief_validation_flags_loaded(monkeypatch):
    monkeypatch.setenv("OPENAI_BRIEF_VALIDATION_ENABLED", "false")
    monkeypatch.setenv("OPENAI_BRIEF_VALIDATION_MODEL", "gpt-5")
    monkeypatch.setenv("OPENAI_BRIEF_MAX_REWRITES", "2")
    settings = load_settings()
    assert settings.openai_brief_validation_enabled is False
    assert settings.openai_brief_validation_model == "gpt-5"
    assert settings.openai_brief_max_rewrites == 2


def test_openai_reasoning_effort_invalid_defaults_to_low(monkeypatch):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "ultra")
    settings = load_settings()
    assert settings.openai_reasoning_effort == "low"


def test_openai_max_output_tokens_bounds(monkeypatch):
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "99999")
    settings = load_settings()
    assert settings.openai_max_output_tokens == 50000


def test_openai_defaults_use_snapshot_model_and_prompt_version(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BRIEF_VALIDATION_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_WEB_SEARCH_MODEL", raising=False)
    monkeypatch.delenv("PROMPT_TEMPLATE_VERSION", raising=False)

    settings = load_settings()

    assert settings.openai_model == DEFAULT_OPENAI_MODEL
    assert settings.openai_brief_validation_model == DEFAULT_OPENAI_MODEL
    assert settings.openai_public_translation_model == DEFAULT_OPENAI_MODEL
    assert settings.openai_web_search_model == DEFAULT_OPENAI_MODEL
    assert settings.prompt_template_version == DEFAULT_PROMPT_TEMPLATE_VERSION


def test_r2_public_settings_loaded(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "brief-public")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")

    settings = load_settings()

    assert settings.r2_public_bucket == "brief-public"
    assert settings.r2_s3_endpoint == "https://example.r2.cloudflarestorage.com"
    assert settings.r2_access_key_id == "key-id"
    assert settings.r2_secret_access_key == "secret"


def test_r2_public_settings_accept_legacy_aliases(monkeypatch):
    monkeypatch.delenv("R2_PUBLIC_BUCKET", raising=False)
    monkeypatch.delenv("R2_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("R2_BUCKET_NAME", "legacy-public")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://legacy.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")

    settings = load_settings()

    assert settings.r2_public_bucket == "legacy-public"
    assert settings.r2_s3_endpoint == "https://legacy.r2.cloudflarestorage.com"


def test_subscription_settings_loaded(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://brief.example.com/")
    monkeypatch.setenv("SUBSCRIPTION_TOKEN_SECRET", "token-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

    settings = load_settings()

    assert settings.public_app_base_url == "https://brief.example.com"
    assert settings.subscription_newsletter_key == DEFAULT_SUBSCRIPTION_NEWSLETTER_KEY
    assert settings.subscription_unsubscribe_path == DEFAULT_SUBSCRIPTION_UNSUBSCRIBE_PATH
    assert settings.subscription_token_secret == "token-secret"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_service_role_key == "service-role-key"


def test_ses_settings_loaded(monkeypatch):
    monkeypatch.setenv("SES_SENDER", "no-reply@sovereignbriefing.com")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("SES_CONFIGURATION_SET", "brief-config")

    settings = load_settings()

    assert settings.ses_sender == "no-reply@sovereignbriefing.com"
    assert settings.ses_region == "ap-northeast-2"
    assert settings.ses_configuration_set == "brief-config"


def test_ses_settings_default_to_operating_values(monkeypatch):
    monkeypatch.delenv("SES_SENDER", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    settings = load_settings()

    assert settings.ses_sender == DEFAULT_SES_SENDER
    assert settings.ses_region == DEFAULT_SES_REGION


def test_grok_x_search_max_items_default(monkeypatch):
    """Property 7: grok_x_search_max_items 기본값이 4."""
    monkeypatch.delenv("GROK_X_SEARCH_MAX_ITEMS", raising=False)
    settings = load_settings()
    assert settings.grok_x_search_max_items == 4


def test_official_x_max_items_default(monkeypatch):
    """Property 8: official_x_max_items 기본값이 3."""
    monkeypatch.delenv("OFFICIAL_X_MAX_ITEMS", raising=False)
    settings = load_settings()
    assert settings.official_x_max_items == 3


def test_grok_x_search_max_items_upper_clamp(monkeypatch):
    """Property 9: grok_x_search_max_items 상한이 8로 클램프됨."""
    monkeypatch.setenv("GROK_X_SEARCH_MAX_ITEMS", "20")
    settings = load_settings()
    assert settings.grok_x_search_max_items == 8


# ─── 도메인 정책 YAML 로더 테스트 ─────────────────────────────────────────


def _minimal_yaml_dict(domains: list[dict]) -> dict:
    return {"version": "1", "domains": domains}


def test_domain_score_reuters_equals_5() -> None:
    """YAML 로드 후 reuters.com 점수가 5.0이어야 한다."""
    assert domain_score("https://reuters.com/article/1") == 5.0


def test_resolve_domain_policy_path_is_absolute() -> None:
    path = _resolve_domain_policy_path()
    assert path.is_absolute()


def test_resolve_domain_policy_path_stable_across_cwd_change(tmp_path: Path) -> None:
    original_cwd = Path.cwd()
    path_before = _resolve_domain_policy_path()
    os.chdir(tmp_path)
    try:
        path_after = _resolve_domain_policy_path()
        assert path_before == path_after
    finally:
        os.chdir(original_cwd)


def test_load_domain_policy_missing_file_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """YAML 미존재 시 WARNING 로그 + fallback 동작 검증."""
    monkeypatch.setattr(
        "morning_brief.data.news_policy._resolve_domain_policy_path",
        lambda: tmp_path / "nonexistent.yaml",
    )
    with caplog.at_level(logging.WARNING):
        scores, tiers, preferred = _load_domain_policy()

    assert "reuters.com" in scores
    assert scores["reuters.com"] == 5.0
    assert any(
        "fallback" in r.message.lower() or "domain_policy" in r.message or "기본값" in r.message
        for r in caplog.records
    )


def test_load_domain_policy_bad_schema_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """스키마 오류 YAML 시 WARNING 로그 + fallback (예외 없음) 검증."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("domains:\n  - domain: reuters.com\n    score: -1.0\n    tier: tier_1\n")
    monkeypatch.setattr(
        "morning_brief.data.news_policy._resolve_domain_policy_path",
        lambda: bad_yaml,
    )
    with caplog.at_level(logging.WARNING):
        scores, tiers, preferred = _load_domain_policy()

    assert "reuters.com" in scores
    assert any(
        "fallback" in r.message.lower() or "domain_policy" in r.message or "기본값" in r.message
        for r in caplog.records
    )


def test_parse_domain_policy_negative_score_raises() -> None:
    raw = _minimal_yaml_dict([{"domain": "bad.com", "score": -1.0, "tier": "tier_2"}])
    with pytest.raises(ValueError, match="score"):
        _parse_domain_policy(raw)


def test_parse_domain_policy_missing_domain_raises() -> None:
    raw = _minimal_yaml_dict([{"score": 3.0, "tier": "tier_2"}])
    with pytest.raises(ValueError):
        _parse_domain_policy(raw)
