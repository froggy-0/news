from __future__ import annotations

import pandas as pd

HYBRID_SIGNAL_WINDOW = 30
HYBRID_SIGNAL_Z_THRESHOLD = 0.5


def hybrid_signal_label(series: pd.Series) -> tuple[str, float | None]:
    """하이브리드 지수 최근 30일 z-score로 risk_on / risk_off / neutral 라벨을 만듭니다.

    반환: (label, zscore). 표본이 부족하거나 std=0이면 zscore가 None일 수 있습니다.

    §4 3-3: 이전에는 pipeline.py와 intelligence.py에 중복 구현이 있었습니다(반환 타입도 달랐음).
    drift를 막기 위해 단일 소스로 통합했습니다.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return "neutral", None
    window = clean.tail(HYBRID_SIGNAL_WINDOW)
    if len(window) < 2:
        return "neutral", None
    mean = float(window.mean())
    std = float(window.std(ddof=0))
    if std == 0:
        return "neutral", 0.0
    zscore = float((window.iloc[-1] - mean) / std)
    if zscore >= HYBRID_SIGNAL_Z_THRESHOLD:
        return "risk_on", zscore
    if zscore <= -HYBRID_SIGNAL_Z_THRESHOLD:
        return "risk_off", zscore
    return "neutral", zscore


__all__ = ["HYBRID_SIGNAL_WINDOW", "HYBRID_SIGNAL_Z_THRESHOLD", "hybrid_signal_label"]
