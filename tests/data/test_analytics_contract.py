from __future__ import annotations

from morning_brief.data.storage.analytics_contract import (
    SUPPORTED_SCHEMA_VERSIONS,
    build_analytics_sentiment_payload,
    validate_analytics_sentiment_payload,
)


def _full_payload(
    *,
    sentiment_status: str = "ok",
    mean: float | None = 0.25,
    std: float | None = 0.1,
    count: int = 5,
) -> dict:
    return {
        "meta": {
            "date": "2026-04-14",
            "generatedAt": "2026-04-14T08:30:00+09:00",
            "sentimentStatus": sentiment_status,
            "signalSentimentStatus": "ok",
            "newsSentiment": {
                "mean": mean,
                "median": 0.2,
                "std": std,
                "bullishRatio": 0.6,
                "bearishRatio": 0.2,
                "count": count,
            },
            "signalSentiment": {"mean": 0.05, "std": 0.02, "count": 3},
        },
        "marketSnapshot": {"items": []},
        "aiJudgment": {"headline": "test", "body": "test"},
        "allNews": [],
    }


class TestBuildAnalyticsPayload:
    def test_only_allowed_keys(self) -> None:
        """Property 2: analytics payload는 허용 필드 외 키를 포함하지 않아야 한다."""
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        allowed = {
            "schemaVersion",
            "producer",
            "generatedAt",
            "date",
            "symbol",
            "sentimentStatus",
            "newsSentiment",
            "_backfill",
        }
        assert set(payload.keys()) == allowed

    def test_excludes_display_only_sentiment_fields(self) -> None:
        """median, bullishRatio, bearishRatio는 제외한다."""
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        sentiment = payload["newsSentiment"]
        assert set(sentiment.keys()) == {"mean", "std", "count"}

    def test_excludes_signal_sentiment(self) -> None:
        """signalSentiment, signalSentimentStatus는 포함하지 않는다."""
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        assert "signalSentiment" not in payload
        assert "signalSentimentStatus" not in payload

    def test_backfill_false_for_live_pipeline(self) -> None:
        """D-3: 라이브 파이프라인 기본값은 _backfill=False."""
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        assert payload["_backfill"] is False

    def test_backfill_true_when_is_backfill_set(self) -> None:
        """D-3: is_backfill=True 전달 시 _backfill=True."""
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
            is_backfill=True,
        )
        assert payload["_backfill"] is True

    def test_schema_version(self) -> None:
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        assert payload["schemaVersion"] == "v1"

    def test_producer_and_generated_at(self) -> None:
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(),
        )
        assert payload["producer"] == "public_site.publish_public_brief"
        assert payload["generatedAt"]  # non-empty

    def test_preserves_sentiment_values(self) -> None:
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(mean=0.35, std=0.2, count=8),
        )
        assert payload["newsSentiment"]["mean"] == 0.35
        assert payload["newsSentiment"]["std"] == 0.2
        assert payload["newsSentiment"]["count"] == 8

    def test_skipped_sentiment_status_propagated(self) -> None:
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload=_full_payload(sentiment_status="skipped"),
        )
        assert payload["sentimentStatus"] == "skipped"

    def test_missing_meta_produces_safe_payload(self) -> None:
        payload = build_analytics_sentiment_payload(
            symbol="btc",
            run_date="2026-04-14",
            full_payload={},
        )
        assert payload["sentimentStatus"] == "skipped"
        assert payload["newsSentiment"]["count"] == 0


class TestValidateAnalyticsPayload:
    def _valid_payload(self) -> dict:
        return {
            "schemaVersion": "v1",
            "producer": "test",
            "generatedAt": "2026-04-14T00:00:00Z",
            "date": "2026-04-14",
            "symbol": "btc",
            "sentimentStatus": "ok",
            "newsSentiment": {"mean": 0.25, "std": 0.1, "count": 5},
            "_backfill": True,
        }

    def test_valid_payload_passes(self) -> None:
        result = validate_analytics_sentiment_payload(self._valid_payload())
        assert result["valid"] is True
        assert result["reason"] is None

    def test_backfill_false_passes_validation(self) -> None:
        """D-3: _backfill=False도 키가 존재하면 valid (라이브 파이프라인 지원)."""
        payload = self._valid_payload()
        payload["_backfill"] = False
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is True

    def test_absent_backfill_rejected(self) -> None:
        payload = self._valid_payload()
        del payload["_backfill"]
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is False
        assert result["reason"] == "missing_backfill_marker"

    def test_unsupported_schema_version_rejected(self) -> None:
        payload = self._valid_payload()
        payload["schemaVersion"] = "v99"
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is False
        assert "unsupported_schema_version" in (result["reason"] or "")

    def test_missing_required_field_rejected(self) -> None:
        payload = self._valid_payload()
        del payload["sentimentStatus"]
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is False
        assert "missing_field" in (result["reason"] or "")

    def test_extra_field_rejected(self) -> None:
        payload = self._valid_payload()
        payload["aiJudgment"] = {"headline": "leak"}
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is False
        assert "extra_fields" in (result["reason"] or "")

    def test_missing_sentiment_subfield_rejected(self) -> None:
        payload = self._valid_payload()
        del payload["newsSentiment"]["count"]
        result = validate_analytics_sentiment_payload(payload)
        assert result["valid"] is False
        assert "missing_sentiment_field" in (result["reason"] or "")

    def test_supported_versions_include_v1(self) -> None:
        assert "v1" in SUPPORTED_SCHEMA_VERSIONS
