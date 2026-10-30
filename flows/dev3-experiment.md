# Flow: Sanmith — Prediction, Forecasting & the Contribution

**Branch:** `dev3-experiment` · **Lane:** predict · forecast · scaler + experiment

**Mission:** Forecast near-term load/breach, drive the hybrid scaler, and run
the matched experiment that is the project's **sole scientific contribution**.
Guard the methodology like it's the thesis — because it is.

## Clone this flow and start

```bash
git clone https://github.com/sanmithvishesh22/AIOps.git
cd AIOps
git checkout dev3-experiment

python3 -m venv .venv && source .venv/bin/activate
# uncomment the prophet extra in requirements.txt first (for forecast)
pip install -r requirements.txt
make selftest                        # offline logic check, no cluster needed
```

Module logic builds against fixtures offline. The experiment *runs* need Dev 1's
live testbed (`make up`) plus the baseline characterization — see D3-000.

## Read these first (only what this lane needs)

- `ARCHITECTURE.md` — the seven modules and positioning guardrails
- `TECHNICAL_ARCHITECTURE.md` — detailed design
- `PARALLEL_DEV_PLAN.md` — ownership boundaries and merge-conflict rules
- `experiment/DECISIONS.md` — the §9 predeclared decisions you must not deviate from
- `docs/CONTRACTS.md` — the `kind` vocabulary and result tables you write
- `tickets/DEV3_TICKETS.md` — your ticket list (D3-000 first)

## Files you own

`aiops/predict/*`, `aiops/forecast/*`, `aiops/scaler/*`,
`experiment/{load,faults,runner,analysis}/*`, `deploy/platform/base/hpa-*.yaml`.
(Deps live in the base `requirements.txt` — uncomment the prophet extra.)

## Contracts you must honor

Write `breach_prob`/`breach_duration_est` (predict), `forecast_p95` +
`forecast_p95_snaive` + `forecast_p95_tree` (forecast), `replicas_target`
(scaler) via `store.py`; write `experiment_run`/`experiment_result` rows to the
tables Dev 1 defined; consume Contract-C feature frames.

**Every §9 constant you use must be the signed-off value from
`experiment/DECISIONS.md`.** The desk values are owner+advisor-signed, but the
three ⚙️ anchors (SLO p95, per-replica capacity, horizon vs pod-ready) are
**provisional pending the baseline characterization run** — until D3-000 freezes
them you build against defaults, but **no result is valid**. Do not pick, invent,
or fabricate these values.

**Lane guardrails:** negative-control faults are mandatory and reported
separately (a null result there is *correct*); chronological holdout +
infected-period exclusion + ≥20 randomized paired reps; the tuned-HPA baseline
must be genuinely tuned (fair comparison); max-replica cap enforced server-side.

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

Work on `dev3-experiment`, open a PR into `main`. **QA-001: `make selftest` must
be green before any merge** — the single merge gate. No experiment result is
presented until D3-000 is signed off and its ⚙️ anchors frozen.
