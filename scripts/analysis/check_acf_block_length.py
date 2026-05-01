#!/usr/bin/env python3
"""signal hits 시계열의 ACF를 분석해 block_length=14 적정성을 확인한다.

T+7 overlapping target 때문에 signal hits 시리즈에 최소 7일의 자기상관이 기대된다.
현재 block_length=14 (2 × horizon)가 충분한지, 혹은 더 길게 설정해야 하는지 판단한다.

사용법:
    python scripts/analysis/check_acf_block_length.py \\
        --parquet data/sentiment_join/master_20260430.parquet \\
        --predictors vix_regime_score_lag1 fng_value_lag1

권장 해석 기준:
    first_insignificant_lag <= 14  : block_length=14 유지
    14 < first_insignificant_lag <= 21 : block_length=21 고려
    first_insignificant_lag > 21   : auto_block_length 도입 검토
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

DEFAULT_MAX_LAG = 35
CURRENT_BLOCK_LENGTH = 14
SIGNIFICANCE_LEVEL = 0.05


def _signal_95_threshold(n: int) -> float:
    """Bartlett 95% 신뢰 임계값: ±1.96 / sqrt(n)."""
    return 1.96 / np.sqrt(n)


def compute_signal_hits(
    signal: pd.Series,
    target: pd.Series,
    direction_label: pd.Series | None = None,
) -> pd.Series:
    """signal이 target의 방향을 맞춘 날(=hit=1)과 틀린 날(=0) 시리즈를 반환한다."""
    aligned = pd.DataFrame({"signal": signal, "ret": target}).dropna()
    active = aligned[aligned["signal"] != 0]
    if direction_label is not None:
        not_flat = (direction_label != "flat").reindex(active.index, fill_value=True)
        active = active[not_flat]
    if active.empty:
        return pd.Series(dtype=float)
    hits = (np.sign(active["signal"]) == np.sign(active["ret"])).astype(float)
    return hits


def acf_manual(series: np.ndarray, max_lag: int) -> np.ndarray:
    """statsmodels 없이 직접 계산하는 ACF (sample autocorrelation)."""
    n = len(series)
    mean = np.mean(series)
    var = np.var(series, ddof=0)
    if var < 1e-15:
        return np.zeros(max_lag + 1)
    centered = series - mean
    acf_vals = np.zeros(max_lag + 1)
    acf_vals[0] = 1.0
    for lag in range(1, max_lag + 1):
        acf_vals[lag] = np.sum(centered[lag:] * centered[:-lag]) / (n * var)
    return acf_vals


def analyze_predictor(
    df: pd.DataFrame,
    predictor: str,
    return_col: str = "btc_fwd_ret_7d",
    max_lag: int = DEFAULT_MAX_LAG,
) -> dict:
    if predictor not in df.columns:
        return {"predictor": predictor, "error": "컬럼 없음"}
    if return_col not in df.columns:
        return {"predictor": predictor, "error": f"{return_col} 없음"}

    direction_label = df.get("btc_direction_label")
    hits = compute_signal_hits(df[predictor], df[return_col], direction_label)
    n = len(hits)
    if n < 20:
        return {"predictor": predictor, "error": f"active row 부족 ({n})"}

    acf_vals = acf_manual(hits.to_numpy(), max_lag)
    threshold = _signal_95_threshold(n)

    # 첫 번째로 신뢰구간 안으로 들어오는 lag
    first_insignificant = None
    for lag in range(1, max_lag + 1):
        if abs(acf_vals[lag]) < threshold:
            first_insignificant = lag
            break

    # 10~21 구간 평균 절댓값 — 잔류 자기상관 요약
    residual_mean_abs = float(np.mean(np.abs(acf_vals[10 : min(22, max_lag + 1)])))

    return {
        "predictor": predictor,
        "n_active": n,
        "threshold_95": round(threshold, 4),
        "first_insignificant_lag": first_insignificant if first_insignificant else f">{max_lag}",
        "acf_at_7": round(float(acf_vals[7]), 4) if max_lag >= 7 else None,
        "acf_at_14": round(float(acf_vals[14]), 4) if max_lag >= 14 else None,
        "acf_at_21": round(float(acf_vals[21]), 4) if max_lag >= 21 else None,
        "residual_mean_abs_lag10_21": round(residual_mean_abs, 4),
        "recommendation": _recommend(first_insignificant, max_lag),
    }


def _recommend(first_insignificant: int | None, max_lag: int) -> str:
    if first_insignificant is None:
        return f"block_length 증가 필요 (first_insignificant > {max_lag})"
    if first_insignificant <= CURRENT_BLOCK_LENGTH:
        return (
            f"block_length={CURRENT_BLOCK_LENGTH} 유지 (first_insignificant={first_insignificant})"
        )
    if first_insignificant <= 21:
        return f"block_length=21 고려 (first_insignificant={first_insignificant})"
    return f"auto_block_length 도입 검토 (first_insignificant={first_insignificant})"


def main() -> None:
    parser = argparse.ArgumentParser(description="ACF block length 분석")
    parser.add_argument("--parquet", required=True, type=Path, help="master parquet 경로")
    parser.add_argument(
        "--predictors",
        nargs="+",
        default=["vix_regime_score_lag1", "fng_value_lag1", "etf_net_inflow_usd_log1p_lag1"],
        help="분석할 predictor 컬럼명",
    )
    parser.add_argument("--return-col", default="btc_fwd_ret_7d")
    parser.add_argument("--max-lag", type=int, default=DEFAULT_MAX_LAG)
    args = parser.parse_args()

    if not args.parquet.exists():
        print(f"[ERROR] parquet 파일 없음: {args.parquet}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(args.parquet)
    print(f"데이터: {len(df)}행, 컬럼 {len(df.columns)}개\n")
    print(f"{'Predictor':<40} {'n_active':>8} {'first_insig':>12} {'acf@14':>8} {'권고'}")
    print("-" * 100)

    any_increase_needed = False
    for pred in args.predictors:
        result = analyze_predictor(df, pred, args.return_col, args.max_lag)
        if "error" in result:
            print(f"{pred:<40} {'[SKIP]':>8} {result['error']}")
            continue
        fi = result["first_insignificant_lag"]
        acf14 = result["acf_at_14"]
        rec = result["recommendation"]
        print(f"{pred:<40} {result['n_active']:>8} {str(fi):>12} {str(acf14):>8}  {rec}")
        if isinstance(fi, int) and fi > CURRENT_BLOCK_LENGTH:
            any_increase_needed = True

    print()
    if any_increase_needed:
        print(
            f"[WARN] 일부 predictor에서 block_length > {CURRENT_BLOCK_LENGTH} 필요. "
            "bootstrap.py DEFAULT_BLOCK_LENGTH 조정 고려."
        )
    else:
        print(f"[OK] 모든 predictor에서 block_length={CURRENT_BLOCK_LENGTH} 유지 가능.")


if __name__ == "__main__":
    main()
