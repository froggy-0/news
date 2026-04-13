"""R2 업로더 단위 테스트. boto3 S3 클라이언트 mock 처리."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backfill.scorer import DailyAggregate
from backfill.uploader import (
    _is_pipeline_file,
    build_minimal_brief_json,
    upload_all,
    upload_brief,
)
from botocore.exceptions import ClientError


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
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)
    meta = payload["meta"]

    assert meta["date"] == "2024-01-01"
    assert meta["sentimentStatus"] == "skipped"
    assert meta["signalSentimentStatus"] == "skipped"
    assert meta["signalSentiment"] is None
    assert meta["_backfill"] is True
    assert meta["_backfillSource"] == "coindesk+alpaca+finbert"
    assert "newsSentiment" in meta


def test_build_minimal_brief_json_mean_none_serializes_null() -> None:
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)
    dumped = json.dumps(payload)
    parsed = json.loads(dumped)

    assert parsed["meta"]["newsSentiment"]["mean"] is None
    assert parsed["meta"]["newsSentiment"]["std"] is None


# ──────────────────────────────────────────────
# _is_pipeline_file
# ──────────────────────────────────────────────


def test_is_pipeline_file_true_when_no_backfill_field() -> None:
    existing = {"meta": {"sentimentStatus": "ok"}}
    assert _is_pipeline_file(existing) is True


def test_is_pipeline_file_false_when_backfill_present() -> None:
    existing = {"meta": {"sentimentStatus": "ok", "_backfill": True}}
    assert _is_pipeline_file(existing) is False


# ──────────────────────────────────────────────
# upload_brief: 파일 미존재 → 신규 업로드
# ──────────────────────────────────────────────


def test_upload_brief_new_file_returns_uploaded() -> None:
    client = _s3_client_mock(exists=False)
    result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "uploaded"
    client.put_object.assert_called_once()


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
    existing = {"meta": {"sentimentStatus": "ok", "_backfill": True}}
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "uploaded"
    client.put_object.assert_called_once()


# ──────────────────────────────────────────────
# upload_brief: force=True + _backfill 없음 → skipped_protected
# ──────────────────────────────────────────────


def test_upload_brief_force_pipeline_file_protected() -> None:
    existing = {"meta": {"sentimentStatus": "ok"}}  # _backfill 없음
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
