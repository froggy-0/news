from __future__ import annotations

import logging

import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


def _compute_sources_used(dfs: dict[str, pd.DataFrame]) -> list[str]:
    column_map = {
        "r2": ["news_sentiment_mean"],
        "fng": ["fng_value"],
        "btc": ["btc_log_return", "btc_return"],
        "usdkrw": ["usdkrw_log_return", "usdkrw_return"],
    }
    used: list[str] = []
    for source, df in dfs.items():
        core_columns = column_map.get(source, [])
        if df.empty:
            continue
        if any(column in df.columns and df[column].notna().any() for column in core_columns):
            used.append(source)
    return used


def detect_outliers_rolling_iqr(
    df: pd.DataFrame,
    cols: list[str],
    window: int = 30,
    iqr_multiplier: float = 3.0,
    min_periods: int = 15,
) -> pd.DataFrame:
    flagged = df.copy()
    if flagged.empty:
        flagged["is_outlier"] = pd.Series(dtype=bool)
        return flagged

    flagged["is_outlier"] = False
    if len(flagged) <= window:
        flagged["is_outlier"] = flagged["is_outlier"].astype(bool)
        return flagged

    for col in cols:
        series = pd.to_numeric(flagged[col], errors="coerce")
        reference = series.shift(1)
        rolling = reference.rolling(window=window, min_periods=min_periods)
        median = rolling.median()
        q1 = rolling.quantile(0.25)
        q3 = rolling.quantile(0.75)
        iqr = q3 - q1
        threshold = iqr_multiplier * iqr
        distances = (series - median).abs()
        mask = series.notna() & median.notna() & threshold.notna() & (distances > threshold)
        if not mask.any():
            continue
        flagged.loc[mask, "is_outlier"] = True
        for row in flagged.loc[mask, ["date", col]].itertuples(index=False):
            idx = flagged.index[flagged["date"] == row.date][0]
            log_structured(
                logger,
                event="outlier.detected",
                message="롤링 IQR 기준 이상값을 감지했습니다.",
                level=logging.WARNING,
                date=row.date,
                column=col,
                value=getattr(row, col),
                threshold=threshold.loc[idx],
            )

    flagged["is_outlier"] = flagged["is_outlier"].astype(bool)
    return flagged


def merge_sources(
    sentiment_df: pd.DataFrame,
    fng_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    usdkrw_df: pd.DataFrame,
) -> pd.DataFrame:
    dropped_no_sentiment = int(sentiment_df["news_sentiment_mean"].isna().sum())
    filtered_sentiment = sentiment_df.dropna(subset=["news_sentiment_mean"]).reset_index(drop=True)
    if dropped_no_sentiment:
        log_structured(
            logger,
            event="rows.dropped",
            message="감성 점수가 없는 날짜를 분석 대상에서 제외합니다.",
            level=logging.WARNING,
            reason="no_sentiment",
            count=dropped_no_sentiment,
        )

    merged = filtered_sentiment.merge(fng_df, on="date", how="inner")
    merged = merged.merge(btc_df, on="date", how="inner")
    merged = merged.merge(usdkrw_df, on="date", how="inner")
    merged = detect_outliers_rolling_iqr(
        merged,
        cols=["btc_return", "usdkrw_return"],
    )

    if len(merged) < 30:
        log_structured(
            logger,
            event="join.insufficient_rows",
            message="결합 결과 행 수가 최소 권장치보다 적습니다.",
            level=logging.WARNING,
            rows=len(merged),
            min_required=30,
        )

    sources_used = _compute_sources_used(
        {
            "r2": sentiment_df,
            "fng": fng_df,
            "btc": btc_df,
            "usdkrw": usdkrw_df,
        }
    )
    log_structured(
        logger,
        event="join.complete",
        message="소스 결합을 완료했습니다.",
        rows=len(merged),
        date_range_start=merged["date"].min() if not merged.empty else None,
        date_range_end=merged["date"].max() if not merged.empty else None,
        sources_used=sources_used,
        outlier_count=int(merged["is_outlier"].sum()) if "is_outlier" in merged else 0,
        dropped_no_sentiment=dropped_no_sentiment,
    )

    return merged.reset_index(drop=True)


__all__ = [
    "detect_outliers_rolling_iqr",
    "merge_sources",
]
