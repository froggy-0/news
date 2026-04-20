"""일회용 진단: ADF/KPSS 단계에서 발생하는 scalar divide RuntimeWarning의 출처 추적.

실행:
  source .venv/bin/activate
  python gw/error/trace_scalar_divide.py \
      --parquet data/sentiment_join/master_20260418.parquet

출력: 컬럼별 ADF+KPSS 수행 결과와, 해당 호출 중 포착된 RuntimeWarning 위치·메시지.

커밋하지 않는 로컬 진단용.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief.analysis.sentiment_join.statistical_tests import (  # noqa: E402
    ADF_TARGETS,
    MIN_ROWS_FOR_ADF,
    _ensure_stationary,
)


def _diagnose_series(col: str, s: pd.Series) -> None:
    s_num = pd.to_numeric(s, errors="coerce").dropna()
    print(f"\n=== {col} ===")
    print(f"  rows: {len(s_num)}  min={s_num.min():.6g}  max={s_num.max():.6g}")
    print(f"  mean={s_num.mean():.6g}  std={s_num.std():.6g}")
    print(f"  n_unique={s_num.nunique()}  n_zero={(s_num == 0).sum()}")
    if len(s_num) < MIN_ROWS_FOR_ADF:
        print("  SKIP: rows < MIN_ROWS_FOR_ADF")
        return

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # _ensure_stationary: ADF+KPSS → 비정상이면 차분 후 재검정
        try:
            _series_out, is_stationary, was_diff = _ensure_stationary(s)
            print(f"  stationary={is_stationary}  differenced={was_diff}")
        except Exception as exc:
            print(f"  ERROR in _ensure_stationary: {exc}")

    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    other_warnings = [w for w in caught if not issubclass(w.category, RuntimeWarning)]
    if runtime_warnings:
        print(f"  !! {len(runtime_warnings)} RuntimeWarning(s):")
        for w in runtime_warnings:
            loc = f"{Path(w.filename).name}:{w.lineno}"
            print(f"     - [{loc}] {w.category.__name__}: {w.message}")
    if other_warnings:
        print(f"  {len(other_warnings)} 기타 warning(s):")
        for w in other_warnings[:3]:
            loc = f"{Path(w.filename).name}:{w.lineno}"
            print(f"     - [{loc}] {w.category.__name__}: {w.message}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    print(f"loaded {args.parquet}: {len(df)} rows, {len(df.columns)} cols")

    # 이상치 마스킹을 파이프라인과 동일하게 적용 (analysis_df 재현)
    if "is_outlier" in df.columns:
        _NON_MASK = {
            "date",
            "is_outlier",
            "sentiment_status",
            "is_backfill_valid",
            "ingest_validation_reason",
            "btc_direction_label",
            "text_schema_version",
        }
        mask_cols = [c for c in df.columns if c not in _NON_MASK]
        df.loc[df["is_outlier"].astype(bool), mask_cols] = np.nan
        print(f"  applied outlier mask to {int(df['is_outlier'].sum())} rows")

    for col in ADF_TARGETS:
        if col not in df.columns:
            print(f"\n=== {col} === (missing — skip)")
            continue
        _diagnose_series(col, df[col])

    return 0


if __name__ == "__main__":
    sys.exit(main())
