from __future__ import annotations

from morning_brief.config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_TEMPLATE_VERSION,
    load_settings,
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


def test_alpha_vantage_api_key_is_ignored(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-test-key")
    settings = load_settings()
    assert settings.alpha_vantage_api_key == ""


def test_perplexity_settings_loaded(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
    monkeypatch.setenv("GROK_API_KEY", "grok-test-key")
    monkeypatch.setenv("GROK_MODEL", "grok-test-model")
    monkeypatch.setenv("RESEARCH_PROVIDER", "legacy")
    monkeypatch.setenv("ENABLE_LEGACY_NEWS_FALLBACK", "false")
    monkeypatch.setenv("ENABLE_OFFICIAL_X_SIGNALS", "false")
    monkeypatch.setenv("OFFICIAL_X_LOOKBACK_HOURS", "36")
    monkeypatch.setenv("OFFICIAL_X_MAX_ITEMS", "2")
    settings = load_settings()
    assert settings.perplexity_api_key == "pplx-test-key"
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
    monkeypatch.setenv("OPENAI_WEB_SEARCH_MAX_RESULTS", "4")
    settings = load_settings()
    assert settings.openai_web_search_enabled is False
    assert settings.openai_web_search_model == "gpt-5"
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
    assert settings.openai_max_output_tokens == 4000


def test_openai_defaults_use_snapshot_model_and_prompt_version(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BRIEF_VALIDATION_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_WEB_SEARCH_MODEL", raising=False)
    monkeypatch.delenv("PROMPT_TEMPLATE_VERSION", raising=False)

    settings = load_settings()

    assert settings.openai_model == DEFAULT_OPENAI_MODEL
    assert settings.openai_brief_validation_model == DEFAULT_OPENAI_MODEL
    assert settings.openai_web_search_model == DEFAULT_OPENAI_MODEL
    assert settings.prompt_template_version == DEFAULT_PROMPT_TEMPLATE_VERSION
