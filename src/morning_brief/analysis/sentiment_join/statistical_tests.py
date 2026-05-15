from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.bootstrap import (
    BootstrapConfig,
    benjamini_hochberg,
    bootstrap_metric,
    bootstrap_paired,
)
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MIN_ROWS_FOR_ADF = 30
MIN_ROWS_FOR_GRANGER = 180
GRANGER_LAGS = [1, 2, 3]
ANNUALIZATION_FACTOR = 365  # BTC 24/7 calendar-day candles, no weekend gap → 365 (not 252)

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
    "funding_rate_zscore_30d",
    "long_short_ratio_zscore_30d",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "etf_net_inflow_usd_log1p",  # log1p 변환 — fat-tail 안정화, 원본과 병행 검정
    "usdkrw_log_return",
    "volume_change_pct",
    # 1-A: delta 피처 — level AR 구조 제거 후 독립적 신호
    "fng_change_1d",
    "sentiment_momentum",
    # taker imbalance z-score — Binance klines index[10] 기반, 추가 API 호출 없음
    "btc_taker_imbalance_zscore_30d",
]

GRANGER_PAIRS_TARGET = [(p, _TARGET) for p in _PREDICTORS_RAW]  # 10쌍

GRANGER_PAIRS_CROSS = [
    # 정보 전파 경로 — Granger lag=k: "k일 전 predictor → 오늘 target"
    # §6: pairwise 결과는 직접 인과의 증거가 아니라 상관 구조의 지표 (omitted variable bias 주의)
    ("news_sentiment_mean", "fng_value"),
    ("fng_value", "news_sentiment_mean"),
    ("news_sentiment_mean", "funding_rate_zscore_30d"),
    ("news_sentiment_mean", "etf_net_inflow_usd"),
    ("fng_value", "long_short_ratio_zscore_30d"),
    ("fng_value", "etf_net_inflow_usd"),
    ("usdkrw_log_return", "volume_change_pct"),
    ("funding_rate_zscore_30d", "etf_net_inflow_usd"),
]  # 8쌍

GRANGER_PAIRS = GRANGER_PAIRS_TARGET + GRANGER_PAIRS_CROSS  # 18쌍 × 3 lag = 54 검정

# §4.3: 역방향 페어 — 가격이 지표를 선행하는지 확인 (단순 선행 해석 방지)
# target은 raw 컬럼 (double-lag 방지와 동일한 이유)
GRANGER_PAIRS_REVERSE = [
    ("btc_log_return", "news_sentiment_mean"),
    ("btc_log_return", "funding_rate_zscore_30d"),
    ("btc_log_return", "fng_value"),
    ("btc_log_return", "long_short_ratio_zscore_30d"),
    ("btc_log_return", "etf_net_inflow_usd"),
]  # 5쌍 × 3 lag = 15 검정

# 전체 BH-FDR family: (18 + 5) × 3 = 69 검정

ADF_TARGETS = [
    # §4: Granger에 투입되는 모든 raw 변수에 ADF+KPSS 합의 검정 적용
    "btc_log_return",
    "news_sentiment_mean",
    "fng_value",
    "funding_rate_zscore_30d",
    "long_short_ratio_zscore_30d",
    "oi_change_pct",
    "etf_net_inflow_usd",
    "etf_net_inflow_usd_log1p",
    "usdkrw_log_return",
    "volume_change_pct",
    # 1-A: delta 피처 추가
    "fng_change_1d",
    "sentiment_momentum",
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


def stationarity_check(series: pd.Series) -> dict[str, Any]:
    """Public stationarity check wrapper used by advanced feature experiments."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < MIN_ROWS_FOR_ADF:
        return {
            "stationary": False,
            "conclusion": "insufficient_rows",
            "rows": int(len(s)),
            "min_required": MIN_ROWS_FOR_ADF,
        }
    return _run_stationarity(s)


@dataclass(frozen=True)
class StationarityGateResult:
    """Detailed stationarity gate outcome for Granger skip diagnostics."""

    series: pd.Series
    stationary: bool
    differenced: bool
    rows: int
    diff_rows: int
    conclusion: str
    diff_conclusion: str | None = None


class TransferEntropy:
    """Discrete lagged-dependence estimator for non-linear signal screening."""

    def __init__(self, *, max_lag: int = 3, bins: int = 3, min_rows: int = 30) -> None:
        self.max_lag = max_lag
        self.bins = bins
        self.min_rows = min_rows

    def fit(self, df: pd.DataFrame, predictor: str, target: str) -> list[dict[str, Any]]:
        from sklearn.metrics import mutual_info_score

        if predictor not in df.columns or target not in df.columns:
            return []
        rows: list[dict[str, Any]] = []
        for lag in range(1, self.max_lag + 1):
            work = pd.DataFrame(
                {
                    "x": pd.to_numeric(df[predictor], errors="coerce").shift(lag),
                    "y": pd.to_numeric(df[target], errors="coerce"),
                }
            ).dropna()
            if len(work) < self.min_rows:
                continue
            try:
                x_bins = pd.qcut(work["x"], q=self.bins, labels=False, duplicates="drop")
                y_bins = pd.qcut(work["y"], q=self.bins, labels=False, duplicates="drop")
                valid = pd.DataFrame({"x": x_bins, "y": y_bins}).dropna()
                if len(valid) < self.min_rows:
                    continue
                score = float(mutual_info_score(valid["x"].astype(int), valid["y"].astype(int)))
            except Exception:
                continue
            rows.append(
                {
                    "predictor": predictor,
                    "target": target,
                    "lag": lag,
                    "transfer_entropy": score,
                    "rows": int(len(valid)),
                    "warning": None,
                }
            )
        return rows


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

    result = _ensure_stationary_result(series)
    return result.series, result.stationary, result.differenced


def _ensure_stationary_result(series: pd.Series) -> StationarityGateResult:
    """ADF+KPSS gate with details preserved for pair-level diagnostics."""

    numeric = pd.to_numeric(series, errors="coerce")
    s = numeric.dropna()
    if len(s) < MIN_ROWS_FOR_ADF:
        # 데이터 부족 → pass-through (Granger에서 행 수 부족으로 자연스럽게 skip)
        return StationarityGateResult(
            series=series,
            stationary=True,
            differenced=False,
            rows=int(len(s)),
            diff_rows=0,
            conclusion="insufficient_rows_for_stationarity_gate",
        )

    adf_result = _run_stationarity(s)
    if adf_result["stationary"]:
        return StationarityGateResult(
            series=series,
            stationary=True,
            differenced=False,
            rows=int(len(s)),
            diff_rows=0,
            conclusion=str(adf_result.get("conclusion", "stationary")),
        )

    # 비정상 → 첫 차분 후 재검정
    diff_s = numeric.diff()
    s_diff = diff_s.dropna()
    if len(s_diff) >= MIN_ROWS_FOR_ADF:
        diff_result = _run_stationarity(s_diff)
        if diff_result["stationary"]:
            return StationarityGateResult(
                series=diff_s,
                stationary=True,
                differenced=True,
                rows=int(len(s)),
                diff_rows=int(len(s_diff)),
                conclusion=str(adf_result.get("conclusion", "non_stationary")),
                diff_conclusion=str(diff_result.get("conclusion", "stationary")),
            )
        return StationarityGateResult(
            series=series,
            stationary=False,
            differenced=False,
            rows=int(len(s)),
            diff_rows=int(len(s_diff)),
            conclusion=str(adf_result.get("conclusion", "non_stationary")),
            diff_conclusion=str(diff_result.get("conclusion", "non_stationary")),
        )

    return StationarityGateResult(
        series=series,
        stationary=False,
        differenced=False,
        rows=int(len(s)),
        diff_rows=int(len(s_diff)),
        conclusion=str(adf_result.get("conclusion", "non_stationary")),
        diff_conclusion="insufficient_rows_after_diff",
    )


def _record_granger_skip(
    skip_collector: list[dict[str, Any]] | None,
    *,
    predictor: str,
    target: str,
    reason: str,
    **extra: Any,
) -> None:
    """Append one structured skip record per Granger pair when diagnostics are requested."""
    if skip_collector is None:
        return
    skip_collector.append(
        {
            "predictor": predictor,
            "target": target,
            "reason": reason,
            **extra,
        }
    )


def _summarize_granger_skips(skips: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("reason", "unknown")) for item in skips)
    return dict(sorted(counts.items()))


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
    *,
    skip_collector: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """grangercausalitytests 단 1회 호출로 lag 1…max_lag 전체 결과 반환.

    §6·§7: F-statistic, df_num, df_denom 기록.
    §2: optimal_lag(AIC 기반), granger_primary 플래그.
    §5·§8: effective_rows, calendar_span_days, max_consecutive_gap_days.
    """
    from statsmodels.tsa.stattools import grangercausalitytests

    if predictor not in df.columns or target not in df.columns:
        missing = [col for col in (predictor, target) if col not in df.columns]
        _record_granger_skip(
            skip_collector,
            predictor=predictor,
            target=target,
            reason="missing_column",
            missing_columns=missing,
        )
        return None

    # Int64(nullable integer) 등을 float으로 변환
    work = df[[target, predictor]].copy()
    work[predictor] = pd.to_numeric(work[predictor], errors="coerce")
    work[target] = pd.to_numeric(work[target], errors="coerce")
    work = work.dropna()

    if len(work) < MIN_ROWS_FOR_GRANGER:
        _record_granger_skip(
            skip_collector,
            predictor=predictor,
            target=target,
            reason="insufficient_pair_rows_pre_stationarity",
            rows=int(len(work)),
            min_required=MIN_ROWS_FOR_GRANGER,
        )
        return None

    # §4.1: 정상성 gate — predictor·target 모두 ADF+KPSS 통과해야 실행
    pred_gate = _ensure_stationary_result(work[predictor])
    tgt_gate = _ensure_stationary_result(work[target])

    if not pred_gate.stationary or not tgt_gate.stationary:
        log_structured(
            logger,
            event="stats.granger_skipped_non_stationary",
            message="비정상 시계열이 포함되어 Granger 검정을 건너뜁니다.",
            level=logging.INFO,
            predictor=predictor,
            target=target,
            pred_stationary=pred_gate.stationary,
            tgt_stationary=tgt_gate.stationary,
            pred_conclusion=pred_gate.conclusion,
            tgt_conclusion=tgt_gate.conclusion,
            pred_diff_conclusion=pred_gate.diff_conclusion,
            tgt_diff_conclusion=tgt_gate.diff_conclusion,
        )
        _record_granger_skip(
            skip_collector,
            predictor=predictor,
            target=target,
            reason="non_stationary_after_diff",
            rows=int(len(work)),
            pred_stationary=pred_gate.stationary,
            tgt_stationary=tgt_gate.stationary,
            pred_conclusion=pred_gate.conclusion,
            tgt_conclusion=tgt_gate.conclusion,
            pred_diff_conclusion=pred_gate.diff_conclusion,
            tgt_diff_conclusion=tgt_gate.diff_conclusion,
        )
        return None

    # 차분이 적용된 경우 정렬된 DataFrame 재구성
    if pred_gate.differenced or tgt_gate.differenced:
        work_stationary = pd.DataFrame(
            {target: tgt_gate.series, predictor: pred_gate.series}
        ).dropna()
        if len(work_stationary) < MIN_ROWS_FOR_GRANGER:
            _record_granger_skip(
                skip_collector,
                predictor=predictor,
                target=target,
                reason="insufficient_pair_rows_post_stationarity",
                rows=int(len(work_stationary)),
                min_required=MIN_ROWS_FOR_GRANGER,
                pred_differenced=pred_gate.differenced,
                tgt_differenced=tgt_gate.differenced,
            )
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
        _record_granger_skip(
            skip_collector,
            predictor=predictor,
            target=target,
            reason="granger_error",
            error=str(exc),
            rows=int(len(work)),
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
            # 정상성 처리 메타데이터: 차분 여부와 ADF+KPSS 결론 기록
            "pred_differenced": pred_gate.differenced,
            "tgt_differenced": tgt_gate.differenced,
            "pred_stationarity": pred_gate.conclusion,
            "tgt_stationarity": tgt_gate.conclusion,
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
    granger_skips: list[dict[str, Any]] = []
    if len(df) >= MIN_ROWS_FOR_GRANGER:
        all_pairs = [(predictor, target, "forward") for predictor, target in GRANGER_PAIRS] + [
            (predictor, target, "reverse") for predictor, target in GRANGER_PAIRS_REVERSE
        ]
        for predictor, target, direction in all_pairs:
            skip_start = len(granger_skips)
            entries = _run_granger_all_lags(
                df,
                predictor,
                target,
                max_lag=max(GRANGER_LAGS),
                skip_collector=granger_skips,
            )
            for skip in granger_skips[skip_start:]:
                skip["direction"] = direction
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
    results["granger_skips"] = granger_skips
    results["granger_skip_summary"] = _summarize_granger_skips(granger_skips)
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


# ---------------------------------------------------------------------------
# Hit Rate Calculator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HitRateResult:
    """단일 Predictor의 방향 적중률 및 분류 성능 결과.

    *_ci_* 필드는 block bootstrap 으로 산출된 신뢰구간. bootstrap 미실행 시 NaN.
    """

    predictor: str
    threshold: float
    hit_rate: float  # 0.0~1.0 또는 NaN
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float  # NaN if denominator == 0
    recall: float
    f1: float
    n_valid: int
    inverted: bool  # VIX 등 방향 반전 여부
    granger_significant: bool | None  # Granger 연계 플래그
    hit_rate_ci_lower: float = float("nan")
    hit_rate_ci_upper: float = float("nan")
    bootstrap_n: int = 0
    bootstrap_method: str = ""
    bootstrap_block_length: int = 0


def compute_hit_rate(
    df: pd.DataFrame,
    predictor_col: str,
    threshold: float,
    *,
    inverted: bool = False,
    granger_significant: bool | None = None,
    bootstrap: BootstrapConfig | None = None,
    threshold_fn: Callable[[pd.Series], pd.Series] | None = None,
    predictor_name: str | None = None,
) -> HitRateResult:
    """단일 Predictor의 방향 적중률 및 분류 성능을 산출한다.

    - predictor > threshold → "up" (inverted=True이면 "down")
    - threshold_fn 이 주어지면 고정 threshold 대신 per-row rolling threshold 를 사용.
    - predictor_name 이 주어지면 결과 predictor 필드를 override (variant 구분용).
    - btc_direction_label == "flat" 행 제외
    - NaN 행 제외
    - 유효 행 0건 시 모든 지표 NaN, CM 모두 0
    - bootstrap 가 주어지면 hit rate 의 CI 를 block bootstrap 으로 산출 (overlapping 보정)
    """
    import numpy as np

    result_name = predictor_name if predictor_name is not None else predictor_col
    work = df[[predictor_col, "btc_direction_label"]].copy()

    # flat 라벨 행 제외
    work = work[work["btc_direction_label"] != "flat"]

    # NaN 행 제외 (predictor 또는 label이 NaN)
    work = work.dropna(subset=[predictor_col, "btc_direction_label"])

    n_valid = len(work)

    if n_valid == 0:
        return HitRateResult(
            predictor=result_name,
            threshold=threshold,
            hit_rate=float("nan"),
            tp=0,
            fp=0,
            tn=0,
            fn=0,
            precision=float("nan"),
            recall=float("nan"),
            f1=float("nan"),
            n_valid=0,
            inverted=inverted,
            granger_significant=granger_significant,
        )

    # 예측 방향 결정
    if threshold_fn is not None:
        thr_series = threshold_fn(df[predictor_col]).reindex(work.index)
        pred_above = work[predictor_col] > thr_series
    else:
        pred_above = work[predictor_col] > threshold
    if inverted:
        predicted_up = ~pred_above  # inverted: > threshold → "down", <= threshold → "up"
    else:
        predicted_up = pred_above  # normal: > threshold → "up"

    actual_up = work["btc_direction_label"] == "up"

    tp = int((predicted_up & actual_up).sum())
    fp = int((predicted_up & ~actual_up).sum())
    tn = int((~predicted_up & ~actual_up).sum())
    fn = int((~predicted_up & actual_up).sum())

    hit_rate = (tp + tn) / n_valid

    # Precision, Recall, F1
    precision_denom = tp + fp
    precision = tp / precision_denom if precision_denom > 0 else float("nan")

    recall_denom = tp + fn
    recall = tp / recall_denom if recall_denom > 0 else float("nan")

    if not math.isnan(precision) and not math.isnan(recall):
        f1_denom = precision + recall
        f1 = 2 * precision * recall / f1_denom if f1_denom > 0 else float("nan")
    else:
        f1 = float("nan")

    ci_lower = float("nan")
    ci_upper = float("nan")
    boot_n = 0
    boot_method = ""
    boot_block_length = 0
    if bootstrap is not None and n_valid > 0:
        hits = (predicted_up == actual_up).to_numpy(dtype=float)
        boot_res = bootstrap_metric(hits, np.mean, bootstrap)
        ci_lower = boot_res.ci_lower
        ci_upper = boot_res.ci_upper
        boot_n = boot_res.n_bootstrap
        boot_method = boot_res.method
        boot_block_length = boot_res.block_length

    return HitRateResult(
        predictor=result_name,
        threshold=threshold,
        hit_rate=hit_rate,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        n_valid=n_valid,
        inverted=inverted,
        granger_significant=granger_significant,
        hit_rate_ci_lower=ci_lower,
        hit_rate_ci_upper=ci_upper,
        bootstrap_n=boot_n,
        bootstrap_method=boot_method,
        bootstrap_block_length=boot_block_length,
    )


# ---------------------------------------------------------------------------
# Correlation Calculator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorrelationResult:
    """Predictor-수익률 또는 Predictor 간 상관 분석 결과."""

    col_a: str
    col_b: str
    pearson_r: float  # NaN if insufficient data
    pearson_pvalue: float
    spearman_rho: float
    spearman_pvalue: float
    n_valid: int
    differenced: bool  # Pearson에 차분 적용 여부


def _strip_lag1_suffix(col: str) -> str:
    """lag1 Predictor 컬럼명에서 _lag1 접미사를 제거하여 raw 컬럼명을 반환한다."""
    if col.endswith("_lag1"):
        return col[: -len("_lag1")]
    return col


def _is_non_stationary(
    col: str,
    stationarity_results: dict[str, Any] | None,
) -> bool:
    """stationarity_results에서 해당 컬럼의 정상성 판정을 확인한다.

    raw 컬럼명으로 조회. conclusion이 "stationary"가 아니면 True(비정상).
    stationarity_results가 None이거나 컬럼이 없으면 False(정상 가정).
    """
    if stationarity_results is None:
        return False
    raw_col = _strip_lag1_suffix(col)
    result = stationarity_results.get(raw_col)
    if result is None:
        return False
    return result.get("conclusion") != "stationary"


def compute_correlations(
    df: pd.DataFrame,
    pairs: list[tuple[str, str]],
    stationarity_results: dict[str, Any] | None = None,
) -> list[CorrelationResult]:
    """Predictor-수익률 및 Predictor 간 상관계수를 산출한다.

    - Pearson: ADF/KPSS 비정상 시 1차 차분 적용, differenced=True 플래그
    - Spearman: 항상 원본 시계열 사용
    - 유효 행 < 2이면 모든 값 NaN
    """
    from scipy.stats import pearsonr, spearmanr

    results: list[CorrelationResult] = []

    for col_a, col_b in pairs:
        if col_a not in df.columns or col_b not in df.columns:
            results.append(
                CorrelationResult(
                    col_a=col_a,
                    col_b=col_b,
                    pearson_r=float("nan"),
                    pearson_pvalue=float("nan"),
                    spearman_rho=float("nan"),
                    spearman_pvalue=float("nan"),
                    n_valid=0,
                    differenced=False,
                )
            )
            continue

        # 원본 시계열에서 양쪽 모두 유효한 행 추출
        mask = df[col_a].notna() & df[col_b].notna()
        a_orig = df.loc[mask, col_a].astype(float)
        b_orig = df.loc[mask, col_b].astype(float)

        n_valid = len(a_orig)

        if n_valid < 2:
            results.append(
                CorrelationResult(
                    col_a=col_a,
                    col_b=col_b,
                    pearson_r=float("nan"),
                    pearson_pvalue=float("nan"),
                    spearman_rho=float("nan"),
                    spearman_pvalue=float("nan"),
                    n_valid=n_valid,
                    differenced=False,
                )
            )
            continue

        # Spearman: 항상 원본 시계열 사용
        sp_rho, sp_pvalue = spearmanr(a_orig, b_orig)

        # Pearson: 정상성 판정에 따라 차분 적용 여부 결정
        # 두 컬럼 중 하나라도 비정상이면 양쪽 모두 차분
        need_diff = _is_non_stationary(col_a, stationarity_results) or _is_non_stationary(
            col_b, stationarity_results
        )

        if need_diff:
            # 1차 차분 적용 후 NaN 제거
            a_diff = a_orig.diff().iloc[1:]
            b_diff = b_orig.diff().iloc[1:]
            # 차분 후 유효 행 재확인
            diff_mask = a_diff.notna() & b_diff.notna()
            a_pearson = a_diff[diff_mask]
            b_pearson = b_diff[diff_mask]

            if len(a_pearson) < 2:
                pr, pp = float("nan"), float("nan")
            else:
                pr, pp = pearsonr(a_pearson, b_pearson)
        else:
            pr, pp = pearsonr(a_orig, b_orig)

        results.append(
            CorrelationResult(
                col_a=col_a,
                col_b=col_b,
                pearson_r=float(pr),
                pearson_pvalue=float(pp),
                spearman_rho=float(sp_rho),
                spearman_pvalue=float(sp_pvalue),
                n_valid=n_valid,
                differenced=need_diff,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestResult:
    """단일 전략의 누적 수익 백테스트 결과."""

    predictor: str
    threshold: float
    strategy_cumulative_return: float
    bnh_cumulative_return: float
    alpha: float  # strategy - bnh
    sharpe_ratio: float  # annualized via sqrt(ANNUALIZATION_FACTOR)
    max_drawdown: float  # <= 0
    n_trades: int  # 포지션 전환 횟수
    n_valid: int
    transaction_cost_bps: float
    inverted: bool
    granger_significant: bool | None
    sharpe_ci_lower: float = float("nan")
    sharpe_ci_upper: float = float("nan")
    cumulative_return_ci_lower: float = float("nan")
    cumulative_return_ci_upper: float = float("nan")
    bootstrap_n: int = 0
    bootstrap_method: str = ""
    bootstrap_block_length: int = 0


def compute_backtest(
    df: pd.DataFrame,
    signal_col: str,
    threshold: float,
    return_col: str = "btc_log_return",
    *,
    transaction_cost_bps: float = 10.0,
    inverted: bool = False,
    granger_significant: bool | None = None,
    bootstrap: BootstrapConfig | None = None,
    threshold_fn: Callable[[pd.Series], pd.Series] | None = None,
    predictor_name: str | None = None,
) -> BacktestResult:
    """단일 전략의 누적 수익 백테스트를 수행한다.

    전략: signal > threshold → 매수(당일 수익률 적용), 이하 → 현금(0)
    inverted: signal <= threshold → 매수, > threshold → 현금
    거래 비용: 포지션 전환 시 편도 transaction_cost_bps / 10000 차감 (log return)
    threshold_fn: callable(pd.Series) → pd.Series 형태의 per-row rolling threshold.
    predictor_name: 결과 predictor 필드 override (variant 구분용).
    bootstrap 가 주어지면 strategy_returns 위에서 Sharpe / cumulative return CI 산출.
    """
    import numpy as np

    result_name = predictor_name if predictor_name is not None else signal_col
    work = df[[signal_col, return_col]].copy()
    work = work.dropna(subset=[signal_col, return_col])

    n_valid = len(work)

    if n_valid == 0:
        return BacktestResult(
            predictor=result_name,
            threshold=threshold,
            strategy_cumulative_return=float("nan"),
            bnh_cumulative_return=float("nan"),
            alpha=float("nan"),
            sharpe_ratio=float("nan"),
            max_drawdown=float("nan"),
            n_trades=0,
            n_valid=0,
            transaction_cost_bps=transaction_cost_bps,
            inverted=inverted,
            granger_significant=granger_significant,
        )

    signal = work[signal_col].to_numpy(dtype=float)
    returns = work[return_col].to_numpy(dtype=float)

    # 포지션 결정: buy (True) or cash (False)
    if threshold_fn is not None:
        thr_arr = threshold_fn(df[signal_col]).reindex(work.index).to_numpy(dtype=float)
        if inverted:
            buy = signal <= thr_arr
        else:
            buy = signal > thr_arr
    elif inverted:
        buy = signal <= threshold
    else:
        buy = signal > threshold

    # 전략 수익률: buy → btc_log_return, cash → 0
    strategy_returns = np.where(buy, returns, 0.0)

    # 포지션 전환 횟수 및 거래 비용 적용
    n_trades = 0
    if n_valid > 1:
        position_changes = buy[1:] != buy[:-1]
        n_trades = int(position_changes.sum())

        if transaction_cost_bps > 0.0 and n_trades > 0:
            cost_per_trade = math.log(1 - transaction_cost_bps / 10000)
            # 첫 번째 행에서 포지션 진입도 전환으로 간주하지 않음 (이전 포지션 없음)
            cost_array = np.where(
                np.concatenate([[False], position_changes]),
                cost_per_trade,
                0.0,
            )
            strategy_returns = strategy_returns + cost_array

    # 누적 수익률 (log return 누적합)
    strategy_cumret = float(np.sum(strategy_returns))
    bnh_cumret = float(np.sum(returns))
    alpha = strategy_cumret - bnh_cumret

    # Sharpe Ratio: mean/std × sqrt(ANNUALIZATION_FACTOR)
    std = float(np.std(strategy_returns, ddof=1)) if n_valid > 1 else 0.0
    if std == 0.0:
        sharpe_ratio = float("nan")
    else:
        sharpe_ratio = float(np.mean(strategy_returns)) / std * math.sqrt(ANNUALIZATION_FACTOR)

    # Max Drawdown: min(cumulative_curve - running_max)
    cumulative_curve = np.cumsum(strategy_returns)
    running_max = np.maximum.accumulate(cumulative_curve)
    drawdowns = cumulative_curve - running_max
    max_drawdown = float(np.min(drawdowns))

    sharpe_ci_lower = float("nan")
    sharpe_ci_upper = float("nan")
    cumret_ci_lower = float("nan")
    cumret_ci_upper = float("nan")
    boot_n = 0
    boot_method = ""
    boot_block_length = 0
    if bootstrap is not None and n_valid > 1:
        ann_factor = math.sqrt(ANNUALIZATION_FACTOR)

        def _sharpe_metric(arr: np.ndarray) -> float:
            if arr.size < 2:
                return float("nan")
            sd = float(np.std(arr, ddof=1))
            if sd <= 0.0:
                return float("nan")
            return float(np.mean(arr)) / sd * ann_factor

        sharpe_boot = bootstrap_metric(strategy_returns, _sharpe_metric, bootstrap)
        cumret_boot = bootstrap_metric(strategy_returns, np.sum, bootstrap)
        sharpe_ci_lower = sharpe_boot.ci_lower
        sharpe_ci_upper = sharpe_boot.ci_upper
        cumret_ci_lower = cumret_boot.ci_lower
        cumret_ci_upper = cumret_boot.ci_upper
        boot_n = sharpe_boot.n_bootstrap
        boot_method = sharpe_boot.method
        boot_block_length = sharpe_boot.block_length

    return BacktestResult(
        predictor=result_name,
        threshold=threshold,
        strategy_cumulative_return=strategy_cumret,
        bnh_cumulative_return=bnh_cumret,
        alpha=alpha,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        n_trades=n_trades,
        n_valid=n_valid,
        transaction_cost_bps=transaction_cost_bps,
        inverted=inverted,
        granger_significant=granger_significant,
        sharpe_ci_lower=sharpe_ci_lower,
        sharpe_ci_upper=sharpe_ci_upper,
        cumulative_return_ci_lower=cumret_ci_lower,
        cumulative_return_ci_upper=cumret_ci_upper,
        bootstrap_n=boot_n,
        bootstrap_method=boot_method,
        bootstrap_block_length=boot_block_length,
    )


# ---------------------------------------------------------------------------
# Walk-Forward Validator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardFoldResult:
    """Walk-Forward 단일 fold 결과."""

    fold: int
    test_start: str
    test_end: str
    hit_rate: float
    cumulative_return: float
    alpha: float
    train_start: str = ""
    train_end: str = ""


@dataclass(frozen=True)
class WalkForwardResult:
    """Walk-Forward Validation 전체 결과."""

    folds: list[WalkForwardFoldResult]
    avg_hit_rate: float
    avg_cumulative_return: float
    avg_alpha: float
    train_days: int
    test_days: int
    # Horizon-aware 확장 (Phase 2) — 기본값은 기존 T+1 동작
    return_col: str = "btc_log_return"
    direction_label_col: str = "btc_direction_label"
    horizon_days: int = 1
    embargo_days: int = 0
    purged_kfold: bool = False
    expanding_window: bool = False
    stability: float = float("nan")


def _fold_stability(values: list[float]) -> float:
    """1 - stdev/|mean| — fold 간 지표 안정성. 값이 2개 미만이면 NaN."""
    valid = [v for v in values if not math.isnan(v)]
    if len(valid) < 2:
        return float("nan")
    mean = sum(valid) / len(valid)
    if abs(mean) < 1e-12:
        return float("nan")
    var = sum((v - mean) ** 2 for v in valid) / (len(valid) - 1)
    std = math.sqrt(var)
    return 1.0 - std / abs(mean)


def _derive_direction_label(series: pd.Series) -> pd.Series:
    """sign(ret) → up/down/flat/None. NaN 은 None 으로 유지한다."""

    def _lbl(val: float) -> str | None:
        if pd.isna(val):
            return None
        if val > 0:
            return "up"
        if val < 0:
            return "down"
        return "flat"

    return series.apply(_lbl)


def walk_forward_validate(
    df: pd.DataFrame,
    train_days: int = 120,
    test_days: int = 30,
    index_name: str = "full",
    *,
    return_col: str = "btc_log_return",
    direction_label_col: str | None = None,
    horizon_days: int = 1,
    embargo_days: int | None = None,
    purged_kfold: bool = False,
    expanding_window: bool = False,
) -> WalkForwardResult | None:
    """Walk-Forward Validation으로 out-of-sample 성능을 평가한다.

    지정된 index_name("full" 또는 "core")의 hybrid_index_score_lag1 기준으로 각 fold에서:
    1. train 구간으로 _compute_single_index (normal mode) → scaler/PCA/min-max 추출
    2. train → test 사이에 embargo_days 만큼 gap 삽입(forward-leak 차단)
    3. test 구간에 pre-fitted mode로 _compute_single_index → test scores
    4. test 구간에서 hit rate + 누적 수익률 산출

    Horizon-aware 확장(Phase 2):
    - return_col: 백테스트에 사용할 수익률 컬럼 (기본 btc_log_return, 선택 btc_fwd_ret_Nd)
    - direction_label_col: hit-rate용 라벨 컬럼. None 이면 return_col 부호로 동적 생성.
    - horizon_days: 예측 지평. multi-horizon 또는 purged split에서
      embargo_days 가 None 이면 max(horizon_days, 5) 로 설정.

    데이터 부족(len < train_days + test_days + embargo) 시 None 반환 + WARNING 로깅.
    """
    from morning_brief.analysis.sentiment_join.hybrid_index import (
        INDEX_SPECS,
        _compute_single_index,
    )

    if embargo_days is not None:
        effective_embargo = embargo_days
    elif horizon_days > 1 or purged_kfold:
        effective_embargo = max(horizon_days, 5)
    else:
        effective_embargo = 0

    n = len(df)
    if n < train_days + test_days + effective_embargo:
        log_structured(
            logger,
            event="stats.walk_forward_insufficient_data",
            message="Walk-Forward Validation에 필요한 데이터가 부족합니다.",
            level=logging.WARNING,
            rows=n,
            min_required=train_days + test_days + effective_embargo,
            index=index_name,
            horizon_days=horizon_days,
            embargo_days=effective_embargo,
        )
        return None

    # index_name에 해당하는 spec 선택
    spec_map = {s.name: s for s in INDEX_SPECS}
    spec = spec_map.get(index_name)
    if spec is None:
        log_structured(
            logger,
            event="stats.walk_forward_invalid_index",
            message=f"유효하지 않은 index_name: {index_name}",
            level=logging.WARNING,
        )
        return None

    score_lag1_col = f"{index_name}_hybrid_index_score_lag1"

    fold_results: list[WalkForwardFoldResult] = []
    fold_num = 0
    start = 0

    while start + train_days + effective_embargo + test_days <= n:
        train_end = start + train_days
        test_start = train_end + effective_embargo
        test_end = test_start + test_days

        train_start = 0 if expanding_window else start
        train_df = df.iloc[train_start:train_end].copy()
        test_df = df.iloc[test_start:test_end].copy()

        # ── Train: normal mode → extract fitted objects ──
        _, train_score_series, train_diag = _compute_single_index(train_df, spec, len(train_df))

        pca_summary = train_diag.get("pca_summary", {})
        if pca_summary.get("status") != "ok":
            # train에서 PCA 실패 → 이 fold 건너뜀
            start += test_days
            fold_num += 1
            continue

        # diagnostics에서 fitted 객체 및 메타데이터 추출 (double-fit 제거)
        selected_features = pca_summary["selected_features"]
        pc1_min = pca_summary["pc1_min"]
        pc1_max = pca_summary["pc1_max"]
        scaler = train_diag["_fitted_scaler"]
        pca_final = train_diag["_fitted_pca"]

        # ── Test: pre-fitted mode ──
        _, test_score_series, _ = _compute_single_index(
            test_df,
            spec,
            len(test_df),
            pre_fitted_scaler=scaler,
            pre_fitted_pca=pca_final,
            pre_fitted_pc1_min=pc1_min,
            pre_fitted_pc1_max=pc1_max,
            pre_fitted_features=selected_features,
        )

        # test 구간에 score를 lag1로 사용하여 hit rate + 누적 수익률 산출
        test_eval = test_df.copy()
        test_eval[score_lag1_col] = test_score_series.shift(1)

        # hit-rate 용 direction label 결정
        if direction_label_col is not None:
            hit_label_col = direction_label_col
        elif return_col == "btc_log_return":
            hit_label_col = "btc_direction_label"
        else:
            # return_col 부호로 동적 라벨 생성 (fwd_ret_Nd 지원)
            hit_label_col = f"_derived_direction_{return_col}"
            if return_col in test_eval.columns:
                test_eval[hit_label_col] = _derive_direction_label(test_eval[return_col])

        # compute_hit_rate 는 'btc_direction_label' 컬럼 이름에 의존 → alias 주입
        if hit_label_col in test_eval.columns and score_lag1_col in test_eval.columns:
            hr_input = test_eval.copy()
            hr_input["btc_direction_label"] = hr_input[hit_label_col]
            hr_result = compute_hit_rate(hr_input, score_lag1_col, threshold=50.0)
            fold_hit_rate = hr_result.hit_rate
        else:
            fold_hit_rate = float("nan")

        # 누적 수익률 (backtest) — return_col 파라미터화
        if return_col in test_eval.columns and score_lag1_col in test_eval.columns:
            bt_result = compute_backtest(
                test_eval,
                score_lag1_col,
                threshold=50.0,
                return_col=return_col,
                transaction_cost_bps=10.0,
            )
            fold_cumret = bt_result.strategy_cumulative_return
            fold_alpha = bt_result.alpha
        else:
            fold_cumret = float("nan")
            fold_alpha = float("nan")

        # test 구간의 날짜 범위
        if "date" in test_df.columns:
            test_start_str = str(test_df["date"].iloc[0])
            test_end_str = str(test_df["date"].iloc[-1])
        else:
            test_start_str = str(test_df.index[0])
            test_end_str = str(test_df.index[-1])
        if "date" in train_df.columns:
            train_start_str = str(train_df["date"].iloc[0])
            train_end_str = str(train_df["date"].iloc[-1])
        else:
            train_start_str = str(train_df.index[0])
            train_end_str = str(train_df.index[-1])

        fold_results.append(
            WalkForwardFoldResult(
                fold=fold_num,
                test_start=test_start_str,
                test_end=test_end_str,
                hit_rate=fold_hit_rate,
                cumulative_return=fold_cumret,
                alpha=fold_alpha,
                train_start=train_start_str,
                train_end=train_end_str,
            )
        )

        start += test_days
        fold_num += 1

    if not fold_results:
        return WalkForwardResult(
            folds=[],
            avg_hit_rate=float("nan"),
            avg_cumulative_return=float("nan"),
            avg_alpha=float("nan"),
            train_days=train_days,
            test_days=test_days,
            return_col=return_col,
            direction_label_col=(
                direction_label_col if direction_label_col is not None else "btc_direction_label"
            ),
            horizon_days=horizon_days,
            embargo_days=effective_embargo,
            purged_kfold=purged_kfold,
            expanding_window=expanding_window,
            stability=float("nan"),
        )

    # 집계: NaN이 아닌 fold만 평균
    hit_rates = [f.hit_rate for f in fold_results]
    cumrets = [f.cumulative_return for f in fold_results]
    alphas = [f.alpha for f in fold_results]
    valid_hrs = [v for v in hit_rates if not math.isnan(v)]
    valid_cumrets = [v for v in cumrets if not math.isnan(v)]
    valid_alphas = [v for v in alphas if not math.isnan(v)]

    avg_hr = sum(valid_hrs) / len(valid_hrs) if valid_hrs else float("nan")
    avg_cumret = sum(valid_cumrets) / len(valid_cumrets) if valid_cumrets else float("nan")
    avg_alpha = sum(valid_alphas) / len(valid_alphas) if valid_alphas else float("nan")

    return WalkForwardResult(
        folds=fold_results,
        avg_hit_rate=avg_hr,
        avg_cumulative_return=avg_cumret,
        avg_alpha=avg_alpha,
        train_days=train_days,
        test_days=test_days,
        return_col=return_col,
        direction_label_col=(
            direction_label_col if direction_label_col is not None else "btc_direction_label"
        ),
        horizon_days=horizon_days,
        embargo_days=effective_embargo,
        purged_kfold=purged_kfold,
        expanding_window=expanding_window,
        stability=_fold_stability(hit_rates),
    )


# ---------------------------------------------------------------------------
# Granger 신뢰도 플래그 헬퍼
# ---------------------------------------------------------------------------

# Predictor lag1 → Granger raw 컬럼 매핑
_PREDICTOR_TO_GRANGER_RAW: dict[str, str | None] = {
    "news_sentiment_mean_lag1": "news_sentiment_mean",
    "fng_value_lag1": "fng_value",
    "fng_change_1d_lag1": "fng_change_1d",
    "sentiment_momentum_lag1": "sentiment_momentum",
    "sentiment_accel_lag1": None,
    "fng_change_5d_lag1": None,
    "vix_lag1": None,
    "btc_bear_regime_lag1": None,
    "sentiment_momentum_x_bear_lag1": None,
    "fng_change_1d_x_bear_lag1": None,
    "funding_rate_x_bear_lag1": None,
    "full_hybrid_index_score_lag1": None,
    "core_hybrid_index_score_lag1": None,
}


def _is_granger_significant(
    granger_results: list[dict[str, Any]],
    predictor_raw: str,
) -> bool | None:
    """Granger 결과에서 해당 predictor의 유의성을 판정한다.

    순방향(forward) 결과 중 하나라도 significant=True이면 True.
    해당 predictor의 forward 결과가 없으면 None.
    """
    forward_entries = [
        e
        for e in granger_results
        if e.get("predictor") == predictor_raw and e.get("direction") == "forward"
    ]
    if not forward_entries:
        return None
    return any(e.get("significant", False) for e in forward_entries)


# ---------------------------------------------------------------------------
# Alpha Validation 오케스트레이션
# ---------------------------------------------------------------------------

# 5개 Predictor 설정
_ALPHA_PREDICTOR_CONFIGS: list[dict[str, Any]] = [
    {"col": "news_sentiment_mean_lag1", "threshold": 0, "inverted": False},
    {"col": "fng_value_lag1", "threshold": 50, "inverted": False},
    {"col": "sentiment_momentum_lag1", "threshold": 0, "inverted": False},
    {"col": "sentiment_accel_lag1", "threshold": 0, "inverted": False},
    {"col": "fng_change_1d_lag1", "threshold": 0, "inverted": False},
    {"col": "fng_change_5d_lag1", "threshold": 0, "inverted": False},
    {"col": "btc_bear_regime_lag1", "threshold": 0.5, "inverted": True},
    {"col": "sentiment_momentum_x_bear_lag1", "threshold": 0, "inverted": False},
    {"col": "fng_change_1d_x_bear_lag1", "threshold": 0, "inverted": False},
    {"col": "funding_rate_x_bear_lag1", "threshold": 0, "inverted": False},
    {"col": "vix_lag1", "threshold": 24, "inverted": True},
    {"col": "vix_regime_score_lag1", "threshold": 0.0, "inverted": False},
    {"col": "full_hybrid_index_score_lag1", "threshold": 50, "inverted": False},
    {"col": "core_hybrid_index_score_lag1", "threshold": 50, "inverted": False},
    # Track A baseline 비교: Gauge > 60 → Long / < 40 → Short (단순 임계값 신호)
    # always_up, btc_momo_20d 대비 Track A 독립 부가가치 측정용
    {
        "col": "full_hybrid_index_score_lag1",
        "threshold": 60,
        "inverted": False,
        "predictor_name": "sovereign_gauge_60_long",
    },
    # etf_net_inflow_usd_log1p_lag1: 기관 포지셔닝 신호 (log1p 변환으로 fat-tail 안정화)
    {"col": "etf_net_inflow_usd_log1p_lag1", "threshold": 0, "inverted": False},
    # --- etf_net_inflow_usd_log1p_lag1 threshold 3-variant 재설계 ---
    # Variant A: inverted — 순유출(음수 inflow) 구간에서 매수 신호
    {
        "col": "etf_net_inflow_usd_log1p_lag1",
        "threshold": 0,
        "inverted": True,
        "predictor_name": "etf_net_inflow_usd_log1p_lag1_inverted",
    },
    # Variant B: rolling q75 — 상위 25% 대규모 순유입 구간만 신호 (high-conviction long)
    {
        "col": "etf_net_inflow_usd_log1p_lag1",
        "threshold": 0,
        "inverted": False,
        "threshold_fn": lambda s: s.rolling(90, min_periods=30).quantile(0.75),
        "predictor_name": "etf_net_inflow_usd_log1p_lag1_q75",
    },
    # Variant C: rolling q80 — 더 selective한 상위 20% 구간 필터
    {
        "col": "etf_net_inflow_usd_log1p_lag1",
        "threshold": 0,
        "inverted": False,
        "threshold_fn": lambda s: s.rolling(90, min_periods=30).quantile(0.80),
        "predictor_name": "etf_net_inflow_usd_log1p_lag1_q80",
    },
    # usdkrw_gap_flag_lag1: 공휴일·주말 갭 재개장 여부 (환율 급등락 맥락 보조 피처)
    {"col": "usdkrw_gap_flag_lag1", "threshold": 0.5, "inverted": False},
    # btc_taker_imbalance_zscore_30d_lag1: taker 매수 치우침 z-score (양수 = 매수 우세)
    {"col": "btc_taker_imbalance_zscore_30d_lag1", "threshold": 0, "inverted": False},
]

_ALPHA_HORIZONS: dict[int, str] = {
    7: "btc_fwd_ret_7d",
}

_COMPOSITE_TRAIN_DAYS = 240
_COMPOSITE_TEST_DAYS = 45
_COMPOSITE_STEP_DAYS = 30
_COMPOSITE_EMBARGO_DAYS = 7
_COMPOSITE_MIN_FEATURE_ROWS = 30
_COMPOSITE_MIN_OOS_ROWS = 250
_COMPOSITE_MIN_HIT_RATE_DELTA = 0.02
_COMPOSITE_MIN_SHARPE_DELTA = 0.10
_COMPOSITE_MIN_AUC = 0.53
_COMPOSITE_MIN_TOP_SIGN_STABILITY = 0.70

_COMPOSITE_NEW_FEATURES: tuple[str, ...] = (
    "funding_rate_zscore_30d_lag1",
    "long_short_ratio_zscore_30d_lag1",
    "binance_top10_up_ratio_7d_lag1",
    "binance_top10_ew_return_7d_lag1",
    "usdt_usdc_supply_change_7d_lag1",
    "usd_broad_index_change_7d_lag1",
    "usd_broad_index_zscore_30d_lag1",
    "us10y_change_7d_lag1",
    "nasdaq_return_7d_lag1",
)

_COMPOSITE_MACRO_LIQUIDITY_RISK_FEATURES: tuple[str, ...] = (
    "nasdaq_return_7d_lag1",
    "us10y_change_7d_lag1",
    "usd_broad_index_zscore_30d_lag1",
    "usdt_usdc_supply_change_7d_lag1",
    "btc_taker_imbalance_zscore_30d_lag1",
    "binance_top10_ew_return_7d_lag1",
    "funding_rate_zscore_30d_lag1",
    "long_short_ratio_zscore_30d_lag1",
    "vix_regime_score_lag1",
)


def _alpha_predictor_feature_columns() -> tuple[str, ...]:
    seen: list[str] = []
    for cfg in _ALPHA_PREDICTOR_CONFIGS:
        col = str(cfg["col"])
        if col not in seen:
            seen.append(col)
    return tuple(seen)


def _composite_feature_sets() -> dict[str, tuple[str, ...]]:
    old = _alpha_predictor_feature_columns()
    new = _COMPOSITE_NEW_FEATURES
    old_plus_new = tuple(dict.fromkeys((*old, *new)))
    return {
        "old_alpha_set": old,
        "new_features_only": new,
        "old_plus_new": old_plus_new,
        "macro_liquidity_risk": _COMPOSITE_MACRO_LIQUIDITY_RISK_FEATURES,
    }


_PREDICTOR_SOURCE_COLUMNS: dict[str, list[str]] = {
    "news_sentiment_mean_lag1": ["news_sentiment_mean"],
    "sentiment_momentum_lag1": ["news_sentiment_mean"],
    "sentiment_accel_lag1": ["news_sentiment_mean"],
    "sentiment_momentum_x_bear_lag1": ["news_sentiment_mean"],
    "fng_value_lag1": ["fng_value"],
    "fng_change_1d_lag1": ["fng_value"],
    "fng_change_5d_lag1": ["fng_value"],
    "fng_change_1d_x_bear_lag1": ["fng_value"],
    "funding_rate_x_bear_lag1": ["funding_rate"],
    "vix_lag1": ["vix"],
    "vix_regime_score_lag1": ["vix"],
    "etf_net_inflow_usd_log1p_lag1": ["etf_net_inflow_usd"],
    "etf_net_inflow_usd_log1p_lag1_inverted": ["etf_net_inflow_usd"],
    "etf_net_inflow_usd_log1p_lag1_q75": ["etf_net_inflow_usd"],
    "etf_net_inflow_usd_log1p_lag1_q80": ["etf_net_inflow_usd"],
    "usdkrw_gap_flag_lag1": ["usdkrw_return"],
    "btc_taker_imbalance_zscore_30d_lag1": ["btc_taker_buy_quote_volume"],
}


def _sanitize_nan(obj: Any) -> Any:
    """float NaN을 None으로 변환하여 JSON 직렬화 안전성을 확보한다.

    Python json.dumps는 NaN을 출력하지만 strict JSON 표준에서는 유효하지 않다.
    외부 시스템(Supabase, API 등) 연동 시 파싱 실패를 방지한다.
    """
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(item) for item in obj]
    return obj


def _with_direction_label_for_return(df: pd.DataFrame, return_col: str) -> pd.DataFrame:
    if return_col == "btc_log_return":
        return df
    result = df.copy()
    if return_col in result.columns:
        result["btc_direction_label"] = _derive_direction_label(result[return_col])
    return result


def _payoff_diagnostics(
    df: pd.DataFrame,
    signal_col: str,
    threshold: float,
    *,
    return_col: str,
    inverted: bool,
    transaction_cost_bps: float = 10.0,
) -> dict[str, Any]:
    work = df[[signal_col, return_col, "btc_direction_label"]].copy()
    work = work[work["btc_direction_label"] != "flat"]
    work = work.dropna(subset=[signal_col, return_col, "btc_direction_label"])
    if work.empty:
        return {
            "avg_return_when_correct": float("nan"),
            "avg_return_when_wrong": float("nan"),
            "median_return_when_correct": float("nan"),
            "median_return_when_wrong": float("nan"),
            "payoff_ratio": float("nan"),
            "correct_count": 0,
            "wrong_count": 0,
            "exposure_ratio": float("nan"),
            "turnover_ratio": float("nan"),
            "avg_strategy_return": float("nan"),
            "avg_bnh_return": float("nan"),
        }

    signal = pd.to_numeric(work[signal_col], errors="coerce").to_numpy(dtype=float)
    returns = pd.to_numeric(work[return_col], errors="coerce").to_numpy(dtype=float)
    pred_above = signal > threshold
    predicted_up = ~pred_above if inverted else pred_above
    actual_up = (work["btc_direction_label"] == "up").to_numpy(dtype=bool)
    correct_mask = predicted_up == actual_up
    wrong_mask = ~correct_mask
    buy = signal <= threshold if inverted else signal > threshold
    strategy_returns = np.where(buy, returns, 0.0)

    n_valid = len(work)
    n_trades = 0
    if n_valid > 1:
        position_changes = buy[1:] != buy[:-1]
        n_trades = int(position_changes.sum())
        if transaction_cost_bps > 0.0 and n_trades > 0:
            cost_per_trade = math.log(1 - transaction_cost_bps / 10000)
            cost_array = np.where(
                np.concatenate([[False], position_changes]),
                cost_per_trade,
                0.0,
            )
            strategy_returns = strategy_returns + cost_array

    avg_correct = (
        float(np.mean(returns[correct_mask])) if bool(correct_mask.any()) else float("nan")
    )
    avg_wrong = float(np.mean(returns[wrong_mask])) if bool(wrong_mask.any()) else float("nan")
    payoff_ratio = (
        abs(avg_correct / avg_wrong)
        if math.isfinite(avg_correct) and math.isfinite(avg_wrong) and avg_wrong != 0.0
        else float("nan")
    )

    return {
        "avg_return_when_correct": avg_correct,
        "avg_return_when_wrong": avg_wrong,
        "median_return_when_correct": (
            float(np.median(returns[correct_mask])) if bool(correct_mask.any()) else float("nan")
        ),
        "median_return_when_wrong": (
            float(np.median(returns[wrong_mask])) if bool(wrong_mask.any()) else float("nan")
        ),
        "payoff_ratio": payoff_ratio,
        "correct_count": int(correct_mask.sum()),
        "wrong_count": int(wrong_mask.sum()),
        "exposure_ratio": float(np.mean(buy)),
        "turnover_ratio": float(n_trades / max(n_valid - 1, 1)),
        "avg_strategy_return": float(np.mean(strategy_returns)),
        "avg_bnh_return": float(np.mean(returns)),
    }


def _mask_stats_for_predictor(
    predictor: str,
    outlier_mask_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(outlier_mask_summary, dict):
        return {
            "masked_ratio": float("nan"),
            "masked_cells": 0,
            "masked_denominator": 0,
            "masked_source_columns": [],
            "masked_ratio_source": "missing",
        }

    rows = int(outlier_mask_summary.get("rows") or 0)
    per_column = outlier_mask_summary.get("per_column")
    if not isinstance(per_column, dict):
        per_column = {}
    source = "source_columns"
    source_columns = _PREDICTOR_SOURCE_COLUMNS.get(predictor)
    if predictor in {"full_hybrid_index_score_lag1", "core_hybrid_index_score_lag1"}:
        hybrid_sources = outlier_mask_summary.get("hybrid_index_source_columns")
        if isinstance(hybrid_sources, dict):
            source_columns = hybrid_sources.get(predictor)
        source = "hybrid_selected_features"

    valid_columns = [
        str(col) for col in (source_columns or []) if isinstance(per_column.get(str(col)), dict)
    ]
    if valid_columns and rows > 0:
        masked_cells = sum(int(per_column[col].get("masked_cells") or 0) for col in valid_columns)
        denominator = rows * len(valid_columns)
        return {
            "masked_ratio": masked_cells / denominator if denominator > 0 else float("nan"),
            "masked_cells": int(masked_cells),
            "masked_denominator": int(denominator),
            "masked_source_columns": valid_columns,
            "masked_ratio_source": source,
        }

    global_cells = int(outlier_mask_summary.get("global_masked_cells") or 0)
    global_denominator = int(outlier_mask_summary.get("global_masked_denominator") or 0)
    global_ratio = outlier_mask_summary.get("global_masked_ratio")
    return {
        "masked_ratio": _finite(global_ratio),
        "masked_cells": global_cells,
        "masked_denominator": global_denominator,
        "masked_source_columns": [],
        "masked_ratio_source": "global",
    }


def _baseline_metrics_by_horizon(
    df: pd.DataFrame,
    *,
    bootstrap_config: BootstrapConfig | None = None,
) -> dict[str, Any]:
    from morning_brief.analysis.sentiment_join.baselines import (
        always_up,
        btc_momo_20d,
        evaluate_baseline,
        fng_contrarian,
        vol_regime,
        vol_regime_v2,
    )

    baseline_factories = {
        "always_up": always_up,
        "fng_contrarian": fng_contrarian,
        "btc_momo_20d": btc_momo_20d,
        "vol_regime": vol_regime,
        "vol_regime_v2": vol_regime_v2,
    }
    metrics: dict[str, Any] = {}
    for horizon_days, return_col in _ALPHA_HORIZONS.items():
        if return_col not in df.columns:
            continue
        horizon_key = str(horizon_days)
        metrics[horizon_key] = {}
        for name, factory in baseline_factories.items():
            signal = factory(df)
            metrics[horizon_key][name] = evaluate_baseline(
                df, signal, return_col=return_col, bootstrap=bootstrap_config
            )
    return metrics


def _signal_hits_series(
    df: pd.DataFrame,
    predictor_col: str,
    threshold: float,
    *,
    inverted: bool,
) -> pd.Series:
    """compute_hit_rate 내부 hits 산출 로직을 index 보존 형태로 재사용한다."""

    work = df[[predictor_col, "btc_direction_label"]].copy()
    work = work[work["btc_direction_label"] != "flat"]
    work = work.dropna(subset=[predictor_col, "btc_direction_label"])
    if work.empty:
        return pd.Series(dtype=float, name="signal_hit")
    pred_above = work[predictor_col] > threshold
    predicted_up = ~pred_above if inverted else pred_above
    actual_up = work["btc_direction_label"] == "up"
    return pd.Series((predicted_up == actual_up).to_numpy(dtype=float), index=work.index)


def _baseline_hits_series(
    df: pd.DataFrame,
    baseline_signal: pd.Series,
    return_col: str,
) -> pd.Series:
    """evaluate_baseline 내부 hits 산출 로직을 index 보존 형태로 재사용한다.

    btc_direction_label 이 df 에 있으면 _signal_hits_series 와 동일한
    "flat 제외" 기준으로 active row 를 결정해 paired bootstrap 정렬성을 높인다.
    없으면 signal != 0 기준으로 fallback.
    """
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(baseline_signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    active = aligned[aligned["signal"] != 0]
    if "btc_direction_label" in df.columns:
        not_flat = (df["btc_direction_label"] != "flat").reindex(active.index, fill_value=True)
        active = active[not_flat]
    if active.empty:
        return pd.Series(dtype=float, name="baseline_hit")
    hits = (np.sign(active["signal"].to_numpy()) == np.sign(active["ret"].to_numpy())).astype(float)
    return pd.Series(hits, index=active.index)


def _signal_hits_series_from_signal(
    df: pd.DataFrame,
    signal: pd.Series,
    return_col: str,
) -> pd.Series:
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    active = aligned[aligned["signal"] != 0]
    if "btc_direction_label" in df.columns:
        not_flat = (df["btc_direction_label"] != "flat").reindex(active.index, fill_value=True)
        active = active[not_flat]
    if active.empty:
        return pd.Series(dtype=float, name="signal_hit")
    hits = (np.sign(active["signal"].to_numpy()) == np.sign(active["ret"].to_numpy())).astype(float)
    return pd.Series(hits, index=active.index, name="signal_hit")


def _alignment_keys_for_rows(df: pd.DataFrame, row_index: pd.Index) -> tuple[pd.Index, str]:
    if "date" not in df.columns:
        return pd.Index(row_index), "index"

    date_values = df["date"].reindex(row_index)
    if date_values.isna().any():
        return pd.Index(row_index), "index"
    return pd.Index(date_values.to_numpy(), name="date"), "date"


def _paired_baseline_comparison(
    df: pd.DataFrame,
    signal_hits: pd.Series,
    baseline_factories: dict[str, Any],
    *,
    return_col: str,
    bootstrap_config: BootstrapConfig | None,
) -> tuple[float, dict[str, Any]]:
    signal_keys, signal_key_name = _alignment_keys_for_rows(df, signal_hits.index)
    signal_frame = pd.DataFrame(
        {
            "alignment_key": signal_keys,
            "signal": signal_hits.to_numpy(dtype=float),
        }
    )

    baseline_p_values: list[float] = []
    baseline_alignment: dict[str, Any] = {}
    for baseline_name, factory in baseline_factories.items():
        baseline_signal = factory(df)
        baseline_hits = _baseline_hits_series(df, baseline_signal, return_col)
        baseline_keys, baseline_key_name = _alignment_keys_for_rows(df, baseline_hits.index)
        baseline_frame = pd.DataFrame(
            {
                "alignment_key": baseline_keys,
                "baseline": baseline_hits.to_numpy(dtype=float),
            }
        )
        paired = signal_frame.merge(baseline_frame, on="alignment_key", how="inner").dropna()
        alignment_key = signal_key_name if signal_key_name == baseline_key_name else "index"

        signal_n = int(len(signal_hits))
        baseline_n = int(len(baseline_hits))
        paired_n = int(len(paired))
        dropped = max(signal_n, baseline_n) - paired_n
        if dropped > 0:
            log_structured(
                logger,
                event="paired_bootstrap.alignment_drop",
                message="paired bootstrap alignment: 일부 날짜가 inner join에서 제거됨",
                level=logging.DEBUG,
                baseline=baseline_name,
                signal_n=signal_n,
                baseline_n=baseline_n,
                paired_n=paired_n,
                dropped=dropped,
                alignment_key=alignment_key,
            )

        baseline_alignment[baseline_name] = {
            "alignment_key": alignment_key,
            "signal_rows": signal_n,
            "baseline_rows": baseline_n,
            "paired_rows": paired_n,
            "dropped_rows": dropped,
        }
        if bootstrap_config is None or len(paired) < 2:
            continue
        sig_arr = paired["signal"].to_numpy(dtype=float)
        base_arr = paired["baseline"].to_numpy(dtype=float)
        sig_res, _ = bootstrap_paired(sig_arr, base_arr, np.mean, bootstrap_config)
        if math.isfinite(sig_res.pvalue_one_sided):
            baseline_p_values.append(sig_res.pvalue_one_sided)

    if not baseline_p_values:
        return float("nan"), baseline_alignment
    return float(max(baseline_p_values)), baseline_alignment


def _adaptive_threshold_hit_rate(
    df: pd.DataFrame,
    predictor_col: str,
    *,
    window: int = 60,
    min_periods: int = 20,
    inverted: bool = False,
    return_col: str,
) -> dict[str, float]:
    """predictor의 rolling median을 adaptive threshold로 사용한 hit_rate / sharpe 계산.

    고정 threshold(=50 or 0)와 비교해 rolling 경계 이탈 개선 여부를 진단한다.
    결과는 기존 predictor row에 additional 필드로 병합된다 (기존 계약 변경 없음).
    """
    empty: dict[str, float] = {
        "adaptive_hit_rate": float("nan"),
        "adaptive_sharpe": float("nan"),
    }
    if predictor_col not in df.columns or return_col not in df.columns:
        return empty

    vals = pd.to_numeric(df[predictor_col], errors="coerce")
    adaptive_thresh = vals.rolling(window, min_periods=min_periods).median()
    rets = pd.to_numeric(df[return_col], errors="coerce")
    direction = (
        df["btc_direction_label"]
        if "btc_direction_label" in df.columns
        else pd.Series("", index=df.index)
    )

    valid = vals.notna() & adaptive_thresh.notna() & rets.notna() & (direction != "flat")
    if int(valid.sum()) < 10:
        return empty

    predicted_up = (vals > adaptive_thresh) if not inverted else (vals <= adaptive_thresh)
    actual_up = direction == "up"
    hit = (predicted_up == actual_up)[valid].astype(float)

    position = ((vals > adaptive_thresh).astype(float) * 2 - 1)[valid]
    if inverted:
        position = -position
    strat_ret = position * rets[valid]
    sigma = float(strat_ret.std(ddof=1)) if len(strat_ret) > 1 else 0.0
    sharpe = (
        float(strat_ret.mean()) / sigma * math.sqrt(ANNUALIZATION_FACTOR)
        if sigma > 1e-12
        else float("nan")
    )
    return {"adaptive_hit_rate": float(hit.mean()), "adaptive_sharpe": sharpe}


def _compute_regime_filtered_compound(
    df: pd.DataFrame,
    hybrid_col: str,
    *,
    neutral_score: float = 50.0,
) -> pd.Series:
    """vol_regime=-1(고변동성) 구간에서 hybrid score를 neutral_score로 강제.

    compound predictor: hybrid가 long을 원하지만 vol_regime이 risk-off이면 포지션 철수.
    vol_regime >= 0인 구간에서만 hybrid 신호를 그대로 사용한다.
    """
    from morning_brief.analysis.sentiment_join.baselines import vol_regime as _vol_regime

    regime = _vol_regime(df)
    score = pd.to_numeric(
        df.get(hybrid_col, pd.Series(dtype=float, index=df.index)), errors="coerce"
    )
    return score.where(regime >= 0, neutral_score)


def _directional_signal_from_col(
    df: pd.DataFrame,
    col: str,
    *,
    threshold: float = 0.0,
    inverted: bool = False,
) -> pd.Series:
    values = pd.to_numeric(df.get(col, pd.Series(dtype=float, index=df.index)), errors="coerce")
    signal = pd.Series(0.0, index=df.index, name=col)
    valid = values.notna()
    if inverted:
        signal.loc[valid & (values <= threshold)] = 1.0
        signal.loc[valid & (values > threshold)] = -1.0
    else:
        signal.loc[valid & (values > threshold)] = 1.0
        signal.loc[valid & (values <= threshold)] = -1.0
    return signal


def _rolling_low_high_signal_from_col(
    df: pd.DataFrame,
    col: str,
    *,
    window: int = 60,
    min_periods: int = 20,
) -> pd.Series:
    values = pd.to_numeric(df.get(col, pd.Series(dtype=float, index=df.index)), errors="coerce")
    threshold = values.rolling(window, min_periods=min_periods).median()
    threshold = threshold.fillna(values.median())
    signal = pd.Series(0.0, index=df.index, name=col)
    valid = values.notna() & threshold.notna()
    signal.loc[valid & (values <= threshold)] = 1.0
    signal.loc[valid & (values > threshold)] = -1.0
    return signal


def _ma200_trend_signal(df: pd.DataFrame) -> pd.Series:
    col = "btc_above_ma200_lag1" if "btc_above_ma200_lag1" in df.columns else "btc_above_ma200"
    values = pd.to_numeric(df.get(col, pd.Series(dtype=float, index=df.index)), errors="coerce")
    signal = pd.Series(0.0, index=df.index, name="ma200_trend")
    signal.loc[values >= 0.5] = 1.0
    signal.loc[values < 0.5] = -1.0
    return signal


def _vote_signal(
    signals: list[pd.Series],
    *,
    min_abs_vote: int,
    name: str,
) -> pd.Series:
    if not signals:
        return pd.Series(dtype=float, name=name)
    votes = pd.concat(signals, axis=1).fillna(0.0).sum(axis=1)
    signal = pd.Series(0.0, index=votes.index, name=name)
    signal.loc[votes >= min_abs_vote] = 1.0
    signal.loc[votes <= -min_abs_vote] = -1.0
    return signal


def _compute_sparse_research_signal(
    df: pd.DataFrame,
    label: str,
) -> pd.Series:
    from morning_brief.analysis.sentiment_join.baselines import (
        vol_regime as _vol_regime,
    )
    from morning_brief.analysis.sentiment_join.baselines import (
        vol_regime_v2 as _vol_regime_v2,
    )

    vol = _vol_regime(df)
    vix = _directional_signal_from_col(df, "vix_regime_score_lag1")
    sentiment = _directional_signal_from_col(df, "sentiment_momentum_lag1")
    fng5 = _directional_signal_from_col(df, "fng_change_5d_lag1")
    if label == "vix_low_long_only":
        return vix.where(vix > 0, 0.0).rename(label)
    if label == "vote_vol_sent_fng5_2of3":
        return _vote_signal([vol, sentiment, fng5], min_abs_vote=2, name=label)
    if label == "vote_vol_vix_sent_fng5_3of4":
        return _vote_signal([vol, vix, sentiment, fng5], min_abs_vote=3, name=label)
    if label == "vol_regime_v2_vix_realized_vol_2of2":
        return _vol_regime_v2(df).rename(label)
    return pd.Series(0.0, index=df.index, name=label)


def _kept_dropped_baseline_diagnostic(
    df: pd.DataFrame,
    signal: pd.Series,
    baseline_signal: pd.Series,
    return_col: str,
) -> dict[str, Any]:
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(signal, errors="coerce"),
            "baseline": pd.to_numeric(baseline_signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    active_baseline = aligned[aligned["baseline"] != 0]
    if "btc_direction_label" in df.columns:
        not_flat = (df["btc_direction_label"] != "flat").reindex(
            active_baseline.index, fill_value=True
        )
        active_baseline = active_baseline[not_flat]

    kept = active_baseline[active_baseline["signal"] != 0]
    dropped = active_baseline[active_baseline["signal"] == 0]

    def _baseline_hit_rate(frame: pd.DataFrame) -> float:
        if frame.empty:
            return float("nan")
        hits = np.sign(frame["baseline"].to_numpy(dtype=float)) == np.sign(
            frame["ret"].to_numpy(dtype=float)
        )
        return float(np.mean(hits))

    kept_hit_rate = _baseline_hit_rate(kept)
    dropped_hit_rate = _baseline_hit_rate(dropped)
    pvalue = float("nan")
    if not kept.empty and not dropped.empty:
        from scipy.stats import fisher_exact

        kept_hits = int(
            (
                np.sign(kept["baseline"].to_numpy(dtype=float))
                == np.sign(kept["ret"].to_numpy(dtype=float))
            ).sum()
        )
        dropped_hits = int(
            (
                np.sign(dropped["baseline"].to_numpy(dtype=float))
                == np.sign(dropped["ret"].to_numpy(dtype=float))
            ).sum()
        )
        _, pvalue = fisher_exact(
            [
                [kept_hits, len(kept) - kept_hits],
                [dropped_hits, len(dropped) - dropped_hits],
            ],
            alternative="greater",
        )
        pvalue = float(pvalue)

    return {
        "baseline_name": "vol_regime",
        "kept_n": int(len(kept)),
        "dropped_n": int(len(dropped)),
        "kept_baseline_hit_rate": kept_hit_rate,
        "dropped_baseline_hit_rate": dropped_hit_rate,
        "kept_baseline_hit_rate_lift": kept_hit_rate - dropped_hit_rate,
        "kept_gt_dropped_pvalue": pvalue,
    }


def _payoff_diagnostics_for_signal(
    df: pd.DataFrame,
    signal: pd.Series,
    return_col: str,
) -> dict[str, Any]:
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    active = aligned[aligned["signal"] != 0]
    if "btc_direction_label" in df.columns:
        not_flat = (df["btc_direction_label"] != "flat").reindex(active.index, fill_value=True)
        active = active[not_flat]
    if active.empty:
        return {
            "avg_return_when_correct": float("nan"),
            "avg_return_when_wrong": float("nan"),
            "median_return_when_correct": float("nan"),
            "median_return_when_wrong": float("nan"),
            "payoff_ratio": float("nan"),
            "correct_count": 0,
            "wrong_count": 0,
            "exposure_ratio": 0.0,
            "turnover_ratio": float("nan"),
            "avg_strategy_return": float("nan"),
            "avg_bnh_return": float("nan"),
        }

    signal_arr = active["signal"].to_numpy(dtype=float)
    returns = active["ret"].to_numpy(dtype=float)
    correct_mask = np.sign(signal_arr) == np.sign(returns)
    wrong_mask = ~correct_mask
    strategy_returns = signal_arr * returns
    avg_correct = (
        float(np.mean(returns[correct_mask])) if bool(correct_mask.any()) else float("nan")
    )
    avg_wrong = float(np.mean(returns[wrong_mask])) if bool(wrong_mask.any()) else float("nan")
    payoff_ratio = (
        abs(avg_correct / avg_wrong)
        if math.isfinite(avg_correct) and math.isfinite(avg_wrong) and avg_wrong != 0.0
        else float("nan")
    )
    all_pos = np.sign(aligned["signal"].fillna(0).to_numpy(dtype=float))
    turnover = float(np.mean(all_pos[1:] != all_pos[:-1])) if len(all_pos) > 1 else float("nan")
    return {
        "avg_return_when_correct": avg_correct,
        "avg_return_when_wrong": avg_wrong,
        "median_return_when_correct": (
            float(np.median(returns[correct_mask])) if bool(correct_mask.any()) else float("nan")
        ),
        "median_return_when_wrong": (
            float(np.median(returns[wrong_mask])) if bool(wrong_mask.any()) else float("nan")
        ),
        "payoff_ratio": payoff_ratio,
        "correct_count": int(correct_mask.sum()),
        "wrong_count": int(wrong_mask.sum()),
        "exposure_ratio": float(len(active) / len(aligned)) if len(aligned) else 0.0,
        "turnover_ratio": turnover,
        "avg_strategy_return": float(np.mean(strategy_returns)),
        "avg_bnh_return": float(np.mean(returns)),
    }


def _backtest_payload_for_signal(
    df: pd.DataFrame,
    signal: pd.Series,
    return_col: str,
    *,
    transaction_cost_bps: float = 10.0,
) -> dict[str, Any]:
    aligned = pd.DataFrame(
        {
            "signal": pd.to_numeric(signal, errors="coerce"),
            "ret": pd.to_numeric(df[return_col], errors="coerce"),
        }
    ).dropna()
    if aligned.empty:
        return {
            "strategy_cumulative_return": float("nan"),
            "bnh_cumulative_return": float("nan"),
            "alpha": float("nan"),
            "max_drawdown": float("nan"),
            "n_trades": 0,
        }

    pos = np.sign(aligned["signal"].fillna(0).to_numpy(dtype=float))
    returns = aligned["ret"].to_numpy(dtype=float)
    strategy_returns = pos * returns
    n_trades = 0
    if len(pos) > 1:
        position_changes = pos[1:] != pos[:-1]
        n_trades = int(position_changes.sum())
        if transaction_cost_bps > 0.0 and n_trades > 0:
            prev_pos = np.concatenate([[0.0], pos[:-1]])
            legs = np.where(prev_pos * pos < 0, 2, np.where(prev_pos != pos, 1, 0))
            strategy_returns = strategy_returns + legs * math.log(1 - transaction_cost_bps / 10000)

    strategy_cumret = float(np.sum(strategy_returns))
    bnh_cumret = float(np.sum(returns))
    cumulative_curve = np.cumsum(strategy_returns)
    running_max = np.maximum.accumulate(cumulative_curve)
    max_drawdown = float(np.min(cumulative_curve - running_max))
    return {
        "strategy_cumulative_return": strategy_cumret,
        "bnh_cumulative_return": bnh_cumret,
        "alpha": strategy_cumret - bnh_cumret,
        "max_drawdown": max_drawdown,
        "n_trades": n_trades,
    }


_COMPOUND_PREDICTOR_CONFIGS: list[dict[str, Any]] = [
    {
        "source_col": "full_hybrid_index_score_lag1",
        "tmp_col": "_vrf_full_hybrid_lag1",
        "label": "vol_regime_filtered_full_hybrid_score_lag1",
        "threshold": 50.0,
        "inverted": False,
        "group": "hybrid",
    },
]

# 가설 집합 (2026-05: BH 보정 부담 완화를 위해 효과 없는 rule 제거)
# 제거 기준: 21일 drift에서 HR delta ≤ 0 또는 coverage < 30%로 구조적 문제 확인
# 제거됨: vol_regime_v3_vix_realized_vol_ma200_2of3 (HR delta -0.1%, 검정력 5%)
# 제거됨: vote_vix_fng_2of2 (HR delta -1.5%, 검정력 2%)
_SPARSE_RESEARCH_RULE_CONFIGS: list[dict[str, Any]] = [
    {
        "label": "vix_low_long_only",
        "group": "research_sparse",
    },
    {
        "label": "vote_vol_sent_fng5_2of3",
        "group": "research_sparse",
    },
    {
        "label": "vote_vol_vix_sent_fng5_3of4",
        "group": "research_sparse",
    },
    {
        "label": "vol_regime_v2_vix_realized_vol_2of2",
        "group": "research_sparse",
    },
]


def _finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if math.isfinite(result) else float("nan")


def _best_baseline(
    baseline_metrics: dict[str, Any],
    metric: str,
) -> tuple[str | None, dict[str, Any]]:
    candidates: list[tuple[str, dict[str, Any], float]] = []
    for name, payload in baseline_metrics.items():
        if not isinstance(payload, dict):
            continue
        value = _finite(payload.get(metric))
        if math.isfinite(value):
            candidates.append((name, payload, value))
    if not candidates:
        return None, {}
    name, payload, _ = max(candidates, key=lambda item: item[2])
    return name, payload


def _temporal_fold_stability(
    df: pd.DataFrame,
    predictor_col: str,
    threshold: float,
    *,
    inverted: bool,
    n_folds: int = 5,
    min_fold_rows: int = 20,
) -> float:
    """시계열을 n_folds 구간으로 등분해 각 fold의 hit_rate 를 계산하고 stability 산출.

    walk-forward 미산출 predictor 에 대한 시간적 안정성 proxy.
    fold 수가 부족하거나 flat 행 제거 후 데이터 부족이면 NaN.
    """
    if predictor_col not in df.columns or "btc_direction_label" not in df.columns:
        return float("nan")
    work = df[[predictor_col, "btc_direction_label"]].copy()
    work = work[work["btc_direction_label"] != "flat"].dropna(subset=[predictor_col])
    if len(work) < n_folds * min_fold_rows:
        return float("nan")
    fold_size = len(work) // n_folds
    hit_rates: list[float] = []
    for i in range(n_folds):
        fold = work.iloc[i * fold_size : (i + 1) * fold_size]
        if len(fold) < min_fold_rows:
            continue
        pred_above = fold[predictor_col] > threshold
        predicted_up = ~pred_above if inverted else pred_above
        actual_up = fold["btc_direction_label"] == "up"
        hit_rates.append(float((predicted_up == actual_up).mean()))
    return _fold_stability(hit_rates)


def _walk_forward_stability(
    walk_forward_horizons: dict[str, Any],
    predictor: str,
    horizon_key: str,
) -> float:
    index_name: str | None = None
    if predictor == "full_hybrid_index_score_lag1":
        index_name = "full"
    elif predictor == "core_hybrid_index_score_lag1":
        index_name = "core"
    if index_name is None:
        return float("nan")
    index_payload = walk_forward_horizons.get(index_name)
    if not isinstance(index_payload, dict):
        return float("nan")
    horizon_payload = index_payload.get(horizon_key)
    if not isinstance(horizon_payload, dict):
        return float("nan")
    return _finite(horizon_payload.get("stability"))


def _feature_group_for_predictor(predictor: str) -> str:
    if predictor in {
        "news_sentiment_mean_lag1",
        "fng_value_lag1",
        "vix_lag1",
        "vix_regime_score_lag1",
    }:
        return "level"
    if predictor in {
        "sentiment_momentum_lag1",
        "sentiment_accel_lag1",
        "fng_change_1d_lag1",
        "fng_change_5d_lag1",
    }:
        return "stationary"
    if predictor in {
        "btc_bear_regime_lag1",
        "sentiment_momentum_x_bear_lag1",
        "fng_change_1d_x_bear_lag1",
        "funding_rate_x_bear_lag1",
    }:
        return "regime"
    if predictor in {
        "full_hybrid_index_score_lag1",
        "core_hybrid_index_score_lag1",
        "vol_regime_filtered_full_hybrid_score_lag1",
    }:
        return "hybrid"
    if predictor in {cfg["label"] for cfg in _SPARSE_RESEARCH_RULE_CONFIGS}:
        return "research_sparse"
    return "other"


def _feature_group_summary(horizon_metrics: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for horizon_key, hcell in horizon_metrics.items():
        if not isinstance(hcell, dict):
            continue
        hit_rows = [row for row in hcell.get("hit_rates", []) if isinstance(row, dict)]
        backtest_rows = {
            row.get("predictor"): row for row in hcell.get("backtest", []) if isinstance(row, dict)
        }
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in hit_rows:
            groups.setdefault(_feature_group_for_predictor(str(row.get("predictor"))), []).append(
                row
            )

        horizon_summary: dict[str, Any] = {}
        for group, rows in groups.items():
            hit_values = [_finite(row.get("hit_rate")) for row in rows]
            hit_values = [value for value in hit_values if math.isfinite(value)]
            q_values = [_finite(row.get("fdr_q")) for row in rows]
            q_values = [value for value in q_values if math.isfinite(value)]
            sharpe_values: list[float] = []
            for row in rows:
                bt = backtest_rows.get(row.get("predictor"))
                if isinstance(bt, dict):
                    sharpe = _finite(bt.get("sharpe_ratio"))
                    if math.isfinite(sharpe):
                        sharpe_values.append(sharpe)
            best_row = max(rows, key=lambda row: _finite(row.get("hit_rate")))
            payoff_rows = [
                row
                for row in rows
                if math.isfinite(_finite((row.get("payoff_diagnostics") or {}).get("payoff_ratio")))
            ]
            payoff_values = [
                _finite((row.get("payoff_diagnostics") or {}).get("payoff_ratio"))
                for row in payoff_rows
            ]
            best_payoff_row = (
                max(
                    payoff_rows,
                    key=lambda row: _finite(
                        (row.get("payoff_diagnostics") or {}).get("payoff_ratio")
                    ),
                )
                if payoff_rows
                else {}
            )
            vol_hit_lifts = [
                _finite(row.get("vol_regime_hit_rate_lift"))
                for row in rows
                if math.isfinite(_finite(row.get("vol_regime_hit_rate_lift")))
            ]
            vol_sharpe_lifts = [
                _finite(row.get("vol_regime_sharpe_lift"))
                for row in rows
                if math.isfinite(_finite(row.get("vol_regime_sharpe_lift")))
            ]
            horizon_summary[group] = {
                "predictor_count": len(rows),
                "avg_hit_rate": float(sum(hit_values) / len(hit_values))
                if hit_values
                else float("nan"),
                "best_predictor": best_row.get("predictor"),
                "best_hit_rate": best_row.get("hit_rate"),
                "avg_sharpe": (
                    float(sum(sharpe_values) / len(sharpe_values))
                    if sharpe_values
                    else float("nan")
                ),
                "min_fdr_q": min(q_values) if q_values else float("nan"),
                "decision_promote_count": sum(
                    1 for row in rows if row.get("decision") == "promote"
                ),
                "decision_strict_promote_count": sum(
                    1 for row in rows if row.get("decision_strict") == "promote"
                ),
                "avg_payoff_ratio": (
                    float(sum(payoff_values) / len(payoff_values))
                    if payoff_values
                    else float("nan")
                ),
                "best_payoff_predictor": best_payoff_row.get("predictor"),
                "avg_vol_regime_hit_rate_lift": (
                    float(sum(vol_hit_lifts) / len(vol_hit_lifts))
                    if vol_hit_lifts
                    else float("nan")
                ),
                "avg_vol_regime_sharpe_lift": (
                    float(sum(vol_sharpe_lifts) / len(vol_sharpe_lifts))
                    if vol_sharpe_lifts
                    else float("nan")
                ),
                "positive_payoff_count": sum(
                    1
                    for row in rows
                    if _finite((row.get("payoff_diagnostics") or {}).get("payoff_ratio")) > 1.0
                ),
                "candidate_count_after_quality_gate": sum(
                    1 for row in rows if _is_next_research_candidate(row)
                ),
            }
        summary[horizon_key] = horizon_summary
    return summary


def _is_next_research_candidate(row: dict[str, Any]) -> bool:
    payoff_ratio = _finite((row.get("payoff_diagnostics") or {}).get("payoff_ratio"))
    paired = row.get("paired_baseline_alignment") or {}
    vol_alignment = paired.get("vol_regime") if isinstance(paired, dict) else {}
    paired_rows = (
        int(vol_alignment.get("paired_rows") or 0) if isinstance(vol_alignment, dict) else 0
    )
    return (
        payoff_ratio > 1.0
        and _finite(row.get("vol_regime_hit_rate_lift")) > -0.05
        and _finite(row.get("masked_ratio")) <= 0.10
        and paired_rows >= 180
    )


def _next_research_candidates(horizon_metrics: dict[str, Any]) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    for horizon_key, hcell in horizon_metrics.items():
        if not isinstance(hcell, dict):
            continue
        rows = [
            row
            for row in hcell.get("hit_rates", [])
            if isinstance(row, dict) and _is_next_research_candidate(row)
        ]
        candidates[horizon_key] = [
            {
                "predictor": row.get("predictor"),
                "feature_group": _feature_group_for_predictor(str(row.get("predictor"))),
                "hit_rate": row.get("hit_rate"),
                "strategy_sharpe": row.get("strategy_sharpe"),
                "payoff_ratio": (row.get("payoff_diagnostics") or {}).get("payoff_ratio"),
                "vol_regime_hit_rate_lift": row.get("vol_regime_hit_rate_lift"),
                "vol_regime_sharpe_lift": row.get("vol_regime_sharpe_lift"),
                "masked_ratio": row.get("masked_ratio"),
                "paired_rows_vs_vol_regime": (
                    (row.get("paired_baseline_alignment") or {})
                    .get("vol_regime", {})
                    .get("paired_rows")
                ),
                "decision": row.get("decision"),
                "decision_strict": row.get("decision_strict"),
            }
            for row in sorted(
                rows,
                key=lambda row: _finite((row.get("payoff_diagnostics") or {}).get("payoff_ratio")),
                reverse=True,
            )
        ]
    return candidates


def _baseline_gap_summary(
    horizon_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for horizon_key, hcell in horizon_metrics.items():
        if not isinstance(hcell, dict):
            continue
        hit_rows = [row for row in hcell.get("hit_rates", []) if isinstance(row, dict)]
        baselines = baseline_metrics.get(horizon_key, {})
        if not hit_rows or not isinstance(baselines, dict):
            continue
        best_baseline_name, _ = _best_baseline(baselines, "hit_rate")
        vol = baselines.get("vol_regime", {}) if isinstance(baselines, dict) else {}
        vol_hit = _finite(vol.get("hit_rate")) if isinstance(vol, dict) else float("nan")
        vol_sharpe = _finite(vol.get("sharpe")) if isinstance(vol, dict) else float("nan")
        top_hit = max(hit_rows, key=lambda row: _finite(row.get("hit_rate")))
        top_sharpe = max(hit_rows, key=lambda row: _finite(row.get("strategy_sharpe")))
        summary[horizon_key] = {
            "best_baseline": best_baseline_name,
            "top_signal_by_hit_rate": {
                "predictor": top_hit.get("predictor"),
                "hit_rate": top_hit.get("hit_rate"),
            },
            "top_signal_by_sharpe": {
                "predictor": top_sharpe.get("predictor"),
                "strategy_sharpe": top_sharpe.get("strategy_sharpe"),
            },
            "vol_regime_hit_rate": vol.get("hit_rate") if isinstance(vol, dict) else float("nan"),
            "vol_regime_sharpe": vol.get("sharpe") if isinstance(vol, dict) else float("nan"),
            "top_signal_hit_rate_gap": _finite(top_hit.get("hit_rate")) - vol_hit,
            "top_signal_sharpe_gap": _finite(top_sharpe.get("strategy_sharpe")) - vol_sharpe,
            "signals_beating_vol_regime_count": sum(
                1
                for row in hit_rows
                if _finite(row.get("vol_regime_hit_rate_lift")) > 0.0
                and _finite(row.get("vol_regime_sharpe_lift")) > 0.0
            ),
            "signals_beating_vol_regime_strict_count": sum(
                1
                for row in hit_rows
                if row.get("decision_strict") == "promote"
                and _finite(row.get("vol_regime_hit_rate_lift")) > 0.0
                and _finite(row.get("vol_regime_sharpe_lift")) > 0.0
            ),
        }
    return summary


def _horizon_metrics(
    df: pd.DataFrame,
    *,
    granger_results: list[dict[str, Any]] | None,
    granger_executed: bool,
    walk_forward_horizons: dict[str, Any] | None = None,
    bootstrap_config: BootstrapConfig | None = None,
    outlier_mask_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from morning_brief.analysis.sentiment_join.baselines import (
        always_up,
        btc_momo_20d,
        evaluate_baseline,
        fng_contrarian,
        vol_regime,
        vol_regime_v2,
    )
    from morning_brief.analysis.sentiment_join.variance import evaluate_promotion_gate

    baseline_factories = {
        "always_up": always_up,
        "fng_contrarian": fng_contrarian,
        "btc_momo_20d": btc_momo_20d,
        "vol_regime": vol_regime,
        "vol_regime_v2": vol_regime_v2,
    }

    metrics: dict[str, Any] = {}
    cell_pvalues: list[tuple[str, str, float]] = []  # (horizon_key, predictor, p_value)

    for horizon_days, return_col in _ALPHA_HORIZONS.items():
        if return_col not in df.columns:
            continue
        eval_df = _with_direction_label_for_return(df, return_col)
        horizon_key = str(horizon_days)
        metrics[horizon_key] = {"return_col": return_col, "hit_rates": [], "backtest": []}
        baseline_metrics = {
            name: evaluate_baseline(
                eval_df,
                factory(eval_df),
                return_col=return_col,
                bootstrap=bootstrap_config,
            )
            for name, factory in baseline_factories.items()
        }
        best_hit_baseline_name, best_hit_baseline = _best_baseline(
            baseline_metrics,
            "hit_rate",
        )
        best_sharpe_baseline_name, best_sharpe_baseline = _best_baseline(
            baseline_metrics,
            "sharpe",
        )
        vol_regime_metrics = baseline_metrics.get("vol_regime", {})
        for cfg in _ALPHA_PREDICTOR_CONFIGS:
            col = cfg["col"]
            if col not in eval_df.columns or eval_df[col].isna().all():
                continue
            granger_raw = _PREDICTOR_TO_GRANGER_RAW.get(col)
            if not granger_executed or granger_results is None or granger_raw is None:
                granger_sig = None
            else:
                granger_sig = _is_granger_significant(granger_results, granger_raw)
            hr = compute_hit_rate(
                eval_df,
                col,
                cfg["threshold"],
                inverted=cfg["inverted"],
                granger_significant=granger_sig,
                bootstrap=bootstrap_config,
            )
            bt = compute_backtest(
                eval_df,
                col,
                cfg["threshold"],
                return_col=return_col,
                inverted=cfg["inverted"],
                granger_significant=granger_sig,
                bootstrap=bootstrap_config,
                transaction_cost_bps=10.0,
            )
            hr_dict = asdict(hr)
            bt_dict = asdict(bt)
            hr_dict["horizon_days"] = horizon_days
            hr_dict["return_col"] = return_col
            bt_dict["horizon_days"] = horizon_days
            bt_dict["return_col"] = return_col

            # Paired bootstrap p-value vs each baseline → take MAX (signal must beat ALL baselines).
            # Hit-rate metric used as the gate signal; CI hard-separation 보강 데이터.
            signal_hits = _signal_hits_series(
                eval_df, col, cfg["threshold"], inverted=cfg["inverted"]
            )
            cell_p_value, baseline_alignment = _paired_baseline_comparison(
                eval_df,
                signal_hits,
                baseline_factories,
                return_col=return_col,
                bootstrap_config=bootstrap_config,
            )
            hr_dict["pvalue_vs_baselines"] = cell_p_value
            hr_dict["fdr_q"] = float("nan")
            hr_dict["paired_baseline_alignment"] = baseline_alignment
            hit_rate_lift = _finite(hr_dict.get("hit_rate")) - _finite(
                best_hit_baseline.get("hit_rate")
            )
            sharpe_lift = _finite(bt_dict.get("sharpe_ratio")) - _finite(
                best_sharpe_baseline.get("sharpe")
            )
            vol_regime_hit_rate_lift = _finite(hr_dict.get("hit_rate")) - _finite(
                vol_regime_metrics.get("hit_rate") if isinstance(vol_regime_metrics, dict) else None
            )
            vol_regime_sharpe_lift = _finite(bt_dict.get("sharpe_ratio")) - _finite(
                vol_regime_metrics.get("sharpe") if isinstance(vol_regime_metrics, dict) else None
            )
            stability = _walk_forward_stability(
                walk_forward_horizons or {},
                col,
                horizon_key,
            )
            if not math.isfinite(stability):
                # walk-forward 미산출 predictor: 시계열 fold 분할로 proxy 산출
                stability = _temporal_fold_stability(
                    eval_df, col, cfg["threshold"], inverted=cfg["inverted"]
                )
            mask_stats = _mask_stats_for_predictor(col, outlier_mask_summary)
            payoff = _payoff_diagnostics(
                eval_df,
                col,
                cfg["threshold"],
                return_col=return_col,
                inverted=cfg["inverted"],
                transaction_cost_bps=10.0,
            )
            gate = evaluate_promotion_gate(
                hit_rate_delta=hit_rate_lift,
                sharpe_delta=sharpe_lift,
                coverage=float(hr.n_valid / len(eval_df)) if len(eval_df) else 0.0,
                masked_ratio=_finite(mask_stats.get("masked_ratio")),
                stability=stability,
                hit_rate_ci_lower=hr.hit_rate_ci_lower,
                hit_rate_ci_upper=hr.hit_rate_ci_upper,
                sharpe_ci_lower=bt.sharpe_ci_lower,
                sharpe_ci_upper=bt.sharpe_ci_upper,
                baseline_hit_rate_ci_upper=_finite(best_hit_baseline.get("hit_rate_ci_upper")),
                baseline_sharpe_ci_upper=_finite(best_sharpe_baseline.get("sharpe_ci_upper")),
            )
            hr_dict.update(
                {
                    "decision": gate.decision,
                    "decision_strict": gate.decision_strict,
                    "best_baseline": best_hit_baseline_name,
                    "best_hit_rate_baseline": best_hit_baseline_name,
                    "best_sharpe_baseline": best_sharpe_baseline_name,
                    "baseline_hit_rate": best_hit_baseline.get("hit_rate"),
                    "baseline_hit_rate_ci_upper": best_hit_baseline.get("hit_rate_ci_upper"),
                    "baseline_sharpe": best_sharpe_baseline.get("sharpe"),
                    "baseline_sharpe_ci_upper": best_sharpe_baseline.get("sharpe_ci_upper"),
                    "strategy_sharpe": bt.sharpe_ratio,
                    "sharpe_ci_lower": bt.sharpe_ci_lower,
                    "sharpe_ci_upper": bt.sharpe_ci_upper,
                    "hit_rate_lift_vs_best_baseline": hit_rate_lift,
                    "sharpe_lift_vs_best_baseline": sharpe_lift,
                    "vol_regime_hit_rate_lift": vol_regime_hit_rate_lift,
                    "vol_regime_sharpe_lift": vol_regime_sharpe_lift,
                    "payoff_diagnostics": payoff,
                    "coverage": gate.coverage,
                    "masked_ratio": gate.masked_ratio,
                    "masked_cells": mask_stats["masked_cells"],
                    "masked_denominator": mask_stats["masked_denominator"],
                    "masked_source_columns": mask_stats["masked_source_columns"],
                    "masked_ratio_source": mask_stats["masked_ratio_source"],
                    "stability": gate.stability,
                    "hit_rate_ok": gate.hit_rate_ok,
                    "sharpe_ok": gate.sharpe_ok,
                    "coverage_ok": gate.coverage_ok,
                    "masked_ratio_ok": gate.masked_ratio_ok,
                    "stability_ok": gate.stability_ok,
                    "hit_rate_ci_ok": gate.hit_rate_ci_ok,
                    "sharpe_ci_ok": gate.sharpe_ci_ok,
                    "fdr_ok": gate.fdr_ok,
                    "fdr_q": float("nan"),
                }
            )
            adaptive = _adaptive_threshold_hit_rate(
                eval_df,
                col,
                inverted=cfg.get("inverted", False),
                return_col=return_col,
            )
            hr_dict.update(adaptive)
            cell_pvalues.append((horizon_key, col, cell_p_value))

            metrics[horizon_key]["hit_rates"].append(hr_dict)
            metrics[horizon_key]["backtest"].append(bt_dict)

    # Compound signal evaluation: vol_regime-filtered hybrid predictors
    for horizon_days, return_col in _ALPHA_HORIZONS.items():
        if return_col not in df.columns:
            continue
        eval_df = _with_direction_label_for_return(df, return_col)
        horizon_key = str(horizon_days)
        if horizon_key not in metrics:
            continue
        baseline_metrics_compound = {
            name: evaluate_baseline(
                eval_df, factory(eval_df), return_col=return_col, bootstrap=bootstrap_config
            )
            for name, factory in baseline_factories.items()
        }
        best_hit_bl_name, best_hit_bl = _best_baseline(baseline_metrics_compound, "hit_rate")
        best_sh_bl_name, best_sh_bl = _best_baseline(baseline_metrics_compound, "sharpe")
        vol_regime_m = baseline_metrics_compound.get("vol_regime", {})
        for compound_cfg in _COMPOUND_PREDICTOR_CONFIGS:
            src = compound_cfg["source_col"]
            if src not in eval_df.columns or eval_df[src].isna().all():
                continue
            tmp = compound_cfg["tmp_col"]
            label = compound_cfg["label"]
            thr = compound_cfg["threshold"]
            inv = compound_cfg["inverted"]
            eval_df[tmp] = _compute_regime_filtered_compound(eval_df, src)
            hr_c = compute_hit_rate(eval_df, tmp, thr, inverted=inv, bootstrap=bootstrap_config)
            bt_c = compute_backtest(
                eval_df,
                tmp,
                thr,
                return_col=return_col,
                inverted=inv,
                bootstrap=bootstrap_config,
                transaction_cost_bps=10.0,
            )
            hr_c_dict = asdict(hr_c)
            bt_c_dict = asdict(bt_c)
            hr_c_dict["predictor"] = label
            bt_c_dict["predictor"] = label
            hr_c_dict["horizon_days"] = horizon_days
            hr_c_dict["return_col"] = return_col
            bt_c_dict["horizon_days"] = horizon_days
            bt_c_dict["return_col"] = return_col
            vr_hr_lift = _finite(hr_c_dict.get("hit_rate")) - _finite(
                vol_regime_m.get("hit_rate") if isinstance(vol_regime_m, dict) else None
            )
            vr_sh_lift = _finite(bt_c_dict.get("sharpe_ratio")) - _finite(
                vol_regime_m.get("sharpe") if isinstance(vol_regime_m, dict) else None
            )
            signal_hits_c = _signal_hits_series(eval_df, tmp, thr, inverted=inv)
            cell_p_value_c, baseline_alignment_c = _paired_baseline_comparison(
                eval_df,
                signal_hits_c,
                baseline_factories,
                return_col=return_col,
                bootstrap_config=bootstrap_config,
            )
            payoff_c = _payoff_diagnostics(eval_df, tmp, thr, return_col=return_col, inverted=inv)
            mask_c = _mask_stats_for_predictor(src, outlier_mask_summary)
            stability_c = _temporal_fold_stability(eval_df, tmp, thr, inverted=inv)
            gate_c = evaluate_promotion_gate(
                hit_rate_delta=_finite(hr_c_dict.get("hit_rate"))
                - _finite(best_hit_bl.get("hit_rate")),
                sharpe_delta=_finite(bt_c_dict.get("sharpe_ratio"))
                - _finite(best_sh_bl.get("sharpe")),
                coverage=float(hr_c.n_valid / len(eval_df)) if len(eval_df) else 0.0,
                masked_ratio=_finite(mask_c.get("masked_ratio")),
                stability=stability_c,
                hit_rate_ci_lower=hr_c.hit_rate_ci_lower,
                hit_rate_ci_upper=hr_c.hit_rate_ci_upper,
                sharpe_ci_lower=bt_c.sharpe_ci_lower,
                sharpe_ci_upper=bt_c.sharpe_ci_upper,
                baseline_hit_rate_ci_upper=_finite(best_hit_bl.get("hit_rate_ci_upper")),
                baseline_sharpe_ci_upper=_finite(best_sh_bl.get("sharpe_ci_upper")),
            )
            adaptive_c = _adaptive_threshold_hit_rate(
                eval_df, tmp, inverted=inv, return_col=return_col
            )
            hr_c_dict.update(
                {
                    "decision": gate_c.decision,
                    "decision_strict": gate_c.decision_strict,
                    "best_baseline": best_hit_bl_name,
                    "best_hit_rate_baseline": best_hit_bl_name,
                    "best_sharpe_baseline": best_sh_bl_name,
                    "baseline_hit_rate": best_hit_bl.get("hit_rate"),
                    "baseline_hit_rate_ci_upper": best_hit_bl.get("hit_rate_ci_upper"),
                    "baseline_sharpe": best_sh_bl.get("sharpe"),
                    "baseline_sharpe_ci_upper": best_sh_bl.get("sharpe_ci_upper"),
                    "strategy_sharpe": bt_c.sharpe_ratio,
                    "sharpe_ci_lower": bt_c.sharpe_ci_lower,
                    "sharpe_ci_upper": bt_c.sharpe_ci_upper,
                    "hit_rate_lift_vs_best_baseline": _finite(hr_c_dict.get("hit_rate"))
                    - _finite(best_hit_bl.get("hit_rate")),
                    "sharpe_lift_vs_best_baseline": _finite(bt_c_dict.get("sharpe_ratio"))
                    - _finite(best_sh_bl.get("sharpe")),
                    "vol_regime_hit_rate_lift": vr_hr_lift,
                    "vol_regime_sharpe_lift": vr_sh_lift,
                    "payoff_diagnostics": payoff_c,
                    "coverage": gate_c.coverage,
                    "masked_ratio": gate_c.masked_ratio,
                    "masked_cells": mask_c["masked_cells"],
                    "masked_denominator": mask_c["masked_denominator"],
                    "masked_source_columns": mask_c["masked_source_columns"],
                    "masked_ratio_source": mask_c["masked_ratio_source"],
                    "stability": gate_c.stability,
                    "hit_rate_ok": gate_c.hit_rate_ok,
                    "sharpe_ok": gate_c.sharpe_ok,
                    "coverage_ok": gate_c.coverage_ok,
                    "masked_ratio_ok": gate_c.masked_ratio_ok,
                    "stability_ok": gate_c.stability_ok,
                    "hit_rate_ci_ok": gate_c.hit_rate_ci_ok,
                    "sharpe_ci_ok": gate_c.sharpe_ci_ok,
                    "fdr_ok": gate_c.fdr_ok,
                    "pvalue_vs_baselines": cell_p_value_c,
                    "fdr_q": float("nan"),
                    "paired_baseline_alignment": baseline_alignment_c,
                    **adaptive_c,
                }
            )
            metrics[horizon_key]["hit_rates"].append(hr_c_dict)
            metrics[horizon_key]["backtest"].append(bt_c_dict)
            cell_pvalues.append((horizon_key, label, cell_p_value_c))
            eval_df.drop(columns=[tmp], inplace=True)

    # Research-only sparse rules: abstain filters around vol_regime / stationary signals.
    # These are intentionally added to artifacts for daily monitoring, not promotion.
    for horizon_days, return_col in _ALPHA_HORIZONS.items():
        if return_col not in df.columns:
            continue
        eval_df = _with_direction_label_for_return(df, return_col)
        horizon_key = str(horizon_days)
        if horizon_key not in metrics:
            continue
        baseline_metrics_sparse = {
            name: evaluate_baseline(
                eval_df, factory(eval_df), return_col=return_col, bootstrap=bootstrap_config
            )
            for name, factory in baseline_factories.items()
        }
        best_hit_sparse_name, best_hit_sparse = _best_baseline(baseline_metrics_sparse, "hit_rate")
        best_sh_sparse_name, best_sh_sparse = _best_baseline(baseline_metrics_sparse, "sharpe")
        vol_sparse = baseline_metrics_sparse.get("vol_regime", {})
        vol_signal = vol_regime(eval_df)

        for sparse_cfg in _SPARSE_RESEARCH_RULE_CONFIGS:
            label = sparse_cfg["label"]
            signal = _compute_sparse_research_signal(eval_df, label)
            signal_metrics = evaluate_baseline(
                eval_df, signal, return_col=return_col, bootstrap=bootstrap_config
            )
            signal_hits = _signal_hits_series_from_signal(eval_df, signal, return_col)
            cell_p_value_s, baseline_alignment_s = _paired_baseline_comparison(
                eval_df,
                signal_hits,
                baseline_factories,
                return_col=return_col,
                bootstrap_config=bootstrap_config,
            )

            active_frame = pd.DataFrame(
                {
                    "signal": pd.to_numeric(signal, errors="coerce"),
                    "ret": pd.to_numeric(eval_df[return_col], errors="coerce"),
                }
            ).dropna()
            active_frame = active_frame[active_frame["signal"] != 0]
            if "btc_direction_label" in eval_df.columns:
                not_flat = (eval_df["btc_direction_label"] != "flat").reindex(
                    active_frame.index, fill_value=True
                )
                active_frame = active_frame[not_flat]
            predicted_up = active_frame["signal"] > 0
            actual_up = active_frame["ret"] > 0
            tp = int((predicted_up & actual_up).sum())
            fp = int((predicted_up & ~actual_up).sum())
            tn = int((~predicted_up & ~actual_up).sum())
            fn = int((~predicted_up & actual_up).sum())
            precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
            recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
            f1 = (
                2 * precision * recall / (precision + recall)
                if math.isfinite(precision) and math.isfinite(recall) and (precision + recall) > 0
                else float("nan")
            )

            hit_lift_s = _finite(signal_metrics.get("hit_rate")) - _finite(
                best_hit_sparse.get("hit_rate")
            )
            sharpe_lift_s = _finite(signal_metrics.get("sharpe")) - _finite(
                best_sh_sparse.get("sharpe")
            )
            vol_hit_lift_s = _finite(signal_metrics.get("hit_rate")) - _finite(
                vol_sparse.get("hit_rate") if isinstance(vol_sparse, dict) else None
            )
            vol_sharpe_lift_s = _finite(signal_metrics.get("sharpe")) - _finite(
                vol_sparse.get("sharpe") if isinstance(vol_sparse, dict) else None
            )
            kept_dropped = _kept_dropped_baseline_diagnostic(
                eval_df, signal, vol_signal, return_col
            )
            payoff_s = _payoff_diagnostics_for_signal(eval_df, signal, return_col)
            backtest_s = _backtest_payload_for_signal(eval_df, signal, return_col)
            gate_s = evaluate_promotion_gate(
                hit_rate_delta=hit_lift_s,
                sharpe_delta=sharpe_lift_s,
                coverage=_finite(signal_metrics.get("coverage")),
                masked_ratio=0.0,
                stability=float("nan"),
                hit_rate_ci_lower=_finite(signal_metrics.get("hit_rate_ci_lower")),
                hit_rate_ci_upper=_finite(signal_metrics.get("hit_rate_ci_upper")),
                sharpe_ci_lower=_finite(signal_metrics.get("sharpe_ci_lower")),
                sharpe_ci_upper=_finite(signal_metrics.get("sharpe_ci_upper")),
                baseline_hit_rate_ci_upper=_finite(best_hit_sparse.get("hit_rate_ci_upper")),
                baseline_sharpe_ci_upper=_finite(best_sh_sparse.get("sharpe_ci_upper")),
            )

            hr_s_dict = {
                "predictor": label,
                "threshold": 0.0,
                "hit_rate": signal_metrics.get("hit_rate"),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "n_valid": int(len(active_frame)),
                "inverted": False,
                "granger_significant": None,
                "hit_rate_ci_lower": signal_metrics.get("hit_rate_ci_lower"),
                "hit_rate_ci_upper": signal_metrics.get("hit_rate_ci_upper"),
                "bootstrap_n": signal_metrics.get("bootstrap_n"),
                "bootstrap_method": signal_metrics.get("bootstrap_method"),
                "bootstrap_block_length": signal_metrics.get("bootstrap_block_length"),
                "horizon_days": horizon_days,
                "return_col": return_col,
                "research_rule": True,
                "research_rule_family": "sparse_abstain_filter",
                "decision": gate_s.decision,
                "decision_strict": gate_s.decision_strict,
                "best_baseline": best_hit_sparse_name,
                "best_hit_rate_baseline": best_hit_sparse_name,
                "best_sharpe_baseline": best_sh_sparse_name,
                "baseline_hit_rate": best_hit_sparse.get("hit_rate"),
                "baseline_hit_rate_ci_upper": best_hit_sparse.get("hit_rate_ci_upper"),
                "baseline_sharpe": best_sh_sparse.get("sharpe"),
                "baseline_sharpe_ci_upper": best_sh_sparse.get("sharpe_ci_upper"),
                "strategy_sharpe": signal_metrics.get("sharpe"),
                "sharpe_ci_lower": signal_metrics.get("sharpe_ci_lower"),
                "sharpe_ci_upper": signal_metrics.get("sharpe_ci_upper"),
                "hit_rate_lift_vs_best_baseline": hit_lift_s,
                "sharpe_lift_vs_best_baseline": sharpe_lift_s,
                "vol_regime_hit_rate_lift": vol_hit_lift_s,
                "vol_regime_sharpe_lift": vol_sharpe_lift_s,
                "payoff_diagnostics": payoff_s,
                "abstain_filter_diagnostics": kept_dropped,
                "kept_baseline_hit_rate": kept_dropped["kept_baseline_hit_rate"],
                "dropped_baseline_hit_rate": kept_dropped["dropped_baseline_hit_rate"],
                "kept_baseline_hit_rate_lift": kept_dropped["kept_baseline_hit_rate_lift"],
                "kept_gt_dropped_pvalue": kept_dropped["kept_gt_dropped_pvalue"],
                "kept_n": kept_dropped["kept_n"],
                "dropped_n": kept_dropped["dropped_n"],
                "coverage": gate_s.coverage,
                "masked_ratio": gate_s.masked_ratio,
                "masked_cells": 0,
                "masked_denominator": 0,
                "masked_source_columns": [],
                "masked_ratio_source": "research_rule",
                "stability": gate_s.stability,
                "hit_rate_ok": gate_s.hit_rate_ok,
                "sharpe_ok": gate_s.sharpe_ok,
                "coverage_ok": gate_s.coverage_ok,
                "masked_ratio_ok": gate_s.masked_ratio_ok,
                "stability_ok": gate_s.stability_ok,
                "hit_rate_ci_ok": gate_s.hit_rate_ci_ok,
                "sharpe_ci_ok": gate_s.sharpe_ci_ok,
                "fdr_ok": gate_s.fdr_ok,
                "pvalue_vs_baselines": cell_p_value_s,
                "fdr_q": float("nan"),
                "paired_baseline_alignment": baseline_alignment_s,
                "adaptive_hit_rate": float("nan"),
                "adaptive_sharpe": float("nan"),
            }
            bt_s_dict = {
                "predictor": label,
                "threshold": 0.0,
                "strategy_cumulative_return": backtest_s["strategy_cumulative_return"],
                "bnh_cumulative_return": backtest_s["bnh_cumulative_return"],
                "alpha": backtest_s["alpha"],
                "sharpe_ratio": signal_metrics.get("sharpe"),
                "max_drawdown": backtest_s["max_drawdown"],
                "n_trades": backtest_s["n_trades"],
                "n_valid": int(len(active_frame)),
                "transaction_cost_bps": 10.0,
                "inverted": False,
                "granger_significant": None,
                "sharpe_ci_lower": signal_metrics.get("sharpe_ci_lower"),
                "sharpe_ci_upper": signal_metrics.get("sharpe_ci_upper"),
                "cumulative_return_ci_lower": float("nan"),
                "cumulative_return_ci_upper": float("nan"),
                "bootstrap_n": signal_metrics.get("bootstrap_n"),
                "bootstrap_method": signal_metrics.get("bootstrap_method"),
                "bootstrap_block_length": signal_metrics.get("bootstrap_block_length"),
                "horizon_days": horizon_days,
                "return_col": return_col,
            }
            metrics[horizon_key]["hit_rates"].append(hr_s_dict)
            metrics[horizon_key]["backtest"].append(bt_s_dict)
            cell_pvalues.append((horizon_key, label, cell_p_value_s))

    # BH-FDR across (predictor × horizon) family
    if cell_pvalues:
        p_array = np.array([p for _, _, p in cell_pvalues], dtype=float)
        q_array = benjamini_hochberg(p_array)
        q_lookup = {(h, c): float(q) for (h, c, _), q in zip(cell_pvalues, q_array)}
        for horizon_key, hcell in metrics.items():
            for hr_dict in hcell["hit_rates"]:
                key = (horizon_key, hr_dict["predictor"])
                hr_dict["fdr_q"] = q_lookup.get(key, float("nan"))
                gate = evaluate_promotion_gate(
                    hit_rate_delta=_finite(hr_dict.get("hit_rate_lift_vs_best_baseline")),
                    sharpe_delta=_finite(hr_dict.get("sharpe_lift_vs_best_baseline")),
                    coverage=_finite(hr_dict.get("coverage")),
                    masked_ratio=_finite(hr_dict.get("masked_ratio")),
                    stability=_finite(hr_dict.get("stability")),
                    hit_rate_ci_lower=_finite(hr_dict.get("hit_rate_ci_lower")),
                    hit_rate_ci_upper=_finite(hr_dict.get("hit_rate_ci_upper")),
                    sharpe_ci_lower=_finite(hr_dict.get("sharpe_ci_lower")),
                    sharpe_ci_upper=_finite(hr_dict.get("sharpe_ci_upper")),
                    baseline_hit_rate_ci_upper=_finite(hr_dict.get("baseline_hit_rate_ci_upper")),
                    baseline_sharpe_ci_upper=_finite(hr_dict.get("baseline_sharpe_ci_upper")),
                    fdr_q=_finite(hr_dict.get("fdr_q")),
                )
                hr_dict.update(
                    {
                        "decision": gate.decision,
                        "decision_strict": gate.decision_strict,
                        "fdr_ok": gate.fdr_ok,
                        "hit_rate_ci_ok": gate.hit_rate_ci_ok,
                        "sharpe_ci_ok": gate.sharpe_ci_ok,
                        "stability_ok": gate.stability_ok,
                    }
                )
    return metrics


def _composite_folds(
    n_rows: int,
    *,
    train_days: int = _COMPOSITE_TRAIN_DAYS,
    test_days: int = _COMPOSITE_TEST_DAYS,
    step_days: int = _COMPOSITE_STEP_DAYS,
    embargo_days: int = _COMPOSITE_EMBARGO_DAYS,
) -> list[tuple[np.ndarray, np.ndarray]]:
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    start = train_days + embargo_days
    while start + test_days <= n_rows:
        train_end = start - embargo_days
        train_idx = np.arange(train_end - train_days, train_end)
        test_idx = np.arange(start, start + test_days)
        folds.append((train_idx, test_idx))
        start += step_days
    return folds


def _safe_balanced_accuracy(actual: pd.Series, predicted: np.ndarray) -> float:
    try:
        from sklearn.metrics import balanced_accuracy_score

        return float(balanced_accuracy_score(actual.astype(bool), predicted))
    except Exception:
        return float("nan")


def _safe_auc(actual: pd.Series, proba: np.ndarray) -> float:
    try:
        if actual.nunique(dropna=True) < 2:
            return float("nan")
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(actual.astype(bool), proba))
    except Exception:
        return float("nan")


def _strategy_sharpe(values: np.ndarray, *, horizon_days: int) -> float:
    if values.size < 2:
        return float("nan")
    sigma = float(np.std(values, ddof=1))
    if sigma <= 1e-12:
        return float("nan")
    return float(np.mean(values)) / sigma * math.sqrt(ANNUALIZATION_FACTOR / horizon_days)


def _format_date_value(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return str(value)


def _weight_summary(coef_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not coef_rows:
        return []
    weights = pd.DataFrame(coef_rows)
    rows: list[dict[str, Any]] = []
    for feature, group in weights.groupby("feature"):
        coef = pd.to_numeric(group["coef"], errors="coerce").dropna()
        if coef.empty:
            continue
        mean_coef = float(coef.mean())
        sign = math.copysign(1.0, mean_coef) if mean_coef != 0 else 0.0
        if sign == 0.0:
            sign_stability = 0.0
        else:
            sign_stability = float((np.sign(coef.to_numpy()) == sign).mean())
        rows.append(
            {
                "feature": str(feature),
                "mean_coef": mean_coef,
                "abs_mean_coef": float(coef.abs().mean()),
                "sign_stability": sign_stability,
                "fold_count": int(len(coef)),
            }
        )
    return sorted(rows, key=lambda item: float(item["abs_mean_coef"]), reverse=True)


def _promotion_candidate_payload(
    row: dict[str, Any],
    *,
    old_alpha_row: dict[str, Any] | None,
) -> dict[str, Any]:
    old_hit = _finite(old_alpha_row.get("hit_rate") if old_alpha_row else None)
    old_sharpe = _finite(old_alpha_row.get("strategy_sharpe") if old_alpha_row else None)
    hit_delta = _finite(row.get("hit_rate")) - old_hit
    sharpe_delta = _finite(row.get("strategy_sharpe")) - old_sharpe
    raw_weights = row.get("weights")
    weights: list[Any] = raw_weights if isinstance(raw_weights, list) else []
    top_weights = weights[:3]
    top_stabilities = [
        _finite(item.get("sign_stability"))
        for item in top_weights
        if isinstance(item, dict) and math.isfinite(_finite(item.get("sign_stability")))
    ]
    top_sign_stability = float(np.mean(top_stabilities)) if top_stabilities else float("nan")
    checks = {
        "hit_rate_delta_ok": hit_delta >= _COMPOSITE_MIN_HIT_RATE_DELTA,
        "sharpe_delta_ok": sharpe_delta >= _COMPOSITE_MIN_SHARPE_DELTA,
        "auc_ok": _finite(row.get("auc")) >= _COMPOSITE_MIN_AUC,
        "top_sign_stability_ok": top_sign_stability >= _COMPOSITE_MIN_TOP_SIGN_STABILITY,
        "n_oos_ok": int(row.get("n_oos") or 0) >= _COMPOSITE_MIN_OOS_ROWS,
    }
    return {
        "hit_rate_delta_vs_old_alpha": hit_delta,
        "sharpe_delta_vs_old_alpha": sharpe_delta,
        "top_sign_stability": top_sign_stability,
        "promotion_candidate": all(checks.values()),
        "promotion_checks": checks,
    }


def _composite_score_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Research-only composite score walk-forward metrics.

    모든 fit/impute/scale은 fold의 train 구간에서만 수행한다. 반환 결과는 metadata와
    latest.json 진단용이며 production signal 승격은 별도 drift gate에서만 다룬다.
    """
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    metrics: dict[str, Any] = {}
    feature_sets = _composite_feature_sets()
    for horizon_days, return_col in _ALPHA_HORIZONS.items():
        horizon_key = str(horizon_days)
        if return_col not in df.columns:
            metrics[horizon_key] = []
            continue
        target_ret = pd.to_numeric(df[return_col], errors="coerce")
        target_up = target_ret > 0
        valid_target = target_ret.notna()
        rows: list[dict[str, Any]] = []
        folds = _composite_folds(len(df), embargo_days=horizon_days)
        for set_name, configured_features in feature_sets.items():
            available_features = [
                col
                for col in configured_features
                if col in df.columns and col.endswith("_lag1") and not df[col].isna().all()
            ]
            pred_rows: list[dict[str, Any]] = []
            coef_rows: list[dict[str, Any]] = []
            fold_payloads: list[dict[str, Any]] = []
            for fold_id, (train_idx, test_idx) in enumerate(folds):
                train_idx = train_idx[valid_target.iloc[train_idx].to_numpy()]
                test_idx = test_idx[valid_target.iloc[test_idx].to_numpy()]
                if len(train_idx) < 80 or len(test_idx) < 10:
                    continue
                X_train_all = df.loc[train_idx, available_features].apply(
                    pd.to_numeric, errors="coerce"
                )
                X_test_all = df.loc[test_idx, available_features].apply(
                    pd.to_numeric, errors="coerce"
                )
                usable_features = [
                    col
                    for col in available_features
                    if X_train_all[col].notna().sum() >= _COMPOSITE_MIN_FEATURE_ROWS
                    and X_test_all[col].notna().any()
                ]
                if not usable_features:
                    continue
                X_train = X_train_all[usable_features]
                X_test = X_test_all[usable_features]
                y_train = target_up.iloc[train_idx].astype(int)
                y_test = target_up.iloc[test_idx].astype(bool)
                model = make_pipeline(
                    SimpleImputer(strategy="median"),
                    StandardScaler(),
                    LogisticRegression(
                        C=0.3,
                        solver="liblinear",
                        class_weight="balanced",
                        random_state=0,
                    ),
                )
                model.fit(X_train, y_train)
                proba = model.predict_proba(X_test)[:, 1]
                predicted = proba >= 0.5
                fold_ret = target_ret.iloc[test_idx].to_numpy(dtype=float)
                fold_strategy_ret = np.where(predicted, 1.0, -1.0) * fold_ret
                for idx, p, pred in zip(test_idx, proba, predicted):
                    pred_rows.append(
                        {
                            "idx": int(idx),
                            "proba": float(p),
                            "predicted": bool(pred),
                            "actual": bool(target_up.iloc[idx]),
                            "return": float(target_ret.iloc[idx]),
                            "fold": fold_id,
                        }
                    )
                estimator = model.steps[-1][1]
                for feature, coef in zip(usable_features, estimator.coef_.ravel()):
                    coef_rows.append({"fold": fold_id, "feature": feature, "coef": float(coef)})
                fold_payloads.append(
                    {
                        "fold": fold_id,
                        "train_start": _format_date_value(df.loc[int(train_idx[0]), "date"]),
                        "train_end": _format_date_value(df.loc[int(train_idx[-1]), "date"]),
                        "test_start": _format_date_value(df.loc[int(test_idx[0]), "date"]),
                        "test_end": _format_date_value(df.loc[int(test_idx[-1]), "date"]),
                        "n_test": int(len(test_idx)),
                        "feature_count": int(len(usable_features)),
                        "hit_rate": float((predicted == y_test.to_numpy()).mean()),
                        "auc": _safe_auc(y_test, proba),
                        "strategy_sharpe": _strategy_sharpe(
                            fold_strategy_ret, horizon_days=horizon_days
                        ),
                        "long_ratio": float(predicted.mean()),
                    }
                )

            predictions = pd.DataFrame(pred_rows)
            if predictions.empty:
                row = {
                    "name": set_name,
                    "feature_count": len(available_features),
                    "features": available_features,
                    "n_oos": 0,
                    "hit_rate": float("nan"),
                    "balanced_accuracy": float("nan"),
                    "auc": float("nan"),
                    "strategy_sharpe": float("nan"),
                    "long_ratio": float("nan"),
                    "avg_strategy_return": float("nan"),
                    "folds": [],
                    "weights": [],
                    "unstable_weight_features": [],
                    "decision": "research_only",
                }
                rows.append(row)
                continue

            predictions = predictions.drop_duplicates("idx")
            actual = predictions["actual"].astype(bool)
            predicted = predictions["predicted"].astype(bool).to_numpy()
            strategy_ret = np.where(predicted, 1.0, -1.0) * predictions["return"].to_numpy(
                dtype=float
            )
            weights = _weight_summary(coef_rows)
            row = {
                "name": set_name,
                "feature_count": len(available_features),
                "features": available_features,
                "n_oos": int(len(predictions)),
                "hit_rate": float((predicted == actual.to_numpy()).mean()),
                "balanced_accuracy": _safe_balanced_accuracy(actual, predicted),
                "auc": _safe_auc(actual, predictions["proba"].to_numpy(dtype=float)),
                "strategy_sharpe": _strategy_sharpe(strategy_ret, horizon_days=horizon_days),
                "long_ratio": float(predicted.mean()),
                "avg_strategy_return": float(np.mean(strategy_ret)),
                "folds": fold_payloads,
                "weights": weights,
                "unstable_weight_features": [
                    str(item["feature"])
                    for item in weights
                    if _finite(item.get("sign_stability")) < 0.70
                ],
                "decision": "research_only",
            }
            rows.append(row)

        old_alpha_row = next((row for row in rows if row.get("name") == "old_alpha_set"), None)
        for row in rows:
            row.update(_promotion_candidate_payload(row, old_alpha_row=old_alpha_row))
        metrics[horizon_key] = rows
    return _sanitize_nan(metrics)


def _walk_forward_horizons(df: pd.DataFrame) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for idx_name in ("full", "core"):
        results[idx_name] = {}
        for horizon_days, return_col in _ALPHA_HORIZONS.items():
            wf = walk_forward_validate(
                df,
                index_name=idx_name,
                return_col=return_col,
                horizon_days=horizon_days,
            )
            if wf is not None:
                results[idx_name][str(horizon_days)] = asdict(wf)
    return results


def run_alpha_validation(
    df: pd.DataFrame,
    stationarity_results: dict[str, Any] | None = None,
    granger_results: list[dict[str, Any]] | None = None,
    granger_executed: bool = False,
    *,
    bootstrap_config: BootstrapConfig | None = None,
    outlier_mask_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Alpha Validation을 실행한다.

    pipeline.py에서 compute_hybrid_indices 완료 후, lag1 컬럼 생성 후에 호출.
    stationarity_results와 granger_results는 run_statistical_tests의 반환값에서 추출.
    bootstrap_config 가 None 이면 기본값 (circular block, L=14, n=1000) 사용.
    horizon_metrics / baseline_metrics 모두 동일 config 로 비교 가능한 CI 산출.

    Returns:
        {"hit_rates": [...], "correlations": [...], "backtest": [...], "walk_forward": {...},
         "baseline_metrics": {...}, "horizon_metrics": {...}, "walk_forward_horizons": {...}}
    """
    if bootstrap_config is None:
        bootstrap_config = BootstrapConfig()

    hit_rates: list[dict[str, Any]] = []
    backtest_results: list[dict[str, Any]] = []

    for cfg in _ALPHA_PREDICTOR_CONFIGS:
        col = cfg["col"]
        threshold = cfg["threshold"]
        inverted = cfg["inverted"]
        threshold_fn = cfg.get("threshold_fn")
        predictor_name: str | None = cfg.get("predictor_name")

        # VIX 전 행 NaN → skip
        if col not in df.columns or df[col].isna().all():
            continue

        # Granger 신뢰도 플래그 결정 (variant들은 원본 col 기반)
        granger_raw = _PREDICTOR_TO_GRANGER_RAW.get(col)
        if not granger_executed or granger_results is None or granger_raw is None:
            granger_sig = None
        else:
            granger_sig = _is_granger_significant(granger_results, granger_raw)

        # Hit Rate
        hr = compute_hit_rate(
            df,
            col,
            threshold,
            inverted=inverted,
            granger_significant=granger_sig,
            bootstrap=bootstrap_config,
            threshold_fn=threshold_fn,
            predictor_name=predictor_name,
        )
        hit_rates.append(asdict(hr))

        # Backtest
        bt = compute_backtest(
            df,
            col,
            threshold,
            inverted=inverted,
            granger_significant=granger_sig,
            bootstrap=bootstrap_config,
            transaction_cost_bps=10.0,
            threshold_fn=threshold_fn,
            predictor_name=predictor_name,
        )
        backtest_results.append(asdict(bt))

    # Correlations: predictor vs btc_log_return + predictor 간 상관 (Req 3.4, 3.5)
    available_predictors: list[str] = []
    for cfg in _ALPHA_PREDICTOR_CONFIGS:
        col = cfg["col"]
        if col not in df.columns or df[col].isna().all():
            continue
        available_predictors.append(col)

    corr_pairs: list[tuple[str, str]] = []
    # (1) predictor vs btc_log_return
    for col in available_predictors:
        corr_pairs.append((col, "btc_log_return"))
    # (2) predictor 간 상관 — 다중공선성 평가용 (Req 3.5)
    for i, col_a in enumerate(available_predictors):
        for col_b in available_predictors[i + 1 :]:
            corr_pairs.append((col_a, col_b))

    corr_results = compute_correlations(df, corr_pairs, stationarity_results)
    correlations = [asdict(c) for c in corr_results]

    # Walk-Forward: full + core 양쪽 실행
    walk_forward: dict[str, Any] = {}
    for idx_name in ("full", "core"):
        wf = walk_forward_validate(df, index_name=idx_name)
        if wf is not None:
            walk_forward[idx_name] = asdict(wf)

    walk_forward_horizons = _walk_forward_horizons(df)
    primary_horizon_key = str(max(_ALPHA_HORIZONS.keys()))
    primary_walk_forward = {
        idx_name: horizon_payload[primary_horizon_key]
        for idx_name, horizon_payload in walk_forward_horizons.items()
        if isinstance(horizon_payload, dict) and primary_horizon_key in horizon_payload
    }
    horizon_metrics = _horizon_metrics(
        df,
        granger_results=granger_results,
        granger_executed=granger_executed,
        walk_forward_horizons=walk_forward_horizons,
        bootstrap_config=bootstrap_config,
        outlier_mask_summary=outlier_mask_summary,
    )
    composite_metrics = _composite_score_metrics(df)
    for horizon_key, rows in composite_metrics.items():
        if horizon_key in horizon_metrics and isinstance(horizon_metrics[horizon_key], dict):
            horizon_metrics[horizon_key]["composite_scores"] = rows
    baseline_metrics = _baseline_metrics_by_horizon(df, bootstrap_config=bootstrap_config)
    feature_group_summary = _feature_group_summary(horizon_metrics)
    baseline_gap_summary = _baseline_gap_summary(horizon_metrics, baseline_metrics)
    next_research_candidates = _next_research_candidates(horizon_metrics)

    return _sanitize_nan(
        {
            "hit_rates": hit_rates,
            "correlations": correlations,
            "backtest": backtest_results,
            "walk_forward": primary_walk_forward,
            "walk_forward_legacy_1d": walk_forward,
            "baseline_metrics": baseline_metrics,
            "horizon_metrics": horizon_metrics,
            "walk_forward_horizons": walk_forward_horizons,
            "feature_group_summary": feature_group_summary,
            "baseline_gap_summary": baseline_gap_summary,
            "next_research_candidates": next_research_candidates,
            "composite_metrics": composite_metrics,
            "outlier_mask_summary": outlier_mask_summary or {},
            "bootstrap_config": {
                "n_bootstrap": bootstrap_config.n_bootstrap,
                "block_length": bootstrap_config.block_length,
                "method": bootstrap_config.method,
                "seed": bootstrap_config.seed,
                "ci_alpha": bootstrap_config.ci_alpha,
            },
        }
    )


__all__ = [
    "ADF_TARGETS",
    "BacktestResult",
    "CorrelationResult",
    "GRANGER_PAIRS",
    "GRANGER_PAIRS_CROSS",
    "GRANGER_PAIRS_REVERSE",
    "GRANGER_PAIRS_TARGET",
    "HitRateResult",
    "MIN_ROWS_FOR_ADF",
    "MIN_ROWS_FOR_GRANGER",
    "StationarityGateResult",
    "TransferEntropy",
    "WalkForwardFoldResult",
    "WalkForwardResult",
    "_ALPHA_HORIZONS",
    "_ALPHA_PREDICTOR_CONFIGS",
    "_PREDICTOR_TO_GRANGER_RAW",
    "_apply_bh_correction",
    "_calendar_span",
    "_ensure_stationary",
    "_ensure_stationary_result",
    "_is_granger_significant",
    "_max_consecutive_gap",
    "_run_granger_all_lags",
    "_run_stationarity",
    "_sanitize_nan",
    "_select_optimal_lag",
    "compute_backtest",
    "compute_correlations",
    "compute_hit_rate",
    "run_alpha_validation",
    "run_statistical_tests",
    "stationarity_check",
    "walk_forward_validate",
]
