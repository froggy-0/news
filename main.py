from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily SOVEREIGN BRIEF runner")
    parser.add_argument(
        "mode",
        choices=["once", "schedule"],
        help="once: execute now, schedule: run every day at 08:00 KST",
    )
    parser.add_argument(
        "--print-brief",
        action="store_true",
        help="Print generated briefing to stdout (disabled by default to avoid log leakage).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from morning_brief.config import load_settings
    from morning_brief.logging_utils import setup_logging

    settings = load_settings()
    setup_logging(output_dir=settings.output_dir)

    if args.mode == "once":
        from morning_brief.pipeline import run_pipeline

        briefing = run_pipeline(settings=settings)
        if args.print_brief:
            print(briefing)
        return

    from morning_brief.scheduler import run_daily

    run_daily(settings=settings, hour=8, minute=0)


if __name__ == "__main__":
    main()
