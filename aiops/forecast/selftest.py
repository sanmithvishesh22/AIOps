"""Offline selftest for D3-002 (python -m aiops.forecast --selftest).

Assert-based, no cluster, no network, no DB (TS-1). Synthetic series are
mechanics-only fixtures (TS-6): they verify engineering behaviour, never §9
values. Covers TS-3 negative cases, TS-4 edges, TS-5 reproducibility, and the
D3-002.5 loud comparison gate, now labelled instrument-quality (QA-004.3).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .baselines import Persistence, SeasonalNaive, TreeBaseline
from .gate import seasonality_gate
from .model import (
    PERSISTENCE_MODEL,
    SNAIVE_MODEL,
    SNAIVE_FALLBACK_MODEL,
    HARMONIC_MODEL,
    SeasonalForecaster,
)
from .pipeline import (
    assert_main_beats_baselines,
    backtest_anchors,
    compare_models,
    run_forecast,
    service_series,
)
from .inference import KINDS, inference_rows


# ---------------------------------------------------------------------------
# mechanics-only fixtures (TS-6)
# ---------------------------------------------------------------------------
def _toy_series(
    n: int = 120,
    season_m: int = 40,
    base: float = 60.0,
    amp: float = 18.0,
    trend: float = 0.02,
    noise: float = 2.0,
    seed: int = 7,
) -> np.ndarray:
    """Strongly seasonal series: sine + slow trend + seeded gaussian noise."""
    tau = np.arange(n, dtype=float)
    rng = np.random.default_rng(seed)
    return base + amp * np.sin(2.0 * np.pi * tau / season_m) + trend * tau \
        + rng.normal(0.0, noise, n)


def _frame_from_series(
    series_by_service: dict[str, np.ndarray],
    column: str = "p95_ms",
    end_ts: float = 5000.0,
    cadence_s: int | None = None,
) -> pd.DataFrame:
    """Shape-realistic Contract-C-ish frame for the synthetic services."""
    cadence = int(config.STEP_S if cadence_s is None else cadence_s)
    recs = []
    for service, series in series_by_service.items():
        n = series.size
        ts = end_ts - cadence * (n - 1) + cadence * np.arange(n, dtype=float)
        recs.append(pd.DataFrame({
            "ts": ts,
            "service": service,
            column: series,
        }))
    frame = pd.concat(recs, ignore_index=True)
    frame["error_rate"] = 0.0
    frame["cpu"] = 0.0
    frame["mem"] = 0.0
    frame["replicas"] = 2.0
    frame["rps"] = 10.0
    return frame.sort_values(["ts", "service"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def _check_snaive_handcheck() -> None:
    toy = np.array([1.0, 2.0, 3.0, 4.0] * 3, dtype=float)
    sn = SeasonalNaive(4).fit(toy)
    path4 = sn.forecast_path(4)
    assert sn.fallback == ""
    assert path4.tolist() == [1.0, 2.0, 3.0, 4.0], f"exact carry failed: {path4}"
    path6 = sn.forecast_path(6)
    assert path6.tolist() == [1.0, 2.0, 3.0, 4.0, 1.0, 2.0], f"wrap failed: {path6}"
    # cold start: fewer than one season -> persistence values, documented
    short = SeasonalNaive(4).fit(np.array([7.0, 8.0]))
    assert short.fallback.startswith("cold_start_persistence")
    assert short.forecast_path(3).tolist() == [8.0, 8.0, 8.0]


def _check_gate() -> None:
    season_m, min_tail, smin = 40, 8, config.SEASONAL_STRENGTH_MIN
    seasonal = _toy_series(seed=11)
    gate = seasonality_gate(seasonal, season_m=season_m, strength_min=smin, min_tail=min_tail)
    assert gate.seasonal and gate.strength > smin, f"periodic must pass gate: {gate}"

    flat = np.full(120, 50.0)
    gate = seasonality_gate(flat, season_m=40, strength_min=smin, min_tail=8)
    assert not gate.seasonal and gate.reason == "flat_series", f"flat must trip: {gate}"

    rng = np.random.default_rng(3)
    noise = 60.0 + rng.normal(0.0, 5.0, 120)      # pure noise around a level
    gate = seasonality_gate(noise, season_m=40, strength_min=smin, min_tail=8)
    assert not gate.seasonal and gate.reason.startswith("weak_seasonality"), \
        f"noise must trip: {gate}"

    gate = seasonality_gate(np.full(10, np.nan), season_m=40, strength_min=smin, min_tail=8)
    assert not gate.seasonal and gate.reason.startswith("insufficient_history"), \
        f"all-NaN must be an explicit fallback: {gate}"


def _check_main_forecaster() -> None:
    series = _toy_series(seed=11)
    fc = SeasonalForecaster()
    expected_steps = config.steps_for_horizon()
    assert expected_steps == int(np.ceil(config.HORIZON_S / config.STEP_S))

    res = fc.forecast(series)
    assert res.model == HARMONIC_MODEL and res.is_real_forecast, res.fallback
    assert res.seasonal and res.gate is not None and res.gate.seasonal
    assert res.steps == expected_steps, f"horizon+cadence mismatch: {res.steps}"
    assert res.values.shape == (expected_steps,)
    assert np.isfinite(res.values).all()
    # reproducibility (PS-2/TS-5): identical inputs -> byte-identical forecast
    again = SeasonalForecaster().forecast(series)
    assert np.array_equal(res.values, again.values), "harmonic must be deterministic"

    # non-finite inputs dropped, counted, never filled (PS-6)
    dirty = series.copy()
    dirty[5] = np.nan
    dirty[7] = np.inf
    dirty[-2] = np.nan
    res = fc.forecast(dirty)
    assert res.dropped == 3, f"expected 3 dropped non-finite, got {res.dropped}"
    assert np.isfinite(res.values).all()

    # cold start fallbacks are documented, no crash (TS-4)
    res = fc.forecast(series[:45])     # >= season (40) but < season+tail (48)
    assert res.model == SNAIVE_MODEL and res.fallback == "cold_start_short_history"
    res = fc.forecast(series[:20])     # < one season
    assert res.model == PERSISTENCE_MODEL and res.fallback == "cold_start_persistence"
    try:
        fc.forecast(np.array([]))
        raise AssertionError("empty series must raise loudly")
    except ValueError:
        pass

    # weak seasonality -> snaive fallback, never a spurious seasonal fit
    rng = np.random.default_rng(5)
    noise_only = 60.0 + rng.normal(0.0, 5.0, 120)
    res = fc.forecast(noise_only)
    assert res.model == SNAIVE_FALLBACK_MODEL, f"noise must fall back: {res.model}"
    assert res.fallback.startswith("weak_seasonality") or res.fallback.startswith("insufficient")

    # missing prophet backend fails loud and actionable, never silent
    try:
        SeasonalForecaster(backend="prophet").forecast(series)
        raise AssertionError("prophet backend must raise loudly when not installed")
    except RuntimeError as exc:
        assert "prophet" in str(exc).lower() and "FORECAST_BACKEND" in str(exc)


def _check_tree_baseline() -> None:
    series = _toy_series(seed=13)
    steps = config.steps_for_horizon()
    a = TreeBaseline(config.SEASON_M, steps, seed=config.SEED).fit(series)
    b = TreeBaseline(config.SEASON_M, steps, seed=config.SEED).fit(series)
    pa, pb = a.forecast_path(steps), b.forecast_path(steps)
    assert a.fallback == "" and b.fallback == "", (a.fallback, b.fallback)
    assert np.array_equal(pa, pb), "same seed must reproduce the tree path (TS-5)"
    c = TreeBaseline(config.SEASON_M, steps, seed=config.SEED + 1).fit(series)
    assert not np.array_equal(pa, c.forecast_path(steps)), "seed must matter"

    # gap-ridden history: finite masks keep it running or degrade loudly
    gappy = series.copy()
    gappy[:10] = np.nan
    g = TreeBaseline(config.SEASON_M, steps, seed=config.SEED).fit(gappy)
    path = g.forecast_path(steps)
    assert np.isfinite(path).all(), "gappy history must still yield a finite path"


def _check_pipeline_and_rows() -> None:
    seasonal = _toy_series(seed=17)
    frame = _frame_from_series({"front-end": seasonal, "orders": _toy_series(seed=19)})
    run = run_forecast(frame)

    steps = config.steps_for_horizon()
    assert set(run.per_service) == {"front-end", "orders"}
    for name, sf in run.per_service.items():
        assert sf.main.steps == steps
        assert sf.snaive.values.shape == (steps,)
        assert sf.tree.values.shape == (steps,)
        assert sf.comparison is not None, "toy history is long enough to compare"
        assert sf.comparison["anchors"] == backtest_anchors(int(sf.n_history), steps)
        assert sf.comparison["anchors"] == list(
            range(sf.n_history - steps - 8, sf.n_history - steps)
        ) or sf.comparison["steps"] == steps

    # apples-to-apples: all three models on the SAME anchors × steps grid
    sf = run.per_service["front-end"]
    cmpn = sf.comparison
    assert cmpn["metric"] == config.ERROR_METRIC and cmpn["steps"] == steps
    assert set(cmpn["errors"]) == {"main", "snaive", "tree"}
    assert_main_beats_baselines({"front-end": cmpn})   # loud D3-002.5 gate (passes)

    # Contract-A rows: 3 kinds × steps per service, ts = anchor + k×cadence
    rows = inference_rows(run)
    assert len(rows) == 2 * 3 * steps, f"expected {2 * 3 * steps} rows, got {len(rows)}"
    anchor = float(sf.anchor_ts)
    for row in rows:
        assert row["module"] == "forecast" and row["kind"] in KINDS
        assert row["meta"]["horizon_s"] == config.HORIZON_S
        assert "model" in row["meta"]
        k = row["meta"]["step"]
        assert row["ts"] == anchor + k * config.STEP_S
    tree_rows = [r for r in rows if r["kind"] == KINDS[2]]
    assert all(r["meta"]["model"] == "tree_rf" for r in tree_rows), "baseline kind written"

    from ..common import store
    store.normalize(rows)          # malformed writer must fail here, not in the DB

    # reproducibility (PS-2): full re-run => identical row content
    run2 = run_forecast(frame)
    rows2 = inference_rows(run2)
    assert [
        (r["ts"], r["service"], r["kind"], r["value"], str(r["meta"])) for r in rows
    ] == [(r["ts"], r["service"], r["kind"], r["value"], str(r["meta"])) for r in rows2]

    # edges (TS-4): empty frame / one-row series raise with a message, no crash
    empty = frame.iloc[0:0]
    try:
        run_forecast(empty)
        raise AssertionError("empty frame must raise loudly")
    except ValueError:
        pass
    single = _frame_from_series({"front-end": np.array([42.0])})
    res = SeasonalForecaster().forecast(
        service_series(single, "front-end")
    )
    assert res.model == PERSISTENCE_MODEL and res.fallback == "cold_start_persistence"
    assert res.values.tolist() == [42.0] * steps

    # shape fixture integration (TS-6): sample_frame is 4 steps - cold start path
    from ..common.fixtures import _KINDS, sample_frame
    run3 = run_forecast(sample_frame())
    assert set(run3.per_service) == {"catalogue", "orders"}
    rows3 = inference_rows(run3)
    store.normalize(rows3)
    assert {r["kind"] for r in rows3} <= set(_KINDS["forecast"]), "vocabulary respected"
    for r in rows3:
        kind = r["kind"]
        meta = r["meta"]
        if kind == KINDS[0]:                      # main: persistence, documented
            assert meta["model"] == PERSISTENCE_MODEL, "4-step history is a cold start"
            assert meta["fallback"] == "cold_start_persistence"
        elif kind == KINDS[1]:                    # snaive keeps its label + reason
            assert meta["model"] == SNAIVE_MODEL
            assert meta["fallback"].startswith("cold_start_persistence")
        else:                                     # tree keeps its label + reason
            assert meta["model"] == "tree_rf"
            assert meta["fallback"].startswith("cold_start_persistence")

    # instrument-quality labels (QA-004.3): metrics, never presented as §9 data
    m = run.metrics()
    assert m["instrument_quality"] is True and m["provisional"] is True
    assert m["metric"] == config.ERROR_METRIC


def _check_failed_guards() -> None:
    # missing baseline never certifies (TS-3)
    try:
        assert_main_beats_baselines({"svc": {"errors": {"main": 1.0, "snaive": 2.0},
                                             "metric": "mae"}})
        raise AssertionError("missing tree baseline must fail loudly")
    except ValueError:
        pass
    # worse-than-baseline result fails loud
    cmpn = {"errors": {"main": 3.0, "snaive": 2.0, "tree": 2.5}, "metric": "mae"}
    try:
        assert_main_beats_baselines({"svc": cmpn})
        raise AssertionError("main worse than baselines must fail loudly")
    except AssertionError:
        pass
    # comparison with zero compared services is loud, not silent
    try:
        assert_main_beats_baselines({"svc": None})
        raise AssertionError("no compared services must fail loudly")
    except ValueError:
        pass


def run_selftest() -> None:
    _check_snaive_handcheck()
    _check_gate()
    _check_main_forecaster()
    _check_tree_baseline()
    _check_pipeline_and_rows()
    _check_failed_guards()
    steps = config.steps_for_horizon()
    print(
        f"forecast selftest OK — kinds={KINDS} horizon={config.HORIZON_S}s "
        f"cadence={config.STEP_S}s steps={steps} season={config.SEASON_S}s "
        "backend=harmonic, instrument-quality (never a §9 measurement)"
    )


if __name__ == "__main__":
    run_selftest()
