from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

OI_PRICE_DIVERGENCE_COLUMNS: tuple[str, ...] = (
    "btc_return_7d",
    "btc_return_7d_lag1",
    "open_interest_change_7d",
    "open_interest_change_7d_lag1",
    "oi_price_divergence_flag_7d",
    "oi_price_divergence_flag_7d_lag1",
    "oi_price_divergence_score_7d",
    "oi_price_divergence_score_7d_lag1",
)


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


def _add_oi_price_divergence_features(df: pd.DataFrame) -> pd.DataFrame:
    """BTC 7일 수익률과 OI 7일 변화율의 방향 불일치 feature를 생성한다."""
    result = df.copy()
    if "btc_log_return" in result.columns:
        btc_log_return = pd.to_numeric(result["btc_log_return"], errors="coerce")
        result["btc_return_7d"] = np.expm1(btc_log_return.rolling(7, min_periods=7).sum())
    else:
        result["btc_return_7d"] = float("nan")

    if "open_interest_usd" in result.columns:
        oi = pd.to_numeric(result["open_interest_usd"], errors="coerce").where(
            lambda values: values > 0
        )
        result["open_interest_change_7d"] = oi.pct_change(periods=7, fill_method=None)
    else:
        result["open_interest_change_7d"] = float("nan")

    btc_7d = pd.to_numeric(result["btc_return_7d"], errors="coerce")
    oi_7d = pd.to_numeric(result["open_interest_change_7d"], errors="coerce")
    valid = btc_7d.notna() & oi_7d.notna()
    diverged = valid & ((btc_7d * oi_7d) < 0)

    flag = pd.Series(np.nan, index=result.index, dtype="float64")
    flag.loc[valid] = 0.0
    flag.loc[diverged] = 1.0
    result["oi_price_divergence_flag_7d"] = flag

    score = pd.Series(np.nan, index=result.index, dtype="float64")
    score.loc[valid] = 0.0
    score.loc[diverged] = btc_7d.loc[diverged].abs() * oi_7d.loc[diverged].abs()
    result["oi_price_divergence_score_7d"] = score

    for col in (
        "btc_return_7d",
        "open_interest_change_7d",
        "oi_price_divergence_flag_7d",
        "oi_price_divergence_score_7d",
    ):
        result[f"{col}_lag1"] = result[col].shift(1)
    return result


def _add_futures_lag_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Req 11.3: 선물 지표에 Lag-1 처리를 적용해 미래 오염을 방지합니다.

    §0: Granger에는 raw 컬럼을 투입해야 double-lag를 방지할 수 있으므로
    raw와 _lag1을 함께 생성합니다. PCA·correlation에는 _lag1을 사용합니다.
    """
    result = df.copy()
    if "funding_rate" in result.columns:
        result["funding_rate_lag1"] = result["funding_rate"].shift(1)
    else:
        result["funding_rate_lag1"] = float("nan")
    if "open_interest_usd" in result.columns:
        oi = pd.to_numeric(result["open_interest_usd"], errors="coerce")
        result["oi_change_pct"] = oi.pct_change()
        result["oi_change_pct_lag1"] = result["oi_change_pct"].shift(1)
    else:
        result["oi_change_pct"] = float("nan")
        result["oi_change_pct_lag1"] = float("nan")
    if "btc_long_short_ratio" in result.columns:
        result["btc_long_short_ratio_lag1"] = result["btc_long_short_ratio"].shift(1)
    else:
        result["btc_long_short_ratio_lag1"] = float("nan")
    # funding_rate z-score: rolling stats는 t-1까지만 사용해 look-ahead bias 차단
    if "funding_rate" in result.columns:
        fr = pd.to_numeric(result["funding_rate"], errors="coerce")
        fr_roll = fr.shift(1).rolling(30, min_periods=20)
        result["funding_rate_zscore_30d"] = (fr - fr_roll.mean()) / fr_roll.std()
        result["funding_rate_zscore_30d_lag1"] = result["funding_rate_zscore_30d"].shift(1)
    else:
        result["funding_rate_zscore_30d"] = float("nan")
        result["funding_rate_zscore_30d_lag1"] = float("nan")
    # long_short_ratio z-score: 동일 패턴
    if "btc_long_short_ratio" in result.columns:
        lsr = pd.to_numeric(result["btc_long_short_ratio"], errors="coerce")
        lsr_roll = lsr.shift(1).rolling(30, min_periods=20)
        result["long_short_ratio_zscore_30d"] = (lsr - lsr_roll.mean()) / lsr_roll.std()
        result["long_short_ratio_zscore_30d_lag1"] = result["long_short_ratio_zscore_30d"].shift(1)
    else:
        result["long_short_ratio_zscore_30d"] = float("nan")
        result["long_short_ratio_zscore_30d_lag1"] = float("nan")
    if "etf_net_inflow_usd" in result.columns:
        result["etf_net_inflow_usd_lag1"] = result["etf_net_inflow_usd"].shift(1)
    else:
        result["etf_net_inflow_usd_lag1"] = float("nan")
    # §7: volume_change_pct raw (Granger용) + lag1 (PCA용)
    if "btc_quote_volume" in result.columns:
        vol = pd.to_numeric(result["btc_quote_volume"], errors="coerce")
        result["volume_change_pct"] = vol.pct_change()
        result["volume_change_pct_lag1"] = result["volume_change_pct"].shift(1)
    else:
        result["volume_change_pct"] = float("nan")
        result["volume_change_pct_lag1"] = float("nan")
    # §4 3-4: VIX optional feature. 수집 실패 시 vix 컬럼이 없으므로 NaN 채우기.
    if "vix" in result.columns:
        result["vix"] = pd.to_numeric(result["vix"], errors="coerce")
        result["vix_lag1"] = result["vix"].shift(1)
    else:
        result["vix"] = float("nan")
        result["vix_lag1"] = float("nan")
    result = _add_oi_price_divergence_features(result)
    return result


def _add_sentiment_lag_columns(df: pd.DataFrame) -> pd.DataFrame:
    """감성·공포지수·환율에 Lag-1 처리를 적용해 look-ahead bias를 제거합니다.

    §0: PCA·correlation용 lag1 컬럼. Granger 검정에는 raw 컬럼을 사용한다(double-lag 방지).
    lag1 = T-1 시점 값 (.shift(1)).

    - news_sentiment_mean_lag1: T-1 시점의 원본 감성 값
    - fng_value_lag1: Int64 → float 변환 후 .shift(1)
    - usdkrw_log_return_lag1: PCA·correlation용. Granger에는 raw usdkrw_log_return 사용.
    """
    result = df.copy()
    if "news_sentiment_mean" in result.columns:
        result["news_sentiment_mean_lag1"] = result["news_sentiment_mean"].shift(1)
    else:
        result["news_sentiment_mean_lag1"] = float("nan")
    if "fng_value" in result.columns:
        # Int64(nullable integer) → float64 명시적 변환 후 shift (MASTER_SCHEMA float 타입 충족)
        result["fng_value_lag1"] = (
            pd.to_numeric(result["fng_value"], errors="coerce").astype("float64").shift(1)
        )
    else:
        result["fng_value_lag1"] = float("nan")
    if "usdkrw_log_return" in result.columns:
        result["usdkrw_log_return_lag1"] = result["usdkrw_log_return"].shift(1)
    else:
        result["usdkrw_log_return_lag1"] = float("nan")
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


def _add_delta_features(df: pd.DataFrame) -> pd.DataFrame:
    """1-A: level → delta 변환으로 AR 구조를 제거해 Granger/correlation 신호 품질 개선.

    fng_change_1d       : FnG 1일 변화량 (AR 0.97 → 차분 시 ~0.1 이하)
    fng_change_5d       : FnG 5일 변화량 (중기 추세)
    sentiment_momentum  : 감성 - 7일 이동평균 이탈도 (AR 0.81 구조 제거)
    sentiment_accel     : 감성 1일 변화 (가속도)

    _lag1 버전은 look-ahead bias 차단용 (PCA / correlation 입력).
    Granger 검정에는 raw 버전을 사용한다 (double-lag 방지).
    """
    result = df.copy()

    if "fng_value" in result.columns:
        fng = pd.to_numeric(result["fng_value"], errors="coerce").astype("float64")
        result["fng_change_1d"] = fng.diff(1)
        result["fng_change_5d"] = fng.diff(5)
    else:
        result["fng_change_1d"] = float("nan")
        result["fng_change_5d"] = float("nan")
    result["fng_change_1d_lag1"] = result["fng_change_1d"].shift(1)
    result["fng_change_5d_lag1"] = result["fng_change_5d"].shift(1)

    if "news_sentiment_mean" in result.columns:
        sent = pd.to_numeric(result["news_sentiment_mean"], errors="coerce")
        result["sentiment_momentum"] = sent - sent.rolling(7, min_periods=4).mean()
        result["sentiment_accel"] = sent.diff(1)
    else:
        result["sentiment_momentum"] = float("nan")
        result["sentiment_accel"] = float("nan")
    result["sentiment_momentum_lag1"] = result["sentiment_momentum"].shift(1)
    result["sentiment_accel_lag1"] = result["sentiment_accel"].shift(1)

    return result


def _add_regime_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """Bear-regime conditioned lagged features for alpha validation."""
    result = df.copy()
    if "btc_above_ma200" in result.columns:
        above = pd.to_numeric(result["btc_above_ma200"], errors="coerce")
        bear = pd.Series(float("nan"), index=result.index, dtype="float64")
        valid = above.notna()
        bear.loc[valid] = (above.loc[valid] == 0.0).astype(float)
    else:
        bear = pd.Series(float("nan"), index=result.index, dtype="float64")

    result["btc_bear_regime_lag1"] = bear.shift(1)
    interaction_sources = {
        "sentiment_momentum_x_bear_lag1": "sentiment_momentum_lag1",
        "fng_change_1d_x_bear_lag1": "fng_change_1d_lag1",
        "funding_rate_x_bear_lag1": "funding_rate_lag1",
    }
    for out_col, source_col in interaction_sources.items():
        if source_col in result.columns:
            result[out_col] = (
                pd.to_numeric(result[source_col], errors="coerce") * result["btc_bear_regime_lag1"]
            )
        else:
            result[out_col] = float("nan")
    return result


def _add_vix_regime_feature(result: pd.DataFrame) -> pd.DataFrame:
    """VIX rolling median 대비 상대적 위치를 연속값으로 파생.

    vix_regime_score = (rolling_median - vix) / (rolling_median.abs() + 1e-8), clip [-3, 3]
    양수 = VIX < median (low-vol, risk-on), 음수 = VIX > median (high-vol, risk-off).
    vol_regime() baseline의 adaptive threshold 로직과 동일한 방향성을 연속값으로 표현해
    PCA가 체제 정보를 흡수할 수 있도록 한다.
    """
    if "vix" not in result.columns:
        result["vix_regime_score"] = float("nan")
        result["vix_regime_score_lag1"] = float("nan")
        return result

    vix = pd.to_numeric(result["vix"], errors="coerce")
    median = vix.rolling(60, min_periods=10).median()
    score = ((median - vix) / (median.abs() + 1e-8)).clip(-3.0, 3.0)
    result["vix_regime_score"] = score
    result["vix_regime_score_lag1"] = score.shift(1)
    return result


def _add_regime_quantile_features(result: pd.DataFrame) -> pd.DataFrame:
    """Regime 분류용 롤링 분위수 컬럼 사전 계산.

    risk_overlay.py 가 .tail() 슬라이스 없이 이 컬럼의 마지막 행만 읽도록 한다.
    호출 시점 독립성을 보장하므로 어떤 df 슬라이스로 compute_regime_state()를 호출해도
    동일한 결과가 나온다.

    vix_q40_90d  : VIX 90일 롤링 q40  (BullQuiet / vol_regime_v2 기준)
    vix_q80_90d  : VIX 90일 롤링 q80  (BearPanic 기준)
    rv_q45_45d   : realized_vol_20d 45일 롤링 q45
    fng_q70_90d  : FNG 90일 롤링 q70  (탐욕 상단 적응형 임계값)
    """
    if "vix" in result.columns:
        vix = pd.to_numeric(result["vix"], errors="coerce")
        result["vix_q40_90d"] = vix.rolling(90, min_periods=30).quantile(0.40)
        result["vix_q80_90d"] = vix.rolling(90, min_periods=30).quantile(0.80)
    else:
        result["vix_q40_90d"] = float("nan")
        result["vix_q80_90d"] = float("nan")

    rv_col = "btc_realized_vol_20d_lag1"
    if rv_col in result.columns:
        rv = pd.to_numeric(result[rv_col], errors="coerce")
        result["rv_q45_45d"] = rv.rolling(45, min_periods=20).quantile(0.45)
    else:
        result["rv_q45_45d"] = float("nan")

    if "fng_value" in result.columns:
        fng = pd.to_numeric(result["fng_value"], errors="coerce")
        # FNG는 0-100 bounded + AR≈0.96이므로 rolling quantile이 절대값보다 적응적
        result["fng_q70_90d"] = fng.rolling(90, min_periods=30).quantile(0.70)
    else:
        result["fng_q70_90d"] = float("nan")

    return result


def _add_macro_features(df: pd.DataFrame) -> pd.DataFrame:
    """Macro feature 파생: USD 광의지수·US10Y·Nasdaq 7일 변화 + zscore.

    usd_broad_index_change_7d   : DTWEXBGS 7일 pct_change (주별 ffill 기반)
    usd_broad_index_zscore_30d  : change_7d의 shift(1).rolling(30) z-score
    us10y_change_7d             : DGS10 7일 level diff (%p)
    nasdaq_return_7d            : NASDAQCOM 7일 pct_change
    _lag1 버전은 look-ahead bias 차단용.
    """
    result = df.copy()

    # USD 광의지수 (DTWEXBGS, 주별 → ffill 후 입력됨)
    if "usd_broad_index" in result.columns:
        idx = pd.to_numeric(result["usd_broad_index"], errors="coerce")
        result["usd_broad_index_change_7d"] = idx.pct_change(periods=7, fill_method=None)
        chg = result["usd_broad_index_change_7d"]
        roll = chg.shift(1).rolling(30, min_periods=20)
        result["usd_broad_index_zscore_30d"] = (chg - roll.mean()) / roll.std()
    else:
        result["usd_broad_index_change_7d"] = float("nan")
        result["usd_broad_index_zscore_30d"] = float("nan")

    # US 10년물 (DGS10, 단위: %)
    if "us10y" in result.columns:
        y10 = pd.to_numeric(result["us10y"], errors="coerce")
        result["us10y_change_7d"] = y10.diff(periods=7)
    else:
        result["us10y_change_7d"] = float("nan")

    # Nasdaq (NASDAQCOM)
    if "nasdaq" in result.columns:
        ndx = pd.to_numeric(result["nasdaq"], errors="coerce")
        result["nasdaq_return_7d"] = ndx.pct_change(periods=7, fill_method=None)
    else:
        result["nasdaq_return_7d"] = float("nan")

    for col in (
        "usd_broad_index_change_7d",
        "usd_broad_index_zscore_30d",
        "us10y_change_7d",
        "nasdaq_return_7d",
    ):
        result[f"{col}_lag1"] = result[col].shift(1)

    return result


def _add_breadth_features(df: pd.DataFrame) -> pd.DataFrame:
    """Market breadth: Binance top10 alt 7일 수익률 기반 지표 파생.

    binance_top10_up_ratio_7d   : 10개 중 7일 수익률 > 0인 비율 (0.0 ~ 1.0)
    binance_top10_ew_return_7d  : 10개 7일 수익률 단순 평균
    _lag1 버전은 look-ahead bias 차단용.
    breadth_df가 merge되지 않은 경우(컬럼 없음) NaN 컬럼만 생성.
    """
    from morning_brief.analysis.sentiment_join.sources.binance_breadth import BREADTH_SYMBOLS

    result = df.copy()
    close_cols = [f"{sym}_close" for sym in BREADTH_SYMBOLS]
    present = [c for c in close_cols if c in result.columns]

    if present:
        closes = result[present]
        ret7 = closes.pct_change(periods=7, fill_method=None)
        result["binance_top10_up_ratio_7d"] = (ret7 > 0).sum(axis=1) / len(present)
        result["binance_top10_ew_return_7d"] = ret7.mean(axis=1)
    else:
        result["binance_top10_up_ratio_7d"] = float("nan")
        result["binance_top10_ew_return_7d"] = float("nan")

    result["binance_top10_up_ratio_7d_lag1"] = result["binance_top10_up_ratio_7d"].shift(1)
    result["binance_top10_ew_return_7d_lag1"] = result["binance_top10_ew_return_7d"].shift(1)
    return result


def _add_taker_features(df: pd.DataFrame) -> pd.DataFrame:
    """Taker buy pressure: 30d z-score 및 7d rolling ratio 파생.

    btc_taker_buy_ratio_7d          : 7일 rolling taker buy ratio (mean)
    btc_taker_imbalance_zscore_30d  : (daily_ratio - 30d_mean) / 30d_std, 매수 치우침 정도
    _lag1 버전은 look-ahead bias 차단용.
    """
    result = df.copy()
    taker_buy = pd.to_numeric(result.get("btc_taker_buy_quote_volume"), errors="coerce")
    total_vol = pd.to_numeric(result.get("btc_quote_volume"), errors="coerce").replace(0, pd.NA)
    daily_ratio = taker_buy / total_vol

    result["btc_taker_buy_ratio_7d"] = daily_ratio.rolling(7, min_periods=4).mean()

    roll30 = daily_ratio.rolling(30, min_periods=20)
    result["btc_taker_imbalance_zscore_30d"] = (daily_ratio - roll30.mean()) / roll30.std()

    result["btc_taker_imbalance_zscore_30d_lag1"] = result["btc_taker_imbalance_zscore_30d"].shift(
        1
    )
    result["btc_taker_buy_ratio_7d_lag1"] = result["btc_taker_buy_ratio_7d"].shift(1)
    return result


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


FWD_LARGE_MOVE_3D_THRESHOLD: float = 0.03
"""|btc_fwd_ret_3d| > 3% 를 'large move' 로 라벨링한다 (≈ 3-day log return 3%)."""

BTC_REALIZED_VOL_20D_MIN_PERIODS: int = 10
FWD_LARGE_MOVE_3D_VOL_MULTIPLIER: float = 1.5

FORWARD_TARGET_COLUMNS: tuple[str, ...] = (
    "btc_fwd_ret_1d",
    "btc_fwd_ret_3d",
    "btc_fwd_ret_7d",
    "btc_fwd_vol_5d",
    "btc_large_move_3d",
    "btc_realized_vol_20d_lag1",
    "btc_large_move_3d_vol_adj",
)


def _add_forward_target_columns(df: pd.DataFrame) -> pd.DataFrame:
    """멀티 호라이즌 예측 타겟 5종을 부착한다.

    모든 타겟은 T+1 이후 값만 사용해 lookahead 를 차단한다. 마지막 k개 행은 NaN 으로 남는다.

    - btc_fwd_ret_1d: 1일 forward log return (= btc_log_return.shift(-1))
    - btc_fwd_ret_3d: T+1..T+3 누적 log return
    - btc_fwd_ret_7d: T+1..T+7 누적 log return
    - btc_fwd_vol_5d: T+1..T+5 의 log return 표준편차
    - btc_large_move_3d: |fwd_ret_3d| > FWD_LARGE_MOVE_3D_THRESHOLD 이진 (Int64, NaN 허용)
    """
    result = df.copy()

    if "btc_log_return" not in result.columns:
        for col in FORWARD_TARGET_COLUMNS:
            if col in {"btc_large_move_3d", "btc_large_move_3d_vol_adj"}:
                result[col] = pd.array([pd.NA] * len(result), dtype="Int64")
            else:
                result[col] = float("nan")
        return result

    ret = pd.to_numeric(result["btc_log_return"], errors="coerce")
    result["btc_realized_vol_20d_lag1"] = (
        ret.rolling(20, min_periods=BTC_REALIZED_VOL_20D_MIN_PERIODS).std(ddof=1).shift(1)
    )

    # 1-day forward
    result["btc_fwd_ret_1d"] = ret.shift(-1)

    # k-day cumulative forward log return: cumsum(t+k) - cumsum(t)
    cumret = ret.cumsum()
    for k in (3, 7):
        result[f"btc_fwd_ret_{k}d"] = cumret.shift(-k) - cumret

    # 5-day forward volatility: std(ret[t+1..t+5]).
    # skipna=False 로 5개 중 하나라도 NaN 이면 결과도 NaN 으로 엄격 처리한다.
    fwd_frame = pd.concat(
        [ret.shift(-i).rename(f"_f{i}") for i in range(1, 6)],
        axis=1,
    )
    result["btc_fwd_vol_5d"] = fwd_frame.std(axis=1, ddof=1, skipna=False)

    # Binary large-move label (T+3 window)
    fwd_3d = result["btc_fwd_ret_3d"]
    large_move = pd.array(
        [pd.NA] * len(result),
        dtype="Int64",
    )
    valid = fwd_3d.notna()
    large_move[valid.to_numpy()] = (
        (fwd_3d[valid].abs() > FWD_LARGE_MOVE_3D_THRESHOLD).astype(int).to_numpy()
    )
    result["btc_large_move_3d"] = large_move

    vol_adj = pd.array(
        [pd.NA] * len(result),
        dtype="Int64",
    )
    vol_threshold = (
        FWD_LARGE_MOVE_3D_VOL_MULTIPLIER * result["btc_realized_vol_20d_lag1"] * math.sqrt(3)
    )
    adaptive_threshold = vol_threshold.clip(lower=FWD_LARGE_MOVE_3D_THRESHOLD)
    valid_vol_adj = fwd_3d.notna() & adaptive_threshold.notna()
    vol_adj[valid_vol_adj.to_numpy()] = (
        (fwd_3d[valid_vol_adj].abs() > adaptive_threshold[valid_vol_adj]).astype(int).to_numpy()
    )
    result["btc_large_move_3d_vol_adj"] = vol_adj

    return result


def _add_stablecoin_features(df: pd.DataFrame) -> pd.DataFrame:
    """Stablecoin supply feature lag1 파생.

    usdt_usdc_supply_change_7d 컬럼이 merge된 경우에만 lag1을 계산합니다.
    """
    if "usdt_usdc_supply_change_7d" in df.columns:
        df = df.copy()
        df["usdt_usdc_supply_change_7d_lag1"] = df["usdt_usdc_supply_change_7d"].shift(1)
    return df


def merge_sources(
    sentiment_df: pd.DataFrame,
    fng_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    usdkrw_df: pd.DataFrame,
    futures_df: pd.DataFrame | None = None,
    etf_df: pd.DataFrame | None = None,
    vix_df: pd.DataFrame | None = None,
    regime_df: pd.DataFrame | None = None,
    macro_df: pd.DataFrame | None = None,
    breadth_df: pd.DataFrame | None = None,
    stablecoin_df: pd.DataFrame | None = None,
    *,
    record_source_lineage: bool = True,
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

    # §4 3-4: VIX optional — fetch 실패 시 vix_df가 None/empty이면 NaN 컬럼으로 left-join fallback.
    if vix_df is not None and not vix_df.empty:
        vix_cols = [c for c in vix_df.columns if c != "date"]
        merged = merged.merge(vix_df[["date"] + vix_cols], on="date", how="left")
    else:
        merged["vix"] = float("nan")

    # TODO(exchange-outflow): BTC 거래소 순유출 온체인 피처 연결 지점
    # exchange_outflow.py 구현 완료 후 아래 주석을 해제하고 merge_sources() 시그니처에
    # outflow_df: pd.DataFrame | None = None 파라미터를 추가하세요.
    #
    # from morning_brief.analysis.sentiment_join.sources.exchange_outflow import (
    #     fetch_exchange_outflow,
    # )
    # if outflow_df is not None and not outflow_df.empty:
    #     merged = merged.merge(
    #         outflow_df[["date", "btc_exchange_net_outflow_usd"]], on="date", how="left"
    #     )
    # else:
    #     merged["btc_exchange_net_outflow_usd"] = float("nan")
    # merged["btc_exchange_net_outflow_usd_lag1"] = (
    #     pd.to_numeric(merged.get("btc_exchange_net_outflow_usd"), errors="coerce").shift(1)
    # )

    # 1-B: BTC 레짐 피처 — 200일 MA 기반 bull/bear 조건 변수
    if regime_df is not None and not regime_df.empty:
        regime_cols = [c for c in regime_df.columns if c != "date"]
        merged = merged.merge(regime_df[["date"] + regime_cols], on="date", how="left")
    else:
        merged["btc_ma_200d"] = float("nan")
        merged["btc_drawdown_90d"] = float("nan")
        merged["btc_above_ma200"] = float("nan")
    merged["btc_above_ma200_lag1"] = pd.to_numeric(
        merged.get("btc_above_ma200"), errors="coerce"
    ).shift(1)

    # Macro feature 조인 (usd_broad_index / us10y / nasdaq)
    if macro_df is not None and not macro_df.empty:
        macro_cols = [c for c in macro_df.columns if c != "date"]
        merged = merged.merge(macro_df[["date"] + macro_cols], on="date", how="left")
    else:
        for col in ("usd_broad_index", "us10y", "nasdaq"):
            if col not in merged.columns:
                merged[col] = float("nan")

    # Breadth feature 조인 (ETHUSDT_close, BNBUSDT_close, ...)
    if breadth_df is not None and not breadth_df.empty:
        breadth_cols = [c for c in breadth_df.columns if c != "date"]
        merged = merged.merge(breadth_df[["date"] + breadth_cols], on="date", how="left")

    # Stablecoin supply feature 조인 (usdt_usdc_supply_change_7d)
    if stablecoin_df is not None and not stablecoin_df.empty:
        sc_cols = [c for c in stablecoin_df.columns if c != "date"]
        merged = merged.merge(stablecoin_df[["date"] + sc_cols], on="date", how="left")

    if record_source_lineage:
        futures_source = (
            str(futures_df.attrs.get("futures_source", "unknown"))
            if futures_df is not None and not futures_df.empty
            else "empty"
        )
        etf_source = (
            str(etf_df.attrs.get("source_mode", "unknown"))
            if etf_df is not None and not etf_df.empty
            else "empty"
        )
        vix_source = (
            str(vix_df.attrs.get("source_mode", "fred"))
            if vix_df is not None and not vix_df.empty
            else "empty"
        )
        merged["funding_source"] = futures_source
        merged["oi_source"] = futures_source
        merged["lsr_source"] = futures_source
        merged["etf_source"] = etf_source
        merged["vix_source"] = vix_source

    # §7: btc_quote_volume 누락 방어 — _empty_return_frame fallback 경로에서 컬럼이 없을 수 있음
    if "btc_quote_volume" not in merged.columns:
        merged["btc_quote_volume"] = float("nan")
    if "btc_taker_buy_quote_volume" not in merged.columns:
        merged["btc_taker_buy_quote_volume"] = float("nan")

    merged = _add_futures_lag_columns(merged)
    merged = _add_sentiment_lag_columns(merged)
    merged = _add_delta_features(merged)
    merged = _add_regime_interaction_features(merged)
    merged = _add_vix_regime_feature(merged)
    merged = _add_taker_features(merged)
    merged = _add_macro_features(merged)
    merged = _add_breadth_features(merged)
    merged = _add_stablecoin_features(merged)
    merged = _add_regime_quantile_features(merged)
    # raw close 컬럼은 파생 피처 계산 후 제거 (MASTER_SCHEMA strict=True)
    from morning_brief.analysis.sentiment_join.sources.binance_breadth import BREADTH_SYMBOLS

    _close_cols = [f"{s}_close" for s in BREADTH_SYMBOLS if f"{s}_close" in merged.columns]
    if _close_cols:
        merged = merged.drop(columns=_close_cols)
    merged = _add_btc_direction_label(merged)
    merged = _add_forward_target_columns(merged)

    # §2: text_schema_version — R2 페이로드에서 전달되지 않은 경우 None으로 채움
    if "text_schema_version" not in merged.columns:
        merged["text_schema_version"] = None
    merged = detect_outliers_rolling_iqr(
        merged,
        cols=[
            # 변화율·수익률 계열에만 rolling IQR 적용.
            # level/bounded 컬럼(fng_value[0,100], news_sentiment_mean[-1,1],
            # btc_long_short_ratio, open_interest_usd, btc_quote_volume)은
            # 분포 특성상 false positive가 많아 제외.
            # etf_net_inflow_usd 제외: 주말 구조적 0값 때문에 rolling IQR이 극소화되어
            # 평일 대형 유입이 모두 outlier로 오탐됨 (false positive 주요 원인).
            "btc_return",
            "usdkrw_return",
            "funding_rate",
            "oi_change_pct",
            "volume_change_pct",
        ],
        window=60,  # 30→60: IQR 추정 안정성 향상 (단기 변동성 급변에 덜 민감)
        min_periods=20,  # window 비례 조정
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
    "OI_PRICE_DIVERGENCE_COLUMNS",
    "detect_outliers_rolling_iqr",
    "merge_sources",
    "_add_oi_price_divergence_features",
    "_add_futures_lag_columns",
    "_add_sentiment_lag_columns",
    "_add_delta_features",
    "_add_regime_interaction_features",
    "_add_taker_features",
    "_add_macro_features",
    "_add_breadth_features",
    "_add_stablecoin_features",
    "_add_btc_direction_label",
    "_add_forward_target_columns",
    "_apply_sentiment_quality_gate",
    "BTC_REALIZED_VOL_20D_MIN_PERIODS",
    "FORWARD_TARGET_COLUMNS",
    "FWD_LARGE_MOVE_3D_VOL_MULTIPLIER",
    "FWD_LARGE_MOVE_3D_THRESHOLD",
]
