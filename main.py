from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from morning_brief.config import load_settings
from morning_brief.scheduler import run_daily, run_once



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Morning Market Brief runner")
    parser.add_argument(
        "mode",
        choices=["once", "schedule"],
        help="once: execute now, schedule: run every day at 08:00 KST",
    )
    return parser.parse_args()



def main() -> None:
    args = parse_args()
    settings = load_settings()

    if args.mode == "once":
        briefing = run_once(settings=settings)
        print(briefing)
        return

    run_daily(settings=settings, hour=8, minute=0)


if __name__ == "__main__":
    main()
