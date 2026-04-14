from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_LOGGER_CALL_FILES: set[str] = {
    "src/morning_brief/data/finbert_sentiment.py",
}
EXPECTED_GET_LOGGER_FILES = {
    "src/morning_brief/analysis/sentiment_join/hybrid_index.py",
    "src/morning_brief/analysis/sentiment_join/intelligence.py",
    "src/morning_brief/analysis/sentiment_join/join.py",
    "src/morning_brief/analysis/sentiment_join/pipeline.py",
    "src/morning_brief/analysis/sentiment_join/sources/binance.py",
    "src/morning_brief/analysis/sentiment_join/sources/btc_prices.py",
    "src/morning_brief/analysis/sentiment_join/sources/etf_flows.py",
    "src/morning_brief/analysis/sentiment_join/sources/fng.py",
    "src/morning_brief/analysis/sentiment_join/sources/futures.py",
    "src/morning_brief/analysis/sentiment_join/sources/r2_sentiment.py",
    "src/morning_brief/analysis/sentiment_join/sources/usdkrw_prices.py",
    "src/morning_brief/analysis/sentiment_join/statistical_tests.py",
    "src/morning_brief/analysis/sentiment_join/storage.py",
    "src/morning_brief/analysis/sentiment_join/validate.py",
    "src/morning_brief/brief_review.py",
    "src/morning_brief/briefing.py",
    "src/morning_brief/data/market.py",
    "src/morning_brief/data/finbert_sentiment.py",
    "src/morning_brief/data/news.py",
    "src/morning_brief/data/news_policy.py",
    "src/morning_brief/data/storage/news_data_writer.py",
    "src/morning_brief/data/sources/btc_etf_official.py",
    "src/morning_brief/data/sources/dynamic_registry_updater.py",
    "src/morning_brief/data/sources/fred.py",
    "src/morning_brief/data/sources/gemini_grounding.py",
    "src/morning_brief/data/sources/google_news_rss.py",
    "src/morning_brief/data/sources/grok_official_signals.py",
    "src/morning_brief/data/sources/grok_web_search.py",
    "src/morning_brief/data/sources/grok_x_keyword.py",
    "src/morning_brief/data/sources/http_client.py",
    "src/morning_brief/data/sources/kis.py",
    "src/morning_brief/data/sources/perplexity_search.py",
    "src/morning_brief/data/sources/perplexity_sonar.py",
    "src/morning_brief/emailer.py",
    "src/morning_brief/logging_utils.py",
    "src/morning_brief/observability.py",
    "src/morning_brief/pipeline.py",
    "src/morning_brief/public_news_analysis.py",
    "src/morning_brief/public_site.py",
    "src/morning_brief/raw_capture.py",
    "src/morning_brief/research_backfill.py",
    "src/morning_brief/scheduler.py",
    "src/morning_brief/unified_output.py",
}
EXPECTED_OBSERVER_CALL_FILES = {
    "src/morning_brief/brief_review.py",
    "src/morning_brief/briefing.py",
    "src/morning_brief/data/market.py",
    "src/morning_brief/data/finbert_sentiment.py",
    "src/morning_brief/data/news.py",
    "src/morning_brief/data/sources/btc_etf_official.py",
    "src/morning_brief/data/sources/dynamic_registry_updater.py",
    "src/morning_brief/data/sources/gemini_grounding.py",
    "src/morning_brief/data/sources/grok_official_signals.py",
    "src/morning_brief/data/sources/grok_web_search.py",
    "src/morning_brief/data/sources/grok_x_keyword.py",
    "src/morning_brief/data/sources/perplexity_search.py",
    "src/morning_brief/data/sources/perplexity_sonar.py",
    "src/morning_brief/pipeline.py",
    "src/morning_brief/public_news_analysis.py",
    "src/morning_brief/public_site.py",
    "src/morning_brief/research_backfill.py",
}

OUT_OF_SCOPE_PRINT_FILES = {
    "main.py",
    "src/morning_brief/analysis/sentiment_join/inspect.py",
}


def _runtime_python_files() -> list[Path]:
    files = [ROOT / "main.py"]
    files.extend(sorted((ROOT / "src" / "morning_brief").rglob("*.py")))
    return files


def test_logger_surface_matches_allowlist() -> None:
    pattern = re.compile(r"logger\.(debug|info|warning|error|exception|critical)\(")
    observed = {
        str(path.relative_to(ROOT))
        for path in _runtime_python_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert observed == EXPECTED_LOGGER_CALL_FILES


def test_get_logger_surface_matches_allowlist() -> None:
    pattern = re.compile(r"logging\.getLogger\(__name__\)")
    observed = {
        str(path.relative_to(ROOT))
        for path in _runtime_python_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert observed == EXPECTED_GET_LOGGER_FILES


def test_observer_surface_matches_allowlist() -> None:
    pattern = re.compile(r"observer\.(log_event|record_provider_usage)\(")
    observed = {
        str(path.relative_to(ROOT))
        for path in _runtime_python_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert observed == EXPECTED_OBSERVER_CALL_FILES


def test_runtime_print_usage_is_explicitly_scoped() -> None:
    pattern = re.compile(r"\bprint\(")
    observed = {
        str(path.relative_to(ROOT))
        for path in _runtime_python_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert observed == OUT_OF_SCOPE_PRINT_FILES


def test_workflow_marks_wrapper_logs_and_uploads_jsonl_artifact() -> None:
    workflow = (ROOT / ".github" / "workflows" / "morning-brief.yml").read_text(encoding="utf-8")
    assert "[workflow]" in workflow
    assert "outputs/observability/*.jsonl" in workflow
