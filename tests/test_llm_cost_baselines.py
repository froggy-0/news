from __future__ import annotations

import json
from pathlib import Path


def _load_fixture(name: str) -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / "llm_cost_baselines" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_llm_cost_baseline_fixtures_capture_recent_regression() -> None:
    stable_run = _load_fixture("23390939438")
    regression_run = _load_fixture("23439961352")

    assert stable_run["provider_usage"]["openai"]["requests"] == 4
    assert regression_run["provider_usage"]["openai"]["requests"] == 9
    assert (
        regression_run["provider_usage"]["openai"]["input_tokens"]
        > stable_run["provider_usage"]["openai"]["input_tokens"]
    )
    assert (
        regression_run["provider_usage"]["openai"]["cost_usd"]
        > stable_run["provider_usage"]["openai"]["cost_usd"]
    )
    assert regression_run["total_cost_usd"] > stable_run["total_cost_usd"]
