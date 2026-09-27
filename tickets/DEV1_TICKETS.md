# Developer 1 — Tickets
## Platform Foundation & Data Plane (contracts + testbed + ingestion)

**Mission:** Stand up the testbed, own every shared contract, feed the ML modules with clean feature frames. You are the critical-path root and the contract authority — the other three build against what you freeze in Phase 0.

**How to use this file (prepend to every AI prompt below):**
> You are in the `aiops-platform` monorepo. Read `ARCHITECTURE.md`, `TECHNICAL_ARCHITECTURE.md`, and `PARALLEL_DEV_PLAN.md` first. Rules: reuse `aiops/common/{prom,store,config}.py` (import, never re-implement); read config from env vars only; every module ships an offline `python -m aiops.<module> --selftest` (assert-based, no framework, no cluster) as its only test; edit only files inside your owned directories; never surface the retired claims ("first integrated platform", "integration is novel", "forecast accuracy proves reliability", "RCA proves causality", "human approval makes remediation safe", "Sock Shop generalizes to production"); keep it minimal — no speculative abstractions.

**Files you own:** `cluster/*`, `deploy/timescaledb/*`, `deploy/monitoring/*`, `deploy/platform/base|overlays/local/kustomization.yaml`, `aiops/common/*`, `aiops/ingest/*`, `experiment/schema.sql`, `Makefile`, base `requirements.txt`, `cluster/bootstrap.sh`.

**Files to avoid:** any module logic in `aiops/{detect,rca,predict,forecast,scaler,remediate,explain,dashboard}`; `experiment/{load,faults,runner,analysis}` (Sanmith).

**Contracts you own (freeze in Phase 0, others sign off):** A `inference.kind` vocabulary · B `prom.py` helper signatures · C feature-frame shape · D `experiment/schema.sql` · G config env vars. Publish `sample_frame()` + inference-row fixtures so Dev 2/3/4 build against mocks day one.

---

### D1-001 — Contracts freeze pack · **Must** · deps: none · Phase 0
**Build:** Finalize Contracts A–G and publish fixtures so every stream can build against mocks.
**Done when:** all 7 contracts documented in `docs/CONTRACTS.md`; `sample_frame()` + `sample_inference_rows()` importable; Dev 2/3/4 sign-off recorded at kickoff.
**Prompt:**
> Produce `docs/CONTRACTS.md` fixing: (A) the `inference.kind` vocabulary per writer module; (B) `prom.py` helper signatures; (C) the feature-frame columns `[ts,service,p95_ms,error_rate,cpu,mem,replicas,rps]` with NaN policy; (D) reference to `experiment/schema.sql`; (G) the config env vars. Add `aiops/common/fixtures.py` exposing `sample_frame()` (a realistic feature frame) and `sample_inference_rows()`. `--selftest` asserts the fixtures match the documented shapes.

### D1-002 — Testbed bring-up · **Must** · deps: D1-001 · Phase 1
**Build:** kind cluster + bootstrap installing kube-prometheus-stack, Sock Shop, Chaos Mesh, then our kustomize.
**Done when:** `make up` → all pods Ready; Prometheus targets show Sock Shop; NodePorts reachable on localhost only.
**Prompt:**
> Finalize `cluster/kind-config.yaml` (1 cp + 2 workers, NodePorts 30080/30300/30090) and `cluster/bootstrap.sh` to install kube-prometheus-stack, Sock Shop (upstream complete-demo), and Chaos Mesh, then apply our kustomize. `make up` must yield all-Ready pods with Prometheus scraping Sock Shop, reachable on localhost only. No auth added anywhere.

### D1-003 — Inference store + read helpers · **Must** · deps: D1-001 · Phase 1
**Build:** the `inference` hypertable, index, loud `normalize()`, and read helpers for the dashboard/eval.
**Done when:** `--selftest` inserts+reads a row offline (psycopg2 mocked); malformed row raises `KeyError`; hypertable + index created idempotently.
**Prompt:**
> In `aiops/common/store.py`, create the `inference(ts,module,service,kind,value,meta)` hypertable + `inference_lookup` index idempotently; `normalize()` must raise `KeyError` on any missing field (fail loud, never store blanks). Add read helpers `recent(module,kind,service,since)`. Lazy-import psycopg2. `--selftest` inserts+reads a row with psycopg2 mocked and asserts a malformed row raises.

### D1-004 — Experiment relational schema · **Must** · deps: D1-001 · Phase 1
**Build:** `experiment/schema.sql` — `experiment_run`, `experiment_result` (1:1 FK), `remediation_action` (append-only).
**Done when:** schema applies cleanly to Timescale/PG16; 1:1 + FK constraints enforced; audit rows cannot be deleted/rewritten (test proves it).
**Prompt:**
> Author `experiment/schema.sql` with `experiment_run`, `experiment_result` (1:1 FK), `remediation_action` (append-only: a trigger blocks DELETE and row rewrites; status only moves forward proposed→approved→applied/failed). Add CHECK constraints (policy ∈ {hpa_tuned,forecast_hybrid}; non-negative durations). Provide a SQL/`--selftest` test proving append-only holds.

### D1-005 — Ingestion feature-window bridge · **Must** · deps: D1-001, D1-003 · Phase 1
**Build:** pull per-service windows from Prometheus via `prom.py`, emit the Contract-C frame; CronJob + `--selftest`.
**Done when:** given a mock Prometheus response, emits a well-formed frame; NaN policy applied; `--selftest` green; deployed as a kustomize component.
**Prompt:**
> In `aiops/ingest/`, pull per-service windows from Prometheus via `prom.py` and emit the Contract-C frame; run as a CronJob (kustomize component) with a batch entrypoint. Apply the documented NaN policy, sort by ts. `--selftest` feeds a mocked Prometheus response and asserts a well-formed frame out.

### D1-006 — Deploy skeleton & manifest convention · **Must** · deps: D1-002 · Phase 1
**Build:** kustomize base + `local` overlay where each module contributes ONE self-contained manifest file.
**Done when:** `make deploy` assembles all component files; adding a module = adding one file, zero edits to shared kustomization by other devs.
**Prompt:**
> Set up `deploy/platform/base` + `overlays/local` so each module contributes ONE self-contained manifest file referenced by the base kustomization. Document the convention in `deploy/platform/README.md`: adding a module = adding one file, no edits to shared lists by other devs. `make deploy` assembles everything.

### D1-007 — Non-OTel / bulk connectors · **Nice** · deps: D1-005 · Phase 4
**Build:** optional CSV importer mapping offline datasets into feature-frame shape.
**Done when:** loads a sample CSV into the frame; clearly labeled "offline model-validation only, not reliability proof"; `--selftest` on a tiny sample.
**Prompt:**
> Optional CSV importer that maps offline datasets into the feature-frame shape; label output "offline model-validation only, not reliability proof". `--selftest` on a tiny sample CSV.

---

## Integration / QA / Security you own

### INT-001 — Contract freeze & fixtures published · **Must** · Phase 0
Lock Contracts A–G, ship `sample_frame()` + inference fixtures, record kickoff sign-off. *(= D1-001 delivered to the other three.)*

### INT-002 — Cluster assembly · **Must** · deps: D1-002/006 · Phase 2
**Prompt:** > Make `make up && make deploy` bring up every module component together on the testbed; fix any kustomize wiring so all pods reach Ready.

### QA-001 — Selftest merge gate · **Must** · deps: D1-001 · Phase 1
The one non-negotiable merge gate: `make selftest` must be green before any merge to main. Wire it as a lightweight check.

### SEC-001 (infra half, shared with Dev 4) — **Must** · Phase 3
**Done when:** scaler/remediation k8s ServiceAccounts are least-privilege (scale/restart only, no secret read); Chaos Mesh cannot target any namespace but `SOCK_NS`. **Launch-blocking** — the Chaos-scope check is highest-stakes.

---

**Definition of done (Dev 1):** `make up && make deploy && make selftest` all green on a fresh machine; contracts published and signed off; ingestion feeding real frames from the live cluster.
