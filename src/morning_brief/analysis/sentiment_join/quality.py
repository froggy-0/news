from __future__ import annotations

STRUCTURED_SOURCE_MIN_COVERAGE_RATIO = 0.60


def calculate_coverage_ratio(non_null_days: int, requested_days: int) -> float:
    if requested_days <= 0:
        return 0.0
    return round(non_null_days / requested_days, 4)


def quality_status_for_ratio(ratio: float) -> str:
    return "ok" if ratio >= STRUCTURED_SOURCE_MIN_COVERAGE_RATIO else "degraded"


__all__ = [
    "STRUCTURED_SOURCE_MIN_COVERAGE_RATIO",
    "calculate_coverage_ratio",
    "quality_status_for_ratio",
]
