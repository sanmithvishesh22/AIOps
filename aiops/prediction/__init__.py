"""Module 4 — SLO-breach prediction at horizon H (D3-001).

Public surface:
    build_features, FEATURE_COLUMNS
    label_frame, severity_masks
    chrono_split, exclude_infected, assert_no_infected
    pr_auc, precision_recall_at, select_threshold, evaluate
    BreachPredictor
    prepare_dataset, run_pipeline, fit_production_predictor
    inference_rows, write_inference

Offline check: ``python -m aiops.predict --selftest``.
"""
from __future__ import annotations

from .features import FEATURE_COLUMNS, build_features
from .inference import KINDS, inference_rows, write_inference
from .labels import label_frame, severity_masks, thresholds
from .metrics import evaluate, pr_auc, precision_recall_at, select_threshold
from .model import BreachPredictor
from .pipeline import (
    PredictionRun,
    fit_production_predictor,
    prepare_dataset,
    run_pipeline,
)
from .split import ChronoSplit, assert_no_infected, chrono_split, exclude_infected

__all__ = [
    "BreachPredictor",
    "ChronoSplit",
    "FEATURE_COLUMNS",
    "KINDS",
    "PredictionRun",
    "assert_no_infected",
    "build_features",
    "chrono_split",
    "evaluate",
    "exclude_infected",
    "fit_production_predictor",
    "inference_rows",
    "label_frame",
    "pr_auc",
    "precision_recall_at",
    "prepare_dataset",
    "run_pipeline",
    "select_threshold",
    "severity_masks",
    "thresholds",
    "write_inference",
]
