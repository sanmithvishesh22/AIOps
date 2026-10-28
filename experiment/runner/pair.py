"""D3-007.1 & D3-007.2 — Matched-pair construction + randomized policy order.

Every cell in the matrix (regime × fault) has ≥20 matched pairs. Each pair:
  * shares identical workload_regime, fault_class, duration, and trial seed (PS-2);
  * differs ONLY in policy (hpa_tuned vs forecast_hybrid);
  * executes in randomized order within the pair (seeded, removing order/warmup bias);
  * is atomic: if either member fails, the entire pair is discarded (D3-007.1 edge).
"""
from __future__ import annotations

import dataclasses
import hashlib
import random
from typing import Sequence

from . import config


@dataclasses.dataclass(frozen=True)
class TrialSpec:
    """Specification for a single run within a matched pair."""

    pair_id: str
    policy: str
    workload_regime: str
    fault_class: str
    is_negative_control: bool
    seed: int
    duration_s: int
    slo_p95_ms: float = config.SLO_P95_MS
    slo_error_rate: float = config.SLO_ERROR_RATE
    horizon_s: int = config.HORIZON_S

    def __post_init__(self) -> None:
        if self.policy not in config.POLICIES:
            raise ValueError(f"Invalid policy {self.policy!r}, expected one of {config.POLICIES}")
        if self.workload_regime not in config.REGIMES:
            raise ValueError(f"Invalid regime {self.workload_regime!r}")
        if self.fault_class not in config.FAULT_CLASSES:
            raise ValueError(f"Invalid fault class {self.fault_class!r}")


@dataclasses.dataclass(frozen=True)
class MatchedPair:
    """A matched pair of trials (hpa_tuned vs forecast_hybrid)."""

    pair_id: str
    regime: str
    fault_class: str
    is_negative_control: bool
    seed: int
    rep_index: int
    ordered_policies: tuple[str, str]
    duration_s: int = config.TRIAL_DURATION_S

    def trials(self) -> tuple[TrialSpec, TrialSpec]:
        """Return the two TrialSpecs in their randomized execution order."""
        t1 = TrialSpec(
            pair_id=self.pair_id,
            policy=self.ordered_policies[0],
            workload_regime=self.regime,
            fault_class=self.fault_class,
            is_negative_control=self.is_negative_control,
            seed=self.seed,
            duration_s=self.duration_s,
        )
        t2 = TrialSpec(
            pair_id=self.pair_id,
            policy=self.ordered_policies[1],
            workload_regime=self.regime,
            fault_class=self.fault_class,
            is_negative_control=self.is_negative_control,
            seed=self.seed,
            duration_s=self.duration_s,
        )
        return (t1, t2)


def derive_pair_seed(master_seed: int, regime: str, fault: str, rep: int) -> int:
    """Deterministic 31-bit seed for a specific cell repetition."""
    raw = f"{master_seed}:{regime}:{fault}:{rep}".encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    return int(h[:8], 16) & 0x7FFFFFFF


def build_matrix(
    reps: int = config.MIN_REPS_PER_CELL,
    master_seed: int = config.MASTER_SEED,
    regimes: Sequence[str] = config.REGIMES,
    faults: Sequence[str] = config.FAULT_CLASSES,
    duration_s: int | None = None,
) -> list[MatchedPair]:
    """Construct the complete matrix of matched pairs with randomized policy order.

    D3-007.1: identical seed/regime/fault/duration across members.
    D3-007.2: seeded randomized order of policy within each pair.
    D3-007.3: reps >= 20 per cell.
    """
    if reps < 1:
        raise ValueError(f"reps must be >= 1, got {reps}")

    trial_duration = int(duration_s if duration_s is not None else config.TRIAL_DURATION_S)
    rng = random.Random(master_seed)
    pairs: list[MatchedPair] = []

    for regime in regimes:
        for fault in faults:
            is_control = config.IS_NEGATIVE_CONTROL[fault]
            for rep in range(reps):
                pair_seed = derive_pair_seed(master_seed, regime, fault, rep)
                pair_id = f"pair-{regime[:4]}-{fault[:4]}-{rep:02d}-{pair_seed:08x}"

                # Seeded policy order randomization (D3-007.2)
                # Flip deterministic bit for policy order
                if rng.random() < 0.5:
                    ordered = ("hpa_tuned", "forecast_hybrid")
                else:
                    ordered = ("forecast_hybrid", "hpa_tuned")

                pair = MatchedPair(
                    pair_id=pair_id,
                    regime=regime,
                    fault_class=fault,
                    is_negative_control=is_control,
                    seed=pair_seed,
                    rep_index=rep,
                    ordered_policies=ordered,
                    duration_s=trial_duration,
                )
                pairs.append(pair)

    return pairs


__all__ = [
    "TrialSpec",
    "MatchedPair",
    "derive_pair_seed",
    "build_matrix",
]
