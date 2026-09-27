# Flow: Dev 2 — Diagnosis Pipeline

**Branch:** `dev2-diagnosis` · **Lane:** detect · rca · explain

**Mission:** Say what's wrong, rank why, and explain the flag — all
offline-testable, never touching infrastructure control. This stream never
blocks the contribution.

## Clone this flow and start

```bash
git clone https://github.com/sanmithvishesh22/AIOps.git
cd AIOps
git checkout dev2-diagnosis

python3 -m venv .venv && source .venv/bin/activate
# uncomment the torch (LSTM-AE) and shap (explain) extras in requirements.txt first
pip install -r requirements.txt
make selftest                        # offline logic check, no cluster needed
```

You build entirely against Dev 1's fixtures — no cluster required for this lane.

## Read these first (only what this lane needs)

- `ARCHITECTURE.md` — the seven modules and positioning guardrails
- `TECHNICAL_ARCHITECTURE.md` — detailed design
- `PARALLEL_DEV_PLAN.md` — ownership boundaries and merge-conflict rules
- `docs/CONTRACTS.md` — the `kind` vocabulary and feature-frame shape you honor
- `tickets/DEV2_TICKETS.md` — your ticket list (start at D2-001)

## Files you own

`aiops/detect/*`, `aiops/rca/*`, `aiops/explain/*`. (Deps live in the base
`requirements.txt` — uncomment the torch/shap extras.)

## Contracts you must honor

Write only the documented `kind` values via `store.py` — detect:
`anomaly_score`, `anomaly_score_seq`, `anomaly_flag`; rca: `culprit_rank`;
explain: `attribution`. Consume the Contract-C feature frame via Dev 1's
`sample_frame()` until the live bridge lands. Read Prometheus only through
`prom.py`.

**Lane guardrail:** RCA output is a **ranking, not causal proof** — say so in
every output and every code comment (D2-004).

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

Work on `dev2-diagnosis`, open a PR into `main`. **QA-001: `make selftest` must
be green before any merge** — the single merge gate.
