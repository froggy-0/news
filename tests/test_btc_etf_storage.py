from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from morning_brief.data.etf_storage import (
    EtfStorageBundle,
    build_stats_metadata_payload,
    normalize_snapshot_to_silver_records,
)
from morning_brief.models import BitcoinEtfIssuerSnapshot


def _snapshot(*, source_type: str = "official_csv") -> BitcoinEtfIssuerSnapshot:
    return BitcoinEtfIssuerSnapshot(
        ticker="GBTC",
        issuer="Grayscale",
        source_url="https://etfs.grayscale.com/gbtc",
        as_of_date=date(2026, 4, 11),
        shares_outstanding=190_850_100,
        daily_volume=3_707_892,
        aum_usd=16_100_265_163.0,
        total_btc=193_530.1058,
        bitcoin_per_share=0.00101403,
        source_type=source_type,
        quality_status="ok" if source_type != "aggregator" else "degraded",
        collected_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        extra_fields={"nav_per_share": 84.32},
    )


def test_normalize_snapshot_to_silver_records_keeps_file_level_metadata() -> None:
    records = normalize_snapshot_to_silver_records(
        _snapshot(),
        run_id="run-1",
        source_format="xlsx",
        parse_method="gbtc_xlsx",
        source_file_url="https://example.com/gbtc.xlsx",
        raw_label_map={"aum_usd": "Non-GAAP AUM"},
        raw_text_map={"aum_usd": "$16,100,265,163"},
    )

    aum_record = next(record for record in records if record.field_name == "aum_usd")
    assert aum_record.source_file_url == "https://example.com/gbtc.xlsx"
    assert aum_record.raw_label == "Non-GAAP AUM"
    assert aum_record.raw_text == "$16,100,265,163"


@dataclass
class _FakeBronzeStorage:
    uploads: list[dict] = field(default_factory=list)

    def upload_raw_payload(self, **kwargs):
        self.uploads.append(kwargs)
        return "bronze/path.json"


@dataclass
class _FakeRepository:
    writes: list[tuple[list[dict], str]] = field(default_factory=list)

    def upsert_many(self, records: list[dict], *, on_conflict: str) -> None:
        self.writes.append((records, on_conflict))


def test_storage_bundle_writes_primary_to_gold_only() -> None:
    bronze = _FakeBronzeStorage()
    silver = _FakeRepository()
    gold = _FakeRepository()
    reference = _FakeRepository()
    bundle = EtfStorageBundle(bronze=bronze, silver=silver, gold=gold, reference=reference)

    bundle.persist_snapshot(
        run_id="run-1",
        snapshot=_snapshot(),
        source_format="xlsx",
        parse_method="gbtc_xlsx",
        payload=b"payload",
        source_checksum="abc123",
        source_file_url="https://example.com/gbtc.xlsx",
    )

    assert len(bronze.uploads) == 1
    assert len(silver.writes) == 1
    assert len(gold.writes) == 1
    assert reference.writes == []


def test_storage_bundle_routes_reference_only_records_to_reference_table() -> None:
    bronze = _FakeBronzeStorage()
    silver = _FakeRepository()
    gold = _FakeRepository()
    reference = _FakeRepository()
    bundle = EtfStorageBundle(bronze=bronze, silver=silver, gold=gold, reference=reference)

    bundle.persist_snapshot(
        run_id="run-2",
        snapshot=_snapshot(source_type="aggregator"),
        source_format="json",
        parse_method="reference_snapshot",
        payload=b"payload",
        source_checksum="def456",
        reference_only=True,
    )

    assert len(bronze.uploads) == 1
    assert len(silver.writes) == 1
    assert gold.writes == []
    assert len(reference.writes) == 1


def test_build_stats_metadata_payload_serializes_contract_fields() -> None:
    payload = build_stats_metadata_payload(
        run_id="sentiment-join-20260412",
        generated_at_utc="2026-04-12T00:00:00+00:00",
        adf={"pvalue": 0.01},
        granger_results=[{"predictor": "fng_value", "lag": 1, "pvalue": 0.03}],
        vif_diagnostics=[{"feature": "fng_value", "vif": 1.2}],
        pca_summary={"status": "ok", "n_components": 1},
        rows_before_outlier_filter=42,
        rows_after_outlier_filter=40,
        outlier_filtered_count=2,
        outlier_filtered_ratio=0.0476,
        hybrid_signal_label="risk_on",
    )

    decoded = payload.decode("utf-8")
    assert '"run_id": "sentiment-join-20260412"' in decoded
    assert '"granger_results"' in decoded
    assert '"pca_summary"' in decoded
    assert '"hybrid_signal_label": "risk_on"' in decoded
