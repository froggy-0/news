from __future__ import annotations

import logging
import os


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # Keep third-party transport logs quiet so the pipeline output stays readable.
    for logger_name in [
        "httpx",
        "openai._base_client",
        "urllib3.connectionpool",
        "googleapiclient.discovery_cache",
        "perplexity",
        "google.genai",
        "google.auth",
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
