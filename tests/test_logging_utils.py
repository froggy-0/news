from __future__ import annotations

import json
import logging
from pathlib import Path

from morning_brief.logging_utils import (
    bind_attempt,
    bind_phase,
    bind_provider,
    build_logging_config,
    set_run_context,
    setup_logging,
    shutdown_logging,
)
from morning_brief.observability import PipelineObserver


def teardown_function() -> None:
    shutdown_logging()
    set_run_context(None)


def test_build_logging_config_centralizes_root_and_third_party_policy() -> None:
    config = build_logging_config()
    assert config["root"]["handlers"] == ["queue"]
    assert config["loggers"]["morning_brief"]["propagate"] is True
    assert config["loggers"]["httpx"]["level"] == "WARNING"


def test_setup_logging_writes_console_and_jsonl_with_context(tmp_path, capsys):
    setup_logging(output_dir=tmp_path)
    set_run_context("run-123")
    logger = logging.getLogger("morning_brief.tests.logging")

    with bind_phase("news"), bind_provider("perplexity"), bind_attempt(2):
        logger.info(
            "selection completed",
            extra={
                "event": "selection.complete",
                "attributes": {"candidate_count": 24, "kept_count": 12},
            },
        )

    shutdown_logging()
    console = capsys.readouterr().out
    assert "run=run-123" in console
    assert "phase=news" in console
    assert "provider=perplexity" in console
    assert "event=selection.complete" in console

    app_events = tmp_path / "observability" / "app-events-run-123.jsonl"
    assert app_events.exists()
    lines = [json.loads(line) for line in app_events.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    event = lines[0]
    assert event["run_id"] == "run-123"
    assert event["phase"] == "news"
    assert event["provider"] == "perplexity"
    assert event["attempt"] == 2
    assert event["event"] == "selection.complete"
    assert event["attributes"]["candidate_count"] == 24
    assert event["attributes"]["kept_count"] == 12


def test_local_and_ci_logging_share_required_field_contract(tmp_path, capsys) -> None:
    setup_logging(output_dir=tmp_path)
    set_run_context("run-parity")
    logger = logging.getLogger("morning_brief.tests.parity")

    with bind_phase("brief"), bind_provider("openai"), bind_attempt(1):
        logger.error(
            "brief generation failed",
            extra={
                "event": "error.raised",
                "attributes": {"reason": "timeout", "retryable": True},
            },
        )

    shutdown_logging()
    console = capsys.readouterr().out
    assert "run=run-parity" in console
    assert "phase=brief" in console
    assert "provider=openai" in console
    assert "event=error.raised" in console

    app_events = tmp_path / "observability" / "app-events-run-parity.jsonl"
    payload = json.loads(app_events.read_text(encoding="utf-8").splitlines()[0])
    for field, expected in {
        "run_id": "run-parity",
        "phase": "brief",
        "provider": "openai",
        "event": "error.raised",
        "message": "brief generation failed",
    }.items():
        assert payload[field] == expected
    assert payload["severity_text"] == "ERROR"
    assert isinstance(payload["attributes"], dict)
    assert payload["attributes"]["reason"] == "timeout"

    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "morning-brief.yml"
    ).read_text(encoding="utf-8")
    assert "python main.py once 2>&1 | tee run.log" in workflow
    assert "outputs/observability/*.jsonl" in workflow


def test_logging_redacts_and_truncates_payloads(tmp_path):
    setup_logging(output_dir=tmp_path)
    set_run_context("run-456")
    logger = logging.getLogger("morning_brief.tests.redaction")

    logger.warning(
        "provider request failed",
        extra={
            "event": "provider.request",
            "attributes": {
                "api_key": "super-secret",
                "body": "x" * 700,
                "items": list(range(15)),
            },
        },
    )

    shutdown_logging()
    app_events = tmp_path / "observability" / "app-events-run-456.jsonl"
    payload = json.loads(app_events.read_text(encoding="utf-8").splitlines()[0])
    assert payload["attributes"]["api_key"] == "***"
    assert "truncated" in payload["attributes"]["body"]
    assert payload["attributes"]["items"][-1]["truncated_count"] == 5


def test_critical_level_uses_canonical_schema(tmp_path):
    setup_logging(output_dir=tmp_path)
    set_run_context("run-critical")
    logger = logging.getLogger("morning_brief.tests.critical")

    logger.critical(
        "critical failure",
        extra={"event": "error.raised", "attributes": {"reason": "boom", "retryable": False}},
    )

    shutdown_logging()
    app_events = tmp_path / "observability" / "app-events-run-critical.jsonl"
    payload = json.loads(app_events.read_text(encoding="utf-8").splitlines()[0])
    assert payload["level"] == "CRITICAL"
    assert payload["severity_text"] == "FATAL"
    assert payload["severity_number"] == 21
    assert payload["event"] == "error.raised"


def test_observer_write_outputs_writes_app_events_and_single_pipeline_summary(tmp_path):
    observer = PipelineObserver(output_dir=tmp_path)
    observer.log_event("custom_event", reason="ok")

    summary = observer.write_outputs(
        status="ok", provider_stats={}, extra={"total_duration_ms": 42}
    )

    run_file = next(tmp_path.glob("observability/pipeline-run-*.json"))
    app_events = next(tmp_path.glob("observability/app-events-*.jsonl"))

    run_payload = json.loads(run_file.read_text(encoding="utf-8"))
    pipeline_summaries = [
        event for event in run_payload["events"] if event["event"] == "pipeline_summary"
    ]

    assert len(pipeline_summaries) == 1
    assert run_payload["events"][-1]["event"] == "pipeline_summary"
    assert summary["app_events_path"] == str(app_events)
    assert app_events.read_text(encoding="utf-8").strip()
