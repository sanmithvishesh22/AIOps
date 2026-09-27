# Flow: Dev 4 — Act, Surface & Measure

**Branch:** `dev4-surface` · **Lane:** remediation · dashboard · evaluation

**Mission:** Turn module outputs into a human-facing surface — the approval
loop, the dashboards, the evaluation views — all built against mocks so you
never wait on another stream.

## Clone this flow and start

```bash
git clone https://github.com/sanmithvishesh22/AIOps.git
cd AIOps
git checkout dev4-surface

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # remediate needs no extra beyond the base
make selftest                        # offline logic check for the Python modules
# dashboard is React/Vite + Express — see aiops/dashboard/package.json (npm install)
```

Everything in this lane runs against mock rows/read-API first — zero backend
required to start.

## Read these first (only what this lane needs)

- `ARCHITECTURE.md` — the seven modules and positioning guardrails
- `TECHNICAL_ARCHITECTURE.md` — detailed design
- `PARALLEL_DEV_PLAN.md` — ownership boundaries and merge-conflict rules
- `SECURITY_AND_ACCESS.md` — the unauthenticated/localhost-only v1 posture you enforce
- `docs/CONTRACTS.md` — Contracts E (read-API) and F (evidence bundle) you own
- `tickets/DEV4_TICKETS.md` — your ticket list (start at D4-001)

## Files you own

`aiops/remediate/*`, `aiops/dashboard/*` (React/Vite frontend + Express
read-API), the evaluation/reporting layer, deferred `aiops/auth/*`, dashboard
`package.json`.

## Contracts you own / honor

Own Contract-E (read-API response shapes) and Contract-F (remediation evidence
bundle) — pin them in Phase 0. Read `inference`/experiment rows only through the
documented vocabulary; write `remediation_action` rows via the append-only table.

**Lane guardrails:** remediation is **human-approved, never autonomous** in v1,
and approval = **accountability, not safety**; execute is idempotent and a
timeout ≠ success; the dashboard/read-API is **unauthenticated and
localhost-only** by deliberate v1 design; evaluation views are **instrument
metrics, not reliability proof**.

## Shared rules (every lane)

- Reuse `aiops/common/{prom,store,config}.py` — import, never re-implement.
- Read config from **env vars only**.
- Python modules ship an offline `--selftest` (assert-based, no framework, no
  cluster) as their only test.
- Edit only files inside your owned directories. A cross-line change is a
  **contract request**, not a silent edit to another lane's files.
- Never surface the retired claims ("first integrated platform", "integration
  is novel", "forecast accuracy proves reliability", "RCA proves causality",
  "human approval makes remediation safe", "Sock Shop generalizes to
  production").
- Keep it minimal — no speculative abstractions.

## Integrate

Work on `dev4-surface`, open a PR into `main`. **QA-001: `make selftest` must be
green before any merge** — the single merge gate.
