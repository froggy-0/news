from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.config import SentimentJoinSettings
from morning_brief.analysis.sentiment_join.hybrid_index import compute_hybrid_index
from morning_brief.analysis.sentiment_join.join import merge_sources
from morning_brief.analysis.sentiment_join.sources.binance import fetch_btc_close_binance
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
        futures_df = fetch_futures_data(settings.lookback_days)
        _log_source_complete(
            "futures",
            futures_df,
            fallback_used=bool(futures_df.attrs.get("fallback_used", False)),
        )

        sentiment_df = normalize_dates(sentiment_df)
        fng_df = normalize_dates(fng_df)
        btc_close_df = normalize_dates(btc_close_df)
        usdkrw_close_df = normalize_dates(usdkrw_close_df)

        total_ffill_days = 0
        btc_close_df, btc_ffill_days = forward_fill_prices(btc_close_df, ["close"])
        usdkrw_close_df, usdkrw_ffill_days = forward_fill_prices(usdkrw_close_df, ["close"])
        total_ffill_days += btc_ffill_days + usdkrw_ffill_days

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
            sentiment_df, fng_df, btc_returns_df, usdkrw_returns_df, futures_df
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

        # Req 12: ADF·Granger 통계 검정 (로그만 남기고 파이프라인을 중단하지 않음)
        statistical_results: dict[str, object] = {}
        try:
            statistical_results = run_statistical_tests(master_df)
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
            master_df = compute_hybrid_index(master_df)
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
        stats_metadata = build_stats_metadata_payload(
            run_id=f"sentiment-join-{run_date}",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            adf=statistical_results.get("adf") if isinstance(statistical_results, dict) else None,
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
