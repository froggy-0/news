from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.config import SentimentJoinSettings
from morning_brief.analysis.sentiment_join.hybrid_index import compute_hybrid_index
from morning_brief.analysis.sentiment_join.join import merge_sources
from morning_brief.analysis.sentiment_join.sources.binance import fetch_btc_close_binance
from morning_brief.analysis.sentiment_join.sources.etf_flows import fetch_etf_flow_features
from morning_brief.analysis.sentiment_join.sources.fng import fetch_fng
from morning_brief.analysis.sentiment_join.sources.futures import fetch_futures_data
from morning_brief.analysis.sentiment_join.sources.r2_sentiment import fetch_r2_sentiment
from morning_brief.analysis.sentiment_join.sources.usdkrw_prices import fetch_usdkrw_close
from morning_brief.analysis.sentiment_join.statistical_tests import run_statistical_tests
from morning_brief.analysis.sentiment_join.storage import (
    cleanup_old_files,
    save_parquet,
    upload_to_r2,
)
from morning_brief.analysis.sentiment_join.transform import (
    compute_returns,
    forward_fill_prices,
    normalize_dates,
    reindex_to_calendar,
    trim_to_date_range,
)
from morning_brief.analysis.sentiment_join.validate import validate_master
from morning_brief.data.etf_storage import build_stats_metadata_payload
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


def _date_strings(start_date: str, end_date: str) -> list[str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    return [
        (start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)
    ]


def _empty_close_frame(start_date: str, end_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": _date_strings(start_date, end_date),
            "close": [np.nan] * len(_date_strings(start_date, end_date)),
        }
    )


def _empty_return_frame(prefix: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = _date_strings(start_date, end_date)
    return pd.DataFrame(
        {
            "date": dates,
            f"{prefix}_log_return": [np.nan] * len(dates),
            f"{prefix}_return": [np.nan] * len(dates),
        }
    )


def _log_source_complete(source: str, df: pd.DataFrame, *, fallback_used: bool) -> None:
    log_structured(
        logger,
        event="source.complete",
        message="소스 수집을 완료했습니다.",
        source=source,
        rows=len(df),
        fallback_used=fallback_used,
    )


def _rename_returns(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    return df.rename(
        columns={
            "close_log_return": f"{prefix}_log_return",
            "close_return": f"{prefix}_return",
        }
    )


def _has_any_data(df: pd.DataFrame, cols: list[str]) -> bool:
    return any(col in df.columns and df[col].notna().any() for col in cols)


def _build_granger_correction(statistical_results: dict[str, object]) -> dict[str, object]:
    """BH-FDR 보정 메타데이터 생성 (pipeline.py → build_stats_metadata_payload 전달용)."""
    granger = statistical_results.get("granger")
    n_tests = len(granger) if isinstance(granger, list) else 0
    return {
        "correction_method": "fdr_bh",  # statsmodels 관례; 설계 §3.D 정렬
        "granger_method": "pairwise_granger",  # §6: 후속 VAR 확장 시 구분 포인트
        "n_tests": n_tests,
        "bonferroni_threshold": round(0.05 / n_tests, 10) if n_tests > 0 else None,
    }


def _hybrid_signal_label(series: pd.Series) -> str | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    window = clean.tail(30)
    if len(window) < 2:
        return "neutral"
    std = float(window.std(ddof=0))
    if std == 0:
        return "neutral"
    zscore = float((window.iloc[-1] - float(window.mean())) / std)
    if zscore >= 0.5:
        return "risk_on"
    if zscore <= -0.5:
        return "risk_off"
    return "neutral"


def run_sentiment_join(settings: SentimentJoinSettings) -> int:
    try:
        today = datetime.now(timezone.utc).date()
        end_date = today.isoformat()
        start_date = (today - timedelta(days=settings.lookback_days)).isoformat()
        btc_start_date = (today - timedelta(days=settings.lookback_days + 1)).isoformat()
        sentiment_dates = _date_strings(start_date, end_date)

        sentiment_df = fetch_r2_sentiment(
            sentiment_dates,
            settings.r2_base_url,
            max_concurrency=settings.r2_max_concurrency,
        )
        _log_source_complete(
            "r2",
            sentiment_df,
            fallback_used=bool(sentiment_df.attrs.get("fallback_used", False)),
        )

        fng_df = fetch_fng(settings.lookback_days)
        _log_source_complete(
            "fng",
            fng_df,
            fallback_used=bool(fng_df.attrs.get("fallback_used", False)),
        )

        btc_close_df = fetch_btc_close_binance(
            btc_start_date, end_date, api_key=settings.binance_api_key
        )
        btc_fallback_used = bool(btc_close_df.attrs.get("fallback_used", False))
        _log_source_complete("btc", btc_close_df, fallback_used=btc_fallback_used)
        btc_source = btc_close_df.attrs.get("btc_source", "unknown")
        if btc_close_df.empty:
            btc_close_df = _empty_close_frame(btc_start_date, end_date)
            btc_close_df["btc_quote_volume"] = float("nan")

        usdkrw_close_df = fetch_usdkrw_close(
            btc_start_date,
            end_date,
            settings.kis_app_key,
            settings.kis_app_secret,
        )
        usdkrw_fallback_used = bool(usdkrw_close_df.attrs.get("fallback_used", False))
        _log_source_complete("usdkrw", usdkrw_close_df, fallback_used=usdkrw_fallback_used)
        if usdkrw_close_df.empty:
            usdkrw_close_df = _empty_close_frame(btc_start_date, end_date)

        # Req 11: 선물 지표 수집 (실패 시 빈 DataFrame — merge_sources에서 NaN 컬럼으로 처리)
        futures_df = fetch_futures_data(settings.lookback_days, settings.futures_lambda_arn)
        _log_source_complete(
            "futures",
            futures_df,
            fallback_used=bool(futures_df.attrs.get("fallback_used", False)),
        )
        etf_df = fetch_etf_flow_features(
            start_date,
            end_date,
            cache_dir=Path(".cache").resolve(),
        )
        _log_source_complete("btc_etf", etf_df, fallback_used=False)

        sentiment_df = normalize_dates(sentiment_df)
        fng_df = normalize_dates(fng_df)
        btc_close_df = normalize_dates(btc_close_df)
        usdkrw_close_df = normalize_dates(usdkrw_close_df)
        etf_df = normalize_dates(etf_df) if not etf_df.empty else etf_df

        total_ffill_days = 0
        btc_close_df, btc_ffill_days = forward_fill_prices(btc_close_df, ["close"])
        # USDKRW는 외환시장이 주말 휴장이라 Sat/Sun 행이 비어 있다.
        # BTC(24/7)와 inner merge 시 주말 행이 전부 drop되어 Granger 최소치(180)에
        # 도달하지 못하므로, 전체 달력일로 reindex해 금요일 close를 주말로 ffill한다.
        # max_periods를 3으로 올려 3일 연휴까지 커버한다.
        usdkrw_close_df = reindex_to_calendar(usdkrw_close_df, btc_start_date, end_date)
        usdkrw_close_df, usdkrw_ffill_days = forward_fill_prices(
            usdkrw_close_df, ["close"], max_periods=3
        )
        total_ffill_days += btc_ffill_days + usdkrw_ffill_days
        if not etf_df.empty:
            etf_df["etf_total_btc"] = pd.to_numeric(
                etf_df["etf_total_btc"], errors="coerce"
            ).ffill()
            etf_df["etf_total_aum_usd"] = pd.to_numeric(
                etf_df["etf_total_aum_usd"], errors="coerce"
            ).ffill()
            etf_df = etf_df.merge(btc_close_df[["date", "close"]], on="date", how="left")
            etf_df["etf_net_inflow_usd"] = etf_df["etf_total_btc"].diff() * etf_df["close"]
            etf_df = etf_df.drop(columns=["close"])
            etf_df = trim_to_date_range(etf_df, start_date, end_date)

        btc_returns_df = compute_returns(btc_close_df, "close")
        btc_returns_df = _rename_returns(btc_returns_df, "btc")
        btc_returns_df = trim_to_date_range(btc_returns_df, start_date, end_date)
        if btc_returns_df.empty:
            btc_returns_df = _empty_return_frame("btc", start_date, end_date)

        usdkrw_returns_df = compute_returns(usdkrw_close_df, "close")
        usdkrw_returns_df = _rename_returns(usdkrw_returns_df, "usdkrw")
        usdkrw_returns_df = trim_to_date_range(usdkrw_returns_df, start_date, end_date)
        if usdkrw_returns_df.empty:
            usdkrw_returns_df = _empty_return_frame("usdkrw", start_date, end_date)

        futures_df = normalize_dates(futures_df) if not futures_df.empty else futures_df

        master_df = merge_sources(
            sentiment_df, fng_df, btc_returns_df, usdkrw_returns_df, futures_df, etf_df
        )

        exclusion_counts = master_df.attrs.get("exclusion_counts", {})
        if exclusion_counts:
            log_structured(
                logger,
                event="quality_gate.summary",
                message="감성 품질 게이트 제외 사유 집계입니다.",
                exclusion_counts=exclusion_counts,
            )

        if master_df.empty:
            log_structured(
                logger,
                event="error.raised",
                message="결합 결과가 비어 있어 Parquet 파일을 만들지 않습니다.",
                level=logging.ERROR,
                reason="empty_after_join",
            )
            return 1

        if not any(
            (
                _has_any_data(sentiment_df, ["news_sentiment_mean"]),
                _has_any_data(fng_df, ["fng_value"]),
                _has_any_data(btc_returns_df, ["btc_log_return", "btc_return"]),
                _has_any_data(usdkrw_returns_df, ["usdkrw_log_return", "usdkrw_return"]),
            )
        ):
            log_structured(
                logger,
                event="error.raised",
                message="모든 소스가 실패해 저장할 데이터가 없습니다.",
                level=logging.ERROR,
                reason="all_sources_failed",
            )
            return 1

        # §8-A: 이상치 행은 제거하지 않고 수치 컬럼만 NaN으로 마스킹.
        # 달력 연속성을 유지해 Granger 검정의 time-index gap 문제를 방지합니다.
        _NON_MASK_COLS = frozenset(
            {
                "date",
                "is_outlier",
                "sentiment_status",
                "is_backfill_valid",
                "ingest_validation_reason",
                "btc_direction_label",
                "text_schema_version",
            }
        )
        analysis_df = master_df.copy()
        _mask_cols = [c for c in analysis_df.columns if c not in _NON_MASK_COLS]
        analysis_df.loc[analysis_df["is_outlier"], _mask_cols] = np.nan
        masked_count = int(analysis_df["is_outlier"].sum())
        masked_ratio = round(masked_count / len(analysis_df), 4) if len(analysis_df) else 0.0
        log_structured(
            logger,
            event="stats.outlier_filter_applied",
            message="통계 분석용 이상값을 NaN으로 마스킹했습니다. (행은 유지)",
            total_rows=len(analysis_df),
            masked_count=masked_count,
            masked_ratio=masked_ratio,
        )

        # Req 12: ADF·Granger 통계 검정 (로그만 남기고 파이프라인을 중단하지 않음)
        statistical_results: dict[str, object] = {}
        try:
            statistical_results = run_statistical_tests(analysis_df)
            log_structured(
                logger,
                event="stats.granger_eligibility",
                message="Granger 검정 자격을 평가했습니다.",
                granger_eligible_rows=statistical_results.get("granger_eligible_rows"),
                granger_executed=statistical_results.get("granger_executed"),
                reason=(
                    None
                    if statistical_results.get("granger_executed")
                    else "insufficient_rows_for_granger"
                ),
            )
        except Exception as exc:
            log_structured(
                logger,
                event="stats.error",
                message="통계 검정 실행 중 오류가 발생했습니다.",
                level=logging.WARNING,
                reason=str(exc),
            )

        # Req 13: PCA 하이브리드 지수 생성
        try:
            analysis_with_hybrid = compute_hybrid_index(analysis_df)
            master_df["hybrid_index"] = float("nan")
            hybrid_map = analysis_with_hybrid.set_index("date")["hybrid_index"].to_dict()
            master_df["hybrid_index"] = master_df["date"].map(hybrid_map)
            master_df.attrs["hybrid_index_diagnostics"] = analysis_with_hybrid.attrs.get(
                "hybrid_index_diagnostics", {}
            )
        except Exception as exc:
            log_structured(
                logger,
                event="stats.error",
                message="하이브리드 지수 생성 중 오류가 발생했습니다.",
                level=logging.WARNING,
                reason=str(exc),
            )
            master_df["hybrid_index"] = float("nan")

        run_date = today.strftime("%Y%m%d")
        hybrid_diagnostics = master_df.attrs.get("hybrid_index_diagnostics", {})
        hybrid_signal_label = _hybrid_signal_label(master_df["hybrid_index"])
        stats_metadata = build_stats_metadata_payload(
            run_id=f"sentiment-join-{run_date}",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            adf=statistical_results.get("stationarity_results")
            if isinstance(statistical_results, dict)
            else None,
            granger_results=(
                statistical_results.get("granger", [])
                if isinstance(statistical_results, dict)
                else []
            ),
            vif_diagnostics=(
                hybrid_diagnostics.get("vif_diagnostics", [])
                if isinstance(hybrid_diagnostics, dict)
                else []
            ),
            pca_summary=(
                hybrid_diagnostics.get("pca_summary")
                if isinstance(hybrid_diagnostics, dict)
                else None
            ),
            rows_before_outlier_filter=len(master_df),
            rows_after_outlier_filter=len(analysis_df),
            outlier_filtered_count=masked_count,
            outlier_filtered_ratio=masked_ratio,
            hybrid_signal_label=hybrid_signal_label,
            granger_eligible_rows=(
                statistical_results.get("granger_eligible_rows")
                if isinstance(statistical_results, dict)
                else None
            ),
            granger_executed=(
                statistical_results.get("granger_executed")
                if isinstance(statistical_results, dict)
                else False
            ),
            exclusion_counts=exclusion_counts if exclusion_counts else None,
            granger_correction=(
                _build_granger_correction(statistical_results)
                if isinstance(statistical_results, dict)
                and statistical_results.get("granger_executed")
                else None
            ),
        )

        validate_master(master_df)
        path = save_parquet(
            master_df,
            settings.output_dir,
            run_date,
            ffill_days=total_ffill_days,
            stats_metadata=stats_metadata,
            btc_source=btc_source,
        )
        cleanup_old_files(settings.output_dir, settings.retain_days)
        upload_to_r2(
            path,
            f"sentiment_join/{path.name}",
            r2_s3_endpoint=os.getenv("R2_S3_ENDPOINT", "").strip(),
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
            r2_public_bucket=settings.r2_public_bucket,
        )
        return 0
    except Exception as exc:
        log_structured(
            logger,
            event="error.raised",
            message="Sentiment Time Join 파이프라인이 실패했습니다.",
            level=logging.ERROR,
            reason=str(exc),
        )
        return 1


__all__ = ["run_sentiment_join"]
