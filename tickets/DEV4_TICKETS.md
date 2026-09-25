# Developer 4 — Tickets
## Act, Surface & Measure (Remediation · Dashboard · Evaluation)

**Mission:** Turn module outputs into a human-facing surface — the approval loop, the dashboards, the evaluation views — all built against mocks so you never wait on another stream.

**How to use this file (prepend to every AI prompt below):**
> You are in the `aiops-platform` monorepo. Read `ARCHITECTURE.md`, `TECHNICAL_ARCHITECTURE.md`, `PARALLEL_DEV_PLAN.md`, and `SECURITY_AND_ACCESS.md` first. Rules: reuse `aiops/common/{prom,store,config}.py` (import, never re-implement); read config from env vars only; Python modules ship an offline `--selftest`; edit only files inside your owned directories; never surface the retired claims ("first integrated platform", "integration is novel", "forecast accuracy proves reliability", "RCA proves causality", "human approval makes remediation safe", "Sock Shop generalizes to production"); keep it minimal — no speculative abstractions.

**Files you own:** `aiops/remediate/*`, `aiops/dashboard/*` (React/Vite frontend + Express read-API), the evaluation/reporting layer, deferred `aiops/auth/*`, `requirements-remediate.txt`, dashboard `package.json`.

**Files to avoid:** `aiops/common/*` (import/read-only), any ML module logic, `experiment/*` internals (you read the results tables via the read-API, you don't run trials).

**Contracts you own/honor:** own Contract-E (read-API response shapes) and Contract-F (remediation evidence bundle) — pin them in Phase 0. Read `inference`/experiment rows only through the documented vocabulary; write `remediation_action` rows via the append-only table.

**Guardrails that live in your stream:** remediation is **human-approved, never autonomous** in v1, and approval = **accountability, not safety**; execute is idempotent, timeout ≠ success; the dashboard/read-API is **unauthenticated and localhost-only** by deliberate v1 design; evaluation views are **instrument metrics, not reliability proof**.

---

### D4-001 — Remediation propose/approve/execute/audit · **Must** · deps: D1-004 (mock rows) · Phase 1
**Build:** propose action w/ evidence bundle → wait for explicit approval → execute via k8s API → log to `remediation_action`.
**Done when:** nothing executes without approval; duplicate approval executes exactly once; timeout ≠ success (marked failed); audit append-only.
**Prompt:**
> In `aiops/remediate/`, propose an action carrying the Contract-F evidence bundle (anomaly+rca+prediction rows), wait for EXPLICIT human approval, execute via the k8s API, and log every state to `remediation_action`. Rules: no autonomous action; execute is idempotent (double-approval → exactly one execution); a timeout is NOT success (mark failed); confirm the change in-cluster before marking applied; comments say "approval = accountability, not safety". `--selftest` (mock k8s + mock DB) asserts no-approval→no-exec, double-approval→one exec, timeout→failed.

### D4-002 — Dashboard read-API (Express) · **Must** · deps: D1-001 · Phase 1
**Build:** Contract-E endpoints over `inference`/experiment tables. **Read-only, localhost-only, no auth.**
**Done when:** all endpoints return documented JSON; read-only; bound to localhost; no write paths exposed.
**Prompt:**
> In `aiops/dashboard/` build an Express read-API with Contract-E endpoints (`/api/anomalies|rca|predictions|forecasts|remediations|experiments`) over `inference`/experiment tables. READ-ONLY, bound to localhost, no auth — add a comment documenting this as a deliberate v1 constraint (see SECURITY_AND_ACCESS.md). No write routes. Test each endpoint returns the documented JSON shape against a seeded DB.

### D4-003 — Dashboard UI (React/Vite) · **Must** · deps: D4-002 · Phase 1
**Build:** anomaly feed, RCA view, prediction alerts, forecast view, approval queue; built against a mock read-API first.
**Done when:** renders all feeds from the live read-API; approval queue drives D4-001; runs against mock with zero backend.
**Prompt:**
> In `aiops/dashboard/` build a React (Vite) app: anomaly feed, RCA view, prediction alerts, forecast view, approval queue that drives D4-001. Build against a MOCK read-API first so it runs with no backend. RCA/forecast views must carry the "ranking, not causality" / "instrument metric, not reliability proof" labels where relevant.

### D4-006 — Evaluation & reporting layer · **Must** · deps: D4-002, D3-008 · Phase 3
**Build:** instrument-quality metrics (PR-AUC, MTTD, forecast error vs baseline, experiment summaries w/ CIs).
**Done when:** renders metrics from the results tables; "instrument metrics, not reliability proof" disclaimer present; exportable.
**Prompt:**
> In the dashboard, render instrument-quality metrics (PR-AUC, MTTD, forecast error vs baseline, experiment summaries with CIs) from the results tables. Every view carries "instrument metrics, not reliability proof". Add export.

### D4-004 — Interactive RCA graph explorer · **Nice** · deps: D2-004, D4-003 · Phase 4
**Build/Prompt:** > Add an interactive graph view rendering `culprit_rank` + edges with time-scrubbing. Label "ranking, not causality".

### D4-005 — Multi-horizon forecast view · **Nice** · deps: D3-002, D4-003 · Phase 4
**Build/Prompt:** > Overlay `forecast_p95` vs the two baselines across horizons. No new backend contract.

### D4-007 — Incident timeline / export · **Nice** · deps: D4-002 · Phase 4
**Build/Prompt:** > Historical incident timeline + postmortem export from `inference`/audit rows.

### D4-008 — Autonomous allow-list + rollback · **Nice** · deps: D4-001 · Phase 4
**Build/Prompt:** > Optional narrow auto-remediation with rollback, OFF by default, allow-list enforced, still logs to the audit table.

### D4-009 — Auth / RBAC / RLS · **Nice (out of v1)** · deps: D4-002
Implement only if productizing; follow `SECURITY_AND_ACCESS.md`. **Not built for v1.**

---

## Integration / QA / Security you own

### INT-003 — E2E data-flow wiring · **Must** · deps: D1-005, D2-*, D3-001/2, D4-002/3 · Phase 2
**Prompt:** > Wire live feature frames → detect/rca/predict/forecast → `inference` → read-API → dashboard. Prove one real signal traverses the whole chain on the live cluster.

### INT-005 — Remediation integration · **Must** · deps: D4-001, D2/D3 rows · Phase 2
**Prompt:** > Wire the evidence bundle from live `inference` rows → approval → k8s scale/restart → audit row, on the live cluster.

### QA-002 — E2E platform flow · **Must** · deps: INT-003, INT-005 · Phase 3
**Prompt:** > Script the full path: inject fault → anomaly → rca → prediction → forecast → remediation proposed → approved → applied → visible on dashboard. Assert each stage produced its expected rows.

### SEC-001 (app half, shared with Dev 1) — **Must** · deps: INT-002 · Phase 3
**Done when:** dashboard/read-API reachable only on localhost with no auth surface beyond it; no secrets/creds in logs. *(Dev 1 owns the k8s ServiceAccount + Chaos-scope half.)* **Launch-blocking.**

---

**Definition of done (Dev 4):** approval loop works end-to-end against the live cluster; dashboard renders every module's rows via the read-API; evaluation views populate from the results tables; the localhost/no-auth constraint is honored and documented.
