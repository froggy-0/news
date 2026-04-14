"""R2 저장 레이어별 writer.

- NewsDataWriter: low-level R2 put 래퍼
- CuratedWriter: curated/{symbol}/{date}.json 저장
- AnalyticsWriter: analytics/{symbol}/{date}.json 저장
- RawCaptureWriter: raw/{domain}/{provider}/{dataset}/{date}/{run_id}.json 저장
"""

from __future__ import annotations

import json
import logging
from typing import Any

from morning_brief.data.storage.news_data_paths import (
    build_publish_paths,
    build_raw_capture_key,
)
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


class NewsDataWriter:
    """Low-level R2 write 래퍼. boto3 S3 client를 감싼다."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            CacheControl="public, max-age=300",
        )

    def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


class CuratedWriter:
    """curated 레이어 전용 writer."""

    def __init__(self, base_writer: NewsDataWriter) -> None:
        self._writer = base_writer

    def write_curated(
        self,
        *,
        symbol: str,
        run_date: str,
        payload: dict[str, Any],
    ) -> str:
        paths = build_publish_paths(symbol=symbol, run_date=run_date)
        self._writer.put_json(paths.curated_key, payload)
        log_structured(
            logger,
            event="storage.curated_written",
            message="curated JSON을 저장했습니다.",
            key=paths.curated_key,
            symbol=symbol,
            date=run_date,
        )
        return paths.curated_key


class AnalyticsWriter:
    """analytics 레이어 전용 writer."""

    def __init__(self, base_writer: NewsDataWriter) -> None:
        self._writer = base_writer

    def write_analytics(
        self,
        *,
        symbol: str,
        run_date: str,
        payload: dict[str, Any],
    ) -> str:
        paths = build_publish_paths(symbol=symbol, run_date=run_date)
        self._writer.put_json(paths.analytics_key, payload)
        log_structured(
            logger,
            event="storage.analytics_written",
            message="analytics JSON을 저장했습니다.",
            key=paths.analytics_key,
            symbol=symbol,
            date=run_date,
        )
        return paths.analytics_key


class RawCaptureWriter:
    """raw 레이어 전용 writer (append-only)."""

    def __init__(self, base_writer: NewsDataWriter) -> None:
        self._writer = base_writer

    def write_capture(
        self,
        *,
        domain: str,
        provider: str,
        dataset: str,
        run_date: str,
        run_id: str,
        payload: dict[str, Any] | bytes,
    ) -> str:
        key = build_raw_capture_key(
            domain=domain,
            provider=provider,
            dataset=dataset,
            run_date=run_date,
            run_id=run_id,
        )
        if isinstance(payload, bytes):
            self._writer.put_bytes(key, payload, "application/octet-stream")
        else:
            self._writer.put_json(key, payload)
        log_structured(
            logger,
            event="storage.raw_captured",
            message="raw capture를 저장했습니다.",
            key=key,
            domain=domain,
            provider=provider,
        )
        return key


__all__ = [
    "AnalyticsWriter",
    "CuratedWriter",
    "NewsDataWriter",
    "RawCaptureWriter",
]
