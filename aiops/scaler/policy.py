"""D3-003.1 — the pure forecast→replicas map.

    desired = clip(ceil(forecast_RPS / (target_util × per_replica_capacity)),
                   min, max)

Ratified values come from :mod:`aiops.scaler.config` (§9 Decision 4). The
function is pure and deterministic (no clock, no RNG, no I/O — PS-2). Every
guard is fail-closed or hold-last-known-good, never a guess:

* capacity anchor absent (pre-D3-000.7)      → refuse to emit a scored target
* forecast NaN / ±inf / non-positive         → hold last-known-good + reason
* target above max / below min               → clamped, reason records the clamp
* nothing known-good to hold                 → refusal (also fail-closed)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import config


@dataclass(frozen=True)
class CapacityAnchor:
    """⚙️ per-replica capacity (RPS per replica) — a testbed MEASUREMENT.

    ``provenance`` must say where the number came from (env, config, or
    test fixture); a fabricated value is a validity failure, not a fallback.
    """

    rps_per_replica: float
    provenance: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.rps_per_replica) or self.rps_per_replica <= 0:
            raise ValueError(
                f"capacity anchor must be finite > 0, got {self.rps_per_replica!r}"
            )


class PolicyRefusal(Exception):
    """The scaler refuses to emit a scored target (fail-closed, PS-3)."""


@dataclass(frozen=True)
class ScaleDecision:
    """Outcome of the policy for one service at one instant."""

    service: str
    replicas: int                    # the decided (bounded) replica count
    reason: str
    forecast_rps: float | None       # None when holding (bad forecast)
    clamped: bool                    # True when bounds/ceil had to trim the ask
    held: bool                       # True when last-known-good was kept


def desired_replicas(
    forecast_rps: float,
    anchor: CapacityAnchor | None,
    *,
    service: str = "service",
    target_util: float | None = None,
    bounds: tuple[int, int] | None = None,
    last_known_good: int | None = None,
) -> ScaleDecision:
    """Pure map: forecast RPS (at horizon H) → desired replicas.

    ``last_known_good`` is the previous sane replica count to hold when the
    forecast is unusable (None + bad forecast ⇒ refusal; there is nothing
    safe to hold).
    """
    util = float(config.TARGET_UTIL if target_util is None else target_util)
    if bounds is None:
        lo, hi = config.MIN_REPLICAS, config.MAX_REPLICAS
    else:
        lo, hi = bounds
    if not 0.0 < util <= 1.0:
        raise ValueError(f"target_util must be in (0, 1], got {util!r}")
    if lo > hi:
        raise ValueError(f"bounds min > max: {(lo, hi)!r}")

    if anchor is None:
        raise PolicyRefusal(
            f"{service}: no capacity anchor (⚙️ pending D3-000.5/D3-000.7) — "
            "refusing to emit a scored replica target"
        )

    fc = float(forecast_rps)
    if not math.isfinite(fc):
        return _hold(service, f"bad_forecast_nonfinite:{fc}", last_known_good)
    if fc <= 0.0:
        return _hold(service, f"bad_forecast_nonpositive:{fc}", last_known_good)

    capacity = util * anchor.rps_per_replica
    raw = int(math.ceil(fc / capacity))
    replicas = int(min(max(raw, lo), hi))
    if raw > hi:
        reason = f"forecast_scaled:{fc:.6f}rps_capped_at_max"
    elif raw < lo:
        reason = f"forecast_scaled:{fc:.6f}rps_floored_at_min"
    else:
        reason = f"forecast_scaled:{fc:.6f}rps"
    return ScaleDecision(service, replicas, reason, fc, raw != replicas, False)


def _hold(service: str, reason: str, last_known_good: int | None) -> ScaleDecision:
    if last_known_good is None:
        raise PolicyRefusal(
            f"{service}: unusable forecast ({reason}) and no last-known-good "
            "replica count to hold — refusing to emit a scored target"
        )
    return ScaleDecision(
        service,
        int(last_known_good),
        f"{reason}_held_last_good",
        None,
        False,
        True,
    )


__all__ = [
    "CapacityAnchor",
    "PolicyRefusal",
    "ScaleDecision",
    "desired_replicas",
]
