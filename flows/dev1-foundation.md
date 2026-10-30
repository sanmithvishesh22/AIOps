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
kubectl, helm** to run `make up` (D1-002). The other lanes don't.

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

## Integrate

Work on `dev1-foundation`, open a PR into `main`. **QA-001: `make selftest`
must be green before any merge** — the single merge gate. As contract authority,
your Phase-0 freeze unblocks everyone, so land D1-001 first.
