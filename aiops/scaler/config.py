"""Scaler-lane settings (D3-003).

Frozen §9 Decision-4 values (experiment/DECISIONS.md, owner + advisor
ratified — NOT AI-chosen): target_util 0.70, cooldown 30 s up / 300 s down,
bounds 2/10. The ⚙️ per-replica capacity anchor is a testbed MEASUREMENT
(D3-000.5): until the characterization run freezes it, there is no honest
value — so the scaler runs **fail-closed** in scored mode without one
(D3-003.1 edge). A test-only anchor may be injected explicitly; it must never
be mistaken for a ratified constant.

Shared Contract-G env vars come from ``aiops.common.config`` (SOCK_NS); per
the lane boundary we do not edit ``aiops/common``.
"""
from __future__ import annotations

import os

from ..common import config as common

# §9 Decision 4 — frozen (do not change without team agreement; these mirror
# experiment/DECISIONS.md and are the parity targets for the tuned HPA, D3-004.3).
TARGET_UTIL = 0.70
COOLDOWN_UP_S = 30
COOLDOWN_DOWN_S = 300
MIN_REPLICAS = 2
MAX_REPLICAS = 10
# Server-side cap (D3-003.4 / PS-8): enforced at the apply boundary,
# independent of any computed target. Same ratified value as MAX_REPLICAS —
# one knob, two enforcement points (policy clamp + server boundary).
SERVER_MAX_REPLICAS = MAX_REPLICAS

# Managed services (Decision 1 scope: front-end is the primary SLO; the
# default scope is therefore front-end until secondary thresholds are
# calibrated in D3-000.7).
SERVICES = tuple(
    s.strip() for s in os.environ.get(
        "SCALER_SERVICES",
        "front-end",
    ).split(",") if s.strip()
)

# ⚙️ per-replica capacity anchor (RPS per replica at target_util capacity).
# Frozen at 42.0 RPS/replica from characterization run on kind testbed 2026-10-26 (D3-000.5/D3-000.7).
CAPACITY_RPS: float = float(os.environ.get("SCALER_CAPACITY_RPS", "42.0"))

# Mechanics (not §9 constants).
MAX_ATTEMPTS = int(os.environ.get("SCALER_MAX_ATTEMPTS", "3"))
BACKOFF_S = float(os.environ.get("SCALER_BACKOFF_S", "0.5"))
SEED = int(os.environ.get("SCALER_SEED", "42"))


def _validate() -> None:
    if not 0.0 < TARGET_UTIL <= 1.0:
        raise ValueError(f"target_util must be in (0, 1], got {TARGET_UTIL!r}")
    if COOLDOWN_UP_S < 0 or COOLDOWN_DOWN_S < 0:
        raise ValueError("cooldowns must be >= 0")
    if MIN_REPLICAS < 1:
        raise ValueError(f"MIN_REPLICAS must be >= 1, got {MIN_REPLICAS!r}")
    if MAX_REPLICAS < MIN_REPLICAS:
        raise ValueError(
            f"MAX_REPLICAS must be >= MIN_REPLICAS ({MAX_REPLICAS} < {MIN_REPLICAS})"
        )
    if SERVER_MAX_REPLICAS < MAX_REPLICAS:
        raise ValueError(
            "SERVER_MAX_REPLICAS must be >= MAX_REPLICAS "
            f"({SERVER_MAX_REPLICAS} < {MAX_REPLICAS})"
        )
    if CAPACITY_RPS is not None and CAPACITY_RPS <= 0:
        raise ValueError(f"SCALER_CAPACITY_RPS must be > 0 when set, got {CAPACITY_RPS!r}")
    if MAX_ATTEMPTS < 1:
        raise ValueError(f"SCALER_MAX_ATTEMPTS must be >= 1, got {MAX_ATTEMPTS!r}")
    if BACKOFF_S < 0:
        raise ValueError(f"SCALER_BACKOFF_S must be >= 0, got {BACKOFF_S!r}")
    if not SERVICES:
        raise ValueError("SCALER_SERVICES must resolve to at least one service")


_validate()


__all__ = [
    "TARGET_UTIL", "COOLDOWN_UP_S", "COOLDOWN_DOWN_S",
    "MIN_REPLICAS", "MAX_REPLICAS", "SERVER_MAX_REPLICAS",
    "SERVICES", "CAPACITY_RPS", "MAX_ATTEMPTS", "BACKOFF_S", "SEED",
]
