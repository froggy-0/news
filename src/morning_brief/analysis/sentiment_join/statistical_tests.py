from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MIN_ROWS_FOR_ADF = 30
MIN_ROWS_FOR_GRANGER = 180
GRANGER_LAGS = [1, 2, 3]
# lag1 = T-1 시점 값. 모든 predictor는 btc_log_return보다 시간적으로 앞서야 합니다.
GRANGER_PAIRS = [
    ("news_sentiment_mean_lag1", "btc_log_return"),
    ("funding_rate_lag1", "btc_log_return"),
    ("fng_value_lag1", "btc_log_return"),
    ("btc_long_short_ratio_lag1", "btc_log_return"),
    ("etf_net_inflow_usd_lag1", "btc_log_return"),
]
# §4.3: 역방향 페어 — 가격이 감성/지표를 선행하는지 확인 (단순 선행 해석 방지)
GRANGER_PAIRS_REVERSE = [
    ("btc_log_return", "news_sentiment_mean_lag1"),
    ("btc_log_return", "funding_rate_lag1"),
    ("btc_log_return", "fng_value_lag1"),
    ("btc_log_return", "btc_long_short_ratio_lag1"),
    ("btc_log_return", "etf_net_inflow_usd_lag1"),
]
ADF_TARGETS = [
    "btc_log_return",
    "news_sentiment_mean_lag1",
    "fng_value_lag1",
    "funding_rate",
    "oi_change_pct_lag1",
    "btc_long_short_ratio",
    "etf_net_inflow_usd_lag1",
]


def _run_adf(series: pd.Series) -> dict[str, Any]:
    from statsmodels.tsa.stattools import adfuller

    stat, pvalue, *_ = adfuller(series.dropna())
    stationary = bool(pvalue < 0.05)
    if not stationary:
        log_structured(
            logger,
            event="stats.adf_non_stationary",
            message="시계열이 정상성 조건(p<0.05)을 만족하지 않습니다.",
            level=logging.WARNING,
            pvalue=float(pvalue),
            statistic=float(stat),
        )
    return {"statistic": float(stat), "pvalue": float(pvalue), "stationary": stationary}


def _ensure_stationary(
    series: pd.Series,
) -> tuple[pd.Series, bool, bool]:
    """ADF 검정 후 비정상이면 첫 차분 적용.

    Returns:
        (series_to_use, is_stationary, was_differenced)
        - series_to_use: 정상화된 시계열 (또는 원본)
        - is_stationary: 최종 정상성 여부 (False면 Granger 건너뜀)
        - was_differenced: 차분 적용 여부
    """
    from statsmodels.tsa.stattools import adfuller

    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < MIN_ROWS_FOR_ADF:
        # 데이터 부족 → pass-through (Granger에서 행 수 부족으로 자연스럽게 skip)
        return series, True, False

    _, pvalue, *_ = adfuller(s)
    if pvalue < 0.05:
        return series, True, False

    # 비정상 → 첫 차분 후 재검정
    diff_s = series.diff()
    s_diff = pd.to_numeric(diff_s, errors="coerce").dropna()
    if len(s_diff) >= MIN_ROWS_FOR_ADF:
        _, pvalue_diff, *_ = adfuller(s_diff)
        if pvalue_diff < 0.05:
            return diff_s, True, True

    return series, False, False


def _run_granger(
    df: pd.DataFrame,
    predictor: str,
    target: str,
    lag: int,
) -> dict[str, Any] | None:
    from statsmodels.tsa.stattools import grangercausalitytests

    if predictor not in df.columns or target not in df.columns:
        return None

    # Int64(nullable integer) 등을 float으로 변환
    work = df[[target, predictor]].copy()
    work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
    work[target] = pd.to_numeric(work[target], errors="coerce")
    work = work.dropna()

    if len(work) < MIN_ROWS_FOR_GRANGER:
        return None

    # §4.1: 정상성 gate — predictor·target 모두 ADF p<0.05 통과해야 실행
    pred_series, pred_stationary, pred_differenced = _ensure_stationary(work[predictor])
    tgt_series, tgt_stationary, tgt_differenced = _ensure_stationary(work[target])

    if not pred_stationary or not tgt_stationary:
        log_structured(
            logger,
            event="stats.granger_skipped_non_stationary",
            message="비정상 시계열(ADF 비통과)이 포함되어 Granger 검정을 건너뜁니다.",
            level=logging.INFO,
            predictor=predictor,
            target=target,
            lag=lag,
            pred_stationary=pred_stationary,
            tgt_stationary=tgt_stationary,
        )
        return None

    # 차분이 적용된 경우 정렬된 DataFrame 재구성
    if pred_differenced or tgt_differenced:
        work_stationary = pd.DataFrame({target: tgt_series, predictor: pred_series}).dropna()
        if len(work_stationary) < MIN_ROWS_FOR_GRANGER:
            return None
        work = work_stationary

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

    # §4.2: pvalue_raw 기록 (BH 보정은 run_statistical_tests에서 일괄 적용)
    entry: dict[str, Any] = {
        "predictor": predictor,
        "target": target,
        "lag": lag,
        "pvalue": pvalue,
        "pvalue_raw": pvalue,
        "significant": pvalue < 0.05,
    }
    return entry


def _apply_bh_correction(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Benjamini–Hochberg FDR 보정을 적용합니다.

    모든 Granger 결과(순방향 + 역방향)에 대해 일괄 보정합니다.
    - pvalue_raw: 보정 전 원본 p-value
    - pvalue_adjusted: BH 보정 후 p-value
    - significant: pvalue_adjusted < 0.05 기준

    귀무가설이 모두 참이어도 family-wise error가 팽창하는 문제를 제거합니다.
    """
    if not entries:
        return entries

    m = len(entries)
    # p-value 오름차순 정렬 인덱스
    order = sorted(range(m), key=lambda i: entries[i]["pvalue"])

    corrected = [dict(e) for e in entries]

    # BH adjusted: adj_p_(k) = p_(k) * m / k
    adj: list[float] = [0.0] * m
    for rank_0, orig_idx in enumerate(order):
        rank = rank_0 + 1
        adj[rank_0] = min(corrected[orig_idx]["pvalue"] * m / rank, 1.0)

    # 단조 감소 강제 (step-up: 뒤에서부터 누적 최솟값)
    for i in range(m - 2, -1, -1):
        adj[i] = min(adj[i], adj[i + 1])

    for rank_0, orig_idx in enumerate(order):
        corrected[orig_idx]["pvalue_adjusted"] = round(adj[rank_0], 10)
        corrected[orig_idx]["significant"] = adj[rank_0] < 0.05

    return corrected


def run_statistical_tests(df: pd.DataFrame) -> dict[str, Any]:
    """Req 12: ADF 정상성 검정 및 Granger 인과성 검정을 실행합니다.

    Returns a dict with 'adf' and 'granger' keys.
    If data is insufficient (< 30 rows), returns empty dict and logs a warning.
    """
    results: dict[str, Any] = {}

    if len(df) < MIN_ROWS_FOR_ADF:
        log_structured(
            logger,
            event="stats.insufficient_rows",
            message="데이터 행 수가 ADF 검정 최소 요건보다 적어 검정을 건너뜁니다.",
            level=logging.WARNING,
            rows=len(df),
            min_required=MIN_ROWS_FOR_ADF,
        )
        return results

    if "btc_log_return" not in df.columns or df["btc_log_return"].dropna().empty:
        return results

    # ── ADF 검정 (MIN_ROWS_FOR_ADF 기준) ──
    adf_results: dict[str, Any] = {}
    for col in ADF_TARGETS:
        if col not in df.columns or df[col].dropna().shape[0] < MIN_ROWS_FOR_ADF:
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

    # ── Granger 검정 (MIN_ROWS_FOR_GRANGER 기준) ──
    granger_results: list[dict[str, Any]] = []
    if len(df) >= MIN_ROWS_FOR_GRANGER:
        all_pairs = [(predictor, target, "forward") for predictor, target in GRANGER_PAIRS] + [
            (predictor, target, "reverse") for predictor, target in GRANGER_PAIRS_REVERSE
        ]
        for predictor, target, direction in all_pairs:
            for lag in GRANGER_LAGS:
                entry = _run_granger(df, predictor, target, lag)
                if entry is not None:
                    entry["direction"] = direction
                    granger_results.append(entry)

        # §4.2: Benjamini–Hochberg FDR 보정 — 모든 테스트에 일괄 적용
        # significant 플래그는 보정 후 기준으로만 True로 설정됩니다.
        granger_results = _apply_bh_correction(granger_results)

        # 순방향 유의 신호 로깅
        for entry in granger_results:
            if entry.get("significant") and entry.get("direction") == "forward":
                log_structured(
                    logger,
                    event="stats.granger_significant",
                    message="Granger 인과성 검정(BH 보정 후)에서 유의미한 선행 신호를 발견했습니다.",
                    predictor=entry["predictor"],
                    target=entry["target"],
                    lag=entry["lag"],
                    pvalue_raw=entry["pvalue_raw"],
                    pvalue_adjusted=entry["pvalue_adjusted"],
                )
    else:
        log_structured(
            logger,
            event="stats.granger_skipped",
            message="유효 행 수가 Granger 검정 최소 요건(180행)보다 적어 건너뜁니다.",
            level=logging.INFO,
            rows=len(df),
            min_required=MIN_ROWS_FOR_GRANGER,
            reason="insufficient_rows_for_granger",
        )
    results["granger"] = granger_results
    results["granger_eligible_rows"] = len(df)
    results["granger_executed"] = len(df) >= MIN_ROWS_FOR_GRANGER

    return results


__all__ = [
    "ADF_TARGETS",
    "GRANGER_PAIRS",
    "GRANGER_PAIRS_REVERSE",
    "MIN_ROWS_FOR_ADF",
    "MIN_ROWS_FOR_GRANGER",
    "_apply_bh_correction",
    "_ensure_stationary",
    "run_statistical_tests",
]
