"""Baselines for D3-002.2 (seasonal-naive) and D3-002.3 (tree) plus the
persistence fallback every model degrades to on a cold start (TS-4).

Shared forecaster interface (duck-typed, used by the pipeline):

    fit(series)                 # store/adapt to the history
    forecast_path(steps)        # deterministic per-step values

Each baseline exposes ``model`` (a stable label for Contract-A meta) and
``fallback`` ("" when the real forecast was produced, else a documented
degradation reason). No randomness except the seeded tree fit (PS-2).
"""
from __future__ import annotations

import math

import numpy as np


class Persistence:
    """Degenerate fallback: carry the last finite value flat over the horizon.

    Only ever produced as a *documented* fallback (cold start / empty season
    history / non-finite model output); never presented as a real seasonal fit.
    """

    model = "persistence"

    def __init__(self) -> None:
        self.fallback = "cold_start_persistence"
        self._last = None

    def fit(self, series) -> "Persistence":
        y = np.asarray(series, dtype=float).ravel()
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            raise ValueError("cannot forecast an empty/finite-only series")
        self._last = float(finite[-1])
        return self

    def forecast_path(self, steps: int) -> np.ndarray:
        if steps <= 0:
            raise ValueError(f"steps must be > 0, got {steps!r}")
        return np.full(int(steps), float(self._last), dtype=float)


class SeasonalNaive:
    """D3-002.2 — carry the last full season forward.

    Forecast succession: ŷ[t+k] = y[t+k-m] (last-season value at the same
    phase). With fewer than one season of history it degrades to persistence
    and records the reason; it never crashes on a cold start.
    """

    model = "snaive"

    def __init__(self, season_m: int) -> None:
        if int(season_m) < 1:
            raise ValueError(f"season_m must be >= 1, got {season_m!r}")
        self.season_m = int(season_m)
        self.fallback = ""
        self._y = None
        self.n = 0

    def fit(self, series) -> "SeasonalNaive":
        y = np.asarray(series, dtype=float).ravel()
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            raise ValueError("cannot forecast an empty/finite-only series")
        self._y = y
        self.n = int(y.size)
        if self.n < self.season_m:
            self.fallback = f"cold_start_persistence:{self.n}of{self.season_m}"
        return self

    def forecast_path(self, steps: int) -> np.ndarray:
        if steps <= 0:
            raise ValueError(f"steps must be > 0, got {steps!r}")
        if self.n < self.season_m:
            return Persistence().fit(self._y).forecast_path(steps)
        m, n = self.season_m, self.n
        base = self._y[n - m: n]                     # the most recent full season
        reps = int(math.ceil(steps / m))
        return np.tile(base, reps)[: int(steps)].astype(float, copy=False)


class TreeBaseline:
    """D3-002.3 — lagged-feature regressor baseline, deterministically seeded.

    Direct multi-step: one RandomForest per horizon step k (targets y[j+k]),
    trained on lag/seasonal-phase/rolling features computed strictly from
    history at or before each anchor ``j`` (no lookahead, PS-6). Same data +
    same seed ⇒ byte-identical paths (TS-5).

    Gap policy (PS-6 — gaps are never filled): training rows with non-finite
    feature cells or a non-finite target are dropped by finite masks; a
    trailing window too gappy to predict from, or too little training data,
    degrades to a documented persistence path rather than emitting garbage.
    """

    model = "tree_rf"

    LAGS = 8            # recent lags feeding the trees (steps)
    WINDOW = 4          # rolling mean/std window (steps)

    def __init__(self, season_m: int, steps: int, seed: int) -> None:
        if int(season_m) < 1:
            raise ValueError(f"season_m must be >= 1, got {season_m!r}")
        if int(steps) < 1:
            raise ValueError(f"steps must be >= 1, got {steps!r}")
        self.season_m = int(season_m)
        self.steps = int(steps)
        self.seed = int(seed)
        self.fallback = ""
        self._y = None
        self.n = 0
        self._n_train: list[int] = []

    # -- features ---------------------------------------------------------
    def _features(self, y: np.ndarray, j: int) -> np.ndarray:
        m = self.season_m
        vals = [y[j - lag] for lag in range(1, self.LAGS + 1)]
        vals += [y[j - m], y[j - 2 * m]]
        window = y[j - self.WINDOW + 1: j + 1]
        vals += [float(np.mean(window)), float(np.std(window))]
        return np.asarray(vals, dtype=float)

    def _degrade(self, reason: str) -> np.ndarray:
        self.fallback = reason
        return Persistence().fit(self._y).forecast_path(self.steps)

    # -- fit / forecast ---------------------------------------------------
    def fit(self, series) -> "TreeBaseline":
        y = np.asarray(series, dtype=float).ravel()
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            raise ValueError("cannot forecast an empty/finite-only series")
        self._y = y
        self.n = int(y.size)
        return self

    def forecast_path(self, steps: int) -> np.ndarray:
        """Train (deterministically, seeded) and emit the contracted path."""
        if int(steps) != self.steps:
            raise ValueError(
                f"TreeBaseline was constructed for steps={self.steps}, "
                f"got {steps!r} (targets y[j+k] are trained per step)"
            )
        y = self._y
        m = self.season_m
        j0 = max(self.LAGS, 2 * m, self.WINDOW)      # earliest usable anchor
        last_anchor = self.n - self.steps - 1        # need y[j+k] observable
        if last_anchor - j0 + 1 < 2:                 # fewer than 2 training anchors
            return self._degrade(
                f"cold_start_persistence:{self.n}_steps_lt_{j0 + self.steps + 1}"
            )

        from sklearn.ensemble import RandomForestRegressor

        anchors = range(j0, last_anchor + 1)
        X = np.asarray([self._features(y, j) for j in anchors])
        x_ok = np.isfinite(X).all(axis=1)
        self._n_train = []

        models = []
        for k in range(self.steps):
            y_target = y[j0 + k: last_anchor + 1 + k]
            y_ok = np.isfinite(y_target)
            rows = x_ok & y_ok                       # finite features AND target
            n_rows = int(rows.sum())
            if n_rows < 2:                           # gap-filtered training too small
                return self._degrade(
                    f"insufficient_training_after_gap_filter:{n_rows}of{X.shape[0]}_step{k}"
                )
            rf = RandomForestRegressor(
                n_estimators=100,
                random_state=self.seed,
                n_jobs=1,                    # single-thread: deterministic (PS-2)
            )
            models.append(rf.fit(X[rows], y_target[rows]))
            self._n_train.append(n_rows)

        feats = self._features(y, self.n - 1)        # newest anchor
        if not np.isfinite(feats).all():
            return self._degrade("feature_window_gaps_at_anchor")
        path = np.asarray(
            [float(est.predict(feats.reshape(1, -1))[0]) for est in models],
            dtype=float,
        )
        if not np.isfinite(path).all():
            return self._degrade("model_output_nonfinite")
        return path


__all__ = ["Persistence", "SeasonalNaive", "TreeBaseline"]
