from __future__ import annotations

from morning_brief.config import load_settings



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


def test_alpha_vantage_api_key_loaded(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-test-key")
    settings = load_settings()
    assert settings.alpha_vantage_api_key == "alpha-test-key"


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


def test_openai_reasoning_effort_invalid_defaults_to_low(monkeypatch):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "ultra")
    settings = load_settings()
    assert settings.openai_reasoning_effort == "low"


def test_openai_max_output_tokens_bounds(monkeypatch):
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "99999")
    settings = load_settings()
    assert settings.openai_max_output_tokens == 4000
