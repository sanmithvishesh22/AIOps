"""Shared fixtures so Dev 2/3/4 build against real-shaped data on day one, no cluster.

Two contracts, one place:
  - sample_frame()          -> Contract C feature frame (re-exported from aiops.ingest)
  - sample_inference_rows() -> Contract A inference rows, one per writer module

Not imported by aiops.common.__init__ on purpose: it pulls pandas (via ingest), and
config/prom/store must stay import-light. Import it explicitly where you need fixtures.
Offline check: `python -m aiops.common.fixtures --selftest`.
"""
from __future__ import annotations
import sys

from . import config
from ..ingest import sample_frame  # noqa: F401  (re-export — Contract C fixture)

# Contract A — the frozen `kind` vocabulary per writer module (remediation/experiment
# use the relational tables, not `inference`, so they are not here).
_KINDS = {
    "detect": {"anomaly_score", "anomaly_score_seq", "anomaly_flag"},
    "rca": {"culprit_rank"},
    "explain": {"attribution"},
    "predict": {"breach_prob", "breach_duration_est"},
    "forecast": {"forecast_p95", "forecast_p95_snaive", "forecast_p95_tree"},
    "scaler": {"replicas_target"},
}


def sample_inference_rows():
    """One representative Contract-A inference row per writer module, spanning the
    fixed `kind` vocabulary. Every row passes store.normalize(). horizon_s is stamped
    from config (the §9-owed placeholder) so fixtures track the real constant."""
    ts = 1000.0
    return [
        {"ts": ts, "module": "detect", "service": "orders", "kind": "anomaly_score",
         "value": 0.92, "meta": {"detector": "iforest", "threshold": 0.8,
                                 "features": ["p95_ms", "error_rate"]}},
        {"ts": ts, "module": "rca", "service": "orders", "kind": "culprit_rank",
         "value": 1, "meta": {"score": 0.71, "incident_id": "inc-1",
                              "graph_edges": [["front-end", "orders"]]}},
        {"ts": ts, "module": "predict", "service": "front-end", "kind": "breach_prob",
         "value": 0.63, "meta": {"horizon_s": config.HORIZON_S, "threshold": 0.5}},
        {"ts": ts, "module": "forecast", "service": "front-end", "kind": "forecast_p95",
         "value": 420.0, "meta": {"horizon_s": config.HORIZON_S, "model": "prophet"}},
        {"ts": ts, "module": "scaler", "service": "front-end", "kind": "replicas_target",
         "value": 5, "meta": {"current": 3, "reason": "forecast_breach",
                              "cooldown_s": 30, "bounds": [2, 10]}},
        {"ts": ts, "module": "explain", "service": "orders", "kind": "attribution",
         "value": 0.55, "meta": {"target_module": "detect",
                                 "shap": {"p95_ms": 0.55, "cpu": 0.30}}},
    ]


def _selftest():
    from . import store          # local import: store needs no heavy deps
    from .. import ingest
    frame = sample_frame()
    assert list(frame.columns) == ingest.COLUMNS, "frame must match Contract C columns"
    rows = sample_inference_rows()
    # Contract A: normalize accepts every row (it fails loudly on missing fields)...
    assert len(store.normalize(rows)) == len(rows)
    # ...and every (module, kind) is in the frozen vocabulary
    for r in rows:
        assert r["kind"] in _KINDS[r["module"]], f"{r['module']}/{r['kind']} off-vocabulary"
    assert {r["module"] for r in rows} == set(_KINDS), "cover every writer module"
    print("fixtures selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(sample_frame().to_string(index=False))
        for r in sample_inference_rows():
            print(r)
