#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

if __name__ == "__main__":
    from morning_brief.analysis.sentiment_join.config import load_sentiment_join_settings
    from morning_brief.analysis.sentiment_join.pipeline import run_sentiment_join
    from morning_brief.logging_utils import setup_logging

    settings = load_sentiment_join_settings()
    setup_logging(output_dir=settings.output_dir)
    sys.exit(run_sentiment_join(settings))
