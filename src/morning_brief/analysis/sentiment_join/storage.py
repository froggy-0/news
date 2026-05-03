from __future__ import annotations

import json
import logging
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
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


def download_from_r2(
    r2_key: str,
    *,
    r2_s3_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_public_bucket: str,
) -> bytes:
    """R2 키를 bytes로 다운로드한다. 키가 없으면 FileNotFoundError."""
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=r2_s3_endpoint,
        aws_access_key_id=r2_access_key_id,
        aws_secret_access_key=r2_secret_access_key,
        region_name="auto",
    )
    try:
        return client.get_object(Bucket=r2_public_bucket, Key=r2_key)["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            raise FileNotFoundError(r2_key) from exc
        raise


def list_r2_keys(
    prefix: str,
    *,
    r2_s3_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_public_bucket: str,
) -> list[str]:
    """prefix 아래 R2 키 목록을 오름차순으로 반환한다."""
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=r2_s3_endpoint,
        aws_access_key_id=r2_access_key_id,
        aws_secret_access_key=r2_secret_access_key,
        region_name="auto",
    )
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=r2_public_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


@contextmanager
def r2_tempfile(
    r2_key: str,
    suffix: str = "",
    *,
    r2_s3_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_public_bucket: str,
) -> Generator[Path, None, None]:
    """R2 키를 임시 파일로 내려받고 Path를 yield한다. 블록 종료 시 자동 삭제."""
    data = download_from_r2(
        r2_key,
        r2_s3_endpoint=r2_s3_endpoint,
        r2_access_key_id=r2_access_key_id,
        r2_secret_access_key=r2_secret_access_key,
        r2_public_bucket=r2_public_bucket,
    )
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        yield tmp_path
    finally:
        tmp_path.unlink(missing_ok=True)


def append_drift_record(
    output_dir: Path,
    run_date: str,
    record: dict,
    *,
    filename: str = "vol_regime_v2_drift.jsonl",
) -> Path:
    """드리프트 추적 레코드를 output_dir/{filename}에 한 줄씩 append한다.

    run_date와 generated_at_utc가 자동으로 추가된다. 파일이 없으면 새로 생성한다.

    Parameters
    ----------
    output_dir : Path
        저장 디렉터리.
    run_date : str
        파이프라인 실행일 (YYYY-MM-DD 또는 YYYYMMDD).
    record : dict
        저장할 지표 딕셔너리.
    filename : str
        JSONL 파일명 (기본 vol_regime_v2_drift.jsonl).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    entry = {
        "run_date": run_date,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return path


def read_drift_records(
    output_dir: Path,
    *,
    filename: str = "vol_regime_v2_drift.jsonl",
) -> list[dict]:
    """드리프트 JSONL을 읽어 레코드 리스트로 반환한다. 파일이 없으면 빈 리스트."""
    path = output_dir / filename
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


__all__ = [
    "append_drift_record",
    "cleanup_old_files",
    "download_from_r2",
    "list_r2_keys",
    "r2_tempfile",
    "read_drift_records",
    "save_parquet",
    "upload_to_r2",
    "write_backfill_manifest",
]
