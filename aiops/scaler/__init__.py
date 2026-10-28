"""Module — forecast-assisted hybrid scaler (D3-003).

Public surface:
    desired_replicas, CapacityAnchor, ScaleDecision, PolicyRefusal   (D3-003.1)
    CooldownState, gate_scale, clamp_bounds                          (D3-003.2)
    ScaleClient, K8sScaleClient, MockScaleClient, server_clamp      (D3-003.3/.4)
    ScalerController, ScaleRun, ServiceOutcome                      (D3-003.5)

Offline check: ``python -m aiops.scaler --selftest`` (mock k8s).
"""
from __future__ import annotations

from . import config
from .cooldown import CooldownState, clamp_bounds, gate_scale, resolve_direction
from .controller import (
    KIND,
    MODULE,
    ScaleRun,
    ScalerController,
    ServiceOutcome,
)
from .policy import CapacityAnchor, PolicyRefusal, ScaleDecision, desired_replicas
from .k8s import (
    K8sScaleClient,
    MockScaleClient,
    ScaleAPIError,
    ScaleClient,
    server_clamp,
)

__all__ = [
    "config",
    "MODULE",
    "KIND",
    "CapacityAnchor",
    "CooldownState",
    "K8sScaleClient",
    "MockScaleClient",
    "PolicyRefusal",
    "ScaleAPIError",
    "ScaleClient",
    "ScaleDecision",
    "ScaleRun",
    "ScalerController",
    "ServiceOutcome",
    "clamp_bounds",
    "desired_replicas",
    "gate_scale",
    "resolve_direction",
    "server_clamp",
]
