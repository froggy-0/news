"""파이프라인 수집 경계 raw capture hook.

build_market_packet()과 build_news_packet() 결과를 R2 raw 레이어에
append-only로 저장한다. R2 미설정 또는 실패 시 경고만 남기고 계속 진행.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from morning_brief.config import Settings
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


def try_raw_capture(
    *,
    settings: Settings,
    run_date: str,
    market_packet: dict[str, Any],
    news_packet: list[dict[str, Any]],
    public_context: dict[str, Any],
) -> None:
    """수집 경계 payload를 raw 레이어에 저장한다. 실패해도 파이프라인을 중단하지 않는다."""
    if not (settings.r2_s3_endpoint.strip() and settings.r2_public_bucket.strip()):
        return

    try:
        from morning_brief.data.storage.news_data_writer import (
            NewsDataWriter,
            RawCaptureWriter,
        )

        base_writer = NewsDataWriter(
            bucket=settings.r2_public_bucket,
            endpoint=settings.r2_s3_endpoint,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
        )
        raw = RawCaptureWriter(base_writer)
        run_id = uuid.uuid4().hex[:12]

        raw.write_capture(
            domain="market",
            provider="pipeline",
            dataset="market_packet",
            run_date=run_date,
            run_id=run_id,
            payload=market_packet,
        )
        raw.write_capture(
            domain="news",
            provider="pipeline",
            dataset="news_packet",
            run_date=run_date,
            run_id=run_id,
            payload={"items": news_packet},
        )
        raw.write_capture(
            domain="news",
            provider="pipeline",
            dataset="public_context",
            run_date=run_date,
            run_id=run_id,
            payload=public_context,
        )
        log_structured(
            logger,
            event="raw_capture.complete",
            message="수집 경계 raw capture를 완료했습니다.",
            run_date=run_date,
            run_id=run_id,
        )
    except Exception as exc:
        log_structured(
            logger,
            event="raw_capture.failed",
            message="raw capture 저장에 실패했지만 파이프라인은 계속 진행합니다.",
            level=logging.WARNING,
            reason=str(exc),
        )


__all__ = ["try_raw_capture"]
