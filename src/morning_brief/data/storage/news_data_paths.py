"""R2 저장 경로 생성 규칙.

publish path (curated/analytics): overwrite-only — 동일 날짜 재실행 시 같은 키.
raw capture path: append-only — 동일 날짜라도 run_id가 다르면 다른 키.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishPathSet:
    """curated + analytics dual-write 경로 묶음."""

    curated_key: str
    analytics_key: str


def build_publish_paths(*, symbol: str, run_date: str) -> PublishPathSet:
    """Overwrite-only publish 경로를 생성한다.

    경로 규칙: ``{layer}/{symbol}/{YYYY-MM-DD}.json``
    """
    return PublishPathSet(
        curated_key=f"curated/{symbol}/{run_date}.json",
        analytics_key=f"analytics/{symbol}/{run_date}.json",
    )


def build_raw_capture_key(
    *,
    domain: str,
    provider: str,
    dataset: str,
    run_date: str,
    run_id: str,
    ext: str = "json",
) -> str:
    """Append-only raw capture 경로를 생성한다.

    경로 규칙: ``raw/{domain}/{provider}/{dataset}/{YYYY-MM-DD}/{run_id}.{ext}``
    """
    return f"raw/{domain}/{provider}/{dataset}/{run_date}/{run_id}.{ext}"


__all__ = ["PublishPathSet", "build_publish_paths", "build_raw_capture_key"]
