"""R2 업로더: 최소 브리프 JSON 생성 및 병렬 업로드.

fetch_r2_sentiment()가 읽는 5개 필드만 포함한 경량 JSON을 briefs/{date}.json에 업로드.
파이프라인 원본 파일(_backfill 없음)은 --force에서도 보호.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from botocore.exceptions import ClientError

from backfill.scorer import DailyAggregate

logger = logging.getLogger(__name__)


@dataclass
class UploadResults:
    """upload_all() 반환 타입."""

    uploaded: int = 0
    skipped_exists: int = 0
    skipped_protected: int = 0
    failed: int = 0
    aggregates_ok: int = 0
    aggregates_degraded: int = 0
    aggregates_skipped: int = 0


def build_minimal_brief_json(date: str, aggregate: DailyAggregate) -> dict:
    """fetch_r2_sentiment()가 읽는 최소 스키마 JSON 생성."""
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "meta": {
            "date": date,
            "generatedAt": f"{date}T08:00:00+09:00",
            "sentimentStatus": aggregate.status,
            "signalSentimentStatus": "skipped",
            "newsSentiment": {
                "mean": aggregate.mean,
                "std": aggregate.std,
                "count": aggregate.count,
            },
            "signalSentiment": None,
            "_backfill": True,
            "_backfillSource": "coindesk+alpaca+finbert",
            "_backfillGeneratedAt": now_utc,
        }
    }


def _is_pipeline_file(existing_json: dict) -> bool:
    """_backfill 필드 없는 파일 = 파이프라인 원본 → 덮어쓰기 금지."""
    return "_backfill" not in existing_json.get("meta", {})


def create_s3_client():
    """boto3 S3 호환 R2 클라이언트 생성."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def upload_brief(
    date: str,
    aggregate: DailyAggregate,
    s3_client,
    bucket: str,
    *,
    force: bool = False,
) -> Literal["uploaded", "skipped_exists", "skipped_protected", "failed"]:
    """단일 날짜 JSON을 R2에 업로드."""
    key = f"briefs/{date}.json"

    try:
        # 파일 존재 여부 확인
        file_exists = False
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            file_exists = True
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("404", "NoSuchKey"):
                raise

        if file_exists:
            if not force:
                logger.info(
                    "업로드 건너뜀 (이미 존재)",
                    extra={
                        "event": "upload.skip",
                        "attributes": {"date": date, "reason": "exists"},
                    },
                )
                return "skipped_exists"

            # --force: _backfill 필드 확인
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            existing = json.loads(resp["Body"].read().decode("utf-8"))
            if _is_pipeline_file(existing):
                logger.warning(
                    "파이프라인 원본 파일 보호 — 덮어쓰기 거부",
                    extra={
                        "event": "upload.skip",
                        "attributes": {"date": date, "reason": "pipeline_file_protected"},
                    },
                )
                return "skipped_protected"

        # 업로드
        payload = build_minimal_brief_json(date, aggregate)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(
            "업로드 성공",
            extra={
                "event": "upload.ok",
                "attributes": {
                    "date": date,
                    "status": aggregate.status,
                    "count": aggregate.count,
                },
            },
        )
        return "uploaded"

    except Exception as exc:
        logger.warning(
            "업로드 실패, 다음 날짜로 계속",
            extra={
                "event": "upload.fail",
                "attributes": {"date": date, "reason": str(exc)},
            },
        )
        return "failed"


def upload_all(
    aggregates: list[DailyAggregate],
    s3_client,
    bucket: str,
    *,
    force: bool = False,
    max_concurrency: int = 5,
) -> UploadResults:
    """ThreadPoolExecutor로 날짜별 병렬 업로드. UploadResults 반환."""
    results = UploadResults(
        aggregates_ok=sum(1 for a in aggregates if a.status == "ok"),
        aggregates_degraded=sum(1 for a in aggregates if a.status == "degraded"),
        aggregates_skipped=sum(1 for a in aggregates if a.status == "skipped"),
    )

    def _upload_one(
        agg: DailyAggregate,
    ) -> Literal["uploaded", "skipped_exists", "skipped_protected", "failed"]:
        return upload_brief(agg.date, agg, s3_client, bucket, force=force)

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_upload_one, agg): agg for agg in aggregates}
        for future in as_completed(futures):
            outcome = future.result()
            if outcome == "uploaded":
                results.uploaded += 1
            elif outcome == "skipped_exists":
                results.skipped_exists += 1
            elif outcome == "skipped_protected":
                results.skipped_protected += 1
            else:
                results.failed += 1

    return results
