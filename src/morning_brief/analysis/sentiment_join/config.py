from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class SentimentJoinSettings:
    lookback_days: int
    output_dir: Path
    r2_public_bucket: str
    r2_base_url: str
    r2_max_concurrency: int
    retain_days: int
    kis_app_key: str
    kis_app_secret: str
    binance_api_key: str
    futures_lambda_arn: str


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


def load_sentiment_join_settings() -> SentimentJoinSettings:
    load_dotenv()

    lookback_days = _env_bounded_int(
        "SENTIMENT_JOIN_LOOKBACK_DAYS",
        default=180,
        minimum=0,
        maximum=10_000,
    )
    if lookback_days < 1 or lookback_days > 730:
        raise ValueError("SENTIMENT_JOIN_LOOKBACK_DAYS must be between 1 and 730")

    output_dir = Path(os.getenv("SENTIMENT_JOIN_OUTPUT_DIR", "data/sentiment_join")).resolve()
    r2_max_concurrency = _env_bounded_int(
        "SENTIMENT_JOIN_R2_MAX_CONCURRENCY",
        default=10,
        minimum=1,
        maximum=64,
    )
    retain_days = _env_bounded_int(
        "SENTIMENT_JOIN_RETAIN_DAYS",
        default=30,
        minimum=0,
        maximum=3650,
    )

    return SentimentJoinSettings(
        lookback_days=lookback_days,
        output_dir=output_dir,
        r2_public_bucket=os.getenv("R2_PUBLIC_BUCKET", "").strip(),
        r2_base_url=os.getenv("NEXT_PUBLIC_R2_BASE_URL", "").strip(),
        r2_max_concurrency=r2_max_concurrency,
        retain_days=retain_days,
        kis_app_key=os.getenv("KIS_APP_KEY", "").strip(),
        kis_app_secret=os.getenv("KIS_APP_SECRET", "").strip(),
        binance_api_key=os.getenv("SENTIMENT_JOIN_BINANCE_KEY", "").strip(),
        futures_lambda_arn=os.getenv("FUTURES_LAMBDA_ARN", "").strip(),
    )


__all__ = [
    "SentimentJoinSettings",
    "load_sentiment_join_settings",
]
