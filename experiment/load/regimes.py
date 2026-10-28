"""D3-005.2..5 — the four §9 regime profiles, deterministic per seed.

Each regime is an RPS-per-sample-step profile over the 15 s Contract-C grid
(80 steps × 1200 s trial), generated from the ratified SHAPES in
``experiment/config.py`` (§9 Decision 3). Levels are FRACTIONS of the
per-replica capacity; magnitudes stay ⚙️ until the characterization run, so
envelope assertions are relative to base and never treated as measurements.

Reproducibility (PS-2/TS-5): identical seed ⇒ byte-identical profile; the
bursts use numpy's PCG64 stream only. Stationary is constant (no RNG);
diurnal is analytic; spike is analytic; bursty is the only drawn series.
"""
from __future__ import annotations

import numpy as np

from . import config
from .config import REGIMES


class UnknownRegime(ValueError):
    """Regime name outside the ratified set — reject before rendering (PS-3)."""


def regime_or_raise(name: str) -> str:
    n = str(name).strip().lower()
    if n not in config.REGIMES:
        raise UnknownRegime(
            f"unknown regime {name!r}; valid regimes: {', '.join(config.REGIMES)}"
        )
    return n


class Profile:
    """One regime's RPS schedule plus provenance (pure NumPy land)."""

    __slots__ = ("name", "rps", "seed", "base_rps")

    def __init__(self, name: str, rps: np.ndarray, seed: int, base_rps: float) -> None:
        self.name = name
        self.rps = np.asarray(rps, dtype=float)
        self.seed = int(seed)
        self.base_rps = float(base_rps)

    @property
    def steps(self) -> int:
        return int(self.rps.size)

    def duration_s(self) -> int:
        return self.steps * config.STEP_S

    def envelope(self) -> dict:
        t = self.rps
        return {
            "mean": float(np.mean(t)),
            "min": float(np.min(t)),
            "max": float(np.max(t)),
            "variance": float(np.var(t)),
        }

    def to_dict(self) -> dict:
        return {
            "regime": self.name,
            "seed": self.seed,
            "base_rps": self.base_rps,
            "steps": self.steps,
            "step_s": config.STEP_S,
            "duration_s": self.duration_s(),
            "rps": [round(float(x), 6) for x in self.rps],
        }


# ---------------------------------------------------------------------------
def _stationary(seed: int, base: float) -> np.ndarray:
    """Constant RPS — the control. Scaling should barely act (Decision 3)."""
    return np.full(config.STEPS, config.STATIONARY_LEVEL * base)


def _diurnal(seed: int, base: float) -> np.ndarray:
    """Slow sinusoid 30%↔90% with period == the forecaster's season.
    `base` here is the full-capacity RPS; the band is [DIURNAL_MIN, DIURNAL_MAX]."""
    t = np.arange(config.STEPS, dtype=float) * config.STEP_S
    mid = (config.DIURNAL_MIN + config.DIURNAL_MAX) / 2.0
    amp = (config.DIURNAL_MAX - config.DIURNAL_MIN) / 2.0
    return (mid + amp * np.sin(2.0 * np.pi * t / config.DIURNAL_PERIOD_S)) * base


def _spike(seed: int, base: float) -> np.ndarray:
    """Step to SPIKE_FACTOR× base held SPIKE_HOLD_S, then drop (Decision 3).

    Spike ONSET is placed at 50% of the trial — predeclared, deterministic —
    with the seeded jitter reserved for the pair/randomization lanes.
    """
    profile = np.full(config.STEPS, config.SPIKE_BASE * base)
    onset = config.STEPS // 2
    end = min(config.STEPS, onset + int(np.ceil(config.SPIKE_HOLD_S / config.STEP_S)))
    profile[onset:end] = config.SPIKE_FACTOR * config.SPIKE_BASE * base
    return profile


def _bursty(seed: int, base: float) -> np.ndarray:
    """Poisson bursts on a low baseline — the low-predictability regime.

    Exponential inter-arrival + exponential (capped) lengths + uniform burst
    amplitude bands, all from the seeded PCG64 stream (PS-2).
    """
    rng = np.random.default_rng(seed)
    profile = np.full(config.STEPS, config.BURSTY_BASE * base)
    step_s = float(config.STEP_S)
    t_next = float(rng.exponential(config.BURST_MEAN_GAP_S))   # first burst
    while t_next < config.DURATION_S:
        burst_len = min(
            float(rng.exponential(config.BURST_MEAN_LEN_S)), config.BURST_MAX_LEN_S
        )
        amp = float(rng.uniform(config.BURST_AMP_MIN, config.BURST_AMP_MAX)) * base
        start = int(t_next / step_s)
        stop = int(min(config.STEPS, (t_next + burst_len) / step_s + 1))
        profile[start:stop] += amp
        t_next += float(rng.exponential(config.BURST_MEAN_GAP_S))
    return profile


_BUILDERS = {
    "stationary": _stationary,
    "diurnal": _diurnal,
    "spike": _spike,
    "bursty": _bursty,
}


def build_profile(name: str, *, seed: int | None = None, base_rps: float = 100.0) -> Profile:
    """Deterministic profile for `name`. `base_rps` is the (⚙️ pending) full
    capacity figure; 100.0 is the shape-fixture default — never a measurement."""
    key = regime_or_raise(name)
    s = int(config.SEED if seed is None else seed)
    rps = _BUILDERS[key](s, base_rps)
    prof = Profile(key, rps, s, base_rps)
    assert_envelope(prof)
    return prof


# ---------------------------------------------------------------------------
# §9 shape envelopes (D3-005.2..5: "each regime ships a shape assertion")
# ---------------------------------------------------------------------------
TOL = 0.011  # tolerance in capacity-fraction units (shape discipline, not tuning)


def assert_envelope(prof: Profile) -> None:
    """Shape envelope in FRACTIONS of base (base = full capacity RPS)."""
    e = prof.envelope()
    b = prof.base_rps
    frac = {k: (v / b if k != "variance" else v / (b ** 2)) for k, v in e.items()}
    name = prof.name
    if prof.steps != config.STEPS:
        raise ValueError(f"{name}: profile must cover exactly the 1200 s trial")
    if name == "stationary":
        assert abs(frac["mean"] - config.STATIONARY_LEVEL) < TOL, frac
        assert frac["variance"] < 1e-6, frac
    elif name == "diurnal":
        if prof.steps >= 80:
            assert abs(frac["mean"] - (config.DIURNAL_MIN + config.DIURNAL_MAX) / 2) < TOL, frac
            assert frac["variance"] > 0.03, frac
        assert config.DIURNAL_MIN - TOL <= frac["min"], frac
        assert frac["max"] <= config.DIURNAL_MAX + TOL, frac
    elif name == "spike":
        assert abs(frac["max"] - config.SPIKE_FACTOR * config.SPIKE_BASE) < TOL, frac
        assert abs(frac["min"] - config.SPIKE_BASE) < TOL, frac
        assert frac["variance"] > 0.02, frac
    elif name == "bursty":
        lo, hi = config.BURSTY_BASE, max(
            config.BURSTY_BASE + config.BURST_AMP_MAX, 0.90
        )
        assert lo - TOL <= frac["mean"] <= hi, frac
        assert frac["min"] >= config.BURSTY_BASE - TOL, frac
        if prof.steps >= 20:
            assert frac["variance"] > 0.002, frac
        elif len(set(prof.rps)) > 1:
            assert frac["variance"] > 0.0, frac
    else:
        raise UnknownRegime(f"no envelope defined for {name!r}")


__all__ = [
    "Profile",
    "UnknownRegime",
    "assert_envelope",
    "build_profile",
    "regime_or_raise",
    "REGIMES",
]
