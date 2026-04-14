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


def _add_futures_lag_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Req 11.3: 선물 지표에 Lag-1 처리를 적용해 미래 오염을 방지합니다."""
    result = df.copy()
    if "funding_rate" in result.columns:
        result["funding_rate_lag1"] = result["funding_rate"].shift(1)
    else:
        result["funding_rate_lag1"] = float("nan")
    if "open_interest_usd" in result.columns:
        result["oi_change_pct_lag1"] = result["open_interest_usd"].pct_change().shift(1)
    else:
        result["oi_change_pct_lag1"] = float("nan")
    if "btc_long_short_ratio" in result.columns:
        result["btc_long_short_ratio_lag1"] = result["btc_long_short_ratio"].shift(1)
    else:
        result["btc_long_short_ratio_lag1"] = float("nan")
    if "etf_net_inflow_usd" in result.columns:
        result["etf_net_inflow_usd_lag1"] = result["etf_net_inflow_usd"].shift(1)
    else:
        result["etf_net_inflow_usd_lag1"] = float("nan")
    return result


def _apply_sentiment_quality_gate(
    sentiment_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Req 6: 감성 품질 게이트. 저품질 관측치를 조인 전에 제거한다."""
    exclusion_counts: dict[str, int] = {
        "missing_backfill_marker": 0,
        "insufficient_article_count": 0,
        "skipped_sentiment": 0,
        "invalid_contract": 0,
        "no_sentiment": 0,
    }
    total_before = len(sentiment_df)
    keep_mask = pd.Series(True, index=sentiment_df.index)

    # _backfill 검증 (is_backfill_valid 컬럼이 있는 경우)
    if "is_backfill_valid" in sentiment_df.columns:
        invalid_backfill = ~sentiment_df["is_backfill_valid"].fillna(False).astype(bool)
        # ingest_validation_reason으로 구분
        if "ingest_validation_reason" in sentiment_df.columns:
            for idx in sentiment_df.index[invalid_backfill]:
                reason = sentiment_df.loc[idx, "ingest_validation_reason"]
                if reason and "missing_backfill_marker" in str(reason):
                    exclusion_counts["missing_backfill_marker"] += 1
                else:
                    exclusion_counts["invalid_contract"] += 1
        else:
            exclusion_counts["missing_backfill_marker"] += int(invalid_backfill.sum())
        keep_mask &= ~invalid_backfill

    # sentimentStatus == "skipped" 제거
    if "sentiment_status" in sentiment_df.columns:
        skipped = sentiment_df["sentiment_status"].str.lower() == "skipped"
        exclusion_counts["skipped_sentiment"] += int(skipped.sum())
        keep_mask &= ~skipped

    # count <= 1 제거
    if "n_articles" in sentiment_df.columns:
        low_count = sentiment_df["n_articles"].fillna(0).astype(int) <= 1
        exclusion_counts["insufficient_article_count"] += int((low_count & keep_mask).sum())
        keep_mask &= ~low_count

    # NaN sentiment 제거
    nan_sentiment = sentiment_df["news_sentiment_mean"].isna()
    exclusion_counts["no_sentiment"] += int((nan_sentiment & keep_mask).sum())
    keep_mask &= ~nan_sentiment

    filtered = sentiment_df.loc[keep_mask].reset_index(drop=True)
    total_after = len(filtered)

    if total_before > total_after:
        log_structured(
            logger,
            event="quality_gate.applied",
            message="감성 품질 게이트를 적용했습니다.",
            level=logging.WARNING if total_after == 0 else logging.INFO,
            rows_before=total_before,
            rows_after=total_after,
            exclusion_counts=exclusion_counts,
        )

    return filtered, exclusion_counts


def _add_btc_direction_label(df: pd.DataFrame) -> pd.DataFrame:
    """Req 8: btc_log_return 부호 기준으로 up/down/flat 라벨을 부여한다."""
    result = df.copy()
    if "btc_log_return" not in result.columns:
        result["btc_direction_label"] = None
        return result

    def _label(val: float) -> str | None:
        if pd.isna(val):
            return None
        if val > 0:
            return "up"
        if val < 0:
            return "down"
        return "flat"

    result["btc_direction_label"] = result["btc_log_return"].apply(_label)
    return result


def merge_sources(
    sentiment_df: pd.DataFrame,
    fng_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    usdkrw_df: pd.DataFrame,
    futures_df: pd.DataFrame | None = None,
    etf_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    filtered_sentiment, exclusion_counts = _apply_sentiment_quality_gate(sentiment_df)

    merged = filtered_sentiment.merge(fng_df, on="date", how="inner")
    merged = merged.merge(btc_df, on="date", how="inner")
    merged = merged.merge(usdkrw_df, on="date", how="inner")

    # Req 11: 선물 지표 조인 (실패해도 NaN 컬럼으로 계속 진행)
    if futures_df is not None and not futures_df.empty:
        futures_cols = [c for c in futures_df.columns if c != "date"]
        merged = merged.merge(futures_df[["date"] + futures_cols], on="date", how="left")
    else:
        merged["funding_rate"] = float("nan")
        merged["open_interest_usd"] = float("nan")
        merged["btc_long_short_ratio"] = float("nan")
    if etf_df is not None and not etf_df.empty:
        etf_cols = [c for c in etf_df.columns if c != "date"]
        merged = merged.merge(etf_df[["date"] + etf_cols], on="date", how="left")
    else:
        merged["etf_total_btc"] = float("nan")
        merged["etf_total_aum_usd"] = float("nan")
        merged["etf_net_inflow_usd"] = float("nan")

    merged = _add_futures_lag_columns(merged)
    merged = _add_btc_direction_label(merged)
    merged = detect_outliers_rolling_iqr(
        merged,
        cols=[
            "btc_return",
            "usdkrw_return",
            "funding_rate",
            "open_interest_usd",
            "btc_long_short_ratio",
        ],
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
        exclusion_counts=exclusion_counts,
        has_futures=bool("funding_rate" in merged.columns and merged["funding_rate"].notna().any()),
    )

    result = merged.reset_index(drop=True)
    result.attrs["exclusion_counts"] = exclusion_counts
    return result


__all__ = [
    "detect_outliers_rolling_iqr",
    "merge_sources",
    "_add_futures_lag_columns",
    "_add_btc_direction_label",
    "_apply_sentiment_quality_gate",
]
