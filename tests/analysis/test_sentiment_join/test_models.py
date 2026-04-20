from __future__ import annotations

import numpy as np
import pandas as pd

from morning_brief.analysis.sentiment_join.models import (
    ElasticNetRegressorModel,
    L1LogisticModel,
    LightGBMModel,
    time_series_cv_split,
)


def _X(n: int = 80) -> pd.DataFrame:
    x = np.linspace(-1, 1, n)
    return pd.DataFrame({"a": x, "b": x**2, "c": np.sin(x)})


def test_l1_logistic_fit_predict_contract() -> None:
    X = _X()
    y = (X["a"] > 0).astype(int)

    model = L1LogisticModel(random_state=1).fit(X, y)
    pred = model.predict_proba(X)

    assert pred.between(0, 1).all()
    assert len(model.feature_importance()) > 0
    assert model._pipeline.steps[-1][1].l1_ratio == 1.0


def test_elastic_net_fit_predict_contract() -> None:
    X = _X()
    y = X["a"] * 0.5 + X["b"] * 0.1

    model = ElasticNetRegressorModel(random_state=1, alpha=0.01).fit(X, y)
    pred = model.predict(X)

    assert len(pred) == len(X)
    assert pred.notna().all()


def test_lightgbm_wrapper_fit_predict_and_shap_safe() -> None:
    X = _X()
    y = X["a"] * 0.5 + X["b"] * 0.1

    model = LightGBMModel(random_state=1).fit(X, y)
    pred = model.predict(X)
    explanation = model.shap_explain(X.head(5))

    assert len(pred) == len(X)
    assert model.backend in {"lightgbm", "sklearn_fallback"}
    assert isinstance(explanation.available, bool)


def test_time_series_cv_split_applies_embargo() -> None:
    X = _X(60)
    splits = time_series_cv_split(X, n_splits=3, embargo_days=2)

    assert len(splits) == 3
    for train_idx, test_idx in splits:
        assert len(test_idx) > 0
        if len(train_idx) > 0:
            assert train_idx.max() < test_idx.min() - 1
