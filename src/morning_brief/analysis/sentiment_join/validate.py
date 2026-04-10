from __future__ import annotations

import logging

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaError

from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

MASTER_SCHEMA = pa.DataFrameSchema(
    {
        "date": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}-\d{2}$"), unique=True),
        "news_sentiment_mean": pa.Column(float, pa.Check.between(-1.0, 1.0), nullable=False),
        "news_sentiment_std": pa.Column(float, pa.Check.ge(0), nullable=True),
        "n_articles": pa.Column("Int64", pa.Check.ge(0), nullable=True),
        "fng_value": pa.Column("Int64", pa.Check.between(0, 100), nullable=True),
        "btc_log_return": pa.Column(float, nullable=True),
        "btc_return": pa.Column(float, nullable=True),
        "usdkrw_log_return": pa.Column(float, nullable=True),
        "usdkrw_return": pa.Column(float, nullable=True),
        "is_outlier": pa.Column(bool, nullable=False),
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
    except SchemaError as exc:
        log_structured(
            logger,
            event="error.raised",
            message="마스터 데이터프레임 스키마 검증에 실패했습니다.",
            level=logging.ERROR,
            reason=str(exc),
        )
        raise


__all__ = ["MASTER_SCHEMA", "validate_master"]
