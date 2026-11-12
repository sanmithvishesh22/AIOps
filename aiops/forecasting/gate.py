"""D3-002.4 — seasonality gate.

The gate decides whether a seasonal model is defensible on the current
history or should fall back to a seasonal-naive carry-forward (never emit a
spurious seasonal fit). Strength is the classical variance-removed statistic:

    strength = 1 - Var(y[t] - y[t-season]) / Var(y[t])

computed over the usable span. A pure periodic series scores ~1 (the lag-season
difference is ~0); white noise scores ~0 (or negative, clamped to 0); a flat
series has zero variance and is reported explicitly as flat rather than
"perfectly seasonal" (a constant carries no seasonality signal).

TS-4 edges (empty, all-NaN, insufficient history) return defined results
instead of crashing; the caller documents the fallback. No randomness.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GateResult:
    """Seasonality decision, with the reason a non-seasonal verdict occurred."""

    seasonal: bool
    strength: float
    reason: str  # "" when seasonal; else a documented fallback reason


def seasonality_gate(
    series,
    *,
    season_m: int,
    strength_min: float,
    min_tail: int,
) -> GateResult:
    """Decide whether ``series`` supports a seasonal fit.

    ``series``: 1-D array of samples (NaN/inf gaps allowed and handled). Units
    are sample steps: ``season_m`` = steps per season, ``min_tail`` = extra
    steps of fit history demanded beyond one full season.
    """
    y = np.asarray(series, dtype=float).ravel()
    if season_m < 1:
        raise ValueError(f"season_m must be >= 1, got {season_m}")
    if not 0.0 <= strength_min <= 1.0:
        raise ValueError(f"strength_min must be in [0, 1], got {strength_min!r}")

    n_finite = int(np.isfinite(y).sum())
    need = int(season_m) + int(min_tail)
    if n_finite < need:
        return GateResult(False, 0.0, f"insufficient_history:{n_finite}of{need}")

    # Lag-season differences; only finite pairs count (gap-aware, PS-6).
    # Var over the same span for numerator and denominator: apples-to-apples.
    span = y[int(season_m):]
    finite_span = span[np.isfinite(span)]
    diffs = span - y[: -int(season_m)]
    finite_diffs = diffs[np.isfinite(diffs)]
    if finite_span.size == 0:
        return GateResult(False, 0.0, "insufficient_history:0of1")

    base_var = float(np.var(finite_span))
    if base_var == 0.0:
        # A constant series is flat, not "perfectly seasonal".
        return GateResult(False, 0.0, "flat_series")
    if finite_diffs.size == 0:
        return GateResult(False, 0.0, "insufficient_history:0_diff_pairs")

    resid_var = float(np.var(finite_diffs))
    strength = float(max(0.0, min(1.0, 1.0 - resid_var / base_var)))
    if strength >= strength_min:
        return GateResult(True, strength, "")
    return GateResult(False, strength, f"weak_seasonality:{strength:.3f}")


__all__ = ["GateResult", "seasonality_gate"]
