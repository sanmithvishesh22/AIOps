"""Contract-A rows for the forecast module (D3-002).

Frozen vocabulary (docs/CONTRACTS.md §A):

* ``forecast/forecast_p95``        — main model, predicted p95 ms
* ``forecast/forecast_p95_snaive`` — seasonal-naive baseline
* ``forecast/forecast_p95_tree``   — seeded tree baseline

One row per (service, kind, horizon step): the value is the predicted p95 at
``anchor_ts + step × cadence_s``; meta stamps ``horizon_s`` + ``model`` per the
contract plus step/season/instrument-quality markers. The ``inference``
hypertable is append-only: rows are deterministic so a replay is reproducible,
and cross-run de-duplication needs a store-side unique key (a Contract-A
change, shared with predict — recorded, not implemented lane-locally).
"""
from __future__ import annotations

from typing import Any

from ..common import store
from .pipeline import ForecastRun

MODULE = "forecast"
KINDS = ("forecast_p95", "forecast_p95_snaive", "forecast_p95_tree")


def _row(run: ForecastRun, service: str, kind: str, result, step: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "horizon_s": int(run.horizon_s),
        "model": str(result.model),
        "cadence_s": int(run.cadence_s),
        "season_s": int(run.season_s),
        "step": int(step),
        "instrument_quality": True,   # mechanics marker, never a §9 measurement
        "provisional": bool(run.provisional),  # ⚙️ anchors pending D3-000.7
    }
    if result.fallback:
        meta["fallback"] = result.fallback  # documented degradation (TS-4)
    anchor_ts = float(run.per_service[service].anchor_ts)
    return {
        "ts": anchor_ts + int(step) * int(run.cadence_s),
        "module": MODULE,
        "service": str(service),
        "kind": kind,
        "value": float(result.values[step - 1]),
        "meta": meta,
    }


def inference_rows(run: ForecastRun) -> list[dict[str, Any]]:
    """One Contract-A row per (service, kind, horizon step)."""
    rows: list[dict[str, Any]] = []
    for service, sf in run.per_service.items():
        for kind, res in (
            (KINDS[0], sf.main),
            (KINDS[1], sf.snaive),
            (KINDS[2], sf.tree),
        ):
            for step in range(1, res.steps + 1):
                rows.append(_row(run, service, kind, res, step))
    return rows


def write_forecast(run: ForecastRun) -> int:
    """Validate + write the Contract-A rows to TimescaleDB."""
    rows = inference_rows(run)
    if not rows:
        return 0
    # Validate before opening a connection: a malformed writer fails offline.
    store.normalize(rows)
    return store.write(rows)


__all__ = ["MODULE", "KINDS", "inference_rows", "write_forecast"]
