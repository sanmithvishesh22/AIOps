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

1. **Foundation Work Merged to Main:** Dev 1 foundation work (`6b4b3be`..`9e2e98d`) has been integrated and merged into `main` via merge commit `6e1c5d380e6bda65f39e89206f6b2d775e02ff70` and pushed to `origin/main`.
2. **Local Tests & Checks Passed:** Offline validation passes locally with 16/16 checks green across all modules (`make selftest`), SEC-001 static chaos guard passes (`make security-test`: 1 positive, 12 safe variants, 100 negative cases), static schema lint passes (`python experiment/schema_offline_test.py`), HPA bounds parity passes (`python -m aiops.scaler.parity`), and `git diff --check` passes with zero whitespace defects.
3. **Remote GitHub Actions Status (Failing / Not Green):** Remote CI run `41071391935` on `main` (`.github/workflows/selftest.yml`) executed on GitHub Actions and **failed** at step 5 (`make selftest`) with exit code 2 (`conclusion: failure`). Step 6 (`make security-test`) was skipped. Investigation shows the GitHub Actions runner installs minimal `requirements.txt`, which lacks `pyyaml` (imported by `aiops.scaler.parity`, `experiment.faults`, and `experiment.load`). Do not describe remote CI as green or passing; CI remains blocked until base requirements declare all consolidated runtime dependencies.
4. **Live Kubernetes & TimescaleDB Verification Status:** Live cluster bring-up (`make up`), live manifest deployment (`make deploy`), live container image build (`platform-image.sh`), live CronJob scheduling, and live Prometheus ingestion remain unverified. Furthermore, `experiment/schema.sql` is not automatically initialized by `deploy/timescaledb/resources.yaml` on cluster bring-up; static schema linting passes offline, but live database execution, hypertable creation, triggers, and constraint enforcement remain unverified against a live TimescaleDB instance.
5. **INT-002 Teammate Dependencies:** INT-002 (cluster assembly) requires live module components from all teammates (Dev 2 diagnosis manifests, Sanmith experiment manifests, Dev 4 surface/dashboard manifests) to be wired and verified together in the live testbed. Dev 1 provides the deployment skeleton (`deploy/platform/base`, `deploy/platform/overlays/local`, CronJob manifest), but full cluster assembly depends on teammates' live runtime manifests.
6. **SEC-001 Admission & ServiceAccount Enforcement:** Dev 1 has completed and hardened the infrastructure half (Chaos Mesh chart 2.8.7 pinned in `cluster/bootstrap.sh`, strict namespace scoping in `cluster/chaos-mesh-values.yaml`, fail-closed regression guard `cluster/chaos_scope_offline_test.py`). Creator-side admission enforcement belongs to Sanmith (experiment harness owner) once the harness is available. Least-privilege Kubernetes ServiceAccounts for scaler and remediation components belong to Dev 4.
7. **Tuned-HPA Integration (`hpa-front-end.yaml`):** The HPA manifest resides decoupled at `deploy/platform/base/hpa-front-end.yaml` with explicit namespace `sock-shop`. It is intentionally not registered in `deploy/platform/base/kustomization.yaml` to prevent namespace collision with `namespace: aiops` and because dynamic HPA scaling is controlled during paired trials by `experiment.runner`. Manifest layout and integration convention remain pending Sanmith's confirmation.
8. **Remaining Blockers & Next Actions:**
   - *Blocker 1 (CI Dependency Alignment):* Minimal `requirements.txt` does not include `pyyaml`, causing remote CI runner failure on `make selftest`. Next action: align base dependencies or CI workflow.
   - *Blocker 2 (Live Testbed Verification):* Cluster bootstrap and automated TimescaleDB schema application must be validated against a live Docker/kind environment.
   - *Blocker 3 (Teammate Assembly):* Coordinate with Dev 4 on least-privilege ServiceAccounts and Sanmith on experiment harness admission enforcement and HPA integration.
9. **Port Mapping:** Clearly distinguish Kubernetes NodePorts `30080/30300/30090` from kind host ports `8080/3300/9090`. Host-browser access uses the mapped host ports (`http://localhost:8080`, `http://localhost:3300`, `http://localhost:9090`), not raw NodePorts.
10. **Naming Integrity:** Preserve the documented name Sanmith where the README/contracts identify Sanmith as the author/owner (`predict.yaml`, `forecast.yaml`, `scaler.yaml`, `experiment/*`, HPA baseline). Do not silently replace Sanmith with Dev 3 or infer ownership beyond the ticket documentation.
