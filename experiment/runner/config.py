"""Runner-lane settings (D3-007) — paired trial orchestration.

§9 Decision-5 matrix: 4 regimes × 6 faults (2 capacity-responsive + 4 controls)
over ≥20 paired reps per cell. Every pair shares seed/regime/fault/duration,
differing only in policy (hpa_tuned vs forecast_hybrid). Policy execution order
within each pair is randomized under the master seed (PS-2, D3-007.2).
"""
from __future__ import annotations

import os

from aiops.common import config as common
from experiment.faults import config as faults_config
from experiment.load import config as load_config

# Matched policies (Contract D / schema.sql)
POLICIES: tuple[str, str] = ("hpa_tuned", "forecast_hybrid")

# Regimes and faults from authoritative lane configs
REGIMES = load_config.REGIMES
FAULT_CLASSES = faults_config.FAULT_CLASSES
IS_NEGATIVE_CONTROL = faults_config.IS_NEGATIVE_CONTROL

# Trial dimensions
TRIAL_DURATION_S = load_config.DURATION_S
STEP_S = common.STEP_S
MIN_REPS_PER_CELL = int(os.environ.get("RUNNER_MIN_REPS", "20"))
MASTER_SEED = int(os.environ.get("RUNNER_MASTER_SEED", "42"))

# §9 calibration anchors (Contract G / DECISIONS.md)
SLO_P95_MS = common.SLO_P95_MS
SLO_ERROR_RATE = common.SLO_ERROR_RATE
SLO_WINDOW_S = common.SLO_WINDOW_S
HORIZON_S = common.HORIZON_S

# Database credentials for results persistence (Contract D)
TIMESCALE_DSN = common.TIMESCALE_DSN

# Cooldown buffer after a run settles (seconds)
INTER_RUN_COOLDOWN_S = int(os.environ.get("RUNNER_INTER_RUN_COOLDOWN_S", "30"))


def _validate() -> None:
    if MIN_REPS_PER_CELL < 1:
        raise ValueError(f"MIN_REPS_PER_CELL must be >= 1, got {MIN_REPS_PER_CELL}")
    if MASTER_SEED < 0:
        raise ValueError(f"MASTER_SEED must be >= 0, got {MASTER_SEED}")
    if set(POLICIES) != {"hpa_tuned", "forecast_hybrid"}:
        raise ValueError(f"Invalid policies: {POLICIES}")


_validate()

__all__ = [
    "POLICIES",
    "REGIMES",
    "FAULT_CLASSES",
    "IS_NEGATIVE_CONTROL",
    "TRIAL_DURATION_S",
    "STEP_S",
    "MIN_REPS_PER_CELL",
    "MASTER_SEED",
    "SLO_P95_MS",
    "SLO_ERROR_RATE",
    "SLO_WINDOW_S",
    "HORIZON_S",
    "TIMESCALE_DSN",
    "INTER_RUN_COOLDOWN_S",
]
