"""Fault-lane settings (D3-006) — Chaos Mesh harness + negative controls.

§9 Decision 5 (ratified): 2 capacity-responsive + 4 negative-control fault
classes, all scoped HARD to ``SOCK_NS``. Fault intensities/durations are
predeclared defaults (Decision 5 "knobs"): they are mechanics starting points
to be frozen at the characterization run — never tuned after seeing trial
data. There is no synthetic fault result here, only manifest builders.

Predeclared detail (harness choice, logged in the execution ledger):
``dependency_kill`` targets the ``orders-db`` backend so the front-end cannot
fix the fault by adding replicas (that is the point of the control).
"""
from __future__ import annotations

import os

from aiops.common import config as common

SOCK_NS = common.SOCK_NS

# Chaos-Mesh API group (live validation pending — no cluster in offline runs).
CHAOS_API = "chaos-mesh.org/v1alpha1"

# Fault durations — predeclared defaults, frozen at D3-000.7.
FAULT_DURATION_S = 300

# Injection point: faults fire halfway through the 20-min trial (predeclared,
# deterministic; the seeded jitter lives in the runner, not here).
FAULT_ONSET_FRACTION = 0.50

# Predeclared dependency-kill target (administrative choice, not §9-numeric).
DEPENDENCY_TARGET = os.environ.get("FAULT_DEPENDENCY_TARGET", "orders-db")

# Predeclared stress-mechanics (freeze at D3-000.7 if the advisor wants other values).
CPU_WORKERS = 8
CPU_LOAD_PCT = 100.0
NET_LATENCY_MS = 100.0
NET_LOSS_PCT = 10.0
MEM_SIZE = "512MB"

# Labels carrying the experiment contract (D3-006.4: EVERY fault is tagged).
LABEL_FAULT = "aiops.platform/fault-class"
LABEL_CONTROL = "aiops.platform/is-negative-control"
LABEL_SEED = "aiops.platform/run-seed"
LABEL_COMPONENT = "aiops.platform/component"
LABEL_PART_OF = "app.kubernetes.io/part-of"

# The ratified fault set — order matters for the complete matrix (Decision 5).
FAULT_CLASSES: tuple[str, ...] = (
    "cpu_stress",        # capacity-responsive
    "pod_kill",          # capacity-responsive
    "network_fault",     # negative control
    "code_fault",        # negative control
    "dependency_kill",   # negative control
    "memory_leak",       # negative control
)
CAPACITY_RESPONSIVE: dict[str, bool] = {
    "cpu_stress": False,
    "pod_kill": False,
    "network_fault": True,
    "code_fault": True,
    "dependency_kill": True,
    "memory_leak": True,
}
IS_NEGATIVE_CONTROL = CAPACITY_RESPONSIVE


def _validate() -> None:
    if not SOCK_NS:
        raise ValueError("SOCK_NS must be a non-empty namespace for any fault work")
    if set(CAPACITY_RESPONSIVE) != set(FAULT_CLASSES):
        raise ValueError("fault registry incomplete: every class needs a control flag")
    if FAULT_DURATION_S <= 0:
        raise ValueError(f"FAULT_DURATION_S must be > 0, got {FAULT_DURATION_S!r}")
    if not 0.0 <= FAULT_ONSET_FRACTION < 1.0:
        raise ValueError(
            f"FAULT_ONSET_FRACTION must be in [0, 1), got {FAULT_ONSET_FRACTION!r}"
        )


_validate()


__all__ = [
    "SOCK_NS", "CHAOS_API", "FAULT_DURATION_S", "FAULT_ONSET_FRACTION",
    "DEPENDENCY_TARGET", "CPU_WORKERS", "CPU_LOAD_PCT", "NET_LATENCY_MS",
    "NET_LOSS_PCT", "MEM_SIZE", "FAULT_CLASSES", "CAPACITY_RESPONSIVE",
    "IS_NEGATIVE_CONTROL", "LABEL_FAULT", "LABEL_CONTROL", "LABEL_SEED",
    "LABEL_COMPONENT", "LABEL_PART_OF",
]
