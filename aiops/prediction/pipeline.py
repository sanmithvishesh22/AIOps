"""D3-001 end-to-end offline pipeline: label -> features -> split -> fit -> score.

The pipeline is the single place where chronological ordering, the embargo and
infected-period exclusion are composed.  It deliberately raises on a
single-class holdout rather than reporting a degenerate PR-AUC as a result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from . import config
from .features import FEATURE_COLUMNS, build_features
from .labels import LABEL_COLUMNS, label_frame
from .metrics import evaluate
from .model import BreachPredictor
from .split import assert_no_infected, chrono_split, exclude_infected


@dataclass
class PredictionRun:
    """Everything needed to inspect or persist one D3-001 run."""

    predictor: BreachPredictor
    train: pd.DataFrame
    test: pd.DataFrame
    predictions: pd.DataFrame
    metrics: dict[str, float | bool]
    feature_cols: list[str]
    cut_ts: float
    horizon_s: int
    infected_windows: list[tuple[float, float]]


def prepare_dataset(
    frame: pd.DataFrame,
    horizon_s: int | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return a feature+label frame and the ordered feature list.

    Rows with an unobservable forward horizon (``label_valid=False``) are
    removed.  Features are computed before labels are merged, and only from
    rows at or before each event time.
    """
    if frame is None or frame.empty:
        raise ValueError("prediction frame is empty")
    labeled = label_frame(frame, horizon_s=horizon_s)
    features, feature_cols = build_features(labeled)
    data = features.merge(
        labeled[["ts", "service"] + LABEL_COLUMNS],
        on=["ts", "service"],
        how="inner",
        validate="one_to_one",
    )
    data = data[data["label_valid"]].copy()
    if data.empty:
        raise ValueError(
            "no rows with a fully observed label window; collect at least H "
            "seconds of history"
        )
    return data.sort_values(["ts", "service"], kind="mergesort").reset_index(drop=True), feature_cols


def _check_two_classes(frame: pd.DataFrame, name: str) -> None:
    classes = set(frame["y_major"].astype(int).unique().tolist())
    if classes != {0, 1}:
        raise ValueError(
            f"{name} labels contain a single class ({sorted(classes)}); "
            "PR-AUC is undefined and fitting would be degenerate"
        )


def run_pipeline(
    frame: pd.DataFrame,
    train_frac: float | None = None,
    infected_windows: Iterable[Sequence[float]] | None = None,
    seed: int | None = None,
    target_precision: float | None = None,
    horizon_s: int | None = None,
) -> PredictionRun:
    """Run the complete D3-001 mechanics on a Contract-C frame.

    ``infected_windows`` are inclusive epoch-second intervals from the
    experiment ledger.  They are applied to the training side only, including
    rows whose forward label window overlaps an injected period.
    """
    horizon = int(config.HORIZON_S if horizon_s is None else horizon_s)
    if horizon <= 0:
        raise ValueError(f"horizon_s must be > 0, got {horizon}")
    windows = [(float(start), float(end)) for start, end in (infected_windows or [])]
    for start, end in windows:
        if start > end:
            raise ValueError(f"infected window start > end: ({start}, {end})")

    data, feature_cols = prepare_dataset(frame, horizon_s=horizon)
    split = chrono_split(data, train_frac=train_frac, horizon_s=horizon, time_col="ts")
    train, test = split.train, split.test

    if windows:
        before = len(train)
        train = exclude_infected(train, windows, horizon_s=horizon, time_col="ts")
        assert_no_infected(train, windows, horizon_s=horizon, time_col="ts")
    else:
        before = len(train)
    if train.empty:
        raise ValueError("infected-period exclusion removed every training row")

    _check_two_classes(train, "training")
    _check_two_classes(test, "holdout")

    predictor = BreachPredictor(
        feature_cols=feature_cols,
        horizon_s=horizon,
        seed=seed,
        target_precision=target_precision,
    ).fit(train)
    predictions = predictor.predict(test)
    if len(predictions) != len(test):
        raise ValueError("prediction row count does not match the holdout")

    metrics = evaluate(
        test["y_major"].astype(int),
        predictions["breach_prob"],
        threshold=float(predictor.threshold),
        target_precision=predictor.target_precision,
    )
    metrics.update(
        {
            "threshold_target_met": bool(predictor.target_met),
            "train_rows": len(train),
            "test_rows": len(test),
            "train_rows_before_infected_exclusion": before,
            "infected_rows_excluded": before - len(train),
            "train_positives": int(train["y_major"].sum()),
            "test_positives": int(test["y_major"].sum()),
            "horizon_s": horizon,
            "seed": int(predictor.seed),
            "provisional": True,
        }
    )
    return PredictionRun(
        predictor=predictor,
        train=train.reset_index(drop=True),
        test=test.reset_index(drop=True),
        predictions=predictions.reset_index(drop=True),
        metrics=metrics,
        feature_cols=feature_cols,
        cut_ts=split.cut_ts,
        horizon_s=horizon,
        infected_windows=windows,
    )


def fit_production_predictor(
    frame: pd.DataFrame,
    seed: int | None = None,
    target_precision: float | None = None,
    horizon_s: int | None = None,
    infected_windows: Iterable[Sequence[float]] | None = None,
) -> BreachPredictor:
    """Fit on all valid, non-infected history (live inference after evaluation)."""
    horizon = int(config.HORIZON_S if horizon_s is None else horizon_s)
    windows = [(float(start), float(end)) for start, end in (infected_windows or [])]
    data, feature_cols = prepare_dataset(frame, horizon_s=horizon)
    if windows:
        data = exclude_infected(data, windows, horizon_s=horizon, time_col="ts")
    if data.empty:
        raise ValueError("no training rows remain after infected-period exclusion")
    _check_two_classes(data, "training")
    return BreachPredictor(
        feature_cols=feature_cols,
        horizon_s=horizon,
        seed=seed,
        target_precision=target_precision,
    ).fit(data)


__all__ = [
    "PredictionRun",
    "FEATURE_COLUMNS",
    "fit_production_predictor",
    "prepare_dataset",
    "run_pipeline",
]
