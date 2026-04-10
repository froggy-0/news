from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_finbert_brief_json.py"
    spec = importlib.util.spec_from_file_location("check_finbert_brief_json", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_news_section_items_prefers_public_json_fields() -> None:
    module = _load_script_module()
    payload = {
        "allNews": [
            {
                "title": "번역 제목",
                "rawTitle": "Raw English Title",
                "summaryKo": "번역 요약",
                "rawSummary": "Raw English Summary",
                "interpretation": "번역 해설",
                "rawInterpretation": "Raw English Interpretation",
                "sentimentScore": 0.2,
            }
        ]
    }

    items = module._load_section_items(payload, "allNews", limit=0, kind="news")

    assert items[0]["rawTitle"] == "Raw English Title"
    assert items[0]["summaryKo"] == "번역 요약"
    assert items[0]["rawSummary"] == "Raw English Summary"
    assert items[0]["interpretation"] == "번역 해설"
    assert items[0]["rawInterpretation"] == "Raw English Interpretation"
    assert items[0]["existing_sentiment_score"] == 0.2


def test_load_signal_section_items_reads_raw_and_display_fields() -> None:
    module = _load_script_module()
    payload = {
        "xSignals": [
            {
                "content": "번역된 내용",
                "impact": "번역된 영향",
                "rawContent": "Raw English content",
                "sentiment_score": -0.1,
            }
        ]
    }

    items = module._load_section_items(payload, "xSignals", limit=0, kind="signal")

    assert items[0]["content"] == "번역된 내용"
    assert items[0]["impact"] == "번역된 영향"
    assert items[0]["rawContent"] == "Raw English content"
    assert items[0]["existing_sentiment_score"] == -0.1


def test_main_prints_section_counts(monkeypatch, tmp_path, capsys) -> None:
    module = _load_script_module()
    payload_path = tmp_path / "brief.json"
    payload_path.write_text(
        json.dumps(
            {
                "meta": {
                    "sentimentStatus": "ok",
                    "newsSentiment": {"count": 1},
                    "signalSentiment": {"count": 1},
                },
                "allNews": [
                    {
                        "title": "번역 제목",
                        "rawTitle": "Raw English Title",
                        "summaryKo": "번역 요약",
                        "rawSummary": "Raw English Summary",
                        "interpretation": "번역 해설",
                        "rawInterpretation": "Raw English Interpretation",
                    }
                ],
                "xSignals": [
                    {
                        "content": "번역된 내용",
                        "impact": "번역된 영향",
                        "rawContent": "Raw English content",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: type("Args", (), {"json_path": str(payload_path), "limit": 0})(),
    )
    monkeypatch.setattr(
        "morning_brief.config.load_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_news_packet",
        lambda items, settings, observer=None, *, text_builder=None: "ok",
    )
    monkeypatch.setattr(
        "morning_brief.data.finbert_sentiment.enrich_public_signal_items",
        lambda items, settings, observer=None: "ok",
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "news_section: allNews" in output
    assert "signal_section: xSignals" in output
    assert "fallback_items:" in output
