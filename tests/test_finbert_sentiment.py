"""FinBERT 감성 분석 모듈 테스트."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from morning_brief.config import load_settings
from morning_brief.data.finbert_sentiment import (
    FinBertScorer,
    _check_deps,
    _select_items_for_scoring,
    build_public_news_sentiment_text,
    build_public_signal_sentiment_text,
    enrich_news_packet,
    enrich_x_signals,
)

# ── combine_fields 단위 테스트 (ML 의존성 불필요) ──


def test_combine_fields_basic() -> None:
    result = FinBertScorer.combine_fields("Hello world", "Summary text", "Why it matters")
    assert "Hello world" in result
    assert "Summary text" in result
    assert "Why it matters" in result


def test_combine_fields_skips_empty() -> None:
    result = FinBertScorer.combine_fields("Title", "", "Matters")
    assert "Title" in result
    assert "Matters" in result
    words = result.split()
    assert len(words) == 2


def test_combine_fields_all_empty() -> None:
    result = FinBertScorer.combine_fields("", "", "")
    assert result == ""


def test_combine_fields_truncates_long_field() -> None:
    long_title = " ".join(f"word{i}" for i in range(200))
    result = FinBertScorer.combine_fields(long_title, "short", "")
    words = result.split()
    assert words[0] == "word0"
    assert len([w for w in words if w.startswith("word")]) <= 64


def test_combine_fields_total_512_cap() -> None:
    f1 = " ".join(f"a{i}" for i in range(60))
    f2 = " ".join(f"b{i}" for i in range(220))
    f3 = " ".join(f"c{i}" for i in range(220))
    result = FinBertScorer.combine_fields(f1, f2, f3)
    assert len(result.split()) <= 512


def test_build_public_news_sentiment_text_prefers_raw_fields() -> None:
    text = build_public_news_sentiment_text(
        {
            "title": "번역 제목",
            "rawTitle": "Raw English Title",
            "summaryKo": "번역 요약",
            "rawSummary": "Raw English Summary",
            "interpretation": "번역 해설",
            "rawInterpretation": "Raw English Interpretation",
        }
    )

    assert "Raw English Title" in text
    assert "Raw English Summary" in text
    assert "Raw English Interpretation" in text
    assert "번역 제목" not in text


def test_build_public_news_sentiment_text_falls_back_to_display_fields() -> None:
    text = build_public_news_sentiment_text(
        {
            "title": "한글 제목",
            "summaryKo": "한글 요약",
            "interpretation": "한글 해설",
        }
    )

    assert "한글 제목" in text
    assert "한글 요약" in text
    assert "한글 해설" in text


def test_build_public_signal_sentiment_text_prefers_raw_content() -> None:
    text = build_public_signal_sentiment_text(
        {
            "rawContent": "Raw English signal content",
            "content": "번역된 시그널 내용",
            "impact": "번역된 영향",
        }
    )

    assert "Raw English signal content" in text
    assert "번역된 영향" in text
    assert "번역된 시그널 내용" not in text


# ── 의존성 미설치 시 동작 테스트 ──


def test_enrich_news_packet_skipped_when_deps_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import morning_brief.data.finbert_sentiment as mod

    monkeypatch.setattr(mod, "_TORCH_AVAILABLE", False)
    monkeypatch.setattr(mod, "_DEPS_WARNING_EMITTED", False)
    settings = load_settings()
    items = [{"title": "Test", "summary": "s", "why_it_matters": "w"}]
    status = enrich_news_packet(items, settings)
    assert status == "skipped"


def test_enrich_news_packet_warning_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import morning_brief.data.finbert_sentiment as mod

    monkeypatch.setattr(mod, "_TORCH_AVAILABLE", False)
    monkeypatch.setattr(mod, "_DEPS_WARNING_EMITTED", False)
    settings = load_settings()
    items = [{"title": "Test"}]

    with caplog.at_level(logging.WARNING):
        enrich_news_packet(items, settings)
        enrich_news_packet(items, settings)

    warning_count = sum(1 for r in caplog.records if "미설치" in r.message)
    assert warning_count == 1


# ── feature flag 테스트 ──


def test_enrich_news_packet_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINBERT_ENABLED", "false")
    settings = load_settings()
    items = [{"title": "Test"}]
    status = enrich_news_packet(items, settings)
    assert status == "skipped"


def test_enrich_x_signals_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINBERT_ENABLED", "false")
    settings = load_settings()
    from morning_brief.data.sources.grok_x_keyword import XSignal

    sig = XSignal(headline="h", summary="s", why_it_matters="w")
    enrich_x_signals([sig], settings)
    assert sig.sentiment_score is None


# ── 빈 입력 테스트 ──


def test_score_texts_empty_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    import morning_brief.data.finbert_sentiment as mod

    monkeypatch.setattr(mod, "_TORCH_AVAILABLE", True)
    settings = load_settings()
    scorer = FinBertScorer(settings)
    scorer._available = True

    with patch.object(scorer, "_ensure_loaded", return_value=True):
        results = scorer.score_texts(["", None, "   "])

    assert len(results) == 3
    for r in results:
        assert r.score is None
        assert r.confidence is None
        assert r.label is None


# ── 120건 초과 선정 로직 테스트 ──


def test_select_items_within_limit() -> None:
    items = [{"title": f"n{i}"} for i in range(50)]
    selected, skipped = _select_items_for_scoring(items)
    assert len(selected) == 50
    assert len(skipped) == 0


def test_select_items_exceeds_limit() -> None:
    items = []
    for i in range(150):
        cat = ["macro", "bigtech", "bitcoin", "us-stocks"][i % 4]
        tier = "tier1" if i < 30 else "standard"
        items.append({"title": f"n{i}", "topic": cat, "source_tier": tier})

    selected, skipped = _select_items_for_scoring(items, max_items=120)
    assert len(selected) <= 120
    assert len(skipped) == 150 - len(selected)
    assert set(selected) & set(skipped) == set()

    selected_cats = {items[i].get("topic") for i in selected}
    assert len(selected_cats) == 4


def test_select_items_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    items = [{"title": f"n{i}", "topic": "macro"} for i in range(130)]
    with caplog.at_level(logging.WARNING):
        _select_items_for_scoring(items)
    assert any("초과" in r.message for r in caplog.records)


# ── 실제 추론 테스트 (ML 의존성 필요) ──


@pytest.mark.skipif(not _check_deps(), reason="ML deps not installed")
def test_score_texts_real_inference() -> None:
    settings = load_settings()
    scorer = FinBertScorer(settings)
    results = scorer.score_texts(
        [
            "Stock market crashes amid global recession fears",
            "Revenue beats expectations as company reports record growth",
            "Federal Reserve holds interest rates steady",
        ]
    )

    assert len(results) == 3
    for r in results:
        assert r.score is not None
        assert -1.0 <= r.score <= 1.0
        assert r.confidence is not None
        assert 0.0 <= r.confidence <= 1.0
        assert r.label in ("bullish", "bearish", "neutral")

    assert results[0].score < 0  # crash → negative
    assert results[1].score > 0  # beats expectations → positive
