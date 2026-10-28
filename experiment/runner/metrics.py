"""D3-007.5 — Metrics calculation & infected-period exclusion.

Computes the Contract-D `experiment_result` scorecard from a trial's telemetry series:
  * Primary: slo_breach_duration_s, breaching_requests, breaching_request_ratio
  * Cost & churn: pod_minutes, scaling_actions, oscillations
  * Quality: mttd_s, rca_top1_correct, remediation_success

Infected exclusion (D3-007.5):
  Samples during the active fault window can be separated or filtered out
  for clean uninfected analysis without deleting raw telemetry from storage.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Sequence

from . import config


@dataclasses.dataclass(frozen=True)
class TelemetryPoint:
    """One discrete time step of trial observations (at config.STEP_S interval)."""

    ts: float                      # epoch seconds
    p95_ms: float                  # front-end p95 latency
    error_rate: float              # 5xx ratio
    rps: float                     # request rate
    replicas: int                  # active replica count
    is_infected: bool = False      # true during active fault window


@dataclasses.dataclass(frozen=True)
class Scorecard:
    """Computed scorecard matching Contract-D `experiment_result` schema."""

    slo_breach_duration_s: float
    breaching_requests: int
    breaching_request_ratio: float
    pod_minutes: float
    scaling_actions: int
    oscillations: int
    mttd_s: float | None = None
    rca_top1_correct: bool | None = None
    remediation_success: bool | None = None
    extra: dict | None = None

    def __post_init__(self) -> None:
        """Validate invariant boundaries and prevent unit or timestamp confusion (PS-3)."""
        dur = float(self.slo_breach_duration_s)
        if not math.isfinite(dur) or dur < 0.0:
            raise ValueError(f"slo_breach_duration_s must be non-negative and finite, got {dur}")
        # Guard against epoch timestamp (e.g. 1.9e9) accidentally passed as duration
        if dur > 86400.0:  # > 24 hours cannot be a trial breach duration
            raise ValueError(
                f"Invalid breach duration: {dur}s exceeds 86400s; "
                "epoch timestamp or unit confusion detected"
            )
        if self.breaching_requests < 0:
            raise ValueError(f"breaching_requests cannot be negative, got {self.breaching_requests}")
        if not (0.0 <= float(self.breaching_request_ratio) <= 1.0):
            raise ValueError(f"breaching_request_ratio must be in [0, 1], got {self.breaching_request_ratio}")
        if float(self.pod_minutes) < 0.0:
            raise ValueError(f"pod_minutes cannot be negative, got {self.pod_minutes}")
        if self.scaling_actions < 0:
            raise ValueError(f"scaling_actions cannot be negative, got {self.scaling_actions}")
        if self.oscillations < 0:
            raise ValueError(f"oscillations cannot be negative, got {self.oscillations}")


def tag_infected_samples(
    points: Sequence[TelemetryPoint],
    fault_onset_s: float,
    fault_duration_s: float,
    trial_start_s: float | None = None,
) -> list[TelemetryPoint]:
    """Tag each point with its infected status based on the fault schedule."""
    if not points:
        return []
    start = points[0].ts if trial_start_s is None else trial_start_s
    fault_start = start + fault_onset_s
    fault_end = fault_start + fault_duration_s

    tagged: list[TelemetryPoint] = []
    for p in points:
        infected = fault_start <= p.ts <= fault_end
        tagged.append(
            TelemetryPoint(
                ts=p.ts,
                p95_ms=p.p95_ms,
                error_rate=p.error_rate,
                rps=p.rps,
                replicas=p.replicas,
                is_infected=infected,
            )
        )
    return tagged


def exclude_infected(
    points: Sequence[TelemetryPoint],
) -> list[TelemetryPoint]:
    """Return only the uninfected telemetry points (D3-007.5)."""
    return [p for p in points if not p.is_infected]


def compute_scorecard(
    points: Sequence[TelemetryPoint],
    step_s: int = config.STEP_S,
    slo_p95_ms: float = config.SLO_P95_MS,
    slo_error_rate: float = config.SLO_ERROR_RATE,
    exclude_infected_period: bool = False,
) -> Scorecard:
    """Calculate the Contract-D scorecard from a sequence of telemetry points."""
    if step_s <= 0:
        raise ValueError(f"step_s must be positive, got {step_s}")

    pts = exclude_infected(points) if exclude_infected_period else list(points)
    if not pts:
        return Scorecard(
            slo_breach_duration_s=0.0,
            breaching_requests=0,
            breaching_request_ratio=0.0,
            pod_minutes=0.0,
            scaling_actions=0,
            oscillations=0,
        )

    # Validate timestamps integrity
    for i, p in enumerate(pts):
        if not math.isfinite(p.ts):
            raise ValueError(f"Telemetry point at index {i} has non-finite timestamp: {p.ts}")
        if i > 0 and p.ts < pts[i - 1].ts:
            raise ValueError(
                f"Invalid telemetry: reversed or non-chronological timestamps detected at index {i} "
                f"({p.ts} < {pts[i - 1].ts})"
            )

    breach_duration_s = 0.0
    breaching_requests = 0
    total_requests = 0.0
    total_pod_seconds = 0.0
    scaling_actions = 0
    oscillations = 0

    prev_replicas: int | None = None
    prev_direction: int = 0  # +1 for scale-up, -1 for scale-down, 0 for none

    for p in pts:
        # Check SLO breach: p95 > SLO OR error_rate > SLO_ERROR_RATE
        is_breach = False
        if math.isfinite(p.p95_ms) and p.p95_ms > slo_p95_ms:
            is_breach = True
        elif math.isfinite(p.error_rate) and p.error_rate > slo_error_rate:
            is_breach = True

        requests_in_step = max(0.0, p.rps * step_s)
        total_requests += requests_in_step

        if is_breach:
            breach_duration_s += float(step_s)
            breaching_requests += int(round(requests_in_step))

        # Resource cost: replica-minutes
        total_pod_seconds += float(p.replicas * step_s)

        # Churn: scaling actions and oscillations
        if prev_replicas is not None:
            if p.replicas != prev_replicas:
                scaling_actions += 1
                curr_direction = 1 if p.replicas > prev_replicas else -1
                if prev_direction != 0 and curr_direction == -prev_direction:
                    oscillations += 1
                prev_direction = curr_direction

        prev_replicas = p.replicas

    ratio = breaching_requests / total_requests if total_requests > 0 else 0.0

    return Scorecard(
        slo_breach_duration_s=round(breach_duration_s, 2),
        breaching_requests=breaching_requests,
        breaching_request_ratio=round(min(1.0, max(0.0, ratio)), 6),
        pod_minutes=round(total_pod_seconds / 60.0, 2),
        scaling_actions=scaling_actions,
        oscillations=oscillations,
    )


__all__ = [
    "TelemetryPoint",
    "Scorecard",
    "tag_infected_samples",
    "exclude_infected",
    "compute_scorecard",
]
