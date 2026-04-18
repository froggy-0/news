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
        # Req 8: BTC 방향 라벨
        "btc_direction_label": pa.Column(nullable=True),
        # §4 v4: full / core 이중 하이브리드 지수 + 0~100 score.
        # 이전 단일 `hybrid_index` 컬럼은 v4에서 삭제되었습니다.
        "full_hybrid_index": pa.Column(float, nullable=True),
        "full_hybrid_index_score": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        "core_hybrid_index": pa.Column(float, nullable=True),
        "core_hybrid_index_score": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        # §1: 감성·공포지수 Lag-1 — look-ahead bias 제거용 (첫 행은 NaN)
        "news_sentiment_mean_lag1": pa.Column(float, pa.Check.between(-1.0, 1.0), nullable=True),
        "fng_value_lag1": pa.Column(float, pa.Check.between(0.0, 100.0), nullable=True),
        # §2: 텍스트 스키마 버전 — 백필/실시간 감성 텍스트 입력 차이 추적용
        # None 허용을 위해 타입 미지정 (ingest_validation_reason와 동일 패턴)
        "text_schema_version": pa.Column(nullable=True),
    },
    strict=True,
)


def validate_master(df: pd.DataFrame) -> None:
    try:
        for column in ("n_articles", "fng_value"):
            if str(df[column].dtype) != "Int64":
                raise SchemaError(
                    schema=MASTER_SCHEMA,
                    data=df,
                    message=f"{column} must use pandas Int64 dtype",
                )
        MASTER_SCHEMA.validate(df)
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
