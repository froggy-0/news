from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.config import SentimentJoinSettings
from morning_brief.analysis.sentiment_join.hybrid_index import (
    INDEX_SPECS,
    compute_hybrid_indices,
)
from morning_brief.analysis.sentiment_join.join import merge_sources
from morning_brief.analysis.sentiment_join.outlier_policy import OutlierPolicyFactory
from morning_brief.analysis.sentiment_join.quality import STRUCTURED_SOURCE_MIN_COVERAGE_RATIO
from morning_brief.analysis.sentiment_join.signals import hybrid_signal_label
from morning_brief.analysis.sentiment_join.sources.binance import fetch_btc_close_binance
from morning_brief.analysis.sentiment_join.sources.etf_flows import fetch_etf_flow_features
from morning_brief.analysis.sentiment_join.sources.fng import fetch_fng
from morning_brief.analysis.sentiment_join.sources.futures import fetch_futures_data
from morning_brief.analysis.sentiment_join.sources.r2_sentiment import fetch_r2_sentiment
from morning_brief.analysis.sentiment_join.sources.usdkrw_prices import fetch_usdkrw_close
from morning_brief.analysis.sentiment_join.sources.vix import fetch_vix_history
from morning_brief.analysis.sentiment_join.statistical_tests import (
    run_alpha_validation,
    run_statistical_tests,
)
from morning_brief.analysis.sentiment_join.storage import (
    cleanup_old_files,
    save_parquet,
    upload_to_r2,
    write_backfill_manifest,
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


def _compute_regime(btc_close_df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """1-B: BTC 200일 MA 기반 레짐 피처 계산.

    btc_ma_200d     : 200일 단순 이동평균 (min_periods=100)
    btc_drawdown_90d: 90일 고점 대비 낙폭 (0 ~ -1)
    btc_above_ma200 : 현재가 > MA200 여부 (1.0 = bull, 0.0 = bear, NaN = MA 미확보)

    lookback_days=365 기준에서 MA200 확보 구간은 약 165일부터 시작.
    초기 NaN은 merge_sources에서 left-join 후 자연스럽게 유지된다.
    """
    empty_dates = _date_strings(start_date, end_date)
    empty = pd.DataFrame(
        {
            "date": empty_dates,
            "btc_ma_200d": [float("nan")] * len(empty_dates),
            "btc_drawdown_90d": [float("nan")] * len(empty_dates),
            "btc_above_ma200": [float("nan")] * len(empty_dates),
        }
    )

    if btc_close_df.empty or "close" not in btc_close_df.columns:
        return empty

    df = btc_close_df[["date", "close"]].copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    df["btc_ma_200d"] = close.rolling(200, min_periods=100).mean()
    df["btc_above_ma200"] = (
        (close > df["btc_ma_200d"])
        .where(df["btc_ma_200d"].notna(), other=float("nan"))
        .astype("float64")
    )
    rolling_max = close.rolling(90, min_periods=30).max()
    df["btc_drawdown_90d"] = (close / rolling_max - 1).where(
        rolling_max.notna(), other=float("nan")
    )

    from morning_brief.analysis.sentiment_join.transform import trim_to_date_range

    return trim_to_date_range(
        df[["date", "btc_ma_200d", "btc_drawdown_90d", "btc_above_ma200"]],
        start_date,
        end_date,
    )


def _structured_sources_metadata(
    *,
    futures_attrs: dict[str, object],
    etf_attrs: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        "btc_etf": {
            "mode": etf_attrs.get("source_mode", "empty"),
            "coverage": {
                "non_null_days": etf_attrs.get("history_non_null_days", 0),
                "requested_days": etf_attrs.get("requested_days", 0),
                "ratio": etf_attrs.get("history_coverage_ratio", 0.0),
            },
            "quality_status": etf_attrs.get("history_quality_status", "degraded"),
            "quality_reasons": etf_attrs.get("history_quality_reasons", []),
        },
        "futures": {
            "mode": futures_attrs.get("futures_source", "none"),
            "coverage": {
                "requested_days": futures_attrs.get("requested_days", 0),
                "funding_days": futures_attrs.get("funding_days", 0),
                "oi_days": futures_attrs.get("oi_days", 0),
                "lsr_days": futures_attrs.get("lsr_days", 0),
                "funding_ratio": futures_attrs.get("funding_coverage_ratio", 0.0),
                "oi_ratio": futures_attrs.get("oi_coverage_ratio", 0.0),
                "lsr_ratio": futures_attrs.get("lsr_coverage_ratio", 0.0),
            },
            "quality_status": futures_attrs.get("quality_status", "degraded"),
            "quality_reasons": futures_attrs.get("quality_reasons", []),
            "funding_quality_status": futures_attrs.get("funding_quality_status", "degraded"),
            "funding_quality_reasons": futures_attrs.get("funding_quality_reasons", []),
            "oi_quality_status": futures_attrs.get("oi_quality_status", "degraded"),
            "oi_quality_reasons": futures_attrs.get("oi_quality_reasons", []),
            "oi_recent_quality_status": futures_attrs.get("oi_recent_quality_status", "degraded"),
            "oi_recent_quality_reasons": futures_attrs.get("oi_recent_quality_reasons", []),
            "oi_api_capped": futures_attrs.get("oi_api_capped", False),
            "lsr_quality_status": futures_attrs.get("lsr_quality_status", "degraded"),
            "lsr_quality_reasons": futures_attrs.get("lsr_quality_reasons", []),
            "lsr_recent_quality_status": futures_attrs.get("lsr_recent_quality_status", "degraded"),
            "lsr_recent_quality_reasons": futures_attrs.get("lsr_recent_quality_reasons", []),
            "lsr_api_capped": futures_attrs.get("lsr_api_capped", False),
            "requested_start_date": futures_attrs.get("requested_start_date"),
            "requested_end_date": futures_attrs.get("requested_end_date"),
            "returned_min_date": futures_attrs.get("returned_min_date", {}),
            "returned_max_date": futures_attrs.get("returned_max_date", {}),
        },
    }


def _apply_structured_source_gates(
    df: pd.DataFrame,
    *,
    futures_attrs: dict[str, object],
    etf_attrs: dict[str, object],
) -> tuple[pd.DataFrame, dict[str, str]]:
    gated = df.copy()
    feature_exclusion_reasons: dict[str, str] = {}

    etf_history_ok = (
        etf_attrs.get("source_mode") == "gold_history"
        and etf_attrs.get("history_quality_status") == "ok"
    )
    if not etf_history_ok:
        for column in ("etf_net_inflow_usd", "etf_net_inflow_usd_lag1"):
            if column in gated.columns:
                gated[column] = np.nan
                feature_exclusion_reasons[column] = "btc_etf_history_unavailable"

    # OI/LSR 게이트: Binance API 30일 보존 제약을 고려해 최근 30일 윈도우 coverage로 판단.
    # oi_quality_status(전체 lookback 기준)가 아닌 oi_recent_quality_status를 우선 사용.
    oi_gate_status = futures_attrs.get("oi_recent_quality_status") or futures_attrs.get(
        "oi_quality_status", "degraded"
    )
    if oi_gate_status != "ok":
        for column in ("open_interest_usd", "oi_change_pct", "oi_change_pct_lag1"):
            if column in gated.columns:
                gated[column] = np.nan
                feature_exclusion_reasons[column] = "futures_oi_incomplete"

    lsr_gate_status = futures_attrs.get("lsr_recent_quality_status") or futures_attrs.get(
        "lsr_quality_status", "degraded"
    )
    if lsr_gate_status != "ok":
        for column in ("btc_long_short_ratio", "btc_long_short_ratio_lag1"):
            if column in gated.columns:
                gated[column] = np.nan
                feature_exclusion_reasons[column] = "futures_lsr_incomplete"

    if futures_attrs.get("funding_quality_status") != "ok":
        for column in ("funding_rate", "funding_rate_lag1"):
            if column in gated.columns:
                gated[column] = np.nan
                feature_exclusion_reasons[column] = "futures_funding_incomplete"

    if feature_exclusion_reasons:
        log_structured(
            logger,
            event="quality_gate.structured_sources",
            message="Structured source coverage gate를 적용했습니다.",
            threshold=STRUCTURED_SOURCE_MIN_COVERAGE_RATIO,
            excluded_features=feature_exclusion_reasons,
        )

    return gated, feature_exclusion_reasons


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


def _target_diagnostics(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    diagnostics: dict[str, dict[str, object]] = {}
    target_cols = [
        "btc_fwd_ret_1d",
        "btc_fwd_ret_3d",
        "btc_fwd_ret_7d",
        "btc_fwd_vol_5d",
        "btc_large_move_3d",
        "btc_realized_vol_20d_lag1",
        "btc_large_move_3d_vol_adj",
    ]
    for col in target_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        valid = series.dropna()
        record: dict[str, object] = {
            "valid_rows": int(len(valid)),
            "null_ratio": round(float(series.isna().mean()), 4) if len(series) else 0.0,
        }
        if col.startswith("btc_large_move"):
            record["positive_rate"] = float(valid.mean()) if len(valid) else None
        elif len(valid):
            record["mean"] = float(valid.mean())
            record["std"] = float(valid.std(ddof=1)) if len(valid) > 1 else None
        diagnostics[col] = record
    return diagnostics


def run_sentiment_join(settings: SentimentJoinSettings) -> int:
    try:
        today = datetime.now(timezone.utc).date()
        end_date = today.isoformat()
        start_date = (today - timedelta(days=settings.lookback_days)).isoformat()
        returns_start_date = (today - timedelta(days=settings.lookback_days + 1)).isoformat()
        btc_history_days = settings.lookback_days + max(settings.regime_warmup_days, 1)
        btc_history_start_date = (today - timedelta(days=btc_history_days)).isoformat()
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
            btc_history_start_date, end_date, api_key=settings.binance_api_key
        )
        btc_fallback_used = bool(btc_close_df.attrs.get("fallback_used", False))
        _log_source_complete("btc", btc_close_df, fallback_used=btc_fallback_used)
        btc_source = btc_close_df.attrs.get("btc_source", "unknown")
        if btc_close_df.empty:
            btc_close_df = _empty_close_frame(btc_history_start_date, end_date)
            btc_close_df["btc_quote_volume"] = float("nan")

        usdkrw_close_df = fetch_usdkrw_close(
            returns_start_date,
            end_date,
            settings.kis_app_key,
            settings.kis_app_secret,
        )
        usdkrw_fallback_used = bool(usdkrw_close_df.attrs.get("fallback_used", False))
        _log_source_complete("usdkrw", usdkrw_close_df, fallback_used=usdkrw_fallback_used)
        if usdkrw_close_df.empty:
            usdkrw_close_df = _empty_close_frame(returns_start_date, end_date)

        # §4 3-4: VIX optional feature. FRED_API_KEY 미설정·실패 시 빈 DataFrame.
        vix_df = fetch_vix_history(returns_start_date, end_date)
        _log_source_complete(
            "vix",
            vix_df,
            fallback_used=bool(vix_df.attrs.get("fallback_used", False)),
        )

        # Req 11: 선물 지표 수집 (실패 시 빈 DataFrame — merge_sources에서 NaN 컬럼으로 처리)
        futures_df = fetch_futures_data(settings.lookback_days, settings.futures_lambda_arn)
        futures_source_attrs = dict(futures_df.attrs)
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
        etf_source_attrs = dict(etf_df.attrs)
        _log_source_complete("btc_etf", etf_df, fallback_used=False)
        structured_sources = _structured_sources_metadata(
            futures_attrs=futures_source_attrs,
            etf_attrs=etf_source_attrs,
        )

        sentiment_df = normalize_dates(sentiment_df)
        fng_df = normalize_dates(fng_df)
        btc_close_df = normalize_dates(btc_close_df)
        usdkrw_close_df = normalize_dates(usdkrw_close_df)
        etf_df = normalize_dates(etf_df) if not etf_df.empty else etf_df
        if not futures_df.empty:
            futures_df.attrs.update(futures_source_attrs)
        if not etf_df.empty:
            etf_df.attrs.update(etf_source_attrs)
        # §4 3-4: VIX는 미국 시장 종가 기반이라 주말/공휴일이 비어 있으므로
        # 전체 달력으로 reindex + 2일 ffill. usdkrw와 동일한 패턴.
        if not vix_df.empty:
            vix_df = normalize_dates(vix_df)
            vix_df = reindex_to_calendar(vix_df, returns_start_date, end_date)
            vix_df, vix_ffill_days = forward_fill_prices(vix_df, ["vix"], max_periods=2)
        else:
            vix_ffill_days = 0

        total_ffill_days = 0
        btc_close_df, btc_ffill_days = forward_fill_prices(btc_close_df, ["close"])
        # USDKRW는 외환시장이 주말 휴장이라 Sat/Sun 행이 비어 있다.
        # BTC(24/7)와 inner merge 시 주말 행이 전부 drop되어 Granger 최소치(180)에
        # 도달하지 못하므로, 전체 달력일로 reindex해 금요일 close를 주말로 ffill한다.
        # max_periods를 3으로 올려 3일 연휴까지 커버한다.
        usdkrw_close_df = reindex_to_calendar(usdkrw_close_df, returns_start_date, end_date)
        usdkrw_close_df, usdkrw_ffill_days = forward_fill_prices(
            usdkrw_close_df, ["close"], max_periods=3
        )
        total_ffill_days += btc_ffill_days + usdkrw_ffill_days + vix_ffill_days
        ffill_breakdown = {
            "btc": {
                "filled_days": btc_ffill_days,
                "max_periods": 2,
                "start_date": btc_history_start_date,
                "end_date": end_date,
            },
            "usdkrw": {
                "filled_days": usdkrw_ffill_days,
                "max_periods": 3,
                "start_date": returns_start_date,
                "end_date": end_date,
            },
            "vix": {
                "filled_days": vix_ffill_days,
                "max_periods": 2,
                "start_date": returns_start_date,
                "end_date": end_date,
            },
        }
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
            etf_df.attrs.update(etf_source_attrs)

        btc_returns_df = compute_returns(btc_close_df, "close")
        btc_returns_df = _rename_returns(btc_returns_df, "btc")
        btc_returns_df = trim_to_date_range(btc_returns_df, start_date, end_date)
        if btc_returns_df.empty:
            btc_returns_df = _empty_return_frame("btc", start_date, end_date)

        # 1-B: close 원본 기반 레짐 피처 (compute_returns 이후에도 btc_close_df 유지)
        regime_df = _compute_regime(btc_close_df, start_date, end_date)

        usdkrw_returns_df = compute_returns(usdkrw_close_df, "close")
        usdkrw_returns_df = _rename_returns(usdkrw_returns_df, "usdkrw")
        usdkrw_returns_df = trim_to_date_range(usdkrw_returns_df, start_date, end_date)
        if usdkrw_returns_df.empty:
            usdkrw_returns_df = _empty_return_frame("usdkrw", start_date, end_date)

        futures_df = normalize_dates(futures_df) if not futures_df.empty else futures_df
        if not futures_df.empty:
            futures_df.attrs.update(futures_source_attrs)
        if not vix_df.empty:
            vix_df = trim_to_date_range(vix_df, start_date, end_date)

        master_df = merge_sources(
            sentiment_df,
            fng_df,
            btc_returns_df,
            usdkrw_returns_df,
            futures_df,
            etf_df,
            vix_df,
            regime_df,
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

        # §8-A: column 정책 — 이상치 셀만 NaN 마스킹, 행 전체는 보존.
        # regime_stress(BTC 급락 등 시장 스트레스일)는 마스킹하지 않고 사유만 기록.
        # IQR 적용 대상은 join.py detect_outliers_rolling_iqr 와 동일한 변화율·수익률 6개 컬럼.
        # level/bounded 컬럼(fng_value, news_sentiment_mean 등)은 false positive가 많아 제외.
        _OUTLIER_IQR_COLS = [
            c
            for c in [
                "btc_return",
                "usdkrw_return",
                "funding_rate",
                "oi_change_pct",
                "volume_change_pct",
                "etf_net_inflow_usd",
            ]
            if c in master_df.columns
        ]
        _outlier_result = OutlierPolicyFactory.create("column").apply(master_df, _OUTLIER_IQR_COLS)
        analysis_df = _outlier_result.df
        analysis_df, feature_exclusion_reasons = _apply_structured_source_gates(
            analysis_df,
            futures_attrs=futures_source_attrs,
            etf_attrs=etf_source_attrs,
        )
        masked_count = int(_outlier_result.stats.get("masked_cells", 0))
        masked_ratio = round(masked_count / max(len(analysis_df), 1), 4)
        log_structured(
            logger,
            event="stats.outlier_filter_applied",
            message="통계 분석용 이상값을 NaN으로 마스킹했습니다. (행은 유지)",
            total_rows=len(analysis_df),
            masked_cells=masked_count,
            masked_ratio=masked_ratio,
            regime_stress_rows=int(_outlier_result.stats.get("regime_stress_rows", 0)),
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

        # §4 v4: full / core 두 하이브리드 지수 + 0~100 score를 생성합니다.
        hybrid_column_names = [f"{spec.name}_hybrid_index" for spec in INDEX_SPECS] + [
            f"{spec.name}_hybrid_index_score" for spec in INDEX_SPECS
        ]
        for col in hybrid_column_names:
            master_df[col] = float("nan")
        analysis_with_hybrid = analysis_df.copy()
        for col in hybrid_column_names:
            analysis_with_hybrid[col] = float("nan")
        try:
            analysis_with_hybrid = compute_hybrid_indices(
                analysis_df,
                feature_exclusion_reasons=feature_exclusion_reasons,
            )
            for col in hybrid_column_names:
                hybrid_map = analysis_with_hybrid.set_index("date")[col].to_dict()
                master_df[col] = master_df["date"].map(hybrid_map)
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

        # §4 v4: hybrid index score Lag-1 컬럼 생성 (alpha validation용)
        for spec_name in ("full", "core"):
            score_col = f"{spec_name}_hybrid_index_score"
            lag1_col = f"{score_col}_lag1"
            master_df[lag1_col] = master_df[score_col].shift(1)
            analysis_with_hybrid[lag1_col] = analysis_with_hybrid[score_col].shift(1)

        # §4 v4: Alpha Validation 실행 (실패 시 파이프라인 중단하지 않음)
        alpha_validation_results: dict[str, object] = {}
        try:
            _sr = (
                statistical_results.get("stationarity_results")
                if isinstance(statistical_results, dict)
                else None
            )
            _gr = (
                statistical_results.get("granger")
                if isinstance(statistical_results, dict)
                else None
            )
            _ge = (
                statistical_results.get("granger_executed", False)
                if isinstance(statistical_results, dict)
                else False
            )
            alpha_validation_results = run_alpha_validation(
                analysis_with_hybrid,
                stationarity_results=_sr if isinstance(_sr, dict) else None,
                granger_results=_gr if isinstance(_gr, list) else None,
                granger_executed=bool(_ge),
            )
        except Exception as exc:
            log_structured(
                logger,
                event="stats.error",
                message="Alpha Validation 실행 중 오류가 발생했습니다.",
                level=logging.WARNING,
                reason=str(exc),
            )

        run_date = today.strftime("%Y%m%d")
        hybrid_diagnostics = master_df.attrs.get("hybrid_index_diagnostics", {})

        hybrid_indices_meta: dict[str, dict[str, object]] = {}
        for spec in INDEX_SPECS:
            diag = (
                hybrid_diagnostics.get(spec.name, {})
                if isinstance(hybrid_diagnostics, dict)
                else {}
            )
            label, zscore = hybrid_signal_label(master_df[f"{spec.name}_hybrid_index"])
            hybrid_indices_meta[spec.name] = {
                "vif_diagnostics": diag.get("vif_diagnostics", [])
                if isinstance(diag, dict)
                else [],
                "pca_summary": diag.get("pca_summary", {}) if isinstance(diag, dict) else {},
                "coverage": diag.get("coverage", {}) if isinstance(diag, dict) else {},
                "excluded_features": diag.get("excluded_features", [])
                if isinstance(diag, dict)
                else [],
                "quality_status": diag.get("quality_status", "degraded")
                if isinstance(diag, dict)
                else "degraded",
                "quality_reasons": diag.get("quality_reasons", [])
                if isinstance(diag, dict)
                else [],
                "signal_label": label,
                "signal_zscore": zscore,
            }

        stats_adf = (
            cast(dict[str, Any], statistical_results.get("stationarity_results"))
            if isinstance(statistical_results, dict)
            and isinstance(statistical_results.get("stationarity_results"), dict)
            else None
        )
        stats_granger_results = (
            cast(list[dict[str, Any]], statistical_results.get("granger", []))
            if isinstance(statistical_results, dict)
            and isinstance(statistical_results.get("granger", []), list)
            else []
        )
        stats_granger_skips = (
            cast(list[dict[str, Any]], statistical_results.get("granger_skips", []))
            if isinstance(statistical_results, dict)
            and isinstance(statistical_results.get("granger_skips", []), list)
            else []
        )
        stats_granger_skip_summary = (
            cast(dict[str, int], statistical_results.get("granger_skip_summary", {}))
            if isinstance(statistical_results, dict)
            and isinstance(statistical_results.get("granger_skip_summary", {}), dict)
            else {}
        )
        stats_granger_eligible_rows = (
            cast(int, statistical_results.get("granger_eligible_rows"))
            if isinstance(statistical_results, dict)
            and isinstance(statistical_results.get("granger_eligible_rows"), int)
            else None
        )
        stats_granger_executed = (
            bool(statistical_results.get("granger_executed"))
            if isinstance(statistical_results, dict)
            else False
        )
        alpha_hit_rates = (
            cast(list[dict[str, Any]], alpha_validation_results.get("hit_rates"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("hit_rates"), list)
            else None
        )
        alpha_correlations = (
            cast(list[dict[str, Any]], alpha_validation_results.get("correlations"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("correlations"), list)
            else None
        )
        alpha_backtest = (
            cast(list[dict[str, Any]], alpha_validation_results.get("backtest"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("backtest"), list)
            else None
        )
        alpha_walk_forward = (
            cast(dict[str, Any], alpha_validation_results.get("walk_forward"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("walk_forward"), dict)
            else None
        )
        alpha_baseline_metrics = (
            cast(dict[str, Any], alpha_validation_results.get("baseline_metrics"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("baseline_metrics"), dict)
            else None
        )
        alpha_horizon_metrics = (
            cast(dict[str, Any], alpha_validation_results.get("horizon_metrics"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("horizon_metrics"), dict)
            else None
        )
        alpha_walk_forward_horizons = (
            cast(dict[str, Any], alpha_validation_results.get("walk_forward_horizons"))
            if isinstance(alpha_validation_results, dict)
            and isinstance(alpha_validation_results.get("walk_forward_horizons"), dict)
            else None
        )

        stats_metadata = build_stats_metadata_payload(
            run_id=f"sentiment-join-{run_date}",
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            adf=stats_adf,
            granger_results=stats_granger_results,
            hybrid_indices=hybrid_indices_meta,
            rows_before_outlier_filter=len(master_df),
            rows_after_outlier_filter=len(analysis_df),
            outlier_filtered_count=masked_count,
            outlier_filtered_ratio=masked_ratio,
            granger_eligible_rows=stats_granger_eligible_rows,
            granger_executed=stats_granger_executed,
            granger_skips=stats_granger_skips,
            granger_skip_summary=stats_granger_skip_summary,
            exclusion_counts=exclusion_counts if exclusion_counts else None,
            granger_correction=(
                _build_granger_correction(statistical_results)
                if isinstance(statistical_results, dict)
                and statistical_results.get("granger_executed")
                else None
            ),
            hit_rates=alpha_hit_rates,
            correlations=alpha_correlations,
            backtest=alpha_backtest,
            walk_forward=alpha_walk_forward,
            baseline_metrics=alpha_baseline_metrics,
            horizon_metrics=alpha_horizon_metrics,
            walk_forward_horizons=alpha_walk_forward_horizons,
            ffill_breakdown=ffill_breakdown,
            target_diagnostics=_target_diagnostics(master_df),
            structured_sources=structured_sources,
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
        write_backfill_manifest(
            settings.output_dir,
            {
                "run_id": f"sentiment-join-{run_date}",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "structured_sources": structured_sources,
                "column_lineage": {
                    col: sorted(str(v) for v in master_df[col].dropna().unique())
                    for col in master_df.columns
                    if col.endswith("_source")
                },
            },
        )
        cleanup_old_files(settings.output_dir, settings.retain_days)
        upload_to_r2(
            path,
            f"sentiment_join/{path.name}",
            r2_s3_endpoint=settings.r2_s3_endpoint,
            r2_access_key_id=settings.r2_access_key_id,
            r2_secret_access_key=settings.r2_secret_access_key,
            r2_public_bucket=settings.r2_public_bucket,
        )

        # §5: 프론트엔드 소비용 아티팩트 추출 및 R2 업로드
        # 통계 로직 수정 없이 이미 만들어진 stats_metadata bytes에서 필드만 필터링한다.
        if stats_metadata is not None:
            from .frontend_artifact import (
                build_frontend_artifact,
                should_skip_artifact,
                write_frontend_artifact,
            )

            fe_artifact = build_frontend_artifact(
                stats_metadata_bytes=stats_metadata,
                reference_date=today.strftime("%Y-%m-%d"),
            )
            if not should_skip_artifact(fe_artifact):
                latest_path, dated_path = write_frontend_artifact(
                    settings.output_dir, fe_artifact, run_date
                )
                for local_path, r2_key in (
                    (latest_path, "analytics/sentiment/latest.json"),
                    (dated_path, f"analytics/sentiment/{run_date}.json"),
                ):
                    upload_to_r2(
                        local_path,
                        r2_key,
                        r2_s3_endpoint=settings.r2_s3_endpoint,
                        r2_access_key_id=settings.r2_access_key_id,
                        r2_secret_access_key=settings.r2_secret_access_key,
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
