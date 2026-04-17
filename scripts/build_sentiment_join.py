#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
SCRIPTS_PATH = PROJECT_ROOT / "scripts"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

if __name__ == "__main__":
    from morning_brief.analysis.sentiment_join.config import load_sentiment_join_settings
    from morning_brief.analysis.sentiment_join.pipeline import run_sentiment_join
    from morning_brief.logging_utils import setup_logging
    from validate_credentials import CredentialValidator

    # 인증정보 검증 (--skip-validation으로 건너뜀 가능)
    if "--skip-validation" not in sys.argv:
        print("\n[1/2] 인증정보 검증 중...\n")
        validator = CredentialValidator(verbose=False)
        if validator.validate_all() != 0:
            print("❌ 인증정보 검증 실패. 필수 환경변수를 설정한 후 다시 시도하세요.")
            print("   python scripts/validate_credentials.py --verbose  # 자세한 정보 보기\n")
            sys.exit(1)
        print("[2/2] 파이프라인 실행 중...\n")
    else:
        print("⏭️  인증정보 검증 건너뜀 (--skip-validation)\n")

    settings = load_sentiment_join_settings()
    setup_logging(output_dir=settings.output_dir)
    sys.exit(run_sentiment_join(settings))
