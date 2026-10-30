"""QA-004 — Forecast/Predict Metric Gate.

Mandatory Protocol:
  - QA-004.1: PR-AUC >= target for predict module on chronological holdout.
  - QA-004.2: Forecast error < seasonal-naive + tree baselines.
  - QA-004.3: Label all outputs with the mandatory caveat:
    "INSTRUMENT-QUALITY METRIC: Not a reliability proof. §9 reliability is determined solely by live paired-trial Contract-D outcomes."
"""
from __future__ import annotations

from typing import Any, Dict
import numpy as np

MANDATORY_CAVEAT = (
    "INSTRUMENT-QUALITY METRIC: Not a reliability proof. "
    "§9 reliability is determined solely by live paired-trial Contract-D outcomes."
)


class MetricGateFailure(AssertionError):
    """Raised when an instrument metric fails to meet acceptance thresholds."""
    pass


def evaluate_predict_metric_gate(
    pr_auc_score: float,
    target_pr_auc: float = 0.70,
) -> Dict[str, Any]:
    """QA-004.1: Assert PR-AUC meets or exceeds target threshold on chronological test set."""
    if np.isnan(pr_auc_score) or pr_auc_score < target_pr_auc:
        raise MetricGateFailure(
            f"QA-004.1 FAILED: PR-AUC ({pr_auc_score:.4f}) < target ({target_pr_auc:.4f})"
        )

    return {
        "metric": "PR-AUC",
        "score": float(pr_auc_score),
        "target": float(target_pr_auc),
        "passed": True,
        "caveat": MANDATORY_CAVEAT,
    }


def evaluate_forecast_metric_gate(
    main_error: float,
    snaive_error: float,
    tree_error: float,
    metric_name: str = "MAE",
) -> Dict[str, Any]:
    """QA-004.2: Assert main forecast model beats both seasonal-naive and tree baselines."""
    beats_snaive = main_error < snaive_error
    beats_tree = main_error < tree_error

    if not (beats_snaive and beats_tree):
        reasons = []
        if not beats_snaive:
            reasons.append(f"main ({main_error:.4f}) >= snaive ({snaive_error:.4f})")
        if not beats_tree:
            reasons.append(f"main ({main_error:.4f}) >= tree ({tree_error:.4f})")
        raise MetricGateFailure(
            f"QA-004.2 FAILED: Main model did not beat all baselines ({metric_name}): {'; '.join(reasons)}"
        )

    return {
        "metric": metric_name,
        "main_error": float(main_error),
        "snaive_error": float(snaive_error),
        "tree_error": float(tree_error),
        "passed": True,
        "caveat": MANDATORY_CAVEAT,
    }


def run_selftest() -> bool:
    print("Running QA-004 Forecast/Predict Metric Gate selftest...")
    
    # Test QA-004.1: predict gate
    res1 = evaluate_predict_metric_gate(0.78, target_pr_auc=0.70)
    assert res1["passed"] is True
    assert MANDATORY_CAVEAT in res1["caveat"]
    print("  ✓ QA-004.1 PR-AUC gate green test passed")

    try:
        evaluate_predict_metric_gate(0.65, target_pr_auc=0.70)
        raise AssertionError("Expected MetricGateFailure on sub-target PR-AUC")
    except MetricGateFailure:
        print("  ✓ QA-004.1 PR-AUC gate red test passed (loud failure on failure)")

    # Test QA-004.2: forecast baselines gate
    res2 = evaluate_forecast_metric_gate(main_error=1.5, snaive_error=2.8, tree_error=2.1)
    assert res2["passed"] is True
    assert MANDATORY_CAVEAT in res2["caveat"]
    print("  ✓ QA-004.2 Forecast baselines gate green test passed")

    try:
        evaluate_forecast_metric_gate(main_error=2.5, snaive_error=2.8, tree_error=2.1)
        raise AssertionError("Expected MetricGateFailure when tree baseline beats main")
    except MetricGateFailure:
        print("  ✓ QA-004.2 Forecast baselines gate red test passed (loud failure on failure)")

    print("All QA-004 metric gate checks green.")
    return True


if __name__ == "__main__":
    run_selftest()
