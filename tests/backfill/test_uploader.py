"""R2 업로더 단위 테스트. boto3 S3 클라이언트 mock 처리."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from backfill.scorer import DailyAggregate
from backfill.uploader import (
    _is_pipeline_file,
    build_backfill_sidecar_json,
    build_minimal_brief_json,
    upload_all,
    upload_brief,
)
from morning_brief.data.storage.analytics_contract import validate_analytics_sentiment_payload

_ALLOWED_KEYS = frozenset(
    {
        "schemaVersion",
        "producer",
        "generatedAt",
        "date",
        "symbol",
        "sentimentStatus",
        "newsSentiment",
        "_backfill",
    }
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


def test_build_minimal_brief_json_passes_analytics_contract() -> None:
    """Property A-1: build_minimal_brief_json 결과는 validate_analytics_sentiment_payload를 반드시 통과해야 한다."""
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)
    result = validate_analytics_sentiment_payload(payload)
    assert result["valid"] is True, f"계약 검증 실패: {result['reason']}"


def test_build_minimal_brief_json_contains_only_allowed_keys() -> None:
    """결과 JSON이 정확히 _ANALYTICS_ALLOWED_KEYS 8개 키만 포함해야 한다."""
    payload = build_minimal_brief_json("2024-01-01", _agg())
    extra = set(payload.keys()) - _ALLOWED_KEYS
    assert extra == set(), f"허용되지 않은 키 포함: {extra}"


def test_build_minimal_brief_json_schema() -> None:
    """flat format으로 생성되며 필수 필드가 올바른 값을 갖는다."""
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)

    # flat format: meta 래퍼 없음
    assert "meta" not in payload
    assert payload["date"] == "2024-01-01"
    assert payload["symbol"] == "btc"
    assert payload["schemaVersion"] == "v1"
    assert payload["producer"] == "backfill.finbert"
    assert payload["sentimentStatus"] == "skipped"
    assert payload["_backfill"] is True
    assert "newsSentiment" in payload

    # 진단 필드는 본체에 없어야 함
    assert "_backfillSource" not in payload
    assert "signalSentimentStatus" not in payload
    assert "signalSentiment" not in payload
    assert "textSchemaVersion" not in payload


def test_build_minimal_brief_json_mean_none_serializes_null() -> None:
    agg = _agg(mean=None, std=None, count=0, status="skipped")
    payload = build_minimal_brief_json("2024-01-01", agg)
    dumped = json.dumps(payload)
    parsed = json.loads(dumped)

    assert parsed["newsSentiment"]["mean"] is None
    assert parsed["newsSentiment"]["std"] is None


# ──────────────────────────────────────────────
# build_backfill_sidecar_json
# ──────────────────────────────────────────────


def test_build_backfill_sidecar_json_contains_diagnostic_fields() -> None:
    """사이드카는 진단 필드를 포함하고 analytics 계약 키와 겹치지 않아야 한다."""
    sidecar = build_backfill_sidecar_json("2024-01-01", _agg())
    assert "_backfillSource" in sidecar
    assert "_backfillGeneratedAt" in sidecar
    assert "textSchemaVersion" in sidecar
    assert "date" in sidecar
    # 사이드카는 계약 키를 포함하지 않아야 함
    assert "schemaVersion" not in sidecar
    assert "newsSentiment" not in sidecar


# ──────────────────────────────────────────────
# _is_pipeline_file
# ──────────────────────────────────────────────


def test_is_pipeline_file_true_for_live_pipeline_producer() -> None:
    """producer가 'public_site.'로 시작하면 파이프라인 원본 → 보호."""
    assert _is_pipeline_file({"producer": "public_site.publish_public_brief"}) is True


def test_is_pipeline_file_true_when_no_producer_no_backfill_source() -> None:
    """producer 없고 meta._backfillSource도 없으면 파이프라인 원본으로 간주."""
    assert _is_pipeline_file({"_backfill": True, "sentimentStatus": "ok"}) is True
    assert _is_pipeline_file({"meta": {"sentimentStatus": "ok"}}) is True


def test_is_pipeline_file_false_for_backfill_producer() -> None:
    """producer가 'backfill.'로 시작하면 백필 파일 → 덮어쓰기 가능."""
    assert _is_pipeline_file({"producer": "backfill.finbert"}) is False
    assert _is_pipeline_file({"producer": "backfill.scorer"}) is False


def test_is_pipeline_file_false_for_legacy_meta_backfill() -> None:
    """레거시 meta 래퍼 백필 파일(meta._backfillSource 존재)도 덮어쓰기 가능."""
    existing_meta = {"meta": {"_backfill": True, "_backfillSource": "coindesk+alpaca+finbert"}}
    assert _is_pipeline_file(existing_meta) is False


# ──────────────────────────────────────────────
# upload_brief: 파일 미존재 → 신규 업로드
# ──────────────────────────────────────────────


def test_upload_brief_new_file_returns_uploaded() -> None:
    client = _s3_client_mock(exists=False)
    result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "uploaded"
    # 본체 + 사이드카 2회 put_object 호출
    assert client.put_object.call_count == 2
    # 첫 번째 호출이 본체 analytics key
    first_call_key = client.put_object.call_args_list[0][1]["Key"]
    assert first_call_key == "analytics/btc/2024-01-01.json"


def test_upload_brief_uses_analytics_path_helper() -> None:
    client = _s3_client_mock(exists=False)
    fake_paths = type("P", (), {"analytics_key": "analytics/btc/2024-01-01.json"})

    with patch("backfill.uploader.build_publish_paths", return_value=fake_paths) as build_paths:
        result = upload_brief("2024-01-01", _agg(), client, "bucket")

    assert result == "uploaded"
    build_paths.assert_called_once_with(symbol="btc", run_date="2024-01-01")
    first_call_key = client.put_object.call_args_list[0][1]["Key"]
    assert first_call_key == "analytics/btc/2024-01-01.json"


def test_upload_brief_sidecar_key_is_backfill_meta_suffix() -> None:
    """사이드카 key는 본체 key + '.backfill-meta.json'이어야 한다."""
    client = _s3_client_mock(exists=False)
    upload_brief("2024-01-01", _agg(), client, "bucket")

    keys_uploaded = [c[1]["Key"] for c in client.put_object.call_args_list]
    assert "analytics/btc/2024-01-01.json.backfill-meta.json" in keys_uploaded


def test_upload_brief_sidecar_failure_does_not_affect_return_value() -> None:
    """사이드카 put_object 실패 시에도 'uploaded'를 반환해야 한다."""
    client = _s3_client_mock(exists=False)
    # 두 번째 put_object(사이드카)만 실패
    call_count = 0

    def _put_object_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("sidecar network error")

    client.put_object.side_effect = _put_object_side_effect
    result = upload_brief("2024-01-01", _agg(), client, "bucket")
    assert result == "uploaded"


# ──────────────────────────────────────────────
# upload_brief: 파일 존재 + force=False → skipped_exists
# ──────────────────────────────────────────────


def test_upload_brief_exists_no_force_returns_skipped_exists() -> None:
    client = _s3_client_mock(exists=True, existing_json={"producer": "public_site.x"})
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=False)

    assert result == "skipped_exists"
    client.put_object.assert_not_called()


# ──────────────────────────────────────────────
# upload_brief: force=True + 백필 파일 → 덮어쓰기
# ──────────────────────────────────────────────


def test_upload_brief_force_with_backfill_producer_overwrites() -> None:
    """producer='backfill.finbert'인 파일은 --force로 덮어쓸 수 있다."""
    existing = {"producer": "backfill.finbert", "_backfill": True, "sentimentStatus": "ok"}
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "uploaded"
    assert client.put_object.call_count >= 1


def test_upload_brief_force_with_legacy_meta_backfill_overwrites() -> None:
    """레거시 meta 래퍼 백필 파일도 덮어쓰기 가능해야 한다."""
    existing = {"meta": {"sentimentStatus": "ok", "_backfillSource": "coindesk+alpaca+finbert"}}
    client = _s3_client_mock(exists=True, existing_json=existing)
    result = upload_brief("2024-01-01", _agg(), client, "bucket", force=True)

    assert result == "uploaded"
    assert client.put_object.call_count >= 1


# ──────────────────────────────────────────────
# upload_brief: force=True + 파이프라인 원본 → skipped_protected
# ──────────────────────────────────────────────


def test_upload_brief_force_pipeline_file_protected() -> None:
    """라이브 파이프라인 파일(producer='public_site.*')은 --force에서도 보호."""
    existing = {"producer": "public_site.publish_public_brief", "_backfill": False}
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
