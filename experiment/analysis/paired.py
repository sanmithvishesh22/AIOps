"""D3-008.1 — Paired outcome estimation & bootstrap confidence intervals.

Implements matched-pair bootstrap resampling (PS-2, TS-5):
  * Resamples PAIRS (not pooled samples) to preserve the matched structure.
  * Estimates mean difference: Δ = outcome(forecast_hybrid) - outcome(hpa_tuned)
  * Constructs (1 - α)% percentile bootstrap confidence intervals.
  * Deterministic under fixed seed.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Sequence

import numpy as np

from . import config


@dataclasses.dataclass(frozen=True)
class PairedComparison:
    """Outcome for a single matched pair."""

    pair_id: str
    workload_regime: str
    fault_class: str
    is_negative_control: bool
    val_hpa: float
    val_hybrid: float

    @property
    def delta(self) -> float:
        """Negative value means forecast_hybrid reduced the metric (improvement for breaches/cost)."""
        return self.val_hybrid - self.val_hpa


@dataclasses.dataclass(frozen=True)
class BootstrapResult:
    """Summary of paired bootstrap estimation."""

    metric: str
    n_pairs: int
    mean_delta: float
    ci_lower: float
    ci_upper: float
    effect_size_dz: float | None
    is_statistically_significant: bool
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "n_pairs": self.n_pairs,
            "mean_delta": round(self.mean_delta, 4),
            "ci_lower": round(self.ci_lower, 4),
            "ci_upper": round(self.ci_upper, 4),
            "effect_size_dz": round(self.effect_size_dz, 4) if self.effect_size_dz is not None else None,
            "significant": self.is_statistically_significant,
            "warning": self.warning,
        }


def paired_bootstrap(
    deltas: Sequence[float],
    metric_name: str = "metric",
    n_resamples: int = config.BOOTSTRAP_RESAMPLES,
    confidence_level: float = config.CONFIDENCE_LEVEL,
    seed: int = config.DEFAULT_SEED,
) -> BootstrapResult:
    """Compute mean delta and (1 - α)% bootstrap confidence interval over paired differences."""
    arr = np.asarray(deltas, dtype=float)
    n = len(arr)

    if n == 0:
        return BootstrapResult(
            metric=metric_name,
            n_pairs=0,
            mean_delta=0.0,
            ci_lower=float("-inf"),
            ci_upper=float("inf"),
            effect_size_dz=None,
            is_statistically_significant=False,
            warning="no_pairs_provided",
        )

    mean_d = float(np.mean(arr))
    std_d = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    dz = (mean_d / std_d) if (std_d > 1e-12 and n > 1) else None

    # Edge: all zero differences
    if np.all(np.abs(arr) < 1e-12):
        return BootstrapResult(
            metric=metric_name,
            n_pairs=n,
            mean_delta=0.0,
            ci_lower=0.0,
            ci_upper=0.0,
            effect_size_dz=0.0,
            is_statistically_significant=False,
            warning="zero_variance" if n >= config.MIN_REPS_FOR_CI else "insufficient_reps",
        )

    # Edge: too few reps for robust CI (D3-008.1: never fabricate precision)
    warning = None
    if n < config.MIN_REPS_FOR_CI:
        warning = f"insufficient_reps:{n}<{config.MIN_REPS_FOR_CI}"

    # Seeded bootstrap resampling (PS-2 / TS-5)
    rng = np.random.default_rng(seed)
    boot_indices = rng.integers(0, n, size=(n_resamples, n))
    boot_means = np.mean(arr[boot_indices], axis=1)

    alpha = 1.0 - confidence_level
    lower_pct = 100.0 * (alpha / 2.0)
    upper_pct = 100.0 * (1.0 - alpha / 2.0)

    ci_lo = float(np.percentile(boot_means, lower_pct))
    ci_hi = float(np.percentile(boot_means, upper_pct))

    # Significant if 0 is strictly outside the (1 - α)% CI
    sig = bool((ci_lo > 0 and ci_hi > 0) or (ci_lo < 0 and ci_hi < 0))

    return BootstrapResult(
        metric=metric_name,
        n_pairs=n,
        mean_delta=mean_d,
        ci_lower=ci_lo,
        ci_upper=ci_hi,
        effect_size_dz=dz,
        is_statistically_significant=sig,
        warning=warning,
    )


__all__ = [
    "PairedComparison",
    "BootstrapResult",
    "paired_bootstrap",
]
