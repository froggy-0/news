from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_OPENAI_MODEL = "gpt-5-mini-2025-08-07"
DEFAULT_PROMPT_TEMPLATE_VERSION = "market_brief_v4"
DEFAULT_SUBSCRIPTION_NEWSLETTER_KEY = "morning-brief"
DEFAULT_SUBSCRIPTION_UNSUBSCRIBE_PATH = "/unsubscribe"
DEFAULT_SES_REGION = "ap-northeast-2"
DEFAULT_SES_SENDER = "no-reply@sovereignbriefing.com"


@dataclass(frozen=True)
class Settings:
    timezone: str
    cache_dir: Path
    openai_api_key: str
    openai_model: str
    openai_brief_validation_enabled: bool
    openai_brief_validation_model: str
    openai_public_translation_model: str
    openai_public_news_analysis_enabled: bool
    openai_public_news_analysis_model: str
    openai_brief_max_rewrites: int
    gemini_api_key: str
    gemini_model: str
    openai_web_search_enabled: bool
    openai_web_search_model: str
    openai_web_search_max_results: int
    openai_reasoning_effort: str
    openai_max_output_tokens: int
    openai_prompt_cache_key: str
    prompt_template_dir: Path
    prompt_template_version: str
    fred_api_key: str
    perplexity_api_key: str
    perplexity_use_sonar: bool
    perplexity_sonar_model: str
    perplexity_sonar_max_tokens: int
    grok_api_key: str
    grok_model: str
    grok_x_keyword_search_enabled: bool
    grok_web_search_enabled: bool
    grok_x_search_max_items: int
    grok_web_search_max_items: int
    research_provider: str
    enable_legacy_news_fallback: bool
    enable_official_x_signals: bool
    official_x_lookback_hours: int
    official_x_max_items: int
    ses_sender: str
    ses_region: str
    ses_configuration_set: str
    public_app_base_url: str
    subscription_newsletter_key: str
    subscription_unsubscribe_path: str
    subscription_token_secret: str
    supabase_url: str
    supabase_service_role_key: str
    newsapi_key: str
    max_news_items: int
    output_dir: Path
    r2_public_bucket: str
    r2_s3_endpoint: str
    r2_access_key_id: str
    r2_secret_access_key: str
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
        openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
        openai_brief_validation_enabled=_env_bool("OPENAI_BRIEF_VALIDATION_ENABLED", True),
        openai_brief_validation_model=os.getenv("OPENAI_BRIEF_VALIDATION_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
        openai_public_translation_model=os.getenv("OPENAI_PUBLIC_TRANSLATION_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
        openai_public_news_analysis_enabled=_env_bool("OPENAI_PUBLIC_NEWS_ANALYSIS_ENABLED", True),
        openai_public_news_analysis_model=os.getenv("OPENAI_PUBLIC_NEWS_ANALYSIS_MODEL", "").strip()
        or os.getenv("OPENAI_PUBLIC_TRANSLATION_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
        openai_brief_max_rewrites=_env_bounded_int(
            "OPENAI_BRIEF_MAX_REWRITES",
            default=1,
            minimum=0,
            maximum=2,
        ),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip(),
        openai_web_search_enabled=_env_bool("OPENAI_WEB_SEARCH_ENABLED", True),
        openai_web_search_model=os.getenv("OPENAI_WEB_SEARCH_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip(),
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
            default=50000,
            minimum=500,
            maximum=50000,
        ),
        openai_prompt_cache_key=os.getenv("OPENAI_PROMPT_CACHE_KEY", "").strip(),
        prompt_template_dir=Path(
            os.getenv("PROMPT_TEMPLATE_DIR", "src/morning_brief/prompts")
        ).resolve(),
        prompt_template_version=os.getenv(
            "PROMPT_TEMPLATE_VERSION", DEFAULT_PROMPT_TEMPLATE_VERSION
        ).strip(),
        fred_api_key=os.getenv("FRED_API_KEY", "").strip(),
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY", "").strip(),
        perplexity_use_sonar=_env_bool("PERPLEXITY_USE_SONAR_SUMMARY", True),
        perplexity_sonar_model=os.getenv("PERPLEXITY_SONAR_MODEL", "sonar").strip(),
        perplexity_sonar_max_tokens=_env_bounded_int(
            "PERPLEXITY_SONAR_MAX_TOKENS", default=1500, minimum=500, maximum=4000
        ),
        grok_api_key=os.getenv("GROK_API_KEY", "").strip(),
        grok_model=os.getenv("GROK_MODEL", "grok-4-1-fast-non-reasoning").strip(),
        grok_x_keyword_search_enabled=_env_bool("GROK_X_KEYWORD_SEARCH_ENABLED", True),
        grok_web_search_enabled=_env_bool("GROK_WEB_SEARCH_ENABLED", False),
        grok_x_search_max_items=_env_bounded_int(
            "GROK_X_SEARCH_MAX_ITEMS", default=4, minimum=1, maximum=8
        ),
        grok_web_search_max_items=_env_bounded_int(
            "GROK_WEB_SEARCH_MAX_ITEMS", default=8, minimum=1, maximum=12
        ),
        research_provider=_env_choice(
            "RESEARCH_PROVIDER",
            default="perplexity",
            allowed={"perplexity", "legacy"},
        ),
        enable_legacy_news_fallback=_env_bool("ENABLE_LEGACY_NEWS_FALLBACK", True),
        enable_official_x_signals=_env_bool("ENABLE_OFFICIAL_X_SIGNALS", True),
        official_x_lookback_hours=_env_bounded_int(
            "OFFICIAL_X_LOOKBACK_HOURS",
            default=48,
            minimum=24,
            maximum=72,
        ),
        official_x_max_items=_env_bounded_int(
            "OFFICIAL_X_MAX_ITEMS",
            default=3,
            minimum=1,
            maximum=5,
        ),
        ses_sender=os.getenv("SES_SENDER", DEFAULT_SES_SENDER).strip() or DEFAULT_SES_SENDER,
        ses_region=os.getenv("AWS_REGION", DEFAULT_SES_REGION).strip() or DEFAULT_SES_REGION,
        ses_configuration_set=os.getenv("SES_CONFIGURATION_SET", "").strip(),
        public_app_base_url=os.getenv("PUBLIC_APP_BASE_URL", "").strip().rstrip("/"),
        subscription_newsletter_key=DEFAULT_SUBSCRIPTION_NEWSLETTER_KEY,
        subscription_unsubscribe_path=DEFAULT_SUBSCRIPTION_UNSUBSCRIBE_PATH,
        subscription_token_secret=os.getenv("SUBSCRIPTION_TOKEN_SECRET", "").strip(),
        supabase_url=os.getenv("SUPABASE_URL", "").strip(),
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        newsapi_key=os.getenv("NEWSAPI_KEY", "").strip(),
        max_news_items=_env_bounded_int("MAX_NEWS_ITEMS", default=5, minimum=3, maximum=5),
        output_dir=output_dir,
        r2_public_bucket=os.getenv("R2_PUBLIC_BUCKET", "").strip(),
        r2_s3_endpoint=os.getenv("R2_S3_ENDPOINT", "").strip(),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        send_email=_env_bool("SEND_EMAIL", True),
    )
