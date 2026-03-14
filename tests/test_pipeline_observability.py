from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.config import load_settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.pipeline import run_pipeline


def _market_packet() -> dict:
    return {
        "generated_at_utc": "2026-03-14T00:00:00+00:00",
        "macro": [],
        "us_indices": [],
        "tech_stocks": [],
        "data_footer_notes": [],
        "bitcoin": {
            "spot": {},
            "etf_points": [],
            "etf_total_volume": None,
            "fear_greed_value": None,
            "fear_greed_label": None,
            "official_etf_snapshots": [],
            "official_etf_total_btc": None,
            "official_etf_total_aum_usd": None,
            "official_etf_daily_flow_btc": None,
            "official_etf_daily_flow_usd": None,
            "official_etf_supported_tickers": [],
            "official_etf_compared_tickers": [],
        },
    }


def test_run_pipeline_skips_email_when_openai_generation_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("CACHE_BTC_ETF_KEY", "btc-etf-snapshots-20260314")
    monkeypatch.setenv("CACHE_BTC_ETF_HIT", "false")
    monkeypatch.setenv("CACHE_BTC_ETF_STATUS", "miss")
    settings = load_settings()
    sent = {"called": False}

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", lambda **_: [])
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: (_ for _ in ()).throw(BriefGenerationError("openai down")),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.GmailSender",
        lambda _settings: SimpleNamespace(
            send=lambda **_: sent.__setitem__("called", True),
        ),
    )

    try:
        run_pipeline(settings=settings)
    except BriefGenerationError as exc:
        assert "openai down" in str(exc)
    else:
        raise AssertionError("BriefGenerationError was expected")

    assert sent["called"] is False
    run_files = list((settings.output_dir / "observability").glob("pipeline-run-*.json"))
    assert len(run_files) == 1
    payload = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert payload["summary"]["status"] == "openai_failed"
    assert payload["summary"]["failure_message"] == "openai down"
    assert payload["summary"]["cache_statuses"][0]["hit"] is False
    assert payload["summary"]["cache_statuses"][0]["status"] == "miss"


def test_run_pipeline_writes_observability_and_perplexity_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("CACHE_BTC_ETF_KEY", "btc-etf-snapshots-20260314")
    monkeypatch.setenv("CACHE_BTC_ETF_HIT", "true")
    monkeypatch.setenv("CACHE_BTC_ETF_STATUS", "primary_hit")
    monkeypatch.setenv("CACHE_MARKET_KEY", "market-snapshot-20260314")
    monkeypatch.setenv("CACHE_MARKET_HIT", "false")
    monkeypatch.setenv("CACHE_MARKET_STATUS", "miss")
    settings = load_settings()

    def fake_build_news_packet(*, observer=None, **_):
        packet = [
            {
                "title": "Fed keeps options open",
                "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                "source": "Reuters",
                "published_at": "2026-03-14T01:00:00+00:00",
                "domain": "reuters.com",
                "source_tier": "tier_1",
                "preferred_source": True,
                "age_hours": 2.0,
                "topic": "macro",
                "provider": "perplexity_search",
            }
        ]
        if observer is not None:
            observer.record_provider_usage("perplexity", requests=1, response_sources=1)
            observer.record_perplexity_topic_results(
                "macro",
                ["https://www.reuters.com/world/us/fed-keeps-options-open"],
            )
            observer.record_perplexity_final_selection(packet)
        return packet

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", fake_build_news_packet)
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "Morning Market Brief (2026-03-14)\n\n1. 거시 환경\n본문",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.GmailSender",
        lambda _settings: SimpleNamespace(send=lambda **_: None),
    )

    briefing = run_pipeline(settings=settings)

    assert briefing.startswith("Morning Market Brief")
    run_files = list((settings.output_dir / "observability").glob("pipeline-run-*.json"))
    audit_files = list((settings.output_dir / "observability").glob("perplexity-audit-*.json"))
    assert len(run_files) == 1
    assert len(audit_files) == 1

    run_payload = json.loads(run_files[0].read_text(encoding="utf-8"))
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert run_payload["summary"]["status"] == "ok"
    assert "market" in run_payload["summary"]["durations_ms"]
    assert "news" in run_payload["summary"]["durations_ms"]
    assert "backfill" in run_payload["summary"]["durations_ms"]
    assert "email" in run_payload["summary"]["durations_ms"]
    assert run_payload["summary"]["cache_statuses"][0]["status"] == "primary_hit"
    assert run_payload["summary"]["cache_statuses"][1]["status"] == "miss"
    assert audit_payload["topics"]["macro"]["final_urls"] == [
        "https://www.reuters.com/world/us/fed-keeps-options-open"
    ]


def test_pipeline_observability_serializes_null_provider_token_usage(tmp_path):
    from morning_brief.observability import PipelineObserver

    observer = PipelineObserver(output_dir=tmp_path)
    observer.record_provider_usage(
        "perplexity",
        requests=1,
        response_sources=1,
        input_tokens=None,
        output_tokens=None,
        cached_input_tokens=None,
        usage_parse_failures=1,
    )

    summary = observer.write_outputs(status="ok", provider_stats={}, extra={})
    usage = summary["provider_usage"]["perplexity"]

    assert usage["requests"] == 1
    assert usage["response_sources"] == 1
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None
    assert usage["cached_input_tokens"] is None
    assert usage["usage_parse_failures"] == 1
    assert (
        summary["provider_usage_line"]
        == "perplexity[requests=1, input=null, output=null, cached=null, reasoning=null, sources=1, parse_failures=1]"
    )


def test_pipeline_observability_writes_provider_usage_summary_event(tmp_path):
    from morning_brief.observability import PipelineObserver

    observer = PipelineObserver(output_dir=tmp_path)
    observer.record_provider_usage(
        "perplexity",
        requests=2,
        response_sources=10,
        input_tokens=None,
        output_tokens=None,
        cached_input_tokens=None,
        reasoning_tokens=None,
        usage_parse_failures=2,
    )
    observer.record_provider_usage(
        "grok",
        requests=1,
        input_tokens=120,
        output_tokens=30,
        cached_input_tokens=8,
        reasoning_tokens=0,
    )
    observer.record_provider_usage(
        "openai",
        requests=3,
        input_tokens=900,
        output_tokens=150,
        cached_input_tokens=40,
        reasoning_tokens=12,
    )

    summary = observer.write_outputs(status="ok", provider_stats={}, extra={})
    run_files = list(tmp_path.glob("observability/pipeline-run-*.json"))
    assert len(run_files) == 1

    payload = json.loads(run_files[0].read_text(encoding="utf-8"))
    summary_event = next(
        event for event in payload["events"] if event["event"] == "provider_usage_summary"
    )

    assert summary["provider_usage_line"] == (
        "openai[requests=3, input=900, output=150, cached=40, reasoning=12, sources=0, parse_failures=0] | "
        "perplexity[requests=2, input=null, output=null, cached=null, reasoning=null, sources=10, parse_failures=2] | "
        "grok[requests=1, input=120, output=30, cached=8, reasoning=0, sources=0, parse_failures=0]"
    )
    assert summary_event["line"] == summary["provider_usage_line"]
    assert summary_event["providers"]["openai"]["input_tokens"] == 900
    assert summary_event["providers"]["perplexity"]["input_tokens"] is None
