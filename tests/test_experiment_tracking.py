from __future__ import annotations

import json
from pathlib import Path

from morning_brief.analysis.sentiment_join.experiments import write_tracking_artifact


def test_write_tracking_artifact(tmp_path: Path) -> None:
    path = write_tracking_artifact(
        tmp_path,
        run_id="run-1",
        spec={"horizon": 3},
        metrics={"hit_rate": 0.55},
        lineage={"funding_source": ["binance"]},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["spec"]["horizon"] == 3
    assert payload["metrics"]["hit_rate"] == 0.55
    assert payload["lineage"]["funding_source"] == ["binance"]
