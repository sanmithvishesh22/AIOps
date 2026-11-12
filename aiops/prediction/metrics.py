"""PR-AUC, precision/recall and train-only threshold selection (numpy only).

The acceptance target is precision >= 70 % at a threshold selected on the
**training** scores.  The holdout is used once, for reporting; it is never used
to pick the threshold.  A target that cannot be met is reported explicitly with
``target_met=False`` — it is never silently rounded up.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from . import config


def _as_arrays(y_true: Iterable, y_score: Iterable) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(list(y_true) if not isinstance(y_true, np.ndarray) else y_true)
    s = np.asarray(list(y_score) if not isinstance(y_score, np.ndarray) else y_score)
    if y.shape != s.shape:
        raise ValueError(f"y_true/y_score shape mismatch: {y.shape} vs {s.shape}")
    if y.ndim != 1:
        raise ValueError("y_true/y_score must be one-dimensional")
    if not np.isin(y, (0, 1)).all():
        raise ValueError("y_true must contain only 0/1")
    s = s.astype(float)
    if not np.isfinite(s).all():
        raise ValueError("y_score contains non-finite values")
    return y.astype(int), s


def pr_auc(y_true: Iterable, y_score: Iterable) -> float:
    """Average precision (step-wise area under the PR curve).

    Returns NaN when the sample has no positives (undefined) and 1.0 when every
    sample is positive.  Ties are handled by evaluating each unique score once.
    """
    y, s = _as_arrays(y_true, y_score)
    positive = int(y.sum())
    if y.size == 0 or positive == 0:
        return float("nan")
    if positive == y.size:
        return 1.0

    ap = 0.0
    previous_recall = 0.0
    for threshold in np.unique(s)[::-1]:
        predicted = s >= threshold
        tp = int(np.sum(predicted & (y == 1)))
        fp = int(np.sum(predicted & (y == 0)))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / positive
        ap += (recall - previous_recall) * precision
        previous_recall = recall
    return float(ap)


def precision_recall_at(
    y_true: Iterable,
    y_score: Iterable,
    threshold: float,
) -> tuple[float, float]:
    """Precision/recall at one score threshold (0/0 is reported as 0, not NaN)."""
    y, s = _as_arrays(y_true, y_score)
    predicted = s >= float(threshold)
    tp = int(np.sum(predicted & (y == 1)))
    fp = int(np.sum(predicted & (y == 0)))
    positives = int(y.sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / positives if positives else 0.0
    return float(precision), float(recall)


def select_threshold(
    y_true: Iterable,
    y_score: Iterable,
    target_precision: float | None = None,
) -> tuple[float, bool]:
    """Pick a decision threshold on training scores.

    Strategy: among thresholds whose precision is at least the target, choose
    the one with maximum recall.  Ties go to the higher precision (larger
    threshold), so we do not add false positives for no recall gain.  If the
    target is unreachable, fall back to the highest-precision threshold and
    return ``target_met=False``.  Ties are broken deterministically by score.
    """
    y, s = _as_arrays(y_true, y_score)
    target = float(config.TARGET_PRECISION if target_precision is None else target_precision)
    if not 0.0 < target <= 1.0:
        raise ValueError(f"target_precision must be in (0, 1], got {target}")
    if int(y.sum()) == 0:
        raise ValueError("threshold selection requires at least one positive label")
    if s.size == 0:
        raise ValueError("threshold selection requires at least one score")

    candidates = np.unique(s)[::-1]
    best_meeting: tuple[float, float, float] | None = None  # (threshold, precision, recall)
    best_any: tuple[float, float, float] | None = None

    for threshold in candidates:
        precision, recall = precision_recall_at(y, s, float(threshold))
        candidate = (float(threshold), precision, recall)
        if best_any is None or (precision, recall, threshold) > (
            best_any[1],
            best_any[2],
            best_any[0],
        ):
            best_any = candidate
        if precision + 1e-12 >= target:
            if best_meeting is None or (recall, precision, threshold) > (
                best_meeting[2],
                best_meeting[1],
                best_meeting[0],
            ):
                best_meeting = candidate

    if best_meeting is not None:
        return best_meeting[0], True
    if best_any is None:  # candidates is non-empty; guard for -O / future edits
        raise ValueError("threshold selection produced no candidate")
    return best_any[0], False


def evaluate(
    y_true: Iterable,
    y_score: Iterable,
    threshold: float,
    target_precision: float | None = None,
) -> dict[str, float | bool]:
    """Holdout metrics using a threshold selected elsewhere (on train)."""
    target = float(config.TARGET_PRECISION if target_precision is None else target_precision)
    precision, recall = precision_recall_at(y_true, y_score, threshold)
    return {
        "pr_auc": pr_auc(y_true, y_score),
        "threshold": float(threshold),
        "target_precision": target,
        "holdout_precision": precision,
        "holdout_recall": recall,
        "holdout_precision_target_met": bool(precision + 1e-12 >= target),
    }
