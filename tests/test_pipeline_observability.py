from __future__ import annotations

import json
from types import SimpleNamespace

from morning_brief.config import load_settings
from morning_brief.llm_errors import BriefGenerationError
from morning_brief.pipeline import run_pipeline


def _market_packet() -> dict:
    return {
        "generated_at_utc": "2026-03-14T00:00:00+00:00",
        "macro": [{"label": "US10Y", "price": 4.25, "change_pct": None, "change_bps": -2.0}],
        "us_indices": [{"label": "SPY", "price": 520.0, "change_pct": 0.5}],
        "tech_stocks": [{"label": "NVDA", "price": 950.0, "change_pct": 1.2}],
        "data_footer_notes": [],
        "bitcoin": {
            "spot": {"label": "BTC", "price": 85000.0, "change_pct": 0.3},
            "etf_points": [{"label": "IBIT", "price": 52.0, "change_pct": 0.1}],
            "fear_greed_value": None,
            "fear_greed_label": None,
            "official_etf_snapshots": [],
            "official_etf_total_btc": None,
            "official_etf_total_aum_usd": None,
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
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", lambda **_: ([], {}, [], {}))
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
            },
            {
                "title": "Nvidia beats earnings expectations",
                "url": "https://www.bloomberg.com/news/nvidia-earnings",
                "source": "Bloomberg",
                "published_at": "2026-03-14T02:00:00+00:00",
                "domain": "bloomberg.com",
                "source_tier": "tier_1",
                "preferred_source": True,
                "age_hours": 1.0,
                "topic": "ai_bigtech",
                "provider": "perplexity_search",
            },
            {
                "title": "Bitcoin ETF inflows surge",
                "url": "https://www.coindesk.com/bitcoin-etf-inflows",
                "source": "CoinDesk",
                "published_at": "2026-03-14T03:00:00+00:00",
                "domain": "coindesk.com",
                "source_tier": "tier_1",
                "preferred_source": True,
                "age_hours": 0.5,
                "topic": "bitcoin",
                "provider": "perplexity_search",
            },
        ]
        if observer is not None:
            observer.record_provider_usage("perplexity", requests=1, response_sources=3)
            observer.record_perplexity_topic_results(
                "macro",
                ["https://www.reuters.com/world/us/fed-keeps-options-open"],
            )
            observer.record_perplexity_final_selection(packet)
        return packet, {}, [], {}

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", fake_build_news_packet)
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda **_: "SOVEREIGN BRIEF (2026-03-14)\n\n1. 거시 환경\n본문",
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.GmailSender",
        lambda _settings: SimpleNamespace(send=lambda **_: None),
    )

    briefing = run_pipeline(settings=settings)

    assert briefing.startswith("SOVEREIGN BRIEF")
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


def test_run_pipeline_marks_brief_fallback_status_when_safe_brief_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()

    def fake_generate_briefing(*, observer=None, **_):
        assert observer is not None
        observer.log_event(
            "brief_fallback_used",
            reason="incomplete_structure",
            issues=["LAYER 2 bullet 수가 부족해요."],
        )
        return "SOVEREIGN BRIEF (2026-03-14)\n\n기본 브리핑"

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr("morning_brief.pipeline.build_news_packet", lambda **_: ([], {}, [], {}))
    monkeypatch.setattr("morning_brief.pipeline.generate_briefing", fake_generate_briefing)
    monkeypatch.setattr(
        "morning_brief.pipeline.GmailSender",
        lambda _settings: SimpleNamespace(send=lambda **_: None),
    )

    run_pipeline(settings=settings)

    run_files = list((settings.output_dir / "observability").glob("pipeline-run-*.json"))
    assert len(run_files) == 1
    payload = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert payload["summary"]["status"] in ("brief_fallback", "degraded")
    assert payload["summary"]["brief_fallback_used"] is True


def test_run_pipeline_uses_openai_backfill_only_when_quality_is_degraded(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = load_settings()
    backfill_called = {"called": False}

    initial_news = [
        {
            "title": "Weak source item",
            "url": "https://example.com/weak-item",
            "source": "Example",
            "published_at": "2026-03-14T01:00:00+00:00",
            "domain": "example.com",
            "source_tier": "tier_3",
            "preferred_source": False,
            "age_hours": 4.0,
        },
        {
            "title": "Weak source item 2",
            "url": "https://example.com/weak-item-2",
            "source": "Example",
            "published_at": "2026-03-14T02:00:00+00:00",
            "domain": "example.com",
            "source_tier": "tier_3",
            "preferred_source": False,
            "age_hours": 3.0,
        },
        {
            "title": "Weak source item 3",
            "url": "https://example.net/weak-item-3",
            "source": "Example",
            "published_at": "2026-03-14T03:00:00+00:00",
            "domain": "example.net",
            "source_tier": "tier_3",
            "preferred_source": False,
            "age_hours": 2.0,
        },
    ]
    merged_news = initial_news + [
        {
            "title": "Fed keeps options open",
            "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
            "source": "Reuters",
            "published_at": "2026-03-14T04:00:00+00:00",
            "domain": "reuters.com",
            "source_tier": "tier_1",
            "preferred_source": True,
            "age_hours": 1.0,
        }
    ]

    monkeypatch.setattr("morning_brief.pipeline.build_market_packet", lambda **_: _market_packet())
    monkeypatch.setattr(
        "morning_brief.pipeline.build_news_packet", lambda **_: (initial_news, {}, [], {})
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.backfill_news_with_web_search",
        lambda **_: backfill_called.__setitem__("called", True)
        or (
            merged_news,
            [
                {
                    "title": "Reuters",
                    "url": "https://www.reuters.com/world/us/fed-keeps-options-open",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.generate_briefing",
        lambda packet, **_: (
            "SOVEREIGN BRIEF (2026-03-14)\n\n참고 출처\n- https://www.reuters.com/world/us/fed-keeps-options-open"
            if packet.get("web_search_references")
            else "SOVEREIGN BRIEF (2026-03-14)"
        ),
    )
    monkeypatch.setattr(
        "morning_brief.pipeline.GmailSender",
        lambda _settings: SimpleNamespace(send=lambda **_: None),
    )

    briefing = run_pipeline(settings=settings)

    assert backfill_called["called"] is True
    assert "Reuters" in briefing or "reuters.com" in briefing


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
    assert usage["cost_usd"] is None
    assert summary["total_cost_usd"] is None
    assert (
        summary["provider_usage_line"]
        == "perplexity[requests=1, input=null, output=null, cached=null, reasoning=null, sources=1, parse_failures=1, cost_usd=null]"
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
        "grok_official",
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
        "openai[requests=3, input=900, output=150, cached=40, reasoning=12, sources=0, parse_failures=0, cost_usd=0.000516] | "
        "perplexity[requests=2, input=null, output=null, cached=null, reasoning=null, sources=10, parse_failures=2, cost_usd=null] | "
        "grok_official[requests=1, input=120, output=30, cached=8, reasoning=0, sources=0, parse_failures=0, cost_usd=3.8e-05]"
    )
    assert summary_event["line"] == summary["provider_usage_line"]
    assert summary_event["providers"]["openai"]["input_tokens"] == 900
    assert summary_event["providers"]["perplexity"]["input_tokens"] is None
    assert summary_event["providers"]["openai"]["cost_usd"] == 0.000516
    assert summary["total_cost_usd"] == 0.000554
