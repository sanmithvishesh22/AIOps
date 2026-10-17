"""Module 8 — dashboard read-API (ticket D4-002).

Two pieces, one directory:

- `bridge.py` — the READ bridge: the only place the dashboard touches the
  database. It reuses `aiops.common.store.recent()` for the Contract-A
  inference reads, adds parameterized, explicit-column reads for the two
  relational tables (`remediation_action`, `experiment_run`/`experiment_result`),
  and answers one JSON request per invocation. Run it as
  `python -m aiops.dashboard.bridge` (JSON on stdin -> JSON on stdout).
- `src/*.js` + `package.json` — the Express read-API (Contract E). It holds the
  six GET routes and nothing else; it never sees a DSN and never builds SQL.

Contract E (docs/CONTRACTS.md §E) pins the six routes:
`GET /api/{anomalies,rca,predictions,forecasts,remediations,experiments}`, each a
documented JSON array, read-only, localhost-only, no auth. See README.md for the
endpoint-to-source mapping, response shapes, error behavior, and the exact local
startup URL.

Offline check: `python -m aiops.dashboard --selftest` (stdlib only — mocked
psycopg2, no DB, no cluster). The Node side has its own offline suite:
`npm test` in this directory.
"""
from __future__ import annotations

__all__ = ["bridge"]
