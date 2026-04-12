from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MIN_ROWS_FOR_TESTS = 30
GRANGER_LAGS = [1, 2, 3]
GRANGER_PAIRS = [
    ("news_sentiment_mean", "btc_log_return"),
    ("funding_rate_lag1", "btc_log_return"),
    ("fng_value", "btc_log_return"),
    ("btc_long_short_ratio_lag1", "btc_log_return"),
]
ADF_TARGETS = [
    "btc_log_return",
    "funding_rate",
    "oi_change_pct_lag1",
    "btc_long_short_ratio",
]


def _run_adf(series: pd.Series) -> dict[str, Any]:
    from statsmodels.tsa.stattools import adfuller

    stat, pvalue, *_ = adfuller(series.dropna())
    stationary = bool(pvalue < 0.05)
    if not stationary:
        log_structured(
            logger,
            event="stats.adf_non_stationary",
            message="btc_log_return이 정상 시계열 조건(p<0.05)을 만족하지 않습니다.",
            level=logging.WARNING,
            pvalue=float(pvalue),
            statistic=float(stat),
        )
    return {"statistic": float(stat), "pvalue": float(pvalue), "stationary": stationary}


def _run_granger(
    df: pd.DataFrame,
    predictor: str,
    target: str,
    lag: int,
) -> dict[str, Any] | None:
    from statsmodels.tsa.stattools import grangercausalitytests

    if predictor not in df.columns or target not in df.columns:
        return None

    # fng_value는 Int64(nullable integer)이므로 float으로 변환 필요
    work = df[[target, predictor]].copy()
    work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
    work = work.dropna()

    if len(work) < MIN_ROWS_FOR_TESTS:
        return None

    try:
        result = grangercausalitytests(work, maxlag=lag, verbose=False)
        pvalue = float(result[lag][0]["ssr_ftest"][1])
    except Exception as exc:
        log_structured(
            logger,
            event="stats.granger_error",
            message="Granger 검정 실행 중 오류가 발생했습니다.",
            level=logging.WARNING,
            predictor=predictor,
            target=target,
            lag=lag,
            reason=str(exc),
        )
        return None

    entry: dict[str, Any] = {
        "predictor": predictor,
        "target": target,
        "lag": lag,
        "pvalue": pvalue,
        "significant": pvalue < 0.05,
    }
    if pvalue < 0.05:
        log_structured(
            logger,
            event="stats.granger_significant",
            message="Granger 인과성 검정에서 유의미한 선행 신호를 발견했습니다.",
            predictor=predictor,
            target=target,
            lag=lag,
            pvalue=pvalue,
        )
    return entry


def run_statistical_tests(df: pd.DataFrame) -> dict[str, Any]:
    """Req 12: ADF 정상성 검정 및 Granger 인과성 검정을 실행합니다.

    Returns a dict with 'adf' and 'granger' keys.
    If data is insufficient (< 30 rows), returns empty dict and logs a warning.
    """
    results: dict[str, Any] = {}

    if len(df) < MIN_ROWS_FOR_TESTS:
        log_structured(
            logger,
            event="stats.insufficient_rows",
            message="데이터 행 수가 통계 검정 최소 요건보다 적어 검정을 건너뜁니다.",
            level=logging.WARNING,
            rows=len(df),
            min_required=MIN_ROWS_FOR_TESTS,
        )
        return results

    if "btc_log_return" not in df.columns or df["btc_log_return"].dropna().empty:
        return results

    adf_results: dict[str, Any] = {}
    for col in ADF_TARGETS:
        if col not in df.columns or df[col].dropna().shape[0] < MIN_ROWS_FOR_TESTS:
            continue
        try:
            adf_results[col] = _run_adf(df[col])
        except Exception as exc:
            log_structured(
                logger,
                event="stats.adf_error",
                message="ADF 검정 실행 중 오류가 발생했습니다.",
                level=logging.WARNING,
                column=col,
                reason=str(exc),
            )
    results["adf"] = adf_results

    granger_results: list[dict[str, Any]] = []
    for predictor, target in GRANGER_PAIRS:
        for lag in GRANGER_LAGS:
            entry = _run_granger(df, predictor, target, lag)
            if entry is not None:
                granger_results.append(entry)
    results["granger"] = granger_results

    return results


__all__ = ["ADF_TARGETS", "GRANGER_PAIRS", "run_statistical_tests"]
