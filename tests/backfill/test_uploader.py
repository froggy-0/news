"""R2 업로더 단위 테스트. boto3 S3 클라이언트 mock 처리."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from backfill.scorer import DailyAggregate
from backfill.uploader import (
    _is_pipeline_file,
    build_minimal_brief_json,
    upload_all,
    upload_brief,
)


def _agg(
    date: str = "2024-01-01",
    status: str = "ok",
    mean: float | None = 0.3,
    std: float | None = 0.1,
    count: int = 5,
) -> DailyAggregate:
    return DailyAggregate(
        date=date,
        mean=mean,
        std=std,
        count=count,
        status=status,  # type: ignore[arg-type]
        coindesk_count=count,
        alpaca_count=0,
    )


def _s3_client_mock(*, exists: bool = False, existing_json: dict | None = None) -> MagicMock:
    """boto3 S3 클라이언트 mock."""
    client = MagicMock()

    if exists:
        client.head_object.return_value = {}
        body_bytes = json.dumps(existing_json or {}).encode()
        client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=body_bytes))
        }
    else:
        err = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        client.head_object.side_effect = err

    return client


# ──────────────────────────────────────────────
# build_minimal_brief_json
# ──────────────────────────────────────────────


def test_build_minimal_brief_json_schema() -> None:
    """flat format으로 생성되어 validate_analytics_sentiment_payload()를 통과해야 한다."""
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)

    # flat format: meta 래퍼 없음
    assert "meta" not in payload
    assert payload["date"] == "2024-01-01"
    assert payload["symbol"] == "btc"
    assert payload["schemaVersion"] == "v1"
    assert payload["sentimentStatus"] == "skipped"
    assert payload["signalSentimentStatus"] == "skipped"
    assert payload["signalSentiment"] is None
    assert payload["_backfill"] is True
    assert payload["_backfillSource"] == "coindesk+alpaca+finbert"
    assert "newsSentiment" in payload
    # §2: textSchemaVersion 포함
    assert "textSchemaVersion" in payload
    assert payload["textSchemaVersion"] == "title_summary"


def test_build_minimal_brief_json_mean_none_serializes_null() -> None:
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)
    dumped = json.dumps(payload)
    parsed = json.loads(dumped)

    # flat format으로 변경
    assert parsed["newsSentiment"]["mean"] is None
    assert parsed["newsSentiment"]["std"] is None


# ──────────────────────────────────────────────
# _is_pipeline_file
# ──────────────────────────────────────────────


def test_is_pipeline_file_true_when_no_backfill_source() -> None:
    """_backfillSource 없음 = 라이브 파이프라인 원본 → 보호."""
    # flat format (라이브 파이프라인)
    assert _is_pipeline_file({"_backfill": True, "sentimentStatus": "ok"}) is True
    # legacy meta 형식 (구 파이프라인 원본)
    assert _is_pipeline_file({"meta": {"sentimentStatus": "ok"}}) is True


def test_is_pipeline_file_false_when_backfill_source_present() -> None:
    """_backfillSource 있음 = 백필 파일 → 덮어쓰기 가능."""
    # flat format (현행 백필)
    existing_flat = {
        "_backfill": True,
        "_backfillSource": "coindesk+alpaca+finbert",
        "sentimentStatus": "ok",
    }
    assert _is_pipeline_file(existing_flat) is False

    # legacy meta 형식 (구 백필)
    existing_meta = {"meta": {"_backfill": True, "_backfillSource": "coindesk+alpaca+finbert"}}
    assert _is_pipeline_file(existing_meta) is False


# ──────────────────────────────────────────────
# upload_brief: 파일 미존재 → 신규 업로드
# ──────────────────────────────────────────────


def test_upload_brief_new_file_returns_uploaded() -> None:
    client = _s3_client_mock(exists=False)
    result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "uploaded"
    client.put_object.assert_called_once()
    assert client.put_object.call_args[1]["Key"] == "analytics/btc/2024-01-01.json"


def test_upload_brief_uses_analytics_path_helper() -> None:
    client = _s3_client_mock(exists=False)
    fake_paths = type("P", (), {"analytics_key": "analytics/btc/2024-01-01.json"})

    with patch("backfill.uploader.build_publish_paths", return_value=fake_paths) as build_paths:
        result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "uploaded"
    build_paths.assert_called_once_with(symbol="btc", run_date="2024-01-01")
    client.put_object.assert_called_once()
    assert client.put_object.call_args[1]["Key"] == "analytics/btc/2024-01-01.json"


# ──────────────────────────────────────────────
# upload_brief: 파일 존재 + force=False → skipped_exists
# ──────────────────────────────────────────────


def test_upload_brief_exists_no_force_returns_skipped_exists() -> None:
    client = _s3_client_mock(exists=True, existing_json={"meta": {"_backfill": True}})
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=False)

    assert result == "skipped_exists"
    client.put_object.assert_not_called()


# ──────────────────────────────────────────────
# upload_brief: force=True + _backfill=true → 덮어쓰기
# ──────────────────────────────────────────────


def test_upload_brief_force_with_backfill_file_overwrites() -> None:
    # flat format 백필 파일 (_backfillSource 포함)
    existing = {
        "_backfill": True,
        "_backfillSource": "coindesk+alpaca+finbert",
        "sentimentStatus": "ok",
    }
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "uploaded"
    client.put_object.assert_called_once()


def test_upload_brief_force_with_legacy_meta_backfill_overwrites() -> None:
    """레거시 meta 래퍼 백필 파일도 덮어쓰기 가능해야 한다."""
    existing = {"meta": {"sentimentStatus": "ok", "_backfillSource": "coindesk+alpaca+finbert"}}
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "uploaded"
    client.put_object.assert_called_once()


# ──────────────────────────────────────────────
# upload_brief: force=True + _backfillSource 없음 → skipped_protected
# ──────────────────────────────────────────────


def test_upload_brief_force_pipeline_file_protected() -> None:
    # 라이브 파이프라인 파일: _backfillSource 없음
    existing = {"_backfill": True, "sentimentStatus": "ok"}
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "skipped_protected"
    client.put_object.assert_not_called()


# ──────────────────────────────────────────────
# upload_brief: put_object 실패 → "failed" 반환
# ──────────────────────────────────────────────


def test_upload_brief_put_object_failure_returns_failed() -> None:
    client = _s3_client_mock(exists=False)
    client.put_object.side_effect = Exception("network error")

    result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "failed"


# ──────────────────────────────────────────────
# upload_all: UploadResults 카운트 정확성
# ──────────────────────────────────────────────


def test_upload_all_counts_correctly() -> None:
    """upload_all()이 UploadResults 카운트를 올바르게 집계."""
    aggs = [
        _agg("2024-01-01", status="ok"),  # → uploaded
        _agg("2024-01-02", status="degraded"),  # → skipped_exists
        _agg("2024-01-03", status="skipped"),  # → failed
    ]

    call_order = ["uploaded", "skipped_exists", "failed"]
    idx = 0

    def mock_upload(date, agg, s3, bucket, force=False):
        nonlocal idx
        r = call_order[idx]
        idx += 1
        return r

    with patch("backfill.uploader.upload_brief", side_effect=mock_upload):
        results = upload_all(aggs, MagicMock(), "bucket")

    assert results.uploaded == 1
    assert results.skipped_exists == 1
    assert results.failed == 1
    assert results.aggregates_ok == 1
    assert results.aggregates_degraded == 1
    assert results.aggregates_skipped == 1
