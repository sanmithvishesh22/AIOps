# aiops/dashboard — Contract-E read-only API (D4-002)

The Express read-API that surfaces module output for the dashboard. Six GET routes
over `inference` and the experiment tables, **read-only, localhost-only, no auth** —
a deliberate v1 constraint (`docs/CONTRACTS.md` §E, `SECURITY_AND_ACCESS.md`,
`TECHNICAL_ARCHITECTURE.md` §10), not an oversight. The React/Vite UI is a separate
ticket (D4-003); this ticket is the read side only.

**Status:** D4-002 code complete and offline-tested (`npm test`, `python -m aiops.dashboard
--selftest`). Live database integration (real TimescaleDB rows, the deployed NodePort
path) is **INT-003** and is **not verified here** — see "Offline verification vs live
integration" below.

## Shape

```
browser ──► Express app (src/)  ──► Python read bridge (bridge.py) ──► TimescaleDB
            6 GET routes only         one JSON request per read,         inference
            no SQL, no DSN            parameterized SQL, read-only       experiment_*
```

The Express layer never opens a database connection and never holds a query string.
The Python bridge is the only place the dashboard reads the database, which is what
lets it reuse the frozen readers instead of copying them:

- inference rows come from **`aiops.common.store.recent(module, kind, service, since)`**
  (Contract A — the same reader the ML modules use);
- the DSN comes from **`aiops.common.config.TIMESCALE_DSN`** (Contract G — the single
  config source), read inside the bridge, never by Node;
- the audit row's column list is D4-001's `aiops.remediate.audit._FIELDS`, so the read
  shape and the write shape cannot drift apart.

Node cannot import Python functions, so the boundary is a single-shot subprocess: one
JSON request on stdin, one JSON response on stdout, **no shell** and nothing
interpolated into a command line. Node therefore needs **no PostgreSQL driver** —
`express` is the only dependency (`package.json`).

| File | Role |
|---|---|
| `src/server.js` | Entry point; binds the loopback host from `src/config.js` |
| `src/app.js` | The Express app: the six GET routes, `?since=` validation, sanitized errors |
| `src/bridge.js` | Isolated adapter: spawns the Python bridge, parses/sanitizes its answer |
| `src/config.js` | Frozen `HOST`, validated `DASHBOARD_PORT` (no DSN, no host override) |
| `src/resources.js` | The frozen Contract-E resource list (the six endpoints) |
| `bridge.py` | The database reads: `store.recent()` + parameterized relational SELECTs |
| `test/*.test.js` | Offline Node suite (`npm test`) |
| `bridge.py::_selftest` | Offline Python check (`python -m aiops.dashboard --selftest`) |

## Install

```powershell
cd aiops/dashboard
npm install                 # express only
```

Python side: the bridge uses `requirements.txt` from the repo root (`psycopg2-binary`,
plus `requests`/`numpy`, which `aiops.common` imports):

```powershell
cd <repo root>
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Start it on Windows

The bridge runs as `python -m aiops.dashboard.bridge`, so **`python` on `PATH` must be
the interpreter that has the requirements installed** — in this repo, the activated
venv. If it is not, every route answers the same sanitized `503` and the server log
says `(bad_response)`: see "Troubleshooting".

```powershell
cd <repo root>
.\.venv\Scripts\Activate.ps1                 # `python` now resolves to the venv

# point the bridge at the local testbed database (port-forward it first):
#   kubectl -n aiops port-forward svc/timescaledb 5432:5432
$env:TIMESCALE_DSN = "postgresql://aiops:aiops@localhost:5432/aiops"

cd aiops\dashboard
npm start
# → aiops dashboard read-API on http://127.0.0.1:8081/api/<resource>
```

Exact local URL: **`http://127.0.0.1:8081/api/<resource>`** (port `DASHBOARD_PORT`,
default **8081**; set it before `npm start` if 8081 is taken). 8081 on purpose: the
in-cluster dashboard path owns localhost:8080 (kind NodePort `30080 → localhost:8080`,
`cluster/kind-config.yaml`), so a local bind on 8080 would collide with a running
cluster.

If `TIMESCALE_DSN` is not set, the bridge falls back to `aiops.common.config`'s
in-cluster default (`timescaledb.aiops:5432`), which a laptop cannot resolve — routes
then answer `503` and the log says `(read_failed)`. That is the expected "no database
reachable" behaviour, not a bug.

## Endpoints

All six are read-only GETs, unauthenticated, and always answer a **JSON array**
(empty `[]` when there is no data).

| Route | Source | Contract-A vocabulary (`module` / `kind`) | `?since=` filters on |
|---|---|---|---|
| `GET /api/anomalies` | `inference` | `detect` / `anomaly_score`, `anomaly_score_seq`, `anomaly_flag` | `ts` |
| `GET /api/rca` | `inference` | `rca` / `culprit_rank` | `ts` |
| `GET /api/predictions` | `inference` | `predict` / `breach_prob`, `breach_duration_est` | `ts` |
| `GET /api/forecasts` | `inference` | `forecast` / `forecast_p95`, `forecast_p95_snaive`, `forecast_p95_tree` | `ts` |
| `GET /api/remediations` | `remediation_action` | — (relational audit log) | `proposed_at` |
| `GET /api/experiments` | `experiment_run` ⟕ `experiment_result` on `run_id` | — (relational) | `started_at` |

`?since=<unix seconds>` is optional and inclusive; it defaults to `0` (the full
retained history). It is validated by the API (`400` if it is not a bounded,
non-negative number) and travels as a **query parameter** — never as query text.

Note what is *not* offered: no `service=` filter, no pagination or limit, and no
per-status filtering of remediation rows. The API returns what Contract A/D describe,
whole. If a view needs one service, filter client-side at this scale; a window/limit
parameter is a contract-level decision for later, not a silent default.

### Response shapes

**Inference endpoints** — the exact `store.recent()` record, one object per row
(Contract A fields, no additions, no renames):

```json
{ "ts": 1767050101.25, "module": "detect", "service": "orders",
  "kind": "anomaly_flag", "value": 1.0, "meta": { "detector": "iforest" } }
```

`ts` is unix seconds (float), `value` is a number or `null`, `meta` is the stored
JSONB or `null`. `/api/rca`'s `value` is a **rank (1 = top)** — RCA is a ranking, not
causal proof.

Order: **`ts` descending**, then the documented kind order above, then `service`, then
`value` (nulls last), then the serialized `meta` — a total order, so the same database
state always produces the same array. Exactly one query per kind is issued (no
duplicates, no re-reads).

**`/api/remediations`** — one object per audit row, exactly the documented columns of
`experiment/schema.sql` §4.4, timestamps as unix seconds:

```json
{ "action_id": 3, "proposed_at": 1767050000.0, "service": "front-end",
  "action_type": "scale", "params": { "replicas": 5 },
  "evidence": { "service": "front-end", "as_of": 1767050000.0, "anomaly": { },
                "rca": { }, "prediction": { }, "forecast": { } },
  "status": "approved", "decided_by": "aryan", "decided_at": 1767050030.0,
  "applied_at": null, "outcome": null, "run_id": 7 }
```

`params`/`evidence` are returned **as stored** (the Contract-F bundle, if present);
the API does not validate, rewrite, or generate them. Order: `proposed_at` descending,
then `action_id` descending. Read-only in the strict sense: this endpoint cannot
change a status, approve, execute, or touch the log.

**`/api/experiments`** — run metadata and measured results are kept in separate
objects, so a run that has no scorecard yet is `"result": null` rather than a bag of
nulls, and the join cannot produce a duplicated key:

```json
{ "run": { "run_id": 7, "started_at": 1767050000.0, "ended_at": 1767050300.0,
           "pair_id": "p-1", "policy": "forecast_hybrid",
           "workload_regime": "spike", "fault_class": "cpu_stress",
           "is_negative_control": false, "seed": 42, "slo_p95_ms": 300.0,
           "slo_error_rate": 0.01, "horizon_s": 120, "notes": "target_util=0.6" },
  "result": { "slo_breach_duration_s": 12.5, "breaching_requests": 40,
              "breaching_request_ratio": 0.25, "pod_minutes": 3.5,
              "scaling_actions": 2, "oscillations": 1, "mttd_s": 4.0,
              "rca_top1_correct": true, "remediation_success": true,
              "extra": { } } }
```

- `result` is `null` until the run has a scorecard row (the 1:1 link is by `run_id`).
- `slo_breach_duration_s` / `breaching_requests` are the **primary** outcomes;
  `pod_minutes` / `scaling_actions` / `oscillations` are the cost-and-churn guard;
  `mttd_s` / `rca_top1_correct` / `remediation_success` are secondary.
- `is_negative_control` runs are **returned, with their flag** — Contract D says the
  *analysis* layer queries them out and reports them separately; the dashboard hiding
  them would be data loss, not rigour. Views separate them.
- Order: `started_at` descending, then `run_id` descending. Values are instrument
  metrics — not reliability proof.

## Error behaviour

| Status | Body | When |
|---|---|---|
| `200` | `[]` or the rows | The read succeeded (empty result is `[]`, never a placeholder) |
| `400` | `{"error":"invalid_request"}` | `?since=` is malformed or out of range |
| `404` | `{"error":"not_found"}` | Unknown path, or any write method on any path — there are no write routes to negotiate with |
| `503` | `{"error":"read_failed"}` | The read did not complete: database unreachable, query failed, or a value could not be serialized |
| `500` | `{"error":"internal_error"}` | Last-resort handler for an unexpected application error |

What never leaves the process: exception text, stack traces, SQL, the DSN,
credentials, environment values, or record contents. Failure details exist only as
the server's own log line, which is a fixed message plus a failure class:

```
dashboard: /api/remediations read failed (read_failed)
```

The bridge writes one line to its stderr (`bridge: read failed (<ExceptionClass>)`)
and the adapter **drains and discards it** — nothing from the child is relayed. Run
the bridge directly to see its diagnostics (see Troubleshooting).

### Troubleshooting the failure class in the log

| Log class | Meaning |
|---|---|
| `read_failed` | The bridge ran and the database read failed (not reachable, not port-forwarded, wrong DSN, missing table) |
| `bad_response` | The bridge never answered: usually `python` on `PATH` is the wrong interpreter (no `requests`/`numpy`) — activate the venv |
| `timeout` | The bridge exceeded 15 s and was killed |
| `spawn_failed` | `python` could not be started at all |
| `invalid_request` | The bridge rejected the request as malformed (a bug, not user input) |

## Localhost-only (and its honest limits)

- The listener binds **`127.0.0.1`** — a literal constant in `src/config.js`, with no
  environment variable and no start option that can widen it to `0.0.0.0` or another
  interface. A test asserts that passing a host option does not change the bind.
- `npm test` also probes the machine's non-loopback IPv4 addresses and asserts the
  configured listener does **not** answer there.
- **No authentication** on purpose, consistent with Contract E and
  `SECURITY_AND_ACCESS.md` §0: a single-user local research instrument. Auth/RBAC is
  D4-009, explicitly out of v1.
- A bind is a bind, not a security boundary for the whole path. This proves nothing
  about anything in front of the process: an SSH tunnel, a reverse proxy, a
  `kubectl port-forward`, or the planned dashboard NodePort (`30080 → localhost:8080`,
  `TECHNICAL_ARCHITECTURE.md` §10) are separate surfaces with their own exposure.
  **Do not forward this port beyond localhost**, and treat any shared deployment as
  needing real auth first.

## Security posture (v1)

- **Read-only surface**: six GET routes, no write route of any kind (a test asserts it
  behaviourally and by scanning the sources). Approval, execution, and the audit
  lifecycle stay in D4-001; this API cannot touch them.
- **No SQL injection surface**: request data never reaches a query as text. The only
  client input is `?since=`, validated as a bounded number and bound as a query
  parameter; `resource` is a whitelisted constant. The bridge issues no statement that
  is not a read (asserted for every statement it can produce).
- **No DSN in Node**: the Express process never reads or logs the connection string.
  The bridge child inherits the parent environment because it needs
  `TIMESCALE_DSN` from `aiops.common.config` (Contract G); nothing from the
  environment, the connection, or a record is ever placed in a response or a log line.
- **Sanitized by construction**: error bodies are constants; the only log lines are
  `dashboard: /api/<resource> read failed (<class>)` and a fixed startup/shutdown
  line. No request/response logging middleware exists, so payloads are never dumped.
- **Minimal fields**: responses contain exactly the Contract-A inference fields and the
  documented relational columns — nothing else.

## Tests (offline — no database, no cluster)

```powershell
cd aiops/dashboard
npm test                                   # Node suite, node:test, no live services
cd <repo root>
python -m aiops.dashboard --selftest       # Python bridge check, psycopg2 mocked
```

Coverage, by the ticket's checklist:

| Requirement | Test |
|---|---|
| All six routes exist, return JSON arrays | `test/api.test.js` (each route, plus empty-result `[]`) |
| Correct inference module/kind mappings | `bridge.py::_selftest` (exact mapping assertions) + the six `src/resources.js` names |
| Multi-kind merge is deterministic | `bridge.py::_selftest` (three identical requests → identical arrays; order asserted) |
| Remediation / experiment routes touch only their tables | `bridge.py::_selftest` (statement text asserted; `SELECT`-only, no write keyword can appear on any path) |
| Parameterized SQL, explicit columns | `bridge.py::_selftest` (`to_timestamp(%s)` with bound params, `*` absent, every documented column present) |
| No write routes | `test/api.test.js` (POST/PUT/PATCH/DELETE → 404) + `test/guards.test.js` (source scan) |
| Non-loopback requests are not served | `test/listener.test.js` (binds loopback, refuses the machine's LAN address) |
| Database errors → sanitized HTTP errors | `test/api.test.js` (503 with no DSN/SQL/stack in the body) + `bridge.py::_selftest` (no DSN/SQL in responses or logs) |
| JSON serialization of real types | `test/api.test.js` (floats, large ints, nulls, nested JSONB, unicode round-trip) + `bridge.py::_selftest` (`Decimal`, `NaN`/`Infinity` → `null`, datetimes → epoch, unknown types refused) |
| No DSN/secrets in the Node layer | `test/guards.test.js` (no driver dependency, no connection string in code) |

## Offline verification vs live integration

Verified **offline, here**: routes, mappings, ordering, SQL text and parameterization,
serialization, sanitization, loopback binding, no write routes, no Node-side DSN. The
database is mocked in every test; nothing above depends on a running PostgreSQL.

**Not verified** (needs the testbed, ticket INT-003): that the live DSN resolves, that
real rows from Dev 2/3 modules serialize as expected end-to-end, and the deployed
NodePort path. To check live, port-forward the database, set `TIMESCALE_DSN`, start the
API, and compare a route against the same data read directly:

```powershell
kubectl -n aiops port-forward svc/timescaledb 5432:5432
$env:TIMESCALE_DSN = "postgresql://aiops:aiops@localhost:5432/aiops"
python -m aiops.dashboard.bridge --selftest      # offline logic still green
'{"resource":"anomalies"}' | python -m aiops.dashboard.bridge   # live read, one line of JSON
curl.exe -s http://127.0.0.1:8081/api/anomalies
```

An empty `[]` from a live route on a fresh database is a correct answer, not a
failure.

## Design choices Contract E does not settle (marked)

Contract E pins the six routes, "documented JSON array", read-only, localhost-only, no
auth. These points were decided here and are open to a contract change:

1. **The Python bridge** rather than a Node PostgreSQL driver — the only way to reuse
   `store.recent()`/`config.TIMESCALE_DSN` without maintaining a second SQL client. Cost:
   one short-lived process per request (~100–300 ms). If it ever becomes hot, revisit
   with a pooled client; that is a design change, not a silent one.
2. **`?since=`** as the only query parameter, validated and bounded.
3. **Local port 8081** and `DASHBOARD_PORT` (dashboard-local; not part of the frozen
   Contract-G environment set).
4. **Nested `{run, result}`** for experiments instead of a flattened join.
5. **`is_negative_control` rows are returned** (flagged) rather than filtered.
6. **Non-finite floats become `null`** in JSON (JSON has no `NaN`); nothing is coerced
   to `0`.
7. **No pagination/limit** in v1; arrays are the full retained history.
8. **Failure codes** `invalid_request` / `read_failed` / `not_found` / `internal_error`
   and their statuses.
