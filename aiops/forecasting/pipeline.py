"""D3-002.5 — per-service forecast pipeline, baseline comparison, rows.

``run_forecast`` walks a Contract-C frame, forecasts the p95 (or load) column
per service with the main model plus both baselines, backtests all three on
the identical anchor × step grid (no lookahead: each anchor's model is fit on
``series[:t+1]`` only), and exposes the comparison + Contract-A-ready state.

``assert_main_beats_baselines`` is the loud QA-004-style gate: every compared
service must beat BOTH baselines with a baseline missing → ValueError, worse
than a baseline → AssertionError. Comparison output is instrument-quality —
it characterizes the instrument on a fixture; it is never a §9 measurement
and never a reliability proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config
from .baselines import SeasonalNaive, TreeBaseline
from .model import ForecastResult, SeasonalForecaster

N_BACKTEST_ANCHORS = 8  # lane mechanic: most recent valid anchors in the comparison


def service_series(frame: pd.DataFrame, service: str, column: str = "p95_ms") -> np.ndarray:
    """The per-service sample series in ts order (NaN gaps stay NaN, PS-6)."""
    if frame is None or frame.empty:
        raise ValueError("forecast frame is empty")
    if column not in frame.columns:
        raise ValueError(f"frame lacks forecast column {column!r}")
    sub = frame[frame["service"] == service]
    if sub.empty:
        raise ValueError(f"missing service {service!r} in forecast frame")
    sub = sub.sort_values(["ts"], kind="mergesort")
    return sub[column].to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# apples-to-apples backtest grid
# ---------------------------------------------------------------------------
def backtest_anchors(n: int, steps: int, n_anchors: int = N_BACKTEST_ANCHORS) -> list[int]:
    """Most recent ``n_anchors`` anchor positions where the full ``steps``-step
    path has observable ground truth (anchor t predicts y[t+1..t+steps]).
    Spaced one step apart; deterministic; identical for every model."""
    last = n - steps - 1
    first = last - n_anchors + 1
    if first < 0:
        raise ValueError(
            f"insufficient history for backtest: need >= {steps + n_anchors} "
            f"samples + season margin, got {n}"
        )
    return list(range(first, last + 1))


def _error(kind: str, true: np.ndarray, pred: np.ndarray) -> float:
    true = np.asarray(true, dtype=float)
    pred = np.asarray(pred, dtype=float)
    if true.shape != pred.shape:
        raise ValueError(f"alignment mismatch: {true.shape} vs {pred.shape}")
    d = true - pred
    if kind == "mae":
        return float(np.mean(np.abs(d)))
    if kind == "rmse":
        return float(np.sqrt(np.mean(d ** 2)))
    if kind == "smape":
        denom = np.abs(true) + np.abs(pred)
        terms = np.where(denom == 0.0, 0.0, 2.0 * np.abs(d) / denom)
        return float(np.mean(terms))
    raise ValueError(f"unknown error metric {kind!r}")


def compare_models(
    series: np.ndarray,
    forecaster: SeasonalForecaster,
    seed: int | None = None,
    metric: str | None = None,
    n_anchors: int = N_BACKTEST_ANCHORS,
) -> dict:
    """Backtest main + both baselines over the SAME anchors × steps grid.

    Every model is re-fit per anchor on a truncated series (no lookahead).
    Returns per-model error, the model labels actually used, and the grid.
    """
    metric = str(config.ERROR_METRIC if metric is None else metric).lower()
    if metric not in {"mae", "rmse", "smape"}:
        raise ValueError(f"unknown error metric {metric!r}")
    steps = forecaster.horizon_s // forecaster.cadence_s
    if forecaster.horizon_s % forecaster.cadence_s:
        steps += 1
    n = int(np.asarray(series).size)
    anchors = backtest_anchors(n, steps, n_anchors)

    season_m = forecaster.season_m
    tree_seed = int(config.SEED if seed is None else seed)

    paths = {"main": [], "snaive": [], "tree": []}
    for anchor in anchors:
        hist = np.asarray(series[: anchor + 1], dtype=float)
        paths["main"].append(forecaster.forecast(hist))
        snv = SeasonalNaive(season_m).fit(hist)
        paths["snaive"].append(
            ForecastResult(snv.forecast_path(steps), snv.model, snv.fallback, 0, False, None, steps)
        )
        tr = TreeBaseline(season_m, steps, tree_seed).fit(hist)
        paths["tree"].append(
            ForecastResult(tr.forecast_path(steps), tr.model, tr.fallback, 0, False, None, steps)
        )

    truth = {
        (a, k): np.asarray(series[a + k], dtype=float)
        for a in anchors
        for k in range(steps)
    }
    out: dict = {"metric": metric, "anchors": anchors, "steps": steps, "errors": {}}
    for name, results in paths.items():
        pairs_t, pairs_p = [], []
        models, fallbacks = set(), set()
        for res, a in zip(results, anchors):
            models.add(res.model)
            fallbacks.add(res.fallback)
            for k in range(steps):
                pairs_t.append(truth[(a, k)])
                pairs_p.append(float(res.values[k]))
        out["errors"][name] = _error(
            metric, np.asarray(pairs_t), np.asarray(pairs_p)
        )
        out.setdefault("models", {})[name] = sorted(models)
        out.setdefault("fallbacks", {})[name] = sorted(fallbacks)
    return out


def assert_main_beats_baselines(comparisons: dict[str, dict | None]) -> None:
    """QA gate (D3-002.5 / QA-004.2): main must beat BOTH baselines.

    Fails loud: a missing baseline metric → ValueError; main not strictly
    better → AssertionError naming the services that failed.
    """
    failed, compared = [], 0
    for service, cmpn in comparisons.items():
        if cmpn is None:
            continue  # skipped backtest (too little history) is reported, not asserted
        compared += 1
        errs = cmpn["errors"]
        for baseline in ("snaive", "tree"):
            if baseline not in errs:
                raise ValueError(
                    f"{service}: missing baseline {baseline!r} -- comparison is "
                    "not apples-to-apples; refusing to certify"
                )
        metric = cmpn["metric"]
        e_main = errs["main"]
        if not (e_main < errs["snaive"] and e_main < errs["tree"]):
            failed.append(
                f"{service}: main {metric}={e_main:.4f} vs snaive="
                f"{errs['snaive']:.4f} tree={errs['tree']:.4f}"
            )
    if compared == 0:
        raise ValueError("no service had enough history for the baseline comparison")
    if failed:
        raise AssertionError(
            "main forecast must beat BOTH baselines on the fixture; failed: "
            + "; ".join(failed)
        )


# ---------------------------------------------------------------------------
# pipeline over a frame
# ---------------------------------------------------------------------------
@dataclass
class ServiceForecast:
    """Everything forecast-knowable for one service at its newest timestamp."""

    service: str
    anchor_ts: float
    n_history: int
    main: ForecastResult
    snaive: ForecastResult
    tree: ForecastResult
    comparison: dict | None = field(default=None)


@dataclass
class ForecastRun:
    """One D3-002 run over a Contract-C frame (instrument-quality output)."""

    per_service: dict[str, ServiceForecast]
    horizon_s: int
    cadence_s: int
    season_s: int
    metric: str
    provisional: bool = True
    instrument_quality: bool = True

    @property
    def comparisons(self) -> dict[str, dict | None]:
        return {s: sf.comparison for s, sf in self.per_service.items()}

    def metrics(self) -> dict:
        """Aggregate view for the CLI/selftest/QA-004 (kept deterministic)."""
        services = {}
        for name, sf in self.per_service.items():
            services[name] = {
                "model_main": sf.main.model,
                "main_fallback": sf.main.fallback,
                "snaive_fallback": sf.snaive.fallback,
                "tree_fallback": sf.tree.fallback,
                "history_samples": sf.n_history,
                "comparison": (
                    None if sf.comparison is None else dict(sf.comparison["errors"])
                ),
            }
        vals = [sf.comparison["errors"] for sf in self.per_service.values()
                if sf.comparison is not None]
        mean = {
            f"mean_err_{k}": float(np.mean([v[k] for v in vals]))
            for k in ("main", "snaive", "tree")
        } if vals else {}
        return {
            "horizon_s": self.horizon_s,
            "cadence_s": self.cadence_s,
            "season_s": self.season_s,
            "metric": self.metric,
            "services": services,
            "n_compared": len(vals),
            **mean,
            "provisional": self.provisional,
            "instrument_quality": self.instrument_quality,
        }


def _as_result(model_label: str, fallback: str, values, steps: int) -> ForecastResult:
    return ForecastResult(values, model_label, fallback, 0, False, None, steps)


def run_forecast(
    frame: pd.DataFrame,
    column: str = "p95_ms",
    forecaster: SeasonalForecaster | None = None,
    seed: int | None = None,
) -> ForecastRun:
    """Forecast every service in ``frame`` on ``column`` with main + baselines."""
    if frame is None or frame.empty:
        raise ValueError("forecast frame is empty")
    if column not in frame.columns:
        raise ValueError(f"frame lacks forecast column {column!r}")
    fc = forecaster or SeasonalForecaster()
    tree_seed = int(config.SEED if seed is None else seed)
    steps = fc.horizon_s // fc.cadence_s + (1 if fc.horizon_s % fc.cadence_s else 0)

    per_service: dict[str, ServiceForecast] = {}
    for service in sorted(frame["service"].astype(str).unique()):
        series = service_series(frame, service, column)
        n = int(series.size)

        main = fc.forecast(series)
        snv = SeasonalNaive(fc.season_m).fit(series)
        snaive_path = snv.forecast_path(steps)              # evaluate BEFORE reading state
        snaive = _as_result(snv.model, snv.fallback, snaive_path, steps)
        tr = TreeBaseline(fc.season_m, steps, tree_seed).fit(series)
        tree_path = tr.forecast_path(steps)                 # degrades iff fallback is set
        tree = _as_result(tr.model, tr.fallback, tree_path, steps)

        comparison: dict | None = None
        try:
            comparison = compare_models(series, fc, seed=tree_seed)
        except ValueError:   # documented skip: too little history to compare
            comparison = None

        anchor_ts = float(
            frame.loc[frame["service"] == service, "ts"].max()
        )
        per_service[service] = ServiceForecast(
            service=str(service),
            anchor_ts=anchor_ts,
            n_history=n,
            main=main,
            snaive=snaive,
            tree=tree,
            comparison=comparison,
        )

    return ForecastRun(
        per_service=per_service,
        horizon_s=fc.horizon_s,
        cadence_s=fc.cadence_s,
        season_s=fc.season_s,
        metric=str(config.ERROR_METRIC),
    )


__all__ = [
    "ServiceForecast",
    "ForecastRun",
    "N_BACKTEST_ANCHORS",
    "assert_main_beats_baselines",
    "backtest_anchors",
    "compare_models",
    "run_forecast",
    "service_series",
]
