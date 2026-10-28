"""Load-lane settings (D3-005) — k6 harness for the four §9 regimes.

Frozen §9 Decision-3 values (experiment/DECISIONS.md, ratified — not AI-picked):
``stationary / diurnal / spike / bursty`` over a **20 min** trial. The RPS
magnitude anchors are ⚙️ (base RPS = a fraction of the measured per-replica
capacity, D3-000.5) — until then every regime is defined as a *fraction of
base*, and shapes are asserted relative to base only. No synthetic number here
is ever presented as a characterization result.

Coupling: the diurnal period is the SAME season the forecaster models
(`aiops.forecast.config.SEASON_S`) — the forecast must see the seasonality the
harness actually generates. One knob, two read sites.
"""
from __future__ import annotations

import os

from aiops.common import config as common
from aiops.forecast import config as forecast_config

# §9 Decision 3 — frozen trial length (configurable via env for bounded integration testing).
DURATION_S = int(os.environ.get("LOAD_DURATION_S", "1200"))
# Sample grid = the Contract-C step, so profiles align 1:1 with ingested frames.
STEP_S = common.STEP_S
STEPS = DURATION_S // STEP_S
assert DURATION_S % STEP_S == 0, "trial length must be a whole number of steps"

def set_duration(duration_s: int) -> None:
    """Override duration for bounded integration tests."""
    global DURATION_S, STEPS, DURATION_CAP_S
    d = int(duration_s)
    if d <= 0 or d % STEP_S != 0:
        raise ValueError(f"duration must be a positive multiple of {STEP_S}, got {d}")
    DURATION_S = d
    STEPS = d // STEP_S
    DURATION_CAP_S = d

# Diurnal period: identical knob as the forecaster's season (single source).
DIURNAL_PERIOD_S = int(forecast_config.SEASON_S)

# Regime shape parameters — §9 Decision 3 shapes, base as a FRACTION of capacity.
STATIONARY_LEVEL = 0.60        # ~60% of capacity (control)
DIURNAL_MIN = 0.30             # 30% ↔ 90% of capacity, over DIURNAL_PERIOD_S
DIURNAL_MAX = 0.90
SPIKE_BASE = 0.40              # 40% → 100%+ (2.5× base)
SPIKE_FACTOR = 2.5
SPIKE_HOLD_S = 180             # ~3 min held
BURSTY_BASE = 0.20             # 20% + Poisson bursts
BURST_MEAN_GAP_S = 120.0       # mean seconds between burst starts (Poisson)
BURST_MEAN_LEN_S = 30.0        # mean burst length (exponential, capped at 120 s)
BURST_MAX_LEN_S = 120.0
BURST_AMP_MIN = 0.20           # burst amplitude as a fraction of capacity
BURST_AMP_MAX = 0.60

DURATION_CAP_S = DURATION_S    # PS-8: jobs bounded; the manifest deadline enforces it

# Sock Shop edge service under load (Decision 1 primary SLO).
TARGET_URL = os.environ.get(
    "LOAD_TARGET_URL",
    f"http://front-end.{common.SOCK_NS}.svc.cluster.local:80/",
)
K6_IMAGE = os.environ.get("LOAD_K6_IMAGE", "grafana/k6:0.49.0")
SEED = int(os.environ.get("LOAD_SEED", "42"))
MANIFEST_NAMESPACE = "aiops"   # jobs/cmaps live in the PLATFORM namespace, not sock-shop

REGIMES = ("stationary", "diurnal", "spike", "bursty")


def _validate() -> None:
    if DURATION_S <= 0 or STEP_S <= 0:
        raise ValueError(f"duration/step must be > 0, got {DURATION_S}/{STEP_S}")
    if not TARGET_URL.startswith("http"):
        raise ValueError("LOAD_TARGET_URL must be an http(s) URL")
    if f".{common.SOCK_NS}." not in TARGET_URL and "cluster.local" in TARGET_URL:
        raise ValueError(
            f"LOAD_TARGET_URL must point into {common.SOCK_NS} (blast radius, PS-8)"
        )
    if SEED < 0:
        raise ValueError(f"LOAD_SEED must be >= 0, got {SEED!r}")
    if not 0.0 < STATIONARY_LEVEL < 1.0 or not 0.0 < BURSTY_BASE < 1.0:
        raise ValueError("regime levels must be in (0, 1) fractions of capacity")
    if not 0.0 < BURST_AMP_MIN < BURST_AMP_MAX:
        raise ValueError("burst amplitude band must satisfy 0 < min < max")


_validate()


__all__ = [
    "DURATION_S", "STEP_S", "STEPS", "DIURNAL_PERIOD_S", "DURATION_CAP_S",
    "STATIONARY_LEVEL", "DIURNAL_MIN", "DIURNAL_MAX",
    "SPIKE_BASE", "SPIKE_FACTOR", "SPIKE_HOLD_S",
    "BURSTY_BASE", "BURST_MEAN_GAP_S", "BURST_MEAN_LEN_S",
    "BURST_MAX_LEN_S", "BURST_AMP_MIN", "BURST_AMP_MAX",
    "TARGET_URL", "K6_IMAGE", "SEED", "MANIFEST_NAMESPACE", "REGIMES",
]
