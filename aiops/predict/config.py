"""Predict-lane settings.

Shared §9 constants come from :mod:`aiops.common.config` (Contract G). The
"major" breach cut (450 ms) is part of Decision 6 in ``experiment/DECISIONS.md``
but is not yet exposed by the shared config module. Per the lane boundary we do
not edit ``aiops/common`` — this module is the narrow, documented shim until the
constant is folded into Contract G.

The ⚙️ anchors (SLO p95, horizon H) are still provisional until the D3-000
characterization run freezes them. Building against them is allowed; presenting
a scored result as valid is not.
"""
from __future__ import annotations

import os

from ..common import config as common

# Frozen/provisional §9 values owned by the shared config.
HORIZON_S = common.HORIZON_S
SLO_P95_MS = common.SLO_P95_MS
SLO_ERROR_RATE = common.SLO_ERROR_RATE

# Decision 6 (experiment/DECISIONS.md): major = p95 > 450 ms OR error > 1 %.
# Cross-lane contract request: add SLO_MAJOR_P95_MS to aiops/common/config.py.
SLO_MAJOR_P95_MS = float(os.environ.get("SLO_MAJOR_P95_MS", "450"))

# Prediction-lane mechanics (not §9 research constants).
TARGET_PRECISION = float(os.environ.get("PREDICT_TARGET_PRECISION", "0.70"))
TRAIN_FRAC = float(os.environ.get("PREDICT_TRAIN_FRAC", "0.6666666667"))
SEED = int(os.environ.get("PREDICT_SEED", "42"))

# D3-009 — Optional per-service failure-mode taxonomy (off by default)
ENABLE_TAXONOMY = os.environ.get("PREDICT_ENABLE_TAXONOMY", "").lower() in ("1", "true", "yes")


def _validate() -> None:
    if HORIZON_S <= 0:
        raise ValueError(f"HORIZON_S must be > 0, got {HORIZON_S!r}")
    if SLO_P95_MS <= 0 or SLO_MAJOR_P95_MS <= 0:
        raise ValueError("SLO thresholds must be > 0")
    if SLO_MAJOR_P95_MS < SLO_P95_MS:
        raise ValueError(
            "SLO_MAJOR_P95_MS must be >= SLO_P95_MS "
            f"({SLO_MAJOR_P95_MS} < {SLO_P95_MS})"
        )
    if not 0.0 <= SLO_ERROR_RATE <= 1.0:
        raise ValueError(f"SLO_ERROR_RATE must be in [0, 1], got {SLO_ERROR_RATE!r}")
    if not 0.0 < TARGET_PRECISION <= 1.0:
        raise ValueError(
            f"PREDICT_TARGET_PRECISION must be in (0, 1], got {TARGET_PRECISION!r}"
        )
    if not 0.0 < TRAIN_FRAC < 1.0:
        raise ValueError(f"PREDICT_TRAIN_FRAC must be in (0, 1), got {TRAIN_FRAC!r}")


_validate()
