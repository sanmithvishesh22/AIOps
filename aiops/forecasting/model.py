"""D3-002.1 — main seasonal forecast of per-service p95/load.

Default backend is a deterministic **harmonic** fit (linear trend + two Fourier
harmonics at the configured season, solved in closed form — pure numpy, no RNG),
which is what makes the offline selftest byte-reproducible (PS-2/TS-5).
``FORECAST_BACKEND=prophet`` selects Prophet (heavy dep, lazily imported); a
missing Prophet raises a loud, actionable error rather than silently
downgrading — the backends differ, so the choice must be explicit (QA-004).

Fallback policy (documented, never a crash — TS-4):
  * cold start, >= one season of history  -> seasonal-naive carry-forward
    (``model="snaive"``, fallback ``cold_start_short_history``)
  * cold start, < one season              -> persistence
    (``model="persistence"``, fallback ``cold_start_persistence``)
  * seasonality gate says weak/absent     -> seasonal-naive carry-forward
    (``model="snaive_fallback"``, fallback = gate reason, D3-002.4)
  * model emitted non-finite values       -> persistence
    (``model="persistence"``, fallback ``model_output_nonfinite``)

Non-finite inputs are dropped, never filled, and the count is returned and
logged (PS-6).
"""
from __future__ import annotations

import logging

import numpy as np

from . import config
from .baselines import Persistence, SeasonalNaive
from .gate import GateResult, seasonality_gate

logger = logging.getLogger("aiops.forecast")

HARMONIC_MODEL = "harmonic"
PROPHET_MODEL = "prophet"
SNAIVE_FALLBACK_MODEL = "snaive_fallback"
SNAIVE_MODEL = "snaive"
PERSISTENCE_MODEL = "persistence"

_RIDGE_ALPHA = 1e-6   # tiny L2 for closed-form conditioning; not a research constant


def _harmonic_design(tau_steps: np.ndarray, season_m: float) -> np.ndarray:
    """Design matrix over sampling-step offsets: intercept, linear trend, and
    the first two Fourier harmonics of the season (Prophet-style additive
    decomposition, reduced to its deterministic core)."""
    tau = np.asarray(tau_steps, dtype=float).ravel()
    omega = 2.0 * np.pi / float(season_m)
    cols = [
        np.ones_like(tau),
        tau,
        np.sin(omega * tau),
        np.cos(omega * tau),
        np.sin(2.0 * omega * tau),
        np.cos(2.0 * omega * tau),
    ]
    return np.column_stack(cols)


def _fit_harmonic(y: np.ndarray, positions: np.ndarray, anchor: int, season_m: float):
    """Closed-form ridge fit at history offsets (position - anchor). Returns
    `(weights, )` used by :meth:`SeasonalForecaster.forecast` to extrapolate."""
    X = _harmonic_design(positions - anchor, season_m)
    gram = X.T @ X
    gram[np.diag_indices_from(gram)] += _RIDGE_ALPHA
    coef = np.linalg.solve(gram, X.T @ y)
    return coef


class ForecastResult:
    """One per-service forecast path plus everything needed to document it."""

    __slots__ = ("values", "model", "fallback", "dropped", "seasonal", "gate", "steps")

    def __init__(self, values, model, fallback, dropped, seasonal, gate, steps) -> None:
        self.values = np.asarray(values, dtype=float).ravel()
        self.model = model
        self.fallback = fallback
        self.dropped = int(dropped)
        self.seasonal = seasonal
        self.gate = gate
        self.steps = int(steps)

    @property
    def is_real_forecast(self) -> bool:
        return self.fallback == ""


class SeasonalForecaster:
    """Main model (D3-002.1): per-step, per-service seasonal forecast."""

    def __init__(
        self,
        season_s: int | None = None,
        horizon_s: int | None = None,
        cadence_s: int | None = None,
        strength_min: float | None = None,
        min_tail: int | None = None,
        backend: str | None = None,
    ) -> None:
        self.season_s = int(config.SEASON_S if season_s is None else season_s)
        self.horizon_s = int(config.HORIZON_S if horizon_s is None else horizon_s)
        self.cadence_s = int(config.STEP_S if cadence_s is None else cadence_s)
        self.season_m = self.season_s // self.cadence_s
        if self.season_m < 1 or self.season_s % self.cadence_s != 0:
            raise ValueError(
                "season must be a whole number of cadence steps "
                f"({self.season_s} % {self.cadence_s})"
            )
        if self.horizon_s <= 0 or self.cadence_s <= 0:
            raise ValueError(f"horizon/cadence must be > 0, got {self.horizon_s}/{self.cadence_s}")
        self.strength_min = float(
            config.SEASONAL_STRENGTH_MIN if strength_min is None else strength_min
        )
        self.min_tail = int(config.MIN_TAIL_STEPS if min_tail is None else min_tail)
        self.backend = str(config.BACKEND if backend is None else backend).lower()
        if self.backend not in {"harmonic", "prophet"}:
            raise ValueError(
                f"FORECAST_BACKEND must be harmonic|prophet, got {self.backend!r}"
            )

    # ------------------------------------------------------------------
    def forecast(self, series) -> ForecastResult:
        """Forecast the next ``ceil(H / cadence)`` steps of a 1-D series."""
        steps = int(np.ceil(self.horizon_s / self.cadence_s))
        y = np.asarray(series, dtype=float).ravel()
        finite = np.isfinite(y)
        dropped = int((~finite).sum())
        if dropped:
            logger.warning(config._NOISE_WARN, dropped)
        if finite.sum() == 0:
            raise ValueError("cannot forecast a series with no finite samples")

        positions = np.flatnonzero(finite)          # indices of usable samples
        y_finite = y[finite]

        # Cold start: fewer than one season + fit margin -> documented fallback.
        if positions.size < self.season_m + self.min_tail:
            if positions.size >= self.season_m:
                path = SeasonalNaive(self.season_m).fit(y).forecast_path(steps)
                return ForecastResult(
                    path, SNAIVE_MODEL, "cold_start_short_history", dropped, False,
                    None, steps,
                )
            path = Persistence().fit(y).forecast_path(steps)
            return ForecastResult(
                path, PERSISTENCE_MODEL, "cold_start_persistence", dropped, False,
                None, steps,
            )

        # Seasonality gate (D3-002.4): never emit a spurious seasonal fit.
        gate = seasonality_gate(
            y,
            season_m=self.season_m,
            strength_min=self.strength_min,
            min_tail=self.min_tail,
        )
        if not gate.seasonal:
            path = SeasonalNaive(self.season_m).fit(y).forecast_path(steps)
            return ForecastResult(
                path, SNAIVE_FALLBACK_MODEL, gate.reason, dropped, False, gate, steps
            )

        anchor = int(positions[-1])                 # newest usable sample
        if self.backend == "harmonic":
            path = self._forecast_harmonic(y_finite, positions, anchor, steps)
            model = HARMONIC_MODEL
        else:
            path = self._forecast_prophet(y_finite, positions, anchor, steps)
            model = PROPHET_MODEL
        if not np.isfinite(path).all():
            path = Persistence().fit(y).forecast_path(steps)
            return ForecastResult(
                path, PERSISTENCE_MODEL, "model_output_nonfinite", dropped, True,
                gate, steps,
            )
        return ForecastResult(path, model, "", dropped, True, gate, steps)

    # ------------------------------------------------------------------
    def _forecast_harmonic(self, y, positions, anchor, steps) -> np.ndarray:
        coef = _fit_harmonic(
            y.astype(float), positions.astype(float), float(anchor),
            float(self.season_m),
        )
        tau = np.arange(1, steps + 1, dtype=float)
        return _harmonic_design(tau, float(self.season_m)) @ coef

    def _forecast_prophet(self, y, positions, anchor, steps) -> np.ndarray:
        """Prophet path (lazy import — heavy dep, D3-002.1).

        The sample grid is rebuilt as a synthetic datetime axis *pinned to a
        fixed epoch* (no wall clock), so the same series + seed yields the same
        forecast. Prophet univariate results are deterministic in default MAP
        mode; validity of this backend is asserted by QA-004, not assumed.
        """
        try:
            from prophet import Prophet
        except Exception as exc:  # ImportError and broken installs alike
            raise RuntimeError(
                "FORECAST_BACKEND=prophet requires the prophet package "
                "(pip install prophet; the extra is uncommented in "
                "requirements.txt). Set FORECAST_BACKEND=harmonic for the "
                "deterministic default."
            ) from exc

        import pandas as pd

        epoch = pd.Timestamp("2000-01-01")           # fixed axis: reproducible
        grid = pd.date_range(
            epoch, periods=anchor + 1 + steps, freq=f"{self.cadence_s}s"
        )
        history = pd.DataFrame({"ds": grid[positions], "y": y.astype(float)})
        model = Prophet(
            weekly_seasonality=False,
            daily_seasonality=False,
            yearly_seasonality=False,
        )
        model.add_seasonality(
            name="season", period=float(self.season_s), fourier_order=4
        )
        # Prophet's uncertainty bands are sampled with numpy RNG; disable them
        # and bracket fit/predict with a state save/restore so no downstream
        # seeded step sees a polluted global RNG (PS-2).
        rng_state = np.random.get_state()
        model.uncertainty_samples = 0
        try:
            model.fit(history)
            future = pd.DataFrame({"ds": grid[anchor + 1:]})
            out = model.predict(future)["yhat"].to_numpy(dtype=float)
        finally:
            np.random.set_state(rng_state)
        return out


__all__ = [
    "ForecastResult",
    "SeasonalForecaster",
    "HARMONIC_MODEL",
    "PROPHET_MODEL",
    "SNAIVE_FALLBACK_MODEL",
    "SNAIVE_MODEL",
    "PERSISTENCE_MODEL",
]
