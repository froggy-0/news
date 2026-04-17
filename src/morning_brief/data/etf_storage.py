from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from morning_brief.models import BitcoinEtfIssuerSnapshot, SilverNormalizedFieldRecord

DEFAULT_ETF_BRONZE_BUCKET = "btc-etf-bronze"
DEFAULT_ETF_SILVER_TABLE = "btc_etf_silver"
DEFAULT_ETF_GOLD_TABLE = "btc_etf_gold"
DEFAULT_ETF_REFERENCE_TABLE = "btc_etf_reference"
DEFAULT_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class EtfStorageConfig:
    supabase_url: str
    service_role_key: str
    bronze_bucket: str = DEFAULT_ETF_BRONZE_BUCKET
    silver_table: str = DEFAULT_ETF_SILVER_TABLE
    gold_table: str = DEFAULT_ETF_GOLD_TABLE
    reference_table: str = DEFAULT_ETF_REFERENCE_TABLE
    schema_version: str = DEFAULT_SCHEMA_VERSION


def _infer_value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def normalize_snapshot_to_silver_records(
    snapshot: BitcoinEtfIssuerSnapshot,
    *,
    run_id: str,
    source_format: str,
    parse_method: str,
    source_file_url: str | None = None,
    raw_label_map: dict[str, str] | None = None,
    raw_text_map: dict[str, str] | None = None,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> list[SilverNormalizedFieldRecord]:
    collected_at = snapshot.collected_at or datetime.now(timezone.utc)
    raw_label_map = raw_label_map or {}
    raw_text_map = raw_text_map or {}
    field_payload: dict[str, Any] = {
        "aum_usd": snapshot.aum_usd,
        "shares_outstanding": snapshot.shares_outstanding,
        "total_btc": snapshot.total_btc,
        "bitcoin_per_share": snapshot.bitcoin_per_share,
        "daily_volume": snapshot.daily_volume,
        **snapshot.extra_fields,
    }
    records: list[SilverNormalizedFieldRecord] = []
    for field_name, field_value in field_payload.items():
        records.append(
            SilverNormalizedFieldRecord(
                run_id=run_id,
                ticker=snapshot.ticker,
                issuer=snapshot.issuer,
                field_name=field_name,
                field_value=field_value,
                value_type=_infer_value_type(field_value),
                unit=None,
                as_of_date=snapshot.as_of_date,
                collected_at=collected_at,
                source_url=snapshot.source_url,
                source_type=snapshot.source_type,
                source_format=source_format,
                parse_method=parse_method,
                source_file_url=source_file_url,
                quality_status=snapshot.quality_status,
                raw_label=raw_label_map.get(field_name),
                raw_text=raw_text_map.get(field_name),
                schema_version=schema_version,
            )
        )
    return records


def build_gold_record(
    snapshot: BitcoinEtfIssuerSnapshot,
    *,
    run_id: str,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> dict[str, Any]:
    collected_at = snapshot.collected_at or datetime.now(timezone.utc)
    payload = {
        "run_id": run_id,
        "schema_version": schema_version,
        "ticker": snapshot.ticker,
        "issuer": snapshot.issuer,
        "source_url": snapshot.source_url,
        "as_of_date": snapshot.as_of_date.isoformat(),
        "collected_at": collected_at.isoformat(),
        "source_type": snapshot.source_type,
        "quality_status": snapshot.quality_status,
        "aum_usd": snapshot.aum_usd,
        "shares_outstanding": snapshot.shares_outstanding,
        "total_btc": snapshot.total_btc,
        "bitcoin_per_share": snapshot.bitcoin_per_share,
        "daily_volume": snapshot.daily_volume,
    }
    payload.update(
        {
            field_name: field_value
            for field_name, field_value in snapshot.extra_fields.items()
            if field_value is not None
        }
    )
    return payload


class SupabaseEtfBronzeStorage:
    def __init__(self, *, client: Client, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name

    def upload_raw_payload(
        self,
        *,
        run_id: str,
        ticker: str,
        source_format: str,
        source_url: str,
        payload: bytes,
        http_status: int,
        source_checksum: str,
        schema_version: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        object_path = (
            f"{ticker}/{now.strftime('%Y%m%d')}/{run_id}-{source_checksum[:12]}.{source_format}"
        )
        metadata = {
            "cacheControl": "3600",
            "content-type": "application/octet-stream",
            "upsert": "true",
            "x-source-url": source_url,
            "x-http-status": str(http_status),
            "x-schema-version": schema_version,
        }
        self._client.storage.from_(self._bucket_name).upload(object_path, payload, metadata)
        return object_path


class SupabaseEtfRecordRepository:
    def __init__(self, *, client: Client, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def upsert_many(self, records: list[dict[str, Any]], *, on_conflict: str) -> None:
        if not records:
            return
        (
            self._client.table(self._table_name)
            .upsert(records, on_conflict=on_conflict, ignore_duplicates=False)
            .execute()
        )


@dataclass
class EtfStorageBundle:
    bronze: SupabaseEtfBronzeStorage
    silver: SupabaseEtfRecordRepository
    gold: SupabaseEtfRecordRepository
    reference: SupabaseEtfRecordRepository
    schema_version: str = DEFAULT_SCHEMA_VERSION

    def persist_snapshot(
        self,
        *,
        run_id: str,
        snapshot: BitcoinEtfIssuerSnapshot,
        source_format: str,
        parse_method: str,
        payload: bytes,
        source_checksum: str,
        http_status: int = 200,
        source_file_url: str | None = None,
        raw_label_map: dict[str, str] | None = None,
        raw_text_map: dict[str, str] | None = None,
        reference_only: bool = False,
    ) -> None:
        bronze_path = self.bronze.upload_raw_payload(
            run_id=run_id,
            ticker=snapshot.ticker,
            source_format=source_format,
            source_url=snapshot.source_url,
            payload=payload,
            http_status=http_status,
            source_checksum=source_checksum,
            schema_version=self.schema_version,
        )
        silver_records = normalize_snapshot_to_silver_records(
            snapshot,
            run_id=run_id,
            source_format=source_format,
            parse_method=parse_method,
            source_file_url=source_file_url,
            raw_label_map=raw_label_map,
            raw_text_map=raw_text_map,
            schema_version=self.schema_version,
        )
        silver_payload = []
        for record in silver_records:
            payload_dict = asdict(record)
            payload_dict["as_of_date"] = record.as_of_date.isoformat()
            payload_dict["collected_at"] = record.collected_at.isoformat()
            payload_dict["bronze_object_path"] = bronze_path
            silver_payload.append(payload_dict)
        self.silver.upsert_many(
            silver_payload,
            on_conflict="ticker,as_of_date,field_name,source_type",
        )
        gold_payload = build_gold_record(
            snapshot, run_id=run_id, schema_version=self.schema_version
        )
        gold_payload["bronze_object_path"] = bronze_path
        if reference_only or snapshot.source_type == "aggregator":
            self.reference.upsert_many([gold_payload], on_conflict="ticker,as_of_date,source_type")
            return
        self.gold.upsert_many([gold_payload], on_conflict="ticker,as_of_date")


def build_storage_bundle_from_env() -> EtfStorageBundle | None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        return None
    client = create_client(supabase_url, service_role_key)
    config = EtfStorageConfig(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        bronze_bucket=os.getenv("BTC_ETF_BRONZE_BUCKET", DEFAULT_ETF_BRONZE_BUCKET).strip()
        or DEFAULT_ETF_BRONZE_BUCKET,
        silver_table=os.getenv("BTC_ETF_SILVER_TABLE", DEFAULT_ETF_SILVER_TABLE).strip()
        or DEFAULT_ETF_SILVER_TABLE,
        gold_table=os.getenv("BTC_ETF_GOLD_TABLE", DEFAULT_ETF_GOLD_TABLE).strip()
        or DEFAULT_ETF_GOLD_TABLE,
        reference_table=os.getenv("BTC_ETF_REFERENCE_TABLE", DEFAULT_ETF_REFERENCE_TABLE).strip()
        or DEFAULT_ETF_REFERENCE_TABLE,
        schema_version=os.getenv("BTC_ETF_SCHEMA_VERSION", DEFAULT_SCHEMA_VERSION).strip()
        or DEFAULT_SCHEMA_VERSION,
    )
    return EtfStorageBundle(
        bronze=SupabaseEtfBronzeStorage(client=client, bucket_name=config.bronze_bucket),
        silver=SupabaseEtfRecordRepository(client=client, table_name=config.silver_table),
        gold=SupabaseEtfRecordRepository(client=client, table_name=config.gold_table),
        reference=SupabaseEtfRecordRepository(client=client, table_name=config.reference_table),
        schema_version=config.schema_version,
    )


def build_stats_metadata_payload(
    *,
    run_id: str,
    generated_at_utc: str,
    adf: dict[str, Any] | None,
    granger_results: list[dict[str, Any]],
    vif_diagnostics: list[dict[str, Any]] | None,
    pca_summary: dict[str, Any] | None,
    rows_before_outlier_filter: int | None = None,
    rows_after_outlier_filter: int | None = None,
    outlier_filtered_count: int | None = None,
    outlier_filtered_ratio: float | None = None,
    hybrid_signal_label: str | None = None,
    granger_eligible_rows: int | None = None,
    granger_executed: bool = False,
    exclusion_counts: dict[str, int] | None = None,
    granger_correction: dict[str, Any] | None = None,
) -> bytes:
    payload = {
        "run_id": run_id,
        "generated_at_utc": generated_at_utc,
        "adf": adf or {},
        "granger_results": granger_results,
        "granger_correction": granger_correction or {},
        "vif_diagnostics": vif_diagnostics or [],
        "pca_summary": pca_summary or {},
        "rows_before_outlier_filter": rows_before_outlier_filter,
        "rows_after_outlier_filter": rows_after_outlier_filter,
        "outlier_filtered_count": outlier_filtered_count,
        "outlier_filtered_ratio": outlier_filtered_ratio,
        "hybrid_signal_label": hybrid_signal_label,
        "granger_eligible_rows": granger_eligible_rows,
        "granger_executed": granger_executed,
        "exclusion_counts": exclusion_counts or {},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


__all__ = [
    "DEFAULT_SCHEMA_VERSION",
    "EtfStorageBundle",
    "SilverNormalizedFieldRecord",
    "SupabaseEtfBronzeStorage",
    "SupabaseEtfRecordRepository",
    "build_gold_record",
    "build_stats_metadata_payload",
    "build_storage_bundle_from_env",
    "normalize_snapshot_to_silver_records",
]
