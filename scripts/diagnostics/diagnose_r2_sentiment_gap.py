"""일회용 진단: R2의 sentiment 계약 파일 존재·유효성을 2025-10-19부터 스캔.

실행 전 셸에 아래 env가 로드돼 있어야 함:
  - R2_S3_ENDPOINT
  - R2_ACCESS_KEY_ID
  - R2_SECRET_ACCESS_KEY
  - R2_PUBLIC_BUCKET
  - NEXT_PUBLIC_R2_BASE_URL  (파이프라인 reader가 실제로 GET하는 HTTPS URL)

사용:
  source .venv/bin/activate
  python scripts/diagnostics/diagnose_r2_sentiment_gap.py \
      --start 2025-10-19 --end 2026-04-17

커밋하지 않는 로컬 진단용.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

# 프로젝트 모듈 임포트 경로 고정
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief.data.storage.analytics_contract import (  # noqa: E402
    validate_analytics_sentiment_payload,
)


def _date_range(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument(
        "--legacy-prefix",
        default="briefs",
        help="비교용 legacy 경로 prefix (기본: briefs)",
    )
    args = ap.parse_args()

    endpoint = os.getenv("R2_S3_ENDPOINT", "").strip()
    access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("R2_PUBLIC_BUCKET", "").strip()
    public_base = os.getenv("NEXT_PUBLIC_R2_BASE_URL", "").strip()

    missing = [
        name
        for name, val in [
            ("R2_S3_ENDPOINT", endpoint),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
            ("R2_PUBLIC_BUCKET", bucket),
        ]
        if not val
    ]
    if missing:
        print(f"[fatal] 누락된 env: {', '.join(missing)}")
        return 2

    import boto3  # type: ignore

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    dates = _date_range(args.start, args.end)

    # 1) analytics/btc/ 키 전체 나열
    print(f"[1/3] list_objects analytics/btc/ under {bucket}")
    analytics_keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="analytics/btc/"):
        for obj in page.get("Contents", []) or []:
            analytics_keys.add(obj["Key"])
    print(f"    analytics objects found: {len(analytics_keys)}")

    # 2) legacy 경로 키 나열 (비교용)
    print(f"[2/3] list_objects {args.legacy_prefix}/ under {bucket}")
    legacy_keys: set[str] = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{args.legacy_prefix}/"):
        for obj in page.get("Contents", []) or []:
            legacy_keys.add(obj["Key"])
    print(f"    legacy objects found: {len(legacy_keys)}")

    # 3) 각 날짜별 상태 확인 + 존재 시 validate + HTTPS public URL 비교
    import urllib.error
    import urllib.request

    def _http_get_status(url: str) -> tuple[int, str]:
        """(status_code, body_preview_or_error). 비-200도 처리."""
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "diag/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(512).decode("utf-8", errors="replace")
                return resp.status, body[:120]
        except urllib.error.HTTPError as e:
            return e.code, str(e.reason)[:120]
        except Exception as e:
            return 0, f"err:{type(e).__name__}:{e}"[:120]

    print(f"[3/3] per-date status ({len(dates)} dates)")
    print(f"[3/3] public base: {public_base or '<UNSET>'}")
    print(f"{'date':<12} {'s3':<3} {'legacy':<6} {'http':<5} {'reason':<60}")
    print("-" * 95)
    http_status_counter: Counter[int] = Counter()

    reason_counter: Counter[str] = Counter()
    analytics_missing = 0
    analytics_present_invalid = 0
    analytics_present_valid = 0
    analytics_present_skipped = 0

    for d in dates:
        a_key = f"analytics/btc/{d}.json"
        l_key = f"{args.legacy_prefix}/{d}.json"
        a_exists = a_key in analytics_keys
        l_exists = l_key in legacy_keys

        reason = ""
        if a_exists:
            try:
                obj = client.get_object(Bucket=bucket, Key=a_key)
                payload = json.loads(obj["Body"].read().decode("utf-8"))
                result = validate_analytics_sentiment_payload(payload)
                if not result["valid"]:
                    reason = f"invalid: {result['reason']}"
                    reason_counter[result["reason"] or "unknown"] += 1
                    analytics_present_invalid += 1
                else:
                    ns = payload.get("newsSentiment", {}) or {}
                    mean = ns.get("mean")
                    status = str(payload.get("sentimentStatus", "")).lower()
                    if status == "skipped" or mean is None:
                        reason = f"valid_but_drop: status={status} mean={mean}"
                        reason_counter[f"valid_but_drop:{status}"] += 1
                        analytics_present_skipped += 1
                    else:
                        count = ns.get("count", 0)
                        reason = f"ok mean={mean:.3f} n={count} bf={payload.get('_backfill')}"
                        analytics_present_valid += 1
                        if count is not None and int(count) <= 1:
                            reason += " [WILL_DROP_low_count]"
                            reason_counter["will_drop_low_count"] += 1
            except Exception as exc:
                reason = f"fetch_error: {exc}"
                reason_counter["fetch_error"] += 1
        else:
            analytics_missing += 1
            reason_counter["analytics_missing"] += 1

        # HTTPS GET 비교: 파이프라인 reader가 실제로 사용하는 URL
        http_code: int | str = "-"
        if public_base:
            url = f"{public_base.rstrip('/')}/analytics/btc/{d}.json"
            code, preview = _http_get_status(url)
            http_code = code
            http_status_counter[code] += 1
            if code != 200 and a_exists:
                # S3에는 있는데 HTTP는 실패 → 핵심 불일치
                reason = f"HTTP_MISMATCH code={code} {preview[:30]}"
                reason_counter[f"http_mismatch:{code}"] += 1

        print(
            f"{d:<12} {'Y' if a_exists else '-':<3} "
            f"{'Y' if l_exists else '-':<6} "
            f"{str(http_code):<5} {reason:<60}"
        )

    # 요약
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"total dates scanned:          {len(dates)}")
    print(f"analytics missing:            {analytics_missing}")
    print(f"analytics present & valid:    {analytics_present_valid}")
    print(f"analytics present & invalid:  {analytics_present_invalid}")
    print(f"analytics present & skipped:  {analytics_present_skipped}")
    print()
    print("reason breakdown:")
    for reason, cnt in reason_counter.most_common():
        print(f"  {reason:<40} {cnt}")
    print()
    print("HTTP status breakdown (public_base GET):")
    for code, cnt in http_status_counter.most_common():
        print(f"  {code:<40} {cnt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
