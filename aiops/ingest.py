"""Feature-window ingestion bridge (ticket B1).

Pulls the six Contract-C metrics from Prometheus via prom.py, aligns them onto one
(ts, service) grid, and emits the Contract-C feature frame. It never fabricates
data: a missing series or a gap in a series stays NaN — never zero.

Contract C (frozen): columns
    [ts, service, p95_ms, error_rate, cpu, mem, replicas, rps]
window WINDOW_MIN, step STEP_S, sorted by (ts, service). Diagnosis/prediction
modules (Dev 2/3) build against sample_frame() until the live bridge lands.

Offline check: `python -m aiops.ingest --selftest` assembles a frame from a
synthetic Prometheus payload (including a gap) and asserts the shape + NaN policy,
with no cluster. The live path (`python -m aiops.ingest`) needs `make up` first.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

from .common import prom

# feature column -> the prom executor that returns it (all keyed by the `name` label)
_METRICS = {
    "p95_ms": prom.q_latency_p95,
    "error_rate": prom.q_error_rate,
    "cpu": prom.q_cpu,
    "mem": prom.q_mem,
    "replicas": prom.q_replicas,
    "rps": prom.q_rps,
}
COLUMNS = ["ts", "service", "p95_ms", "error_rate", "cpu", "mem", "replicas", "rps"]


def build_frame(series_by_metric: dict) -> pd.DataFrame:
    """Assemble the Contract-C frame from already-fetched series.

    series_by_metric: {metric_name: [(labels, ts, vals), ...]} as prom.range_query
    returns. One row per (ts, service) seen in any metric, sorted by (ts, service);
    a metric absent for a given (ts, service) is left NaN — gaps are never filled.
    """
    recs = []
    for metric, series in series_by_metric.items():
        for labels, ts, vals in series:
            svc = labels.get("name") or labels.get("deployment")
            if svc is None:
                continue  # unlabeled series can't be tied to a service — drop it
            recs.append(pd.DataFrame({
                "ts": np.asarray(ts, dtype=float),
                "service": svc,
                "metric": metric,
                "value": np.asarray(vals, dtype=float),
            }))
    if not recs:
        return pd.DataFrame(columns=COLUMNS)
    long = pd.concat(recs, ignore_index=True)
    # pivot to wide: missing (ts,service,metric) cells become NaN, present-NaN stays NaN
    wide = long.pivot_table(index=["ts", "service"], columns="metric",
                            values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    # reindex guarantees column order + presence (a metric that returned nothing = NaN col)
    return (wide.reindex(columns=COLUMNS)
                .sort_values(["ts", "service"])
                .reset_index(drop=True))


def fetch(window: int | None = None) -> pd.DataFrame:
    """Live path: run the six executors for the last `window` minutes and assemble
    the Contract-C frame. Requires a reachable Prometheus (config.PROM_URL)."""
    return build_frame({m: q(window) for m, q in _METRICS.items()})


def _synthetic(gap: bool = True) -> dict:
    """Synthetic series_by_metric for two services over 4 steps. If gap=True, one
    (ts, service, metric) cell is missing and one survives parsing as NaN."""
    grid = [1000.0, 1015.0, 1030.0, 1045.0]
    out: dict = {}
    for i, metric in enumerate(_METRICS):
        base = 10.0 * (i + 1)
        orders_ts, orders_vals = list(grid), [base + t / 100 for t in range(4)]
        if gap and metric == "cpu":
            orders_ts, orders_vals = grid[:2] + grid[3:], [base, base + 0.1, base + 0.3]  # drop ts=1030
        if gap and metric == "error_rate":
            orders_vals = [base, np.nan, base + 0.2, base + 0.3]  # NaN gap survives
        out[metric] = [
            ({"name": "orders"}, orders_ts, orders_vals),
            ({"name": "catalogue"}, grid, [base + 1 + t / 100 for t in range(4)]),
        ]
    # replicas arrives labeled by `deployment` (relabeled to name live) — exercise fallback
    out["replicas"] = [
        ({"deployment": "orders"}, grid, [2, 2, 3, 3]),
        ({"deployment": "catalogue"}, grid, [2, 2, 2, 2]),
    ]
    return out


def sample_frame() -> pd.DataFrame:
    """Contract-C fixture (2 services, 4 steps, one dropped cell + one NaN gap) so
    Dev 2/3 can build detectors/forecasters against real-shaped data with no cluster."""
    return build_frame(_synthetic(gap=True))


def _selftest():
    f = sample_frame()
    assert list(f.columns) == COLUMNS, f"columns/order wrong: {list(f.columns)}"
    assert set(f["service"]) == {"orders", "catalogue"}, "both services expected"
    # sorted by (ts, service)
    assert f[["ts", "service"]].values.tolist() == \
        sorted(f[["ts", "service"]].values.tolist(), key=lambda r: (r[0], r[1])), "must be sorted"
    # dropped cpu cell (orders @ ts=1030) is NaN, not zero-filled
    cell = f[(f.service == "orders") & (f.ts == 1030.0)]["cpu"]
    assert len(cell) == 1 and np.isnan(cell.iloc[0]), "dropped series must surface as NaN"
    # NaN gap in error_rate (orders @ ts=1015) survives as NaN, not 0
    egap = f[(f.service == "orders") & (f.ts == 1015.0)]["error_rate"]
    assert np.isnan(egap.iloc[0]), "parsed NaN gap must stay NaN"
    # present cells are real numbers (no accidental zeroing)
    assert f[(f.service == "catalogue")]["p95_ms"].notna().all(), "present values must survive"
    # deployment-labeled replicas mapped onto the service via the name/deployment fallback
    assert f[(f.service == "orders") & (f.ts == 1030.0)]["replicas"].iloc[0] == 3, "replicas fallback"
    # empty input -> empty, well-shaped frame (no crash)
    assert list(build_frame({}).columns) == COLUMNS
    # unlabeled series is dropped, not crashed on
    assert build_frame({"rps": [({}, [1.0], [5.0])]}).empty
    # fetch(): the six executors are wired and `window` is forwarded to each (mock prom)
    global _METRICS
    saved, calls = _METRICS, {}
    def _mk(metric):
        def q(window):
            calls[metric] = window
            return [({"name": "orders"}, [1000.0, 1015.0], [1.0, 2.0])]
        return q
    try:
        _METRICS = {m: _mk(m) for m in saved}
        ff = fetch(7)
    finally:
        _METRICS = saved
    assert set(calls) == set(saved), "fetch must call every metric executor"
    assert set(calls.values()) == {7}, "fetch must forward window to each executor"
    assert list(ff.columns) == COLUMNS and not ff.empty, "fetch assembles the frame"
    print("ingest selftest OK")
    print(f.to_string(index=False))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:  # live path — needs Prometheus reachable (make up)
        print(fetch().to_string(index=False))
