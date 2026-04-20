from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.join import detect_outliers_rolling_iqr
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)

PolicyName = Literal["row", "column", "winsorize", "none"]
Reason = Literal["data_error", "regime_stress", "iqr_single"]

NON_MASK_COLS: frozenset[str] = frozenset(
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

DATA_ERROR_RULES: dict[str, tuple[str, float]] = {
    # operator ∈ {"lt", "abs_gt"}, threshold
    "open_interest_usd": ("lt", 0.0),
    "funding_rate": ("abs_gt", 0.05),
}

WINSOR_LOW_Q = 0.01
WINSOR_HIGH_Q = 0.99

ROLLING_WINDOW = 30
ROLLING_MIN_PERIODS = 15
IQR_MULTIPLIER = 3.0

REGIME_STRESS_COLS: tuple[str, ...] = ("btc_return", "funding_rate", "volume_change_pct")
REGIME_STRESS_WINDOW = 30
REGIME_STRESS_MIN_PERIODS = 10
REGIME_STRESS_PERCENTILE = 0.95
REGIME_STRESS_MIN_CONCURRENT = 2


@dataclass
class OutlierResult:
    """Outlier policy 적용 결과.

    attributes:
        df: 마스킹/윈저라이즈 적용된 DataFrame (입력과 동일 shape).
        flags: 셀 단위 변경 여부 (True = 값이 NaN 또는 clip됨).
        classification: 셀 단위 사유 ("data_error"|"regime_stress"|"iqr_single"|None).
        stats: 집계 통계 (masked_row_ratio, masked_cells, data_error_cells,
            regime_stress_rows, winsorized_cells).
    """

    df: pd.DataFrame
    flags: pd.DataFrame
    classification: pd.DataFrame
    stats: dict[str, float]


@runtime_checkable
class OutlierPolicy(Protocol):
    name: PolicyName

    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult: ...


def _empty_flags(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(False, index=df.index, columns=df.columns)


def _empty_classification(df: pd.DataFrame) -> pd.DataFrame:
    cls = pd.DataFrame(index=df.index, columns=df.columns, dtype=object)
    cls[:] = None
    return cls


def _maskable_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in NON_MASK_COLS]


def _data_error_mask(df: pd.DataFrame) -> pd.DataFrame:
    """부호 불가능값·provider 오염 셀을 True 로 표시."""
    flags = pd.DataFrame(False, index=df.index, columns=df.columns)
    for col, (op, thr) in DATA_ERROR_RULES.items():
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if op == "lt":
            mask = (series < thr).fillna(False)
        elif op == "abs_gt":
            mask = (series.abs() > thr).fillna(False)
        else:
            continue
        flags.loc[mask.to_numpy(), col] = True
    return flags


def _regime_stress_rows(df: pd.DataFrame) -> pd.Series:
    """변화율 컬럼이 rolling 95퍼센타일을 동시에 2개 이상 초과하는 행."""
    present = [c for c in REGIME_STRESS_COLS if c in df.columns]
    concurrent = pd.Series(0, index=df.index, dtype=int)
    if not present:
        return concurrent >= REGIME_STRESS_MIN_CONCURRENT
    for col in present:
        series = pd.to_numeric(df[col], errors="coerce").abs()
        q = series.rolling(REGIME_STRESS_WINDOW, min_periods=REGIME_STRESS_MIN_PERIODS).quantile(
            REGIME_STRESS_PERCENTILE
        )
        over = (series > q).fillna(False)
        concurrent = concurrent + over.astype(int)
    return concurrent >= REGIME_STRESS_MIN_CONCURRENT


def _cell_iqr_flags(
    df: pd.DataFrame,
    cols: list[str],
    *,
    window: int = ROLLING_WINDOW,
    min_periods: int = ROLLING_MIN_PERIODS,
    multiplier: float = IQR_MULTIPLIER,
) -> pd.DataFrame:
    """`detect_outliers_rolling_iqr` 와 동일 규칙을 셀 단위로 산출."""
    flags = pd.DataFrame(False, index=df.index, columns=cols)
    if len(df) <= window:
        return flags
    for col in cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        reference = series.shift(1)
        rolling = reference.rolling(window=window, min_periods=min_periods)
        median = rolling.median()
        q1 = rolling.quantile(0.25)
        q3 = rolling.quantile(0.75)
        iqr = q3 - q1
        threshold = multiplier * iqr
        distances = (series - median).abs()
        mask = (
            series.notna() & median.notna() & threshold.notna() & (distances > threshold)
        ).fillna(False)
        flags[col] = mask
    return flags


def _apply_data_error(
    result: pd.DataFrame,
    flags: pd.DataFrame,
    classification: pd.DataFrame,
    maskables: list[str],
    *,
    data_error: pd.DataFrame,
) -> pd.DataFrame:
    """사전 계산된 data_error 셀을 NaN 으로 강제 마스크하고 flags/classification 갱신.

    data_error 감지는 반드시 입력 원본 기준으로 해야 한다. winsorize/row-mask 가 선행되면
    극단값이 clip/NaN 이 되어 `|funding| > 0.05` 같은 규칙이 False 가 되는 회귀가 발생한다.
    """
    for col in maskables:
        if col not in data_error.columns:
            continue
        de_mask = data_error[col]
        if de_mask.any():
            result.loc[de_mask, col] = np.nan
            flags.loc[de_mask, col] = True
            classification.loc[de_mask, col] = "data_error"
    return data_error


class RowMaskPolicy:
    """기존 파이프라인 동작: rolling IQR×3.0 에 걸린 행의 모든 수치 컬럼을 NaN 으로 마스크."""

    name: PolicyName = "row"

    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult:
        flagged = detect_outliers_rolling_iqr(df, cols)
        # data_error 는 반드시 원본에서 감지한다 (clip/mask 이후 규칙이 False 로 회귀하는 것을 방지).
        data_error = _data_error_mask(flagged)
        is_row_outlier = flagged["is_outlier"].fillna(False).astype(bool)

        maskables = _maskable_cols(flagged)
        flags = _empty_flags(flagged)
        classification = _empty_classification(flagged)

        for col in maskables:
            flags.loc[is_row_outlier, col] = True
            classification.loc[is_row_outlier, col] = "iqr_single"

        result = flagged.copy()
        for col in maskables:
            if flags[col].any():
                result.loc[flags[col], col] = np.nan

        de = _apply_data_error(result, flags, classification, maskables, data_error=data_error)

        total = max(len(result), 1)
        stats: dict[str, float] = {
            "masked_row_ratio": float(int(is_row_outlier.sum())) / total,
            "masked_cells": float(int(flags.to_numpy().sum())),
            "data_error_cells": float(int(de.to_numpy().sum())),
            "regime_stress_rows": 0.0,
            "winsorized_cells": 0.0,
        }
        log_structured(
            logger,
            event="outlier_policy.applied",
            message="Outlier policy applied.",
            policy=self.name,
            **stats,
        )
        return OutlierResult(df=result, flags=flags, classification=classification, stats=stats)


class ColumnMaskPolicy:
    """셀 단위 마스킹: IQR 초과 셀만 NaN 처리하고 행은 보존.

    regime_stress 행(변화율 95퍼센타일 동시 ≥2) 은 마스크하지 않고 사유만 기록.
    data_error 는 정책과 무관하게 항상 마스크.
    """

    name: PolicyName = "column"

    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult:
        flagged = detect_outliers_rolling_iqr(df, cols)
        data_error = _data_error_mask(flagged)
        regime_rows = _regime_stress_rows(flagged)
        cell_iqr = _cell_iqr_flags(flagged, cols)

        flags = _empty_flags(flagged)
        classification = _empty_classification(flagged)

        for col in cols:
            if col not in cell_iqr.columns:
                continue
            iqr_col = cell_iqr[col]
            mask_cells = iqr_col & ~regime_rows
            stress_cells = iqr_col & regime_rows
            if mask_cells.any():
                flags.loc[mask_cells, col] = True
                classification.loc[mask_cells, col] = "iqr_single"
            if stress_cells.any():
                classification.loc[stress_cells, col] = "regime_stress"

        result = flagged.copy()
        for col in cols:
            if col in result.columns and flags[col].any():
                result.loc[flags[col], col] = np.nan

        maskables = _maskable_cols(result)
        de = _apply_data_error(result, flags, classification, maskables, data_error=data_error)
        result["is_outlier"] = False

        total = max(len(result), 1)
        stats: dict[str, float] = {
            "masked_row_ratio": 0.0,
            "masked_cells": float(int(flags.to_numpy().sum())),
            "data_error_cells": float(int(de.to_numpy().sum())),
            "regime_stress_rows": float(int(regime_rows.sum())),
            "winsorized_cells": 0.0,
        }
        # coverage 개선 지표
        stats["coverage_gain_vs_row_mask"] = float(int(flagged["is_outlier"].sum())) / total
        log_structured(
            logger,
            event="outlier_policy.applied",
            message="Outlier policy applied.",
            policy=self.name,
            **stats,
        )
        return OutlierResult(df=result, flags=flags, classification=classification, stats=stats)


class WinsorizePolicy:
    """분포 꼬리 clip(q01/q99). 값을 보존하되 극단만 잘라 PCA 입력 안정성 확보."""

    name: PolicyName = "winsorize"

    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult:
        flagged = detect_outliers_rolling_iqr(df, cols)
        data_error = _data_error_mask(flagged)
        flags = _empty_flags(flagged)
        classification = _empty_classification(flagged)

        result = flagged.copy()
        for col in cols:
            if col not in result.columns:
                continue
            series = pd.to_numeric(result[col], errors="coerce")
            if series.dropna().empty:
                continue
            q_low = series.quantile(WINSOR_LOW_Q)
            q_high = series.quantile(WINSOR_HIGH_Q)
            clipped = series.clip(lower=q_low, upper=q_high)
            changed = ((series != clipped) & series.notna()).fillna(False)
            if changed.any():
                flags.loc[changed, col] = True
                classification.loc[changed, col] = "iqr_single"
            result[col] = clipped

        winsorized_cells = int(flags.to_numpy().sum())
        maskables = _maskable_cols(result)
        de = _apply_data_error(result, flags, classification, maskables, data_error=data_error)
        result["is_outlier"] = False

        stats: dict[str, float] = {
            "masked_row_ratio": 0.0,
            "masked_cells": float(int(de.to_numpy().sum())),
            "data_error_cells": float(int(de.to_numpy().sum())),
            "regime_stress_rows": 0.0,
            "winsorized_cells": float(winsorized_cells),
        }
        log_structured(
            logger,
            event="outlier_policy.applied",
            message="Outlier policy applied.",
            policy=self.name,
            **stats,
        )
        return OutlierResult(df=result, flags=flags, classification=classification, stats=stats)


class NoMaskPolicy:
    """data_error 만 마스크. regime stress 를 포함한 모든 정상 관측치는 통과."""

    name: PolicyName = "none"

    def apply(self, df: pd.DataFrame, cols: list[str]) -> OutlierResult:
        flagged = detect_outliers_rolling_iqr(df, cols)
        data_error = _data_error_mask(flagged)
        flags = _empty_flags(flagged)
        classification = _empty_classification(flagged)

        result = flagged.copy()
        maskables = _maskable_cols(result)
        de = _apply_data_error(result, flags, classification, maskables, data_error=data_error)
        result["is_outlier"] = False

        stats: dict[str, float] = {
            "masked_row_ratio": 0.0,
            "masked_cells": float(int(flags.to_numpy().sum())),
            "data_error_cells": float(int(de.to_numpy().sum())),
            "regime_stress_rows": 0.0,
            "winsorized_cells": 0.0,
        }
        log_structured(
            logger,
            event="outlier_policy.applied",
            message="Outlier policy applied.",
            policy=self.name,
            **stats,
        )
        return OutlierResult(df=result, flags=flags, classification=classification, stats=stats)


_POLICY_REGISTRY: dict[PolicyName, Callable[[], OutlierPolicy]] = {
    "row": RowMaskPolicy,
    "column": ColumnMaskPolicy,
    "winsorize": WinsorizePolicy,
    "none": NoMaskPolicy,
}


class OutlierPolicyFactory:
    """Policy 이름으로 구현체를 생성. 실험 matrix 에서 spec 기반 주입용."""

    @staticmethod
    def create(name: PolicyName) -> OutlierPolicy:
        if name not in _POLICY_REGISTRY:
            raise ValueError(f"Unknown outlier policy: {name!r}")
        return _POLICY_REGISTRY[name]()


__all__ = [
    "ColumnMaskPolicy",
    "DATA_ERROR_RULES",
    "IQR_MULTIPLIER",
    "NON_MASK_COLS",
    "NoMaskPolicy",
    "OutlierPolicy",
    "OutlierPolicyFactory",
    "OutlierResult",
    "PolicyName",
    "REGIME_STRESS_COLS",
    "REGIME_STRESS_MIN_CONCURRENT",
    "Reason",
    "RowMaskPolicy",
    "WINSOR_HIGH_Q",
    "WINSOR_LOW_Q",
    "WinsorizePolicy",
]
