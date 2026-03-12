from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    timezone: str
    openai_api_key: str
    openai_model: str
    gmail_sender: str
    gmail_recipient: str
    gmail_credentials_file: Path
    gmail_token_file: Path
    newsapi_key: str
    max_news_items: int
    output_dir: Path
    send_email: bool



def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}



def load_settings() -> Settings:
    load_dotenv()

    output_dir = Path(os.getenv("OUTPUT_DIR", "outputs")).resolve()

    return Settings(
        timezone=os.getenv("TIMEZONE", "Asia/Seoul"),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        gmail_sender=os.getenv("GMAIL_SENDER", "").strip(),
        gmail_recipient=os.getenv("GMAIL_RECIPIENT", "").strip(),
        gmail_credentials_file=Path(
            os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
        ).resolve(),
        gmail_token_file=Path(os.getenv("GMAIL_TOKEN_FILE", "token.json")).resolve(),
        newsapi_key=os.getenv("NEWSAPI_KEY", "").strip(),
        max_news_items=int(os.getenv("MAX_NEWS_ITEMS", "5")),
        output_dir=output_dir,
        send_email=_env_bool("SEND_EMAIL", True),
    )
