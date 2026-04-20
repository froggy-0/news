from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ModelExplanation:
    available: bool
    method: str
    values: Any = None
    reason: str | None = None


def _numeric_frame(X: pd.DataFrame) -> pd.DataFrame:
    return X.apply(pd.to_numeric, errors="coerce")


def _feature_importance_from_estimator(estimator: Any, feature_names: list[str]) -> pd.Series:
    if hasattr(estimator, "coef_"):
        values = np.ravel(estimator.coef_)
        return pd.Series(values, index=feature_names[: len(values)], dtype=float)
    if hasattr(estimator, "feature_importances_"):
        values = np.ravel(estimator.feature_importances_)
        return pd.Series(values, index=feature_names[: len(values)], dtype=float)
    return pd.Series(dtype=float)


class L1LogisticModel:
    def __init__(self, *, random_state: int = 0, C: float = 1.0) -> None:
        self.random_state = random_state
        self.C = C
        self._pipeline: Any | None = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> L1LogisticModel:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self._feature_names = list(X.columns)
        self._pipeline = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                solver="liblinear",
                C=self.C,
                l1_ratio=1.0,
                random_state=self.random_state,
            ),
        )
        self._pipeline.fit(_numeric_frame(X), y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        if self._pipeline is None:
            raise RuntimeError("model is not fitted")
        proba = self._pipeline.predict_proba(_numeric_frame(X))[:, 1]
        return pd.Series(proba, index=X.index, dtype=float)

    def feature_importance(self) -> pd.Series:
        if self._pipeline is None:
            return pd.Series(dtype=float)
        estimator = self._pipeline.steps[-1][1]
        return _feature_importance_from_estimator(estimator, self._feature_names)


class ElasticNetRegressorModel:
    def __init__(
        self,
        *,
        random_state: int = 0,
        alpha: float = 1.0,
        l1_ratio: float = 0.5,
    ) -> None:
        self.random_state = random_state
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self._pipeline: Any | None = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> ElasticNetRegressorModel:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import ElasticNet
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self._feature_names = list(X.columns)
        self._pipeline = make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            ElasticNet(alpha=self.alpha, l1_ratio=self.l1_ratio, random_state=self.random_state),
        )
        self._pipeline.fit(_numeric_frame(X), pd.to_numeric(y, errors="coerce"))
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self._pipeline is None:
            raise RuntimeError("model is not fitted")
        pred = self._pipeline.predict(_numeric_frame(X))
        return pd.Series(pred, index=X.index, dtype=float)

    def feature_importance(self) -> pd.Series:
        if self._pipeline is None:
            return pd.Series(dtype=float)
        estimator = self._pipeline.steps[-1][1]
        return _feature_importance_from_estimator(estimator, self._feature_names)


class LightGBMModel:
    def __init__(
        self,
        *,
        task: Literal["classification", "regression"] = "regression",
        random_state: int = 0,
    ) -> None:
        self.task = task
        self.random_state = random_state
        self.backend = "unfitted"
        self._model: Any | None = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> LightGBMModel:
        self._feature_names = list(X.columns)
        X_num = _numeric_frame(X)
        try:
            import lightgbm as lgb

            if self.task == "classification":
                self._model = lgb.LGBMClassifier(random_state=self.random_state, verbose=-1)
            else:
                self._model = lgb.LGBMRegressor(random_state=self.random_state, verbose=-1)
            self.backend = "lightgbm"
        except Exception:
            from sklearn.ensemble import (
                HistGradientBoostingClassifier,
                HistGradientBoostingRegressor,
            )

            if self.task == "classification":
                self._model = HistGradientBoostingClassifier(random_state=self.random_state)
            else:
                self._model = HistGradientBoostingRegressor(random_state=self.random_state)
            self.backend = "sklearn_fallback"

        self._model.fit(X_num, y)
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self._model is None:
            raise RuntimeError("model is not fitted")
        X_num = _numeric_frame(X)
        if self.task == "classification" and hasattr(self._model, "predict_proba"):
            values = self._model.predict_proba(X_num)[:, 1]
        else:
            values = self._model.predict(X_num)
        return pd.Series(values, index=X.index, dtype=float)

    def feature_importance(self) -> pd.Series:
        if self._model is None:
            return pd.Series(dtype=float)
        return _feature_importance_from_estimator(self._model, self._feature_names)

    def shap_explain(self, X: pd.DataFrame) -> ModelExplanation:
        if self._model is None:
            return ModelExplanation(False, "shap", reason="model_not_fitted")
        try:
            import shap

            explainer = shap.TreeExplainer(self._model)
            return ModelExplanation(True, "shap", values=explainer.shap_values(_numeric_frame(X)))
        except Exception as exc:
            return ModelExplanation(False, "shap", reason=str(exc))


def time_series_cv_split(
    df: pd.DataFrame,
    *,
    n_splits: int,
    embargo_days: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    from sklearn.model_selection import TimeSeriesSplit

    splitter = TimeSeriesSplit(n_splits=n_splits)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for train_idx, test_idx in splitter.split(df):
        if embargo_days > 0 and len(test_idx) > 0:
            cutoff = int(test_idx[0]) - embargo_days
            train_idx = train_idx[train_idx < cutoff]
        out.append((train_idx, test_idx))
    return out


__all__ = [
    "ElasticNetRegressorModel",
    "L1LogisticModel",
    "LightGBMModel",
    "ModelExplanation",
    "time_series_cv_split",
]
