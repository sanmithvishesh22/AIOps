# aiops/remediate — human-approved remediation (D4-001)

Module 6, Dev 4 lane. Proposes a remediation action with the Contract-F evidence
bundle, waits for an explicit human decision, executes **only** after approval via
the injected k8s interface, verifies the change through that same interface, and
records every state to the append-only `remediation_action` audit table.

**Status:** D4-001 logic complete and self-tested offline. Live wiring (cluster +
TimescaleDB) is INT-005.

## Lifecycle (the only legal moves)

```
propose()  ──► proposed ──approve()──► approved ──execute()──► applied
                  │                      │
                  └──reject()──► rejected └──failure/timeout──► failed
```

- `execute()` runs only from `approved`; anything else raises `StateError`
  without touching the cluster.
- `applied` is written **only after** the change is confirmed through the k8s
  interface; a timeout or unconfirmed change is recorded `failed` with
  `applied_at` NULL — **timeout ≠ success**.
- Exactly-once: the store holds a row lock (`SELECT … FOR UPDATE`) across the
  whole execute attempt, and the decision update is race-gated
  (`WHERE … AND status = 'proposed'`), so duplicate/concurrent approvals execute
  once. `experiment/schema.sql`'s `remediation_audit_guard` trigger enforces the
  forward-only, no-DELETE rules in the DB as well.

## Guardrails (do not weaken)

Human-approved, **never autonomous**. Approval = **accountability, not safety** —
it does not make the action correct, harmless, or "proven safe".

## Contract F — evidence bundle (pinned shape, proposed clarification)

The frozen prose ("the specific `inference` rows that justify it — anomaly, ranked
culprit, prediction/forecast — read via the Contract-A vocabulary") pins *what*
goes in but not the JSON keys. Smallest clarification, as implemented here:

```json
{
  "service": "<target service>",
  "as_of": 1750000000.0,
  "anomaly":    { "ts": …, "module": "detect",   "service": …, "kind": "anomaly_flag|anomaly_score|anomaly_score_seq", "value": …, "meta": {…} },
  "rca":        { "…": "rca / culprit_rank row" },
  "prediction": { "…": "predict / breach_prob|breach_duration_est row" },
  "forecast":   { "…": "forecast / forecast_p95* row (optional)" }
}
```

- Required slots: `anomaly`, `rca`, `prediction`. `forecast` is included when present.
- Each slot is a raw Contract-A row (same columns `store.recent()` returns).
- `build_evidence(service, rows)` assembles it from Contract-A rows; a missing
  required slot raises (`InvalidInput`) — an action is never proposed on half an
  argument. Cross-service bundles are passed pre-built to `propose(evidence=…)`.
- `validate_evidence()` fails loudly at propose() time; the bundle documents the
  reasoning for the operator, it does not make the action autonomous.

**Ask for the owner / Dev 2 / Sanmith:** sign off this key layout and add it to
`docs/CONTRACTS.md` §F (docs are Dev-1-curated; this module cannot edit them).

## Actions and configuration

- v1 executes `scale` (`{"replicas": int ≥ 0}`) and `restart` (no params). The
  schema vocabulary `rollout` / `traffic_shift` fails loudly at propose() until
  implemented.
- Config comes from env vars via `aiops.common.config` only: `SOCK_NS` (target
  namespace) and `TIMESCALE_DSN` (audit store). Verification window
  (`DEFAULT_EXECUTE_TIMEOUT_S = 30s`) is a function parameter, not a new env var.
- `RealK8s` uses the standard kube config chain (in-cluster SA token / local
  kubeconfig) and bounds every API call; `PgAudit` uses psycopg2 lazily.

## Run the offline check

```bash
python -m aiops.remediate --selftest     # also part of `make selftest`
```

Runs with stdlib only (Python 3.11+): `FakeK8s` + `InMemoryAudit`, plus a mocked
psycopg2 pass over `PgAudit`'s statements. Asserts: no approval → no execution;
duplicate (and concurrent) approval → exactly one execution; timeout → failed,
never applied; applied only after verification; audit appended/forward-only,
never overwritten or deleted.
