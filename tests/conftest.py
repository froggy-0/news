from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(autouse=True)
def reset_provider_runtime_state():
    from morning_brief.data.sources.provider_runtime import reset_provider_runtime_state

    reset_provider_runtime_state()
    yield
    reset_provider_runtime_state()
