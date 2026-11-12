"""Backward-compatibility shim. Migrated to aiops.scaling.

All public names are re-exported from aiops.scaling for backward
compatibility. New code should import directly from aiops.scaling.
"""
from aiops.scaling import (  # noqa: F401
    config,
    MODULE,
    KIND,
    CapacityAnchor,
    CooldownState,
    K8sScaleClient,
    MockScaleClient,
    PolicyRefusal,
    ScaleAPIError,
    ScaleClient,
    ScaleDecision,
    ScaleRun,
    ScalerController,
    ServiceOutcome,
    clamp_bounds,
    desired_replicas,
    gate_scale,
    resolve_direction,
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