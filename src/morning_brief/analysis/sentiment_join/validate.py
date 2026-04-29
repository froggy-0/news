from __future__ import annotations

import logging

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaError, SchemaErrors

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MASTER_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}-\d{2}$"), unique=True),
        "news_sentiment_mean": pa.Column(float, pa.Check.between(-1.0, 1.0), nullable=False),
        "news_sentiment_std": pa.Column(float, pa.Check.ge(0), nullable=True),
        "n_articles": pa.Column("Int64", pa.Check.ge(0), nullable=True),
        "sentiment_status": pa.Column(str, nullable=True),
        "is_backfill_valid": pa.Column(bool, nullable=True),
        "ingest_validation_reason": pa.Column(nullable=True),
        "fng_value": pa.Column("Int64", pa.Check.between(0, 100), nullable=True),
        "btc_log_return": pa.Column(float, nullable=True),
        "btc_return": pa.Column(float, nullable=True),
        "btc_quote_volume": pa.Column(float, pa.Check.ge(0), nullable=True),
        "usdkrw_log_return": pa.Column(float, nullable=True),
        "usdkrw_return": pa.Column(float, nullable=True),
        "is_outlier": pa.Column(bool, nullable=False),
        # Req 11: 선물 시장 지표 (수집 실패 시 NaN 허용)
        "funding_rate": pa.Column(float, nullable=True),
        "open_interest_usd": pa.Column(float, nullable=True),
        "funding_rate_lag1": pa.Column(float, nullable=True),
        # §3: Granger raw predictors — Granger 내부에서 lag 처리, double-lag 방지
        "oi_change_pct": pa.Column(float, nullable=True),
        "oi_change_pct_lag1": pa.Column(float, nullable=True),
        "btc_long_short_ratio": pa.Column(float, pa.Check.ge(0), nullable=True),
        "btc_long_short_ratio_lag1": pa.Column(float, nullable=True),
        "etf_total_btc": pa.Column(float, pa.Check.ge(0), nullable=True),
        "etf_total_aum_usd": pa.Column(float, pa.Check.ge(0), nullable=True),
        "etf_net_inflow_usd": pa.Column(float, nullable=True),
        "etf_net_inflow_usd_lag1": pa.Column(float, nullable=True),
        # §3: Granger raw predictor
        "volume_change_pct": pa.Column(float, nullable=True),
        # §5: PCA / correlation용 lag1 (Granger에는 미사용)
        "usdkrw_log_return_lag1": pa.Column(float, nullable=True),
        "volume_change_pct_lag1": pa.Column(float, nullable=True),
        # §4 3-4: VIX optional feature. 수집 실패/키 미설정 시 전 행 NaN.
        "vix": pa.Column(float, nullable=True),
        "vix_lag1": pa.Column(float, nullable=True),
        "vix_regime_score": pa.Column(float, nullable=True),
        "vix_regime_score_lag1": pa.Column(float, nullable=True),
        "funding_source": pa.Column(str, nullable=True),
        "oi_source": pa.Column(str, nullable=True),
        "lsr_source": pa.Column(str, nullable=True),
        "etf_source": pa.Column(str, nullable=True),
        "vix_source": pa.Column(str, nullable=True),
        # Req 8: BTC 방향 라벨
        "btc_direction_label": pa.Column(nullable=True),
        # Multi-horizon forward targets (last k rows are NaN by design — lookahead 차단)
        "btc_fwd_ret_1d": pa.Column(float, nullable=True),
        "btc_fwd_ret_3d": pa.Column(float, nullable=True),
        "btc_fwd_ret_7d": pa.Column(float, nullable=True),
        "btc_fwd_vol_5d": pa.Column(float, pa.Check.ge(0), nullable=True),
        "btc_large_move_3d": pa.Column("Int64", pa.Check.isin([0, 1]), nullable=True),
        "btc_realized_vol_20d_lag1": pa.Column(float, pa.Check.ge(0), nullable=True),
        "btc_large_move_3d_vol_adj": pa.Column("Int64", pa.Check.isin([0, 1]), nullable=True),
        # §4 v4: full / core 이중 하이브리드 지수 + 0~100 score.
        # 이전 단일 `hybrid_index` 컬럼은 v4에서 삭제되었습니다.
        "full_hybrid_index": pa.Column(float, nullable=True),
        "full_hybrid_index_score": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        "core_hybrid_index": pa.Column(float, nullable=True),
        "core_hybrid_index_score": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        # §4 v4: hybrid index score Lag-1 — alpha validation용 (첫 행은 NaN)
        "full_hybrid_index_score_lag1": pa.Column(
            float, pa.Check.between(0.0, 100.0), nullable=True
        ),
        "core_hybrid_index_score_lag1": pa.Column(
            float, pa.Check.between(0.0, 100.0), nullable=True
        ),
        # §1: 감성·공포지수 Lag-1 — look-ahead bias 제거용 (첫 행은 NaN)
        "news_sentiment_mean_lag1": pa.Column(float, pa.Check.between(-1.0, 1.0), nullable=True),
        "fng_value_lag1": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        # §2: 텍스트 스키마 버전 — 백필/실시간 감성 텍스트 입력 차이 추적용
        # None 허용을 위해 타입 미지정 (ingest_validation_reason와 동일 패턴)
        "text_schema_version": pa.Column(nullable=True),
        # 1-A: Level→Delta 피처 — AR 구조 제거로 Granger/correlation 신호 품질 개선
        "fng_change_1d": pa.Column(float, nullable=True),
        "fng_change_5d": pa.Column(float, nullable=True),
        "fng_change_1d_lag1": pa.Column(float, nullable=True),
        "fng_change_5d_lag1": pa.Column(float, nullable=True),
        "sentiment_momentum": pa.Column(float, nullable=True),
        "sentiment_accel": pa.Column(float, nullable=True),
        "sentiment_momentum_lag1": pa.Column(float, nullable=True),
        "sentiment_accel_lag1": pa.Column(float, nullable=True),
        # 1-B: BTC 200일 MA 기반 레짐 피처
        "btc_ma_200d": pa.Column(float, pa.Check.ge(0), nullable=True),
        "btc_drawdown_90d": pa.Column(float, nullable=True),
        "btc_above_ma200": pa.Column(float, nullable=True),
        "btc_above_ma200_lag1": pa.Column(float, nullable=True),
        "btc_bear_regime_lag1": pa.Column(float, nullable=True),
        "sentiment_momentum_x_bear_lag1": pa.Column(float, nullable=True),
        "fng_change_1d_x_bear_lag1": pa.Column(float, nullable=True),
        "funding_rate_x_bear_lag1": pa.Column(float, nullable=True),
    },
    strict=True,
)


def _check_lag1_first_row_nan(df: pd.DataFrame) -> None:
    """date 정렬 시 첫 행의 모든 `*_lag1` 컬럼은 NaN 이어야 한다 (lookahead 감사).

    단일 행 DataFrame 은 시간 invariant 평가 대상이 아니므로 검사를 건너뛴다
    (기존 단위 테스트의 1-row fixture 호환).
    """
    if "date" not in df.columns or len(df) < 2:
        return
    sorted_df = df.sort_values("date").reset_index(drop=True)
    offenders: list[str] = []
    for col in sorted_df.columns:
        if not col.endswith("_lag1"):
            continue
        first = sorted_df[col].iloc[0]
        if not pd.isna(first):
            offenders.append(f"{col}={first!r}")
    if offenders:
        raise SchemaError(
            schema=MASTER_SCHEMA,
            data=df,
            message=(
                "lag1 columns must have NaN at first date (lookahead audit): "
                + ", ".join(offenders)
            ),
        )


def validate_master(df: pd.DataFrame) -> None:
    try:
        for column in (
            "n_articles",
            "fng_value",
            "btc_large_move_3d",
            "btc_large_move_3d_vol_adj",
        ):
            if str(df[column].dtype) != "Int64":
                raise SchemaError(
                    schema=MASTER_SCHEMA,
                    data=df,
                    message=f"{column} must use pandas Int64 dtype",
                )
        MASTER_SCHEMA.validate(df)
        _check_lag1_first_row_nan(df)
    except (SchemaError, SchemaErrors) as exc:
        if isinstance(exc, SchemaErrors):
            primary_error = exc.schema_errors[0] if exc.schema_errors else None
            message = (
                str(primary_error) if primary_error is not None else "schema validation failed"
            )
            if len(exc.schema_errors) > 1:
                message = f"{message} (+{len(exc.schema_errors) - 1} more schema errors)"
            normalized_exc = SchemaError(schema=MASTER_SCHEMA, data=df, message=message)
        else:
            normalized_exc = exc
        log_structured(
            logger,
            event="error.raised",
            message="마스터 데이터프레임 스키마 검증에 실패했습니다.",
            level=logging.ERROR,
            reason=str(normalized_exc),
        )
        raise normalized_exc from exc


__all__ = ["MASTER_SCHEMA", "validate_master"]
