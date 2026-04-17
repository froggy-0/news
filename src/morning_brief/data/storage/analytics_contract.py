"""Analytics 최소 데이터 계약.

curated full payload에서 통계 분석 전용 필드만 추출한다.
전시 전용 필드(median, bullishRatio, bearishRatio, signalSentiment 등)는 제외.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

SCHEMA_VERSION = "v1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"v1"})

_ANALYTICS_ALLOWED_KEYS = frozenset(
    {
        "schemaVersion",
        "producer",
        "generatedAt",
        "date",
        "symbol",
        "sentimentStatus",
        "newsSentiment",
        "_backfill",
    }
)

_SENTIMENT_ALLOWED_KEYS = frozenset({"mean", "std", "count"})


class AnalyticsSentimentPayload(TypedDict):
    schemaVersion: str
    producer: str
    generatedAt: str
    date: str
    symbol: str
    sentimentStatus: str
    newsSentiment: dict[str, float | int | None]
    _backfill: bool


class AnalyticsValidationResult(TypedDict):
    valid: bool
    reason: str | None


def build_analytics_sentiment_payload(
    *,
    symbol: str,
    run_date: str,
    full_payload: dict[str, Any],
    is_backfill: bool = False,
) -> AnalyticsSentimentPayload:
    """curated full payload → analytics 최소 JSON을 파생한다.

    is_backfill: 라이브 파이프라인은 False(기본값), 백필 경로는 True.
    _backfill 필드를 호출자가 제어할 수 있어 validate_analytics_sentiment_payload의
    키 존재 여부 검증을 통과하면서도 실시간/백필을 구분합니다.
    """
    meta = full_payload.get("meta", {})
    raw_sentiment = meta.get("newsSentiment", {})
    if not isinstance(raw_sentiment, dict):
        raw_sentiment = {}

    return AnalyticsSentimentPayload(
        schemaVersion=SCHEMA_VERSION,
        producer="public_site.publish_public_brief",
        generatedAt=datetime.now(timezone.utc).isoformat(),
        date=run_date,
        symbol=symbol,
        sentimentStatus=str(meta.get("sentimentStatus", "skipped")),
        newsSentiment={
            "mean": raw_sentiment.get("mean"),
            "std": raw_sentiment.get("std"),
            "count": raw_sentiment.get("count", 0),
        },
        _backfill=is_backfill,
    )


def validate_analytics_sentiment_payload(
    payload: dict[str, Any],
) -> AnalyticsValidationResult:
    """analytics payload가 계약을 만족하는지 검증한다."""
    # _backfill 키 존재 필수 (값이 False여도 키가 있으면 통과 — 실시간 파이프라인 지원)
    if "_backfill" not in payload:
        return AnalyticsValidationResult(valid=False, reason="missing_backfill_marker")

    # schemaVersion 지원 여부
    version = payload.get("schemaVersion")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return AnalyticsValidationResult(
            valid=False, reason=f"unsupported_schema_version:{version}"
        )

    # 필수 필드 존재
    for key in ("date", "symbol", "sentimentStatus", "newsSentiment"):
        if key not in payload:
            return AnalyticsValidationResult(valid=False, reason=f"missing_field:{key}")

    # newsSentiment 구조 검증
    sentiment = payload.get("newsSentiment")
    if not isinstance(sentiment, dict):
        return AnalyticsValidationResult(valid=False, reason="invalid_sentiment_structure")
    for required_key in ("mean", "std", "count"):
        if required_key not in sentiment:
            return AnalyticsValidationResult(
                valid=False, reason=f"missing_sentiment_field:{required_key}"
            )

    # 허용 필드 외 키 누출 검사
    extra_keys = set(payload.keys()) - _ANALYTICS_ALLOWED_KEYS
    if extra_keys:
        return AnalyticsValidationResult(
            valid=False, reason=f"extra_fields:{','.join(sorted(extra_keys))}"
        )

    return AnalyticsValidationResult(valid=True, reason=None)


__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "AnalyticsSentimentPayload",
    "AnalyticsValidationResult",
    "build_analytics_sentiment_payload",
    "validate_analytics_sentiment_payload",
]
