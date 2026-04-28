"""Ablation experiment runner (Phase 3).

OutlierPolicy × ScalerKind × horizon × index 조합을 walk-forward 로 돌려
fold-level 지표를 수집한다. `statistical_tests.walk_forward_validate` 를 공통 엔진으로 사용.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.hybrid_index import (
    HYBRID_FEATURE_CANDIDATES_CORE,
    HYBRID_FEATURE_CANDIDATES_FULL,
    VIF_THRESHOLD_FULL,
    IndexSpec,
    ScalerKind,
    compute_hybrid_indices,
)
from morning_brief.analysis.sentiment_join.outlier_policy import (
    NON_MASK_COLS,
    OutlierPolicyFactory,
    PolicyName,
)
from morning_brief.analysis.sentiment_join.statistical_tests import (
    walk_forward_validate,
)
from morning_brief.logging_utils import log_structured

logger = logging.getLogger(__name__)


FOLDS_SCHEMA_COLUMNS: tuple[str, ...] = (
    "spec_id",
    "scaler",
    "mask",
    "horizon",
    "index_name",
    "fold",
    "test_start",
    "test_end",
    "hit_rate",
    "cumret",
    "alpha",
    "sharpe",
    "coverage",
    "masked_ratio",
    "stability",
    "correct_mean",
    "wrong_mean",
    "correct_n",
    "wrong_n",
    "fold_payoff_ratio",
)

TRADING_DAYS_PER_YEAR = 365  # BTC 24/7 calendar-day candles, no weekend gap → 365 (not 252)


@dataclass(frozen=True)
class ExperimentSpec:
    """단일 실험 cell 의 config.

    spec_id 는 파일/리포트에서 cell 을 참조하는 키다.
    """

    scaler: ScalerKind
    mask: PolicyName
    horizon_days: int
    index_name: str  # "full" | "core"

    @property
    def spec_id(self) -> str:
        return f"{self.scaler}-{self.mask}-T{self.horizon_days}-{self.index_name}"

    @property
    def return_col(self) -> str:
        """horizon_days 에 맞는 수익률 컬럼."""
        if self.horizon_days == 1:
            return "btc_log_return"
        return f"btc_fwd_ret_{self.horizon_days}d"


@dataclass(frozen=True)
class ExperimentArtifact:
    run_id: str
    spec: dict[str, Any]
    metrics: dict[str, Any]
    lineage: dict[str, Any]


def write_tracking_artifact(
    run_dir: Path,
    *,
    run_id: str,
    spec: dict[str, Any],
    metrics: dict[str, Any],
    lineage: dict[str, Any] | None = None,
) -> Path:
    artifact = ExperimentArtifact(
        run_id=run_id,
        spec=spec,
        metrics=metrics,
        lineage=lineage or {},
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "tracking.json"
    path.write_text(
        json.dumps(
            {
                "run_id": artifact.run_id,
                "spec": artifact.spec,
                "metrics": artifact.metrics,
                "lineage": artifact.lineage,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def default_grid(
    scalers: tuple[ScalerKind, ...] = ("standard", "robust"),
    masks: tuple[PolicyName, ...] = ("row", "column", "winsorize", "none"),
    horizons: tuple[int, ...] = (7,),
    indices: tuple[str, ...] = ("full", "core"),
) -> list[ExperimentSpec]:
    """2×4×1×2 = 16 기본 grid. T+7 단일 horizon."""
    return [
        ExperimentSpec(scaler=s, mask=m, horizon_days=h, index_name=i)
        for s in scalers
        for m in masks
        for h in horizons
        for i in indices
    ]


def _mask_cols_from(df: pd.DataFrame) -> list[str]:
    """NON_MASK_COLS · hybrid index · forward target 컬럼 제외한 마스킹 대상."""
    excluded = set(NON_MASK_COLS) | {
        "full_hybrid_index",
        "full_hybrid_index_score",
        "full_hybrid_index_score_lag1",
        "core_hybrid_index",
        "core_hybrid_index_score",
        "core_hybrid_index_score_lag1",
        "btc_fwd_ret_1d",
        "btc_fwd_ret_3d",
        "btc_fwd_ret_7d",
        "btc_fwd_vol_5d",
        "btc_large_move_3d",
        "btc_realized_vol_20d_lag1",
        "btc_large_move_3d_vol_adj",
    }
    return [c for c in df.columns if c not in excluded]


def _build_custom_specs(scaler: ScalerKind) -> tuple[IndexSpec, ...]:
    return (
        IndexSpec("full", HYBRID_FEATURE_CANDIDATES_FULL, VIF_THRESHOLD_FULL, scaler),
        IndexSpec("core", HYBRID_FEATURE_CANDIDATES_CORE, None, scaler),
    )


def _fold_sharpe(df: pd.DataFrame, return_col: str, signal_col: str) -> float:
    """fold 내 strategy sharpe = mean / std * sqrt(TRADING_DAYS_PER_YEAR).

    strategy 수익률 = sign(signal - 50) * return. NaN·flat 은 제외.
    BTC 24/7 → 365 일 기준 연환산 (baselines.py / statistical_tests.py 와 동일).
    """
    if signal_col not in df.columns or return_col not in df.columns:
        return float("nan")
    sub = df[[signal_col, return_col]].dropna()
    if len(sub) < 5:
        return float("nan")
    position = np.sign(sub[signal_col].to_numpy() - 50.0)
    rets = position * sub[return_col].to_numpy()
    mu = float(np.mean(rets))
    sigma = float(np.std(rets, ddof=1))
    if sigma < 1e-12:
        return float("nan")
    return mu / sigma * math.sqrt(TRADING_DAYS_PER_YEAR)


def _fold_payoff_decompose(
    fold_df: pd.DataFrame,
    return_col: str,
    signal_col: str,
    *,
    neutral_score: float = 50.0,
) -> dict[str, Any]:
    """fold 내 correct/wrong return 분해.

    fold_payoff_ratio = |avg_correct_return| / |avg_wrong_return|.
    tail-winner 진단: 이 값이 1~2개 fold에 집중되어 있으면 payoff ratio의 tail dependency.
    """
    nan_result: dict[str, Any] = {
        "correct_mean": float("nan"),
        "wrong_mean": float("nan"),
        "correct_n": 0,
        "wrong_n": 0,
        "fold_payoff_ratio": float("nan"),
    }
    if signal_col not in fold_df.columns or return_col not in fold_df.columns:
        return nan_result
    sub = fold_df[[signal_col, return_col]].dropna()
    if len(sub) < 5:
        return nan_result
    pos = np.sign(sub[signal_col].to_numpy(dtype=float) - neutral_score)
    ret = sub[return_col].to_numpy(dtype=float)
    nonzero = pos != 0
    correct_mask = nonzero & (pos == np.sign(ret))
    wrong_mask = nonzero & (pos != np.sign(ret))
    correct_ret = ret[correct_mask]
    wrong_ret = ret[wrong_mask]
    c_mean = float(np.mean(correct_ret)) if len(correct_ret) > 0 else float("nan")
    w_mean = float(np.mean(wrong_ret)) if len(wrong_ret) > 0 else float("nan")
    payoff = (
        abs(c_mean / w_mean)
        if (math.isfinite(c_mean) and math.isfinite(w_mean) and abs(w_mean) > 1e-12)
        else float("nan")
    )
    return {
        "correct_mean": c_mean,
        "wrong_mean": w_mean,
        "correct_n": int(len(correct_ret)),
        "wrong_n": int(len(wrong_ret)),
        "fold_payoff_ratio": payoff,
    }


class ExperimentRunner:
    """raw master(pre-mask) 를 받아 ExperimentSpec 별 fold 지표를 수집한다.

    입력 DataFrame 요구:
    - merge_sources 의 출력 + forward target 컬럼
    - is_outlier 컬럼은 참고용 (runner 가 policy 별로 새로 마스킹하므로 의존하지 않음)
    - 원본 수치 컬럼(btc_return, funding_rate, volume_change_pct, ...)은 NaN 마스킹 *전* 상태여야 한다
    """

    def __init__(
        self,
        raw_master: pd.DataFrame,
        *,
        train_days: int = 120,
        test_days: int = 30,
    ) -> None:
        if raw_master.empty:
            raise ValueError("raw_master must not be empty")
        self._raw = raw_master.reset_index(drop=True)
        self._train_days = train_days
        self._test_days = test_days

    def run(self, spec: ExperimentSpec) -> pd.DataFrame:
        """단일 spec 실행 → fold-level DataFrame."""
        return self._run_one(spec)

    def run_many(self, specs: list[ExperimentSpec]) -> pd.DataFrame:
        """여러 spec 을 순차 실행 후 concat."""
        frames = []
        for spec in specs:
            try:
                frame = self._run_one(spec)
            except Exception as exc:  # 단일 cell 실패가 전체를 망가뜨리지 않도록 격리
                log_structured(
                    logger,
                    event="experiment.cell_failed",
                    message="실험 cell 실행 실패",
                    level=logging.WARNING,
                    spec_id=spec.spec_id,
                    reason=str(exc),
                )
                frame = _empty_fold_frame(spec)
            frames.append(frame)
        if not frames:
            return _empty_fold_frame(None)
        return pd.concat(frames, ignore_index=True)

    # --------------------------------------------------------------- internals

    def _run_one(self, spec: ExperimentSpec) -> pd.DataFrame:
        # 1) policy 적용
        policy = OutlierPolicyFactory.create(spec.mask)
        mask_cols = _mask_cols_from(self._raw)
        outlier_result = policy.apply(self._raw, mask_cols)
        masked_df = outlier_result.df

        total_cells = max(len(masked_df) * len(mask_cols), 1)
        masked_cells = int(outlier_result.stats.get("masked_cells", 0))
        winsorized = int(outlier_result.stats.get("winsorized_cells", 0))
        masked_ratio = (masked_cells + winsorized) / total_cells

        # 2) hybrid index 계산 (custom scaler 주입)
        specs_custom = _build_custom_specs(spec.scaler)
        enriched = compute_hybrid_indices(masked_df, specs=specs_custom)

        # score_lag1 컬럼 보강 (walk_forward_validate 는 내부에서 재계산하지만,
        # coverage 계산용으로 보유)
        score_col = f"{spec.index_name}_hybrid_index_score"
        score_lag1_col = f"{score_col}_lag1"
        if score_col in enriched.columns:
            enriched[score_lag1_col] = enriched[score_col].shift(1)

        # 3) walk-forward
        wf = walk_forward_validate(
            enriched,
            train_days=self._train_days,
            test_days=self._test_days,
            index_name=spec.index_name,
            return_col=spec.return_col,
            horizon_days=spec.horizon_days,
        )

        if wf is None or not wf.folds:
            return _empty_fold_frame(spec)

        # 4) fold-level 집계 (sharpe · coverage 는 runner 에서 재산출)
        rows: list[dict[str, Any]] = []
        for fold in wf.folds:
            fold_df = enriched[
                (enriched["date"] >= fold.test_start) & (enriched["date"] <= fold.test_end)
            ]
            coverage = (
                float(fold_df[score_lag1_col].notna().mean())
                if score_lag1_col in fold_df.columns and len(fold_df) > 0
                else float("nan")
            )
            sharpe = _fold_sharpe(fold_df, spec.return_col, score_lag1_col)
            payoff_decomp = _fold_payoff_decompose(fold_df, spec.return_col, score_lag1_col)
            rows.append(
                {
                    "spec_id": spec.spec_id,
                    "scaler": spec.scaler,
                    "mask": spec.mask,
                    "horizon": spec.horizon_days,
                    "index_name": spec.index_name,
                    "fold": fold.fold,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "hit_rate": fold.hit_rate,
                    "cumret": fold.cumulative_return,
                    "alpha": fold.alpha,
                    "sharpe": sharpe,
                    "coverage": coverage,
                    "masked_ratio": masked_ratio,
                    "stability": wf.stability,
                    **payoff_decomp,
                }
            )

        return pd.DataFrame(rows, columns=list(FOLDS_SCHEMA_COLUMNS))


def _empty_fold_frame(spec: ExperimentSpec | None) -> pd.DataFrame:
    """fold 가 없거나 실패한 cell 용 single-row placeholder."""
    row: dict[str, Any] = {c: None for c in FOLDS_SCHEMA_COLUMNS}
    if spec is not None:
        row.update(
            {
                "spec_id": spec.spec_id,
                "scaler": spec.scaler,
                "mask": spec.mask,
                "horizon": spec.horizon_days,
                "index_name": spec.index_name,
            }
        )
    row.update(
        {
            "fold": -1,
            "hit_rate": float("nan"),
            "cumret": float("nan"),
            "alpha": float("nan"),
            "correct_mean": float("nan"),
            "wrong_mean": float("nan"),
            "correct_n": 0,
            "wrong_n": 0,
            "fold_payoff_ratio": float("nan"),
            "sharpe": float("nan"),
            "coverage": float("nan"),
            "masked_ratio": float("nan"),
            "stability": float("nan"),
        }
    )
    return pd.DataFrame([row], columns=list(FOLDS_SCHEMA_COLUMNS))


__all__ = [
    "ExperimentRunner",
    "ExperimentSpec",
    "ExperimentArtifact",
    "FOLDS_SCHEMA_COLUMNS",
    "default_grid",
    "write_tracking_artifact",
    "_fold_payoff_decompose",
]
