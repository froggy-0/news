from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    timezone: str
    cache_dir: Path
    openai_api_key: str
    openai_model: str
    openai_brief_validation_enabled: bool
    openai_brief_validation_model: str
    openai_brief_max_rewrites: int
    openai_web_search_enabled: bool
    openai_web_search_model: str
    openai_web_search_max_results: int
    openai_reasoning_effort: str
    openai_max_output_tokens: int
    openai_prompt_cache_key: str
    prompt_template_dir: Path
    prompt_template_version: str
    fred_api_key: str
    alpha_vantage_api_key: str
    perplexity_api_key: str
    research_provider: str
    enable_legacy_news_fallback: bool
    gmail_sender: str
    gmail_recipient: str
    gmail_credentials_file: Path
    gmail_token_file: Path
    gmail_oauth_interactive: bool
    newsapi_key: str
    max_news_items: int
    output_dir: Path
    send_email: bool



def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = int(raw.strip())
    except ValueError:
        return default

    return max(minimum, min(maximum, value))


def _env_choice(name: str, default: str, allowed: set[str]) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in allowed:
        return value
    return default



def load_settings() -> Settings:
    load_dotenv()

    output_dir = Path(os.getenv("OUTPUT_DIR", "outputs")).resolve()

    return Settings(
        timezone=os.getenv("TIMEZONE", "Asia/Seoul"),
        cache_dir=Path(os.getenv("CACHE_DIR", ".cache")).resolve(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        openai_brief_validation_enabled=_env_bool("OPENAI_BRIEF_VALIDATION_ENABLED", True),
        openai_brief_validation_model=os.getenv("OPENAI_BRIEF_VALIDATION_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        openai_brief_max_rewrites=_env_bounded_int(
            "OPENAI_BRIEF_MAX_REWRITES",
            default=1,
            minimum=0,
            maximum=2,
        ),
        openai_web_search_enabled=_env_bool("OPENAI_WEB_SEARCH_ENABLED", True),
        openai_web_search_model=os.getenv("OPENAI_WEB_SEARCH_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        openai_web_search_max_results=_env_bounded_int(
            "OPENAI_WEB_SEARCH_MAX_RESULTS",
            default=3,
            minimum=1,
            maximum=5,
        ),
        openai_reasoning_effort=_env_choice(
            "OPENAI_REASONING_EFFORT",
            default="low",
            allowed={"minimal", "low", "medium", "high"},
        ),
        openai_max_output_tokens=_env_bounded_int(
            "OPENAI_MAX_OUTPUT_TOKENS",
            default=1700,
            minimum=500,
            maximum=4000,
        ),
        openai_prompt_cache_key=os.getenv("OPENAI_PROMPT_CACHE_KEY", "").strip(),
        prompt_template_dir=Path(
            os.getenv("PROMPT_TEMPLATE_DIR", "src/morning_brief/prompts")
        ).resolve(),
        prompt_template_version=os.getenv("PROMPT_TEMPLATE_VERSION", "market_brief_v3").strip(),
        fred_api_key=os.getenv("FRED_API_KEY", "").strip(),
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY", "").strip(),
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY", "").strip(),
        research_provider=_env_choice(
            "RESEARCH_PROVIDER",
            default="perplexity",
            allowed={"perplexity", "legacy"},
        ),
        enable_legacy_news_fallback=_env_bool("ENABLE_LEGACY_NEWS_FALLBACK", True),
        gmail_sender=os.getenv("GMAIL_SENDER", "").strip(),
        gmail_recipient=os.getenv("GMAIL_RECIPIENT", "").strip(),
        gmail_credentials_file=Path(
            os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
        ).resolve(),
        gmail_token_file=Path(os.getenv("GMAIL_TOKEN_FILE", "token.json")).resolve(),
        gmail_oauth_interactive=_env_bool(
            "GMAIL_OAUTH_INTERACTIVE",
            default=not _env_bool("CI", False),
        ),
        newsapi_key=os.getenv("NEWSAPI_KEY", "").strip(),
        max_news_items=_env_bounded_int("MAX_NEWS_ITEMS", default=5, minimum=3, maximum=5),
        output_dir=output_dir,
        send_email=_env_bool("SEND_EMAIL", True),
    )
