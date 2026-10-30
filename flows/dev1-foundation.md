# Flow: Dev 1 — Platform Foundation & Data Plane

**Branch:** `dev1-foundation` · **Lane:** contracts + testbed + ingestion

**Mission:** Stand up the testbed, own every shared contract, and feed the ML
modules clean feature frames. You are the critical-path root and the contract
authority — the other three lanes build against what you freeze in Phase 0.

## Clone this flow and start

```bash
git clone https://github.com/sanmithvishesh22/AIOps.git
cd AIOps
git checkout dev1-foundation

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # you own the base file — no extras to uncomment
make selftest                        # offline logic check, no cluster needed
```

You also own the live testbed, so on your machine you need **Docker, kind,
kubectl, helm** to run `make up` (D1-002). The other lanes don't. Note on port mapping: Kubernetes NodePorts `30080/30300/30090` are distinct from kind host ports `8080/3300/9090`. `cluster/kind-config.yaml` maps container ports 30080 (dashboard) -> 8080, 30300 (Grafana) -> 3300, and 30090 (Prometheus) -> 9090. Host-browser access must use the mapped host ports (`http://localhost:8080`, `http://localhost:3300`, `http://localhost:9090`), not the raw in-cluster NodePorts.

## Read these first (only what this lane needs)

- `ARCHITECTURE.md` — the seven modules, stack choices, positioning guardrails
- `TECHNICAL_ARCHITECTURE.md` — detailed design
- `PARALLEL_DEV_PLAN.md` — ownership boundaries and merge-conflict rules
- `docs/CONTRACTS.md` — **you own this**; freeze Contracts A–G here
- `tickets/DEV1_TICKETS.md` — your ticket list (start at D1-001)

## Files you own

`cluster/*`, `deploy/timescaledb/*`, `deploy/monitoring/*`,
`deploy/platform/base|overlays/local/kustomization.yaml`, `aiops/common/*`,
`aiops/ingest/*`, `experiment/schema.sql`, `Makefile`, base `requirements.txt`,
`cluster/bootstrap.sh`.

## Contracts you own (freeze in Phase 0, others sign off)

A `inference.kind` vocabulary · B `prom.py` signatures · C feature-frame shape ·
D `experiment/schema.sql` · G config env vars. Publish `sample_frame()` +
inference-row fixtures so Dev 2/Sanmith/Dev 4 build against mocks on day one.

## Shared rules (every lane)

- Reuse `aiops/common/{prom,store,config}.py` — import, never re-implement.
- Read config from **env vars only**.
- Every module ships an offline `python -m aiops.<module> --selftest`
  (assert-based, no framework, no cluster) as its only test.
- Edit only files inside your owned directories. A cross-line change is a
  **contract request**, not a silent edit to another lane's files.
- Never surface the retired claims ("first integrated platform", "integration
  is novel", "forecast accuracy proves reliability", "RCA proves causality",
  "human approval makes remediation safe", "Sock Shop generalizes to
  production").
- Keep it minimal — no speculative abstractions.

## Integrate & Handover Notes

Work on `dev1-foundation`, open a PR into `main`. **QA-001: `make selftest`
must be green before any merge** — the single merge gate. As contract authority,
your Phase-0 freeze unblocks everyone, so land D1-001 first.

### Handover & Current Status

1. **CI Status:** `.github/workflows/selftest.yml` is configured and locally validated (running both `make selftest` and `make security-test`). Remote GitHub Actions execution has not yet been verified because the latest six commits are local and have not been pushed. Do not describe CI as green until verified on remote.
2. **SEC-001 Ownership:** Dev 1 has completed and committed the infrastructure half (chart 2.8.7 pinned in `cluster/bootstrap.sh`, `cluster/chaos-mesh-values.yaml`, fail-closed regression guard `cluster/chaos_scope_offline_test.py`). Creator-side admission enforcement belongs to Sanmith, the experiment harness owner, once the harness is available. Dev 4 owns least-privilege ServiceAccounts for scaler and remediation components. Do not assign creator-side admission enforcement to Dev 4.
3. **D1-005 (Ingestion):** Offline acceptance is complete (`python -m aiops.ingest --selftest` passes, Contract C frame shape and NaN policy verified, CronJob manifest authored). Live image execution, CronJob scheduling, Prometheus connectivity, and downstream frame delivery remain unverified.
4. **Tuned-HPA (`hpa-*.yaml`):** Preserve the unresolved manifest-layout question (`deploy/platform/README.md`). Dev 1 must not register an HPA manifest until Sanmith and Dev 1 agree on the exact filename and path.
5. **Port Mapping:** Clearly distinguish Kubernetes NodePorts `30080/30300/30090` from kind host ports `8080/3300/9090`. Host-browser access uses the mapped host ports (`http://localhost:8080`, `http://localhost:3300`, `http://localhost:9090`), not raw NodePorts.
6. **Database Initialization:** `experiment/schema.sql` is not automatically applied by the TimescaleDB deployment, according to the current manifest documentation (`deploy/timescaledb/resources.yaml`). `make schema-test` tests applying the schema against a reachable PostgreSQL instance, but does not prove automated in-cluster initialization. The actual schema-application procedure on cluster bring-up must be confirmed and documented.
7. **Naming Integrity:** Preserve the documented name Sanmith where the README/contracts identify Sanmith as the author/owner (`predict.yaml`, `forecast.yaml`, `scaler.yaml`, `experiment/*`, HPA baseline). Do not silently replace Sanmith with Dev 3 or infer ownership beyond the ticket documentation.
