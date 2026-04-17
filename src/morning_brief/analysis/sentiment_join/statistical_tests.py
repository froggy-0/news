from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MIN_ROWS_FOR_ADF = 30
MIN_ROWS_FOR_GRANGER = 180
GRANGER_LAGS = [1, 2, 3]

# §0: Granger 내부에서 predictor[t-1..t-k]를 자체 처리하므로 raw 컬럼을 투입해야 한다.
# _lag1 버전을 투입하면 실제 검정 관계가 한 칸 더 밀리는 double-lag이 발생한다.
_TARGET = "btc_log_return"

# usdkrw_log_return: 두 채널로 btc_log_return 선행 가능 (한국 투자자 차별화 지표)
# (1) KIMP 채널: 원달러 변동 → 업비트·빗썸 프리미엄(KIMP) → 국내 BTC 유동성 전가
# (2) 글로벌 리스크온/오프: USD 강세 → 리스크자산 매도 연쇄 → BTC 하방 압력
# 채널 근거가 약하다고 판단될 경우 GRANGER_PAIRS_EXPLORATORY로 이동 고려 (§8)
_PREDICTORS_RAW = [
    "news_sentiment_mean",
    "fng_value",
    "funding_rate",
    "btc_long_short_ratio",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "usdkrw_log_return",
    "volume_change_pct",
]

GRANGER_PAIRS_TARGET = [(p, _TARGET) for p in _PREDICTORS_RAW]  # 8쌍

GRANGER_PAIRS_CROSS = [
    # 정보 전파 경로 — Granger lag=k: "k일 전 predictor → 오늘 target"
    # §6: pairwise 결과는 직접 인과의 증거가 아니라 상관 구조의 지표 (omitted variable bias 주의)
    ("news_sentiment_mean", "fng_value"),
    ("fng_value", "news_sentiment_mean"),
    ("news_sentiment_mean", "funding_rate"),
    ("news_sentiment_mean", "etf_net_inflow_usd"),
    ("fng_value", "btc_long_short_ratio"),
    ("fng_value", "etf_net_inflow_usd"),
    ("usdkrw_log_return", "volume_change_pct"),
    ("funding_rate", "etf_net_inflow_usd"),
]  # 8쌍

GRANGER_PAIRS = GRANGER_PAIRS_TARGET + GRANGER_PAIRS_CROSS  # 16쌍 × 3 lag = 48 검정

# §4.3: 역방향 페어 — 가격이 지표를 선행하는지 확인 (단순 선행 해석 방지)
# target은 raw 컬럼 (double-lag 방지와 동일한 이유)
GRANGER_PAIRS_REVERSE = [
    ("btc_log_return", "news_sentiment_mean"),
    ("btc_log_return", "funding_rate"),
    ("btc_log_return", "fng_value"),
    ("btc_log_return", "btc_long_short_ratio"),
    ("btc_log_return", "etf_net_inflow_usd"),
]  # 5쌍 × 3 lag = 15 검정

# 전체 BH-FDR family: (16 + 5) × 3 = 63 검정

ADF_TARGETS = [
    # §4: Granger에 투입되는 모든 raw 변수에 ADF+KPSS 합의 검정 적용
    "btc_log_return",
    "news_sentiment_mean",
    "fng_value",
    "funding_rate",
    "btc_long_short_ratio",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "usdkrw_log_return",
    "volume_change_pct",
]


def _calendar_span(date_series: pd.Series) -> int:
    """날짜 시계열의 달력 span 일수 (max - min)."""
    dates = pd.to_datetime(date_series.dropna(), errors="coerce").dropna()
    if len(dates) < 2:
        return 0
    return int((dates.max() - dates.min()).days)


def _max_consecutive_gap(date_series: pd.Series) -> int:
    """연속 날짜 간 최대 갭 일수."""
    dates = pd.to_datetime(date_series.dropna(), errors="coerce").dropna().sort_values()
    if len(dates) < 2:
        return 0
    return int(dates.diff().dropna().dt.days.max())


def _run_stationarity(series: pd.Series) -> dict[str, Any]:
    """ADF + KPSS 공동검정. 둘 다 동의할 때만 확정 판정.

    판정 기준 (표준 관행):
    - adf_p < 0.05 AND kpss_p > 0.05 → "stationary"
    - adf_p >= 0.05 AND kpss_p <= 0.05 → "non_stationary"
    - adf_p < 0.05 AND kpss_p <= 0.05 → "trend_stationary" (불일치)
    - adf_p >= 0.05 AND kpss_p > 0.05 → "difference_stationary" (불일치)

    불일치 케이스는 stationary=False로 Granger gate에서 차단됩니다.
    ADF보다 KPSS를 병행함으로써 fng_value 같은 bounded persistent series의
    false positive를 줄입니다.
    """
    from statsmodels.tsa.stattools import adfuller, kpss

    s = series.dropna()
    adf_stat, adf_p, *_ = adfuller(s)
    kpss_stat, kpss_p, *_ = kpss(s, regression="c", nlags="auto")

    if adf_p < 0.05 and kpss_p > 0.05:
        conclusion = "stationary"
    elif adf_p >= 0.05 and kpss_p <= 0.05:
        conclusion = "non_stationary"
    elif adf_p < 0.05 and kpss_p <= 0.05:
        conclusion = "trend_stationary"
    else:
        conclusion = "difference_stationary"

    stationary = conclusion == "stationary"
    if not stationary:
        log_structured(
            logger,
            event="stats.stationarity_non_stationary",
            message="시계열이 정상성 조건을 만족하지 않습니다.",
            level=logging.WARNING,
            adf_pvalue=float(adf_p),
            kpss_pvalue=float(kpss_p),
            conclusion=conclusion,
        )
    return {
        "adf_statistic": float(adf_stat),
        "adf_pvalue": float(adf_p),
        "kpss_statistic": float(kpss_stat),
        "kpss_pvalue": float(kpss_p),
        "stationary": stationary,
        "conclusion": conclusion,
    }


def _ensure_stationary(
    series: pd.Series,
) -> tuple[pd.Series, bool, bool]:
    """ADF+KPSS 공동검정 후 비정상이면 첫 차분 적용.

    Returns:
        (series_to_use, is_stationary, was_differenced)
        - series_to_use: 정상화된 시계열 (또는 원본)
        - is_stationary: 최종 정상성 여부 (False면 Granger 건너뜀)
        - was_differenced: 차분 적용 여부
    """

    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < MIN_ROWS_FOR_ADF:
        # 데이터 부족 → pass-through (Granger에서 행 수 부족으로 자연스럽게 skip)
        return series, True, False

    adf_result = _run_stationarity(s)
    if adf_result["stationary"]:
        return series, True, False

    # 비정상 → 첫 차분 후 재검정
    diff_s = series.diff()
    s_diff = pd.to_numeric(diff_s, errors="coerce").dropna()
    if len(s_diff) >= MIN_ROWS_FOR_ADF:
        diff_result = _run_stationarity(s_diff)
        if diff_result["stationary"]:
            return diff_s, True, True

    return series, False, False


def _select_optimal_lag(work: pd.DataFrame, max_lag: int = 5) -> int:
    """VAR AIC 기준 최적 lag 선택. 실패 시 1 반환."""
    from statsmodels.tsa.vector_ar.var_model import VAR

    try:
        cap = max(1, min(max_lag, len(work) // 10))
        res = VAR(work.astype(float)).select_order(maxlags=cap)
        return max(int(res.aic), 1)
    except Exception:
        return 1


def _run_granger_all_lags(
    df: pd.DataFrame,
    predictor: str,
    target: str,
    max_lag: int = 3,
) -> list[dict[str, Any]] | None:
    """grangercausalitytests 단 1회 호출로 lag 1…max_lag 전체 결과 반환.

    §6·§7: F-statistic, df_num, df_denom 기록.
    §2: optimal_lag(AIC 기반), granger_primary 플래그.
    §5·§8: effective_rows, calendar_span_days, max_consecutive_gap_days.
    """
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

    # §4.1: 정상성 gate — predictor·target 모두 ADF+KPSS 통과해야 실행
    pred_series, pred_stationary, pred_differenced = _ensure_stationary(work[predictor])
    tgt_series, tgt_stationary, tgt_differenced = _ensure_stationary(work[target])

    if not pred_stationary or not tgt_stationary:
        log_structured(
            logger,
            event="stats.granger_skipped_non_stationary",
            message="비정상 시계열이 포함되어 Granger 검정을 건너뜁니다.",
            level=logging.INFO,
            predictor=predictor,
            target=target,
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
        gc_result = grangercausalitytests(work, maxlag=max_lag, verbose=False)
    except Exception as exc:
        log_structured(
            logger,
            event="stats.granger_error",
            message="Granger 검정 실행 중 오류가 발생했습니다.",
            level=logging.WARNING,
            predictor=predictor,
            target=target,
            reason=str(exc),
        )
        return None

    # §5·§8: 쌍별 유효 행 수 + 달력 gap 진단 (페어당 1회 계산)
    if "date" in df.columns:
        span_dates = df.loc[work.index, "date"]
        calendar_span = _calendar_span(span_dates)
        gap_days = _max_consecutive_gap(span_dates)
    else:
        calendar_span, gap_days = 0, 0

    # §2: AIC 기반 최적 lag
    optimal_lag = _select_optimal_lag(work, max_lag=max_lag)

    entries: list[dict[str, Any]] = []
    for lag in range(1, max_lag + 1):
        pvalue = float(gc_result[lag][0]["ssr_ftest"][1])
        entry: dict[str, Any] = {
            "predictor": predictor,
            "target": target,
            "lag": lag,
            "pvalue": pvalue,
            "pvalue_raw": pvalue,
            "significant": pvalue < 0.05,
            "f_statistic": float(gc_result[lag][0]["ssr_ftest"][0]),
            "df_num": int(gc_result[lag][0]["ssr_ftest"][2]),
            "df_denom": int(gc_result[lag][0]["ssr_ftest"][3]),
            "effective_rows": len(work),
            "calendar_span_days": calendar_span,
            "max_consecutive_gap_days": gap_days,
            "optimal_lag": optimal_lag,
            "granger_primary": lag == optimal_lag,
            "inference": "ssr_ftest_ols",
        }
        if gap_days > 1:
            entry["warning"] = "non_contiguous_dates"
        entries.append(entry)

    return entries


# _run_granger는 단일 lag 결과가 필요한 테스트 호환성을 위해 유지.
# 내부적으로 _run_granger_all_lags를 호출하고 해당 lag 항목만 반환합니다.
def _run_granger(
    df: pd.DataFrame,
    predictor: str,
    target: str,
    lag: int,
) -> dict[str, Any] | None:
    entries = _run_granger_all_lags(df, predictor, target, max_lag=lag)
    if entries is None:
        return None
    for e in entries:
        if e["lag"] == lag:
            return e
    return None


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
    bonferroni_threshold = round(0.05 / m, 10)
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
        corrected[orig_idx]["bonferroni_threshold"] = bonferroni_threshold

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

    # ── ADF+KPSS 공동 정상성 검정 (MIN_ROWS_FOR_ADF 기준) ──
    stationarity_results: dict[str, Any] = {}
    for col in ADF_TARGETS:
        if col not in df.columns or df[col].dropna().shape[0] < MIN_ROWS_FOR_ADF:
            continue
        try:
            stationarity_results[col] = _run_stationarity(df[col])
        except Exception as exc:
            log_structured(
                logger,
                event="stats.stationarity_error",
                message="정상성 검정(ADF+KPSS) 실행 중 오류가 발생했습니다.",
                level=logging.WARNING,
                column=col,
                reason=str(exc),
            )
    results["stationarity_results"] = stationarity_results

    # ── Granger 검정 (MIN_ROWS_FOR_GRANGER 기준) ──
    # §6: _run_granger_all_lags로 페어당 1회 호출 (중복 grangercausalitytests 제거)
    granger_results: list[dict[str, Any]] = []
    if len(df) >= MIN_ROWS_FOR_GRANGER:
        all_pairs = [(predictor, target, "forward") for predictor, target in GRANGER_PAIRS] + [
            (predictor, target, "reverse") for predictor, target in GRANGER_PAIRS_REVERSE
        ]
        for predictor, target, direction in all_pairs:
            entries = _run_granger_all_lags(df, predictor, target, max_lag=max(GRANGER_LAGS))
            if entries is not None:
                for entry in entries:
                    entry["direction"] = direction
                granger_results.extend(entries)

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
                    pvalue_adjusted=entry.get("pvalue_adjusted"),
                    optimal_lag=entry.get("optimal_lag"),
                    granger_primary=entry.get("granger_primary"),
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

    # §3.D ⚠️ 검정력 경고: 작은 효과는 현재 데이터 규모에서 검출이 어려울 수 있음
    if len(df) >= MIN_ROWS_FOR_GRANGER:
        n_tests = len(granger_results)
        results["power_warning"] = (
            f"n≈{len(df)}, BH-FDR, {n_tests} tests: "
            "작은 효과(f²≈0.02)의 검정력은 약 20~40% 수준. "
            "'유의하지 않음'이 효과 부재가 아닌 검정력 부족에서 기인할 수 있음. "
            "360일 이상 확보 권장."
        )

    return results


__all__ = [
    "ADF_TARGETS",
    "GRANGER_PAIRS",
    "GRANGER_PAIRS_CROSS",
    "GRANGER_PAIRS_REVERSE",
    "GRANGER_PAIRS_TARGET",
    "MIN_ROWS_FOR_ADF",
    "MIN_ROWS_FOR_GRANGER",
    "_apply_bh_correction",
    "_calendar_span",
    "_ensure_stationary",
    "_max_consecutive_gap",
    "_run_granger_all_lags",
    "_run_stationarity",
    "_select_optimal_lag",
    "run_statistical_tests",
]
