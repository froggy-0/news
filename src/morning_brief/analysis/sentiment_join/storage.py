from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MASTER_FILE_RE = re.compile(r"^master_(\d{8})\.parquet$")


def save_parquet(
    df: pd.DataFrame,
    output_dir: Path,
    run_date: str,
    *,
    ffill_days: int = 0,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"master_{run_date}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[b"ffill_days"] = str(ffill_days).encode()
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, path, compression="snappy")
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
    return


__all__ = ["cleanup_old_files", "save_parquet", "upload_to_r2"]
