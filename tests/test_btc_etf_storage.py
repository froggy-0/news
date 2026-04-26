from __future__ import annotations

import json
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
        hybrid_indices={
            "full": {
                "pca_summary": {"status": "ok", "n_components": 1},
                "vif_diagnostics": [{"feature": "fng_value_lag1", "vif": 1.2}],
                "coverage": {"rows_total": 40, "rows_used": 30, "ratio": 0.75},
                "signal_label": "risk_on",
            },
            "core": {
                "pca_summary": {"status": "ok", "n_components": 1},
                "vif_diagnostics": [],
                "coverage": {"rows_total": 40, "rows_used": 38, "ratio": 0.95},
                "signal_label": "neutral",
            },
        },
        rows_before_outlier_filter=42,
        rows_after_outlier_filter=40,
        outlier_filtered_count=2,
        outlier_filtered_ratio=0.0476,
        structured_sources={
            "btc_etf": {"mode": "gold_history", "quality_status": "ok"},
            "futures": {"mode": "binance", "quality_status": "degraded"},
        },
    )

    decoded = payload.decode("utf-8")
    assert '"run_id": "sentiment-join-20260412"' in decoded
    assert '"granger_results"' in decoded
    assert '"hybrid_indices"' in decoded
    assert '"structured_sources"' in decoded
    assert '"full"' in decoded
    assert '"core"' in decoded


# ---------------------------------------------------------------------------
# Metadata 확장 필드 단위 테스트 (Alpha Validation)
# Validates: Requirements 6.4
# ---------------------------------------------------------------------------


def test_build_stats_metadata_payload_includes_alpha_validation_fields() -> None:
    """hit_rates, correlations, backtest, walk_forward 필드가 직렬화에 포함된다."""
    hit_rates = [
        {
            "predictor": "news_sentiment_mean_lag1",
            "threshold": 0,
            "hit_rate": 0.55,
            "tp": 40,
            "fp": 30,
            "tn": 35,
            "fn": 25,
            "precision": 0.57,
            "recall": 0.62,
            "f1": 0.59,
            "n_valid": 130,
            "inverted": False,
            "granger_significant": True,
        }
    ]
    correlations = [
        {
            "col_a": "news_sentiment_mean_lag1",
            "col_b": "btc_log_return",
            "pearson_r": 0.12,
            "pearson_pvalue": 0.08,
            "spearman_rho": 0.15,
            "spearman_pvalue": 0.04,
            "n_valid": 130,
            "differenced": False,
        }
    ]
    backtest = [
        {
            "predictor": "full_hybrid_index_score_lag1",
            "threshold": 50,
            "strategy_cumulative_return": 0.15,
            "bnh_cumulative_return": 0.10,
            "alpha": 0.05,
            "sharpe_ratio": 1.2,
            "max_drawdown": -0.08,
            "n_trades": 25,
            "transaction_cost_bps": 10.0,
            "inverted": False,
            "granger_significant": None,
        }
    ]
    walk_forward = {
        "folds": [{"fold": 0, "test_start": "2024-05-01", "test_end": "2024-05-30"}],
        "avg_hit_rate": 0.52,
        "avg_cumulative_return": 0.03,
        "avg_alpha": 0.01,
        "train_days": 120,
        "test_days": 30,
    }

    payload = build_stats_metadata_payload(
        run_id="sentiment-join-20260501",
        generated_at_utc="2026-05-01T00:00:00+00:00",
        adf={"pvalue": 0.01},
        granger_results=[],
        hybrid_indices=None,
        hit_rates=hit_rates,
        correlations=correlations,
        backtest=backtest,
        walk_forward=walk_forward,
        baseline_metrics={"1": {"always_up": {"hit_rate": 0.51}}},
        horizon_metrics={"3": {"return_col": "btc_fwd_ret_3d", "hit_rates": []}},
        walk_forward_horizons={"full": {"3": {"avg_hit_rate": 0.53}}},
    )

    decoded = json.loads(payload.decode("utf-8"))

    assert decoded["hit_rates"] == hit_rates
    assert decoded["correlations"] == correlations
    assert decoded["backtest"] == backtest
    assert decoded["walk_forward"] == walk_forward
    assert decoded["baseline_metrics"] == {"1": {"always_up": {"hit_rate": 0.51}}}
    assert decoded["horizon_metrics"] == {"3": {"return_col": "btc_fwd_ret_3d", "hit_rates": []}}
    assert decoded["walk_forward_horizons"] == {"full": {"3": {"avg_hit_rate": 0.53}}}


def test_build_stats_metadata_payload_defaults_empty_when_none() -> None:
    """alpha validation 파라미터가 None이면 빈 dict/list로 직렬화된다."""
    payload = build_stats_metadata_payload(
        run_id="sentiment-join-20260501",
        generated_at_utc="2026-05-01T00:00:00+00:00",
        adf=None,
        granger_results=[],
        hybrid_indices=None,
    )

    decoded = json.loads(payload.decode("utf-8"))

    assert decoded["hit_rates"] == []
    assert decoded["correlations"] == []
    assert decoded["backtest"] == []
    assert decoded["walk_forward"] == {}
    assert decoded["baseline_metrics"] == {}
    assert decoded["horizon_metrics"] == {}
    assert decoded["walk_forward_horizons"] == {}
    assert decoded["granger_skips"] == []
    assert decoded["granger_skip_summary"] == {}
    assert decoded["ffill_breakdown"] == {}
    assert decoded["target_diagnostics"] == {}
    assert decoded["structured_sources"] == {}
