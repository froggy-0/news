"""R2 업로더: 최소 브리프 JSON 생성 및 병렬 업로드.

fetch_r2_sentiment()가 읽는 5개 필드만 포함한 경량 JSON을 analytics/btc/{date}.json에 업로드.
파이프라인 원본 파일(_backfill 없음)은 --force에서도 보호.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from botocore.exceptions import ClientError

from backfill.scorer import DailyAggregate
from morning_brief.data.storage.news_data_paths import build_publish_paths
from morning_brief.r2_env import load_public_r2_env

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
    """fetch_r2_sentiment()가 읽는 최소 스키마 JSON 생성.

    analytics_contract.validate_analytics_sentiment_payload()와 호환되는
    flat format으로 생성합니다. _ANALYTICS_ALLOWED_KEYS 범위 내 키만 포함합니다.
    textSchemaVersion은 본체에 포함해 r2_sentiment.py가 text_schema_version을
    마스터 DataFrame에 전달할 수 있도록 합니다.
    """
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schemaVersion": "v1",
        "producer": "backfill.finbert",
        "generatedAt": now_utc,
        "date": date,
        "symbol": "btc",
        "sentimentStatus": aggregate.status,
        "newsSentiment": {
            "mean": aggregate.mean,
            "std": aggregate.std,
            "count": aggregate.count,
        },
        "_backfill": True,
        "textSchemaVersion": aggregate.text_schema_version,  # r2_sentiment.py 투명 공개
    }


def build_backfill_sidecar_json(date: str, aggregate: DailyAggregate) -> dict:
    """진단용 사이드카 JSON 생성 (analytics 계약 미적용).

    본체(_ANALYTICS_ALLOWED_KEYS)에 포함되지 않는 백필 진단 필드를
    {key}.backfill-meta.json에 별도 저장합니다.
    """
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "_backfillSource": "coindesk+alpaca+finbert",
        "_backfillGeneratedAt": now_utc,
        "textSchemaVersion": aggregate.text_schema_version,
        "date": date,
    }


def _is_pipeline_file(existing_json: dict) -> bool:
    """파이프라인 원본 파일 판별 → True이면 덮어쓰기 금지.

    판별 순서:
    1. flat format (현행): producer 접두사로 판별.
       - "backfill."로 시작하면 백필 파일 → False
       - 그 외("public_site." 등)는 파이프라인 원본 → True
    2. legacy meta-wrapped 백필: meta._backfillSource 존재 여부로 폴백 → False
    3. producer 없고 _backfillSource도 없으면 파이프라인 원본으로 간주 → True
    """
    # flat format (현행 및 신규 백필): producer 접두사로 판별
    producer = str(existing_json.get("producer", ""))
    if producer:
        return not producer.startswith("backfill.")
    # legacy meta-wrapped 백필: _backfillSource 존재 여부로 폴백
    if "_backfillSource" in existing_json.get("meta", {}):
        return False
    return True


def create_s3_client():
    """boto3 S3 호환 R2 클라이언트 생성."""
    import boto3

    r2_env = load_public_r2_env()
    return boto3.client(
        "s3",
        endpoint_url=r2_env.s3_endpoint,
        aws_access_key_id=r2_env.access_key_id,
        aws_secret_access_key=r2_env.secret_access_key,
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
    key = build_publish_paths(symbol="btc", run_date=date).analytics_key

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

        # 본체 업로드
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

        # 사이드카 업로드 (진단용, 실패해도 반환값에 영향 없음)
        try:
            sidecar_key = f"{key}.backfill-meta.json"
            sidecar = build_backfill_sidecar_json(date, aggregate)
            s3_client.put_object(
                Bucket=bucket,
                Key=sidecar_key,
                Body=json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as sidecar_exc:
            logger.warning(
                "사이드카 업로드 실패 (무시)",
                extra={
                    "event": "upload.sidecar_fail",
                    "attributes": {"date": date, "reason": str(sidecar_exc)},
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
    progress_callback: Callable[[dict[str, object]], None] | None = None,
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
        total = len(futures)
        completed = 0
        for future in as_completed(futures):
            outcome = future.result()
            completed += 1
            if outcome == "uploaded":
                results.uploaded += 1
            elif outcome == "skipped_exists":
                results.skipped_exists += 1
            elif outcome == "skipped_protected":
                results.skipped_protected += 1
            else:
                results.failed += 1
            if progress_callback:
                aggregate = futures[future]
                progress_callback(
                    {
                        "status": "running" if completed < total else "completed",
                        "date": aggregate.date,
                        "completed": completed,
                        "total": total,
                        "outcome": outcome,
                        "uploaded": results.uploaded,
                        "skipped_exists": results.skipped_exists,
                        "skipped_protected": results.skipped_protected,
                        "failed": results.failed,
                    }
                )

    return results
