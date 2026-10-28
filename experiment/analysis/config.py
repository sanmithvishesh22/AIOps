"""Settings for statistical analysis of matched pairs (D3-008).

§9 Decision 5 & 6 analysis requirements:
  * Primary: slo_breach_duration_s, breaching_requests (with 95% bootstrap CIs)
  * Secondary: pod_minutes (cost), scaling_actions (churn), oscillations
  * Separate negative-control reporting (null results printed as-is)
  * Paired bootstrap respects pairing (resamples pairs, not pooled trials)
  * Deterministic under seed (PS-2)
"""
from __future__ import annotations

import os

# Default number of bootstrap resamples
BOOTSTRAP_RESAMPLES = int(os.environ.get("ANALYSIS_BOOTSTRAP_RESAMPLES", "2000"))

# Primary confidence level
CONFIDENCE_LEVEL = float(os.environ.get("ANALYSIS_CONFIDENCE_LEVEL", "0.95"))
ALPHA = 1.0 - CONFIDENCE_LEVEL

# Master RNG seed for reproducibility (PS-2)
DEFAULT_SEED = int(os.environ.get("ANALYSIS_SEED", "42"))

# Minimum reps required for high-fidelity CI (warn if fewer)
MIN_REPS_FOR_CI = 20

__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "CONFIDENCE_LEVEL",
    "ALPHA",
    "DEFAULT_SEED",
    "MIN_REPS_FOR_CI",
]
