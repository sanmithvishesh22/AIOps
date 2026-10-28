"""Breach classifier + duration regressor behind :class:`BreachPredictor`.

scikit-learn is imported lazily inside :meth:`BreachPredictor._build`, so the
rest of the module (and its offline helpers) can be imported on a machine where
the optional ML stack is not installed yet.  The persisted artifact records the
feature schema, seed, horizon and train-selected threshold; loading an artifact
built with a stale feature set fails loudly.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import numpy as np
import pandas as pd

from . import config
from .features import FEATURE_COLUMNS
from .metrics import select_threshold

ARTIFACT_VERSION = 1


class _ConstantRegressor:
    """Fallback for a duration target with no variance (or a single positive)."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_ConstantRegressor":
        self.value = float(np.mean(y)) if len(y) else 0.0
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(len(X), self.value, dtype=float)


class BreachPredictor:
    """Predict ``P(major SLO breach within H)`` and a duration proxy."""

    def __init__(
        self,
        feature_cols: Sequence[str] | None = None,
        horizon_s: int | float | None = None,
        seed: int | None = None,
        target_precision: float | None = None,
    ) -> None:
        self.feature_cols = list(FEATURE_COLUMNS if feature_cols is None else feature_cols)
        unknown = [c for c in self.feature_cols if c not in FEATURE_COLUMNS]
        if unknown:
            raise ValueError(f"unknown feature columns: {unknown}")
        self.horizon_s = int(config.HORIZON_S if horizon_s is None else horizon_s)
        if self.horizon_s <= 0:
            raise ValueError(f"horizon_s must be > 0, got {self.horizon_s}")
        self.seed = int(config.SEED if seed is None else seed)
        self.target_precision = float(
            config.TARGET_PRECISION if target_precision is None else target_precision
        )
        if not 0.0 < self.target_precision <= 1.0:
            raise ValueError("target_precision must be in (0, 1]")

        self.classifier: Any | None = None
        self.regressor: Any | None = None
        self.threshold: float | None = None
        self.target_met: bool | None = None
        self.metadata: dict[str, Any] = {}

    # ------------------------------------------------------------------ build
    def _build(self) -> tuple[Any, Any]:
        """Construct fresh estimators.  Patchable in offline tests."""
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        classifier = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=2000,
                        random_state=self.seed,
                        solver="lbfgs",
                    ),
                ),
            ]
        )
        regressor = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                (
                    "model",
                    GradientBoostingRegressor(
                        n_estimators=80,
                        max_depth=2,
                        learning_rate=0.05,
                        random_state=self.seed,
                    ),
                ),
            ]
        )
        return classifier, regressor

    # ------------------------------------------------------------------ matrix
    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.feature_cols if c not in frame.columns]
        if missing:
            raise ValueError(
                "missing feature columns (stale artifact or wrong frame): "
                f"{missing}"
            )
        X = frame[self.feature_cols].to_numpy(dtype=float)
        if not np.isfinite(X).all():
            # NaN is the Contract-C gap marker; inf is corrupt and is treated as
            # missing rather than clipped into a fake value.
            X = X.copy()
            X[~np.isfinite(X)] = np.nan
        return X

    # --------------------------------------------------------------------- fit
    def fit(
        self,
        train: pd.DataFrame,
        label_col: str = "y_major",
        duration_col: str = "dur_est_s",
    ) -> "BreachPredictor":
        if train is None or train.empty:
            raise ValueError("cannot fit on an empty training frame")
        required = set(self.feature_cols) | {label_col, duration_col}
        missing = sorted(required - set(train.columns))
        if missing:
            raise ValueError(f"training frame missing columns: {missing}")
        if train[label_col].isna().any():
            raise ValueError(f"{label_col} contains null labels")

        y = train[label_col].astype(int).to_numpy()
        if not np.isin(y, (0, 1)).all():
            raise ValueError(f"{label_col} must contain only 0/1")
        if int(y.sum()) == 0 or int(y.sum()) == len(y):
            raise ValueError(
                "training labels contain a single class; refusing to fit a "
                "degenerate predictor"
            )

        X = self._matrix(train)
        self.classifier, self.regressor = self._build()
        self.classifier.fit(X, y)

        proba = np.asarray(self.classifier.predict_proba(X))[:, 1]
        self.threshold, self.target_met = select_threshold(
            y, proba, self.target_precision
        )

        # Duration is a positive-only severity proxy.  A constant target (or a
        # single positive) uses a deterministic fallback rather than an unstable
        # tree fit.
        positive = y == 1
        durations = (
            pd.to_numeric(train.loc[positive, duration_col], errors="coerce")
            .to_numpy(dtype=float)
        )
        durations = np.clip(durations, 0.0, float(self.horizon_s))
        valid = durations[np.isfinite(durations)]
        if len(valid) >= 2 and float(np.ptp(valid)) > 0.0:
            self.regressor.fit(X[positive][np.isfinite(durations)], valid)
        else:
            value = float(np.mean(valid)) if len(valid) else 0.0
            self.regressor = _ConstantRegressor(value)

        self.metadata = {
            "artifact_version": ARTIFACT_VERSION,
            "feature_cols": list(self.feature_cols),
            "horizon_s": self.horizon_s,
            "seed": self.seed,
            "target_precision": self.target_precision,
            "threshold": self.threshold,
            "target_met": bool(self.target_met),
            "trained_rows": int(len(train)),
            "positive_rows": int(y.sum()),
            "duration_model": type(self.regressor).__name__,
            "provisional": True,
        }
        return self

    # ----------------------------------------------------------------- predict
    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.classifier is None or self.regressor is None or self.threshold is None:
            raise RuntimeError("BreachPredictor must be fitted or loaded before predict()")
        if frame is None:
            raise ValueError("cannot predict on a None frame")
        out = frame.copy()
        if frame.empty:
            out["breach_prob"] = pd.Series(dtype="float64")
            out["breach_duration_est"] = pd.Series(dtype="float64")
            out["breach_flag"] = pd.Series(dtype="bool")
            return out

        X = self._matrix(frame)
        proba = np.asarray(self.classifier.predict_proba(X), dtype=float)[:, 1]
        duration = np.asarray(self.regressor.predict(X), dtype=float)
        proba = np.clip(proba, 0.0, 1.0)
        duration = np.clip(duration, 0.0, float(self.horizon_s))
        out["breach_prob"] = proba
        out["breach_duration_est"] = duration
        out["breach_flag"] = proba >= float(self.threshold)
        return out

    # -------------------------------------------------------------- persistence
    def save(self, path: str | os.PathLike[str]) -> None:
        if self.classifier is None or self.regressor is None or self.threshold is None:
            raise RuntimeError("cannot save an unfitted BreachPredictor")
        import joblib

        target = os.fspath(path)
        parent = os.path.dirname(os.path.abspath(target))
        os.makedirs(parent, exist_ok=True)
        payload = {
            "artifact_version": ARTIFACT_VERSION,
            "feature_cols": list(self.feature_cols),
            "horizon_s": self.horizon_s,
            "seed": self.seed,
            "target_precision": self.target_precision,
            "threshold": self.threshold,
            "target_met": self.target_met,
            "classifier": self.classifier,
            "regressor": self.regressor,
            "metadata": dict(self.metadata),
        }
        joblib.dump(payload, target)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "BreachPredictor":
        import joblib

        payload = joblib.load(os.fspath(path))
        if not isinstance(payload, dict):
            raise ValueError("model artifact is not a BreachPredictor payload")
        version = payload.get("artifact_version")
        if version != ARTIFACT_VERSION:
            raise ValueError(
                f"stale model artifact version {version!r}; expected {ARTIFACT_VERSION}"
            )
        feature_cols = list(payload.get("feature_cols", []))
        if feature_cols != FEATURE_COLUMNS:
            raise ValueError(
                "stale model artifact feature schema; retrain after feature changes"
            )
        threshold = payload.get("threshold")
        if threshold is None or not 0.0 <= float(threshold) <= 1.0:
            raise ValueError("model artifact has an invalid threshold")

        model = cls(
            feature_cols=feature_cols,
            horizon_s=payload["horizon_s"],
            seed=payload["seed"],
            target_precision=payload.get("target_precision", config.TARGET_PRECISION),
        )
        model.classifier = payload["classifier"]
        model.regressor = payload["regressor"]
        model.threshold = float(threshold)
        model.target_met = payload.get("target_met")
        model.metadata = dict(payload.get("metadata", {}))
        return model
