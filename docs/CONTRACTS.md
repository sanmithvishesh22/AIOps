# Contracts (Phase-0 freeze)

**What this file is:** the seven shared contracts (A–G) that let four developers build
in parallel against mocks instead of waiting on each other. Dev 1 authors and owns
them; Dev 2/3/4 review and sign off at the ~1-hour kickoff. **Once frozen, they change
only by explicit team agreement.** Authoritative sources: `PARALLEL_DEV_PLAN.md` §4 and
`TECHNICAL_ARCHITECTURE.md` §4; this file is the single-page freeze.

The Python package is `aiops` (never `platform` — a top-level `platform` package
shadows the stdlib module and breaks pandas). Modules run as `python -m aiops.<module>`.

---

## A — `inference` write/read contract (the linchpin)

One row per derived signal, in the single hypertable defined in `aiops/common/store.py`:

```
inference(ts, module, service, kind, value, meta JSONB)
```

`store.normalize()` fails loudly on missing fields, so a malformed writer breaks at
write time, not silently. `store.recent(module, kind, service=None, since=0.0)` reads
them back (newest first; `service=None` = all services). The `kind` vocabulary is fixed
so modules and the dashboard agree without coupling:

| Writer | `module` | `kind` values | `value` | key `meta` |
|---|---|---|---|---|
| Detect (Dev 2) | `detect` | `anomaly_score`, `anomaly_score_seq`, `anomaly_flag` | score ∈ [0,1] / flag | `detector`, `threshold`, `features` |
| RCA (Dev 2) | `rca` | `culprit_rank` | rank (1 = top) | `score`, `incident_id`, `graph_edges` |
| Explain (Dev 2) | `explain` | `attribution` | top weight | `target_module`, `shap` |
| Predict (Dev 3) | `predict` | `breach_prob`, `breach_duration_est` | prob / seconds | `horizon_s`, `threshold` |
| Forecast (Dev 3) | `forecast` | `forecast_p95`, `forecast_p95_snaive`, `forecast_p95_tree` | predicted p95 ms | `horizon_s`, `model` |
| Scaler (Dev 3) | `scaler` | `replicas_target` | desired replicas | `current`, `reason`, `cooldown_s`, `bounds` |

Remediation and experiment records do **not** go in `inference` — they use the
relational tables (Contract D). `RCA is a ranking, not causal proof` — the vocabulary
says `culprit_rank`, never "root cause".

## B — Prometheus read helpers (`aiops/common/prom.py`)

Prometheus is the raw-metrics source of truth. Fixed signatures — consumers call these
and **never hand-roll PromQL**:

- `q_latency_p95(window)`, `q_error_rate(window)`, `q_replicas(window)`, `q_cpu(window)`,
  `q_mem(window)`, `q_rps(window)` — each **executes** the query for the last `window`
  minutes (default `WINDOW_MIN`) and returns **all** Sock Shop services in one call:
  a list of `(labels, ts, vals)`, one entry per service, keyed by the `name` label.
  Filter that list by `name` for a single service.
- `range_query(promql, start, end, step)` — the escape hatch; returns the same
  `(labels, ts, vals)` shape.

Env: `PROM_URL`. **Live-calibration caveat:** the `name`-label and kube-state/cAdvisor
join assumptions are marked `ponytail:` in `prom.py` and must be verified once against
the real cluster (ticket A1) — the frame assembly does not depend on the labels being
right, only on each series carrying a resolvable service name.

## C — feature-window frame (`aiops.ingest` output)

The `(ts, service)` grid the ML modules consume. Columns, in order:

```
[ts, service, p95_ms, error_rate, cpu, mem, replicas, rps]
```

Window `WINDOW_MIN`, step `STEP_S`, sorted by `(ts, service)`. **NaN policy: gaps are
never filled.** A metric missing for a `(ts, service)` cell, or a gap inside a series,
stays `NaN` — never zero-filled — so a downstream model can tell "no data" from "zero
load". Dev 1 ships `sample_frame()` (`aiops/common/fixtures.py`, re-exported from
`aiops.ingest`) so Dev 2/3 build against a real-shaped frame — including a dropped cell
and a NaN gap — on day one, with no cluster.

## D — experiment relational schema (`experiment/schema.sql`)

The low-volume relational counterpart to `inference` (kept out of `store.py`'s hot
path). Idempotent DDL; authoritative shape in `TECHNICAL_ARCHITECTURE.md` §4.2–4.4:

- **`experiment_run`** — trial ledger: `pair_id`, `policy` ∈ {`hpa_tuned`,
  `forecast_hybrid`}, `workload_regime`, `fault_class`, `is_negative_control`, `seed`,
  and the predeclared SLO/`horizon_s` stamps. The two runs sharing a `pair_id` (same
  regime + fault + seed, opposite policy) are the matched pair the analysis compares.
- **`experiment_result`** — 1:1 to a run: `slo_breach_duration_s` + `breaching_requests`
  are the **primary** outcomes; `pod_minutes`/`scaling_actions`/`oscillations` are the
  cost-and-churn guard; `mttd_s`/`rca_top1_correct`/`remediation_success` are secondary.
- **`remediation_action`** — append-only human-in-the-loop audit log
  (`proposed → approved/rejected → applied/failed`), nullable `run_id` FK. The log
  records that *a human approved* — accountability, **not** proof remediation is "safe".

`is_negative_control` marks the fault classes where scaling cannot help; those runs are
queried out and **reported separately** (a null result there is the correct result).

## E — dashboard read-API shapes (`aiops/dashboard`, Express)

Dev 4 owns; pinned in Phase 0:
`GET /api/{anomalies,rca,predictions,forecasts,remediations,experiments}`, each a
documented JSON array over `inference` / experiment rows (backed by `store.recent()`
and the relational tables). **Read-only, localhost-only via NodePort, no auth** — a
deliberate v1 constraint, not an oversight. No secrets in responses or logs.

## F — remediation evidence bundle

The JSON a proposed action carries into `remediation_action.evidence`: the specific
`inference` rows that justify it — the anomaly (`detect`), the ranked culprit (`rca`),
and the prediction/forecast (`predict`/`forecast`) — read via the Contract-A
vocabulary. Dev 4 owns. This bundle is what the operator sees before approving; it
documents the reasoning, it does not make the action autonomous or "proven safe".

## G — config / env vars (`aiops/common/config.py`)

Single source; every module reads config from here — never re-reads env directly.

| Var | Default | Meaning |
|---|---|---|
| `PROM_URL` | in-cluster Prometheus DNS | raw-metrics source of truth |
| `TIMESCALE_DSN` | `postgresql://aiops:aiops@…/aiops` | inference-results store (local-testbed creds only) |
| `SOCK_NS` | `sock-shop` | namespace under test; the **only** namespace faults may target |
| `WINDOW_MIN` | `15` | ingest lookback per pull (minutes) |
| `STEP_S` | `15` | sample step (seconds) |
| `SLO_P95_MS` | `300` | ⚙️ §9, owner-ratified provisional — front-end p95 SLO (recalibrate from char run) |
| `SLO_ERROR_RATE` | `0.01` | §9, owner-ratified — 5xx SLO |
| `SLO_WINDOW_S` | `60` | §9, owner-ratified — SLO evaluation window (**not** `WINDOW_MIN`) |
| `HORIZON_S` | `120` | ⚙️ §9, owner-ratified provisional — prediction/forecast horizon *H* |

**`WINDOW_MIN` (ingest lookback, 15 min) is NOT the SLO evaluation window** — that is
`SLO_WINDOW_S` (60 s). Two different knobs; do not conflate them.

## §9 research constants are a contract too — but not a developer's to set

SLO, horizon *H*, workload regimes, scaling params, fault taxonomy, and severity are a
contract (`experiment/DECISIONS.md`, ticket D3-000), **decided by the team + advisor**,
not by code or an AI agent. As of 2026-09-25 the owner has ratified the desk-decidable
values (see `experiment/DECISIONS.md` ratification log); **advisor sign-off and a
baseline characterization run are still pending**, so the `⚙️` values remain provisional.
**No experiment result is valid until they are predeclared, signed off, and frozen** —
choosing them after seeing results is p-hacking and invalidates the contribution.
