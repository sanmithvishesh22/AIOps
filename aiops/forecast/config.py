"""Forecast-lane settings (D3-002).

Shared §9 constants come from :mod:`aiops.common.config` (Contract G): ``HORIZON_S``
(the forecast horizon H, ⚙️ provisional until D3-000.7) and ``STEP_S`` (the sample
cadence). Per the lane boundary we do not edit ``aiops/common``.

The season length is a **lane mechanic**, not a §9 constant: it must match the
period of the diurnal regime the load harness (D3-005) generates, so both sides
read the same default and it stays explicit. Everything here is provisional
until the D3-000 characterization run freezes the ⚙️ anchors; mechanics building
against them is allowed, presenting scored results as valid is not.
"""
from __future__ import annotations

import math
import os

from ..common import config as common

# §9-owned constants (shared with ingest/predict, provisional until D3-000.7).
HORIZON_S = common.HORIZON_S
STEP_S = common.STEP_S

# Lane mechanics (not §9 research constants).
# Dominant cycle the forecaster models. MUST match the diurnal-regime period the
# load harness generates (D3-005); override only with team agreement.
SEASON_S = int(os.environ.get("FORECAST_SEASON_S", "600"))
# Sample steps per season — enforced to be a whole number so seasonal-naive
# carry-forward and the harmonic fit sample the same phase grid.
SEASON_M = SEASON_S // STEP_S
# Error metric for the main-vs-baseline comparison (D3-002.5): mae|rmse|smape.
ERROR_METRIC = os.environ.get("FORECAST_ERROR_METRIC", "mae").lower()
# Seasonality gate: strength >= this value keeps the seasonal fit (D3-002.4).
SEASONAL_STRENGTH_MIN = float(os.environ.get("FORECAST_STRENGTH_MIN", "0.40"))
# Minimum tail beyond one season (in steps) for the main model / gate.
MIN_TAIL_STEPS = int(os.environ.get("FORECAST_MIN_TAIL", "8"))
# Seed for every stochastic step (tree baseline) — PS-2.
SEED = int(os.environ.get("FORECAST_SEED", "42"))
# Backends: "harmonic" (Fourier+trend ridge, deterministic default) or
# "prophet" (heavy dep, lazily imported — D3-002.1).
BACKEND = os.environ.get("FORECAST_BACKEND", "harmonic").lower()

_NOISE_WARN = "forecast: dropped %d non-finite sample(s) from the series"


def steps_for_horizon(horizon_s: int | None = None, cadence_s: int | None = None) -> int:
    """Number of cadence steps the forecast covers: ceil(H / STEP_S)."""
    h = int(HORIZON_S if horizon_s is None else horizon_s)
    c = int(STEP_S if cadence_s is None else cadence_s)
    if h <= 0 or c <= 0:
        raise ValueError(f"horizon and cadence must be > 0, got {h} / {c}")
    return int(math.ceil(h / c))


def _validate() -> None:
    if HORIZON_S <= 0:
        raise ValueError(f"HORIZON_S must be > 0, got {HORIZON_S!r}")
    if STEP_S <= 0:
        raise ValueError(f"STEP_S must be > 0, got {STEP_S!r}")
    if SEASON_S <= 0:
        raise ValueError(f"FORECAST_SEASON_S must be > 0, got {SEASON_S!r}")
    if SEASON_S % STEP_S != 0:
        raise ValueError(
            "FORECAST_SEASON_S must be a whole number of sample steps "
            f"({SEASON_S} % {STEP_S} != 0; phase grids would misalign)"
        )
    if SEASON_M < 1:
        raise ValueError(f"season must span at least one sample step, got {SEASON_M}")
    if ERROR_METRIC not in {"mae", "rmse", "smape"}:
        raise ValueError(
            f"FORECAST_ERROR_METRIC must be mae|rmse|smape, got {ERROR_METRIC!r}"
        )
    if not 0.0 <= SEASONAL_STRENGTH_MIN <= 1.0:
        raise ValueError(
            "FORECAST_STRENGTH_MIN must be in [0, 1], "
            f"got {SEASONAL_STRENGTH_MIN!r}"
        )
    if MIN_TAIL_STEPS < 1:
        raise ValueError(f"FORECAST_MIN_TAIL must be >= 1, got {MIN_TAIL_STEPS!r}")
    if BACKEND not in {"harmonic", "prophet"}:
        raise ValueError(
            f"FORECAST_BACKEND must be harmonic|prophet, got {BACKEND!r}"
        )


_validate()
