"""Contract-A rows for the prediction module (D3-001.6).

Writers use the frozen vocabulary exactly:

* ``predict/breach_prob``            — probability in [0, 1]
* ``predict/breach_duration_est``    — seconds in [0, H]

The ``inference`` hypertable is append-only; this module guarantees deterministic
row values so a replay is reproducible, but cross-run de-duplication needs a
store-side unique key (a Contract-A change, not lane-local code).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..common import store
from .model import BreachPredictor

MODULE = "predict"
KINDS = ("breach_prob", "breach_duration_est")


def inference_rows(
    predictor: BreachPredictor,
    frame: pd.DataFrame,
    ts: float | None = None,
) -> list[dict[str, Any]]:
    """Return two Contract-A rows per input row (probability + duration)."""
    if frame is None or frame.empty:
        return []
    scored = predictor.predict(frame)
    if len(scored) != len(frame):
        raise ValueError("predict() changed the row count")

    rows: list[dict[str, Any]] = []
    for row in scored.itertuples(index=False):
        event_ts = float(ts) if ts is not None else float(row.ts)
        meta = {
            "horizon_s": int(predictor.horizon_s),
            "threshold": float(predictor.threshold),
        }
        rows.append(
            {
                "ts": event_ts,
                "module": MODULE,
                "service": str(row.service),
                "kind": "breach_prob",
                "value": float(row.breach_prob),
                "meta": dict(meta),
            }
        )
        rows.append(
            {
                "ts": event_ts,
                "module": MODULE,
                "service": str(row.service),
                "kind": "breach_duration_est",
                "value": float(row.breach_duration_est),
                "meta": dict(meta),
            }
        )
    return rows


def write_inference(
    predictor: BreachPredictor,
    frame: pd.DataFrame,
    ts: float | None = None,
) -> int:
    """Score ``frame`` and write the Contract-A rows to TimescaleDB."""
    rows = inference_rows(predictor, frame, ts=ts)
    if not rows:
        return 0
    # Validate before opening a connection: a malformed writer fails offline.
    store.normalize(rows)
    return store.write(rows)
