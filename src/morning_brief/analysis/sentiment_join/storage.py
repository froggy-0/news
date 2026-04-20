from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MASTER_FILE_RE = re.compile(r"^master_(\d{8})\.parquet$")


def save_parquet(
    df: pd.DataFrame,
    output_dir: Path,
    run_date: str,
    *,
    ffill_days: int = 0,
    stats_metadata: bytes | None = None,
    btc_source: str = "unknown",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"master_{run_date}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[b"ffill_days"] = str(ffill_days).encode()
    metadata[b"btc_source"] = btc_source.encode()
    if stats_metadata is not None:
        metadata[b"sentiment_join_stats"] = stats_metadata
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, path, compression="snappy")
    return path


def write_backfill_manifest(
    output_dir: Path,
    manifest: dict[str, object],
    *,
    filename: str = "backfill_manifest.json",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return path


def cleanup_old_files(output_dir: Path, retain_days: int) -> None:
    if retain_days == 0 or not output_dir.exists():
        return

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=retain_days)
    for path in output_dir.glob("master_*.parquet"):
        match = MASTER_FILE_RE.match(path.name)
        if match is None:
            continue
        file_date = datetime.strptime(match.group(1), "%Y%m%d").date()
        if file_date < cutoff:
            path.unlink(missing_ok=True)


def upload_to_r2(
    local_path: Path,
    r2_key: str,
    *,
    r2_s3_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_public_bucket: str,
) -> None:
    if not r2_s3_endpoint:
        return

    import boto3

    try:
        client = boto3.client(
            "s3",
            endpoint_url=r2_s3_endpoint,
            aws_access_key_id=r2_access_key_id,
            aws_secret_access_key=r2_secret_access_key,
            region_name="auto",
        )
        body = local_path.read_bytes()
        client.put_object(
            Bucket=r2_public_bucket,
            Key=r2_key,
            Body=body,
            ContentType="application/octet-stream",
            CacheControl="public, max-age=3600",
        )
        log_structured(
            logger,
            event="r2.uploaded",
            message="Parquet 파일을 R2에 업로드했습니다.",
            key=r2_key,
            size_bytes=len(body),
        )
    except Exception as exc:
        log_structured(
            logger,
            event="r2.upload_failed",
            message="R2 업로드에 실패했습니다.",
            level=logging.WARNING,
            reason=str(exc),
        )


__all__ = ["cleanup_old_files", "save_parquet", "upload_to_r2", "write_backfill_manifest"]
