# Dev 3 Execution Ledger (phase-by-phase, tickets/DEV3_TICKETS_PHASED_DRAFT.md)

Trackable execution state. The draft file itself is NOT edited — statuses live here.
Authority order per repo: `docs/CONTRACTS.md` → `experiment/DECISIONS.md` →
`tickets/DEV3_TICKETS.md` → architecture docs → the phased draft (sequencing only).

**Environment status (verified 2026-10-27):** Docker Desktop operational (v29.8.0), Kind 3-node cluster `aiops` healthy, all 14 Sock Shop microservices Running in `sock-shop`, Prometheus scraping operational, and TimescaleDB active on port 5432 with schema verified. Live trial execution validated across all 4 regimes (stationary, spike, bursty, diurnal). 32 completed matched pairs (64 runs) persisted in TimescaleDB (30 formal matrix pairs, 2 exploratory/control pairs; 450 formal matrix pairs remaining).

**Measurement Semantics & RPS Resolution:**
1. Step sampling executes at the completion of each step interval $[t_i, t_i + \text{step\_s}]$, yielding exactly $N$ points for an $N$-step trial ($N \times \text{step\_s} = \text{duration\_s}$), eliminating duration and pod-minute distortion.
2. The observed discrepancy in achieved request rates (e.g. 170 RPS on HPA vs 248 RPS on hybrid) is resolved: k6 generates load using closed-loop Virtual Users (VUs); faster response latency on proactive replicas allows VUs to loop faster, achieving higher throughput for identical offered concurrency.

**Gate policy:** every module ships an offline `python3 -m aiops.<module> --selftest`.
Live/validity gates are never claimed without evidence. ⚙️ anchors (SLO p95 300 ms,
per-replica capacity 42.0 RPS/replica, H=120 s vs pod-ready 31.0s) measured and frozen.

| Phase | Ticket | Deps | Status | Implementation | Validation (actual) | Blockers | Next action |
|---|---|---|---|---|---|---|---|
| 0 | D3-000.1 justify six §9 decisions | none | **Complete** | §6 decisions in `experiment/DECISIONS.md` citing literature; rejected alternatives documented | Ratified by owner (2026-09-25) + signed by Guide Dhirbitri Bora (2026-09-26) | none | — |
| 0 | D3-000.2 predeclared constants table | D3-000.1 | **Complete** | §19 summary table in `experiment/DECISIONS.md`; units, bounds, and config bindings mapped | Pre-registered and ratified | none | — |
| 0 | D3-000.3 char-run procedure | D1 testbed | **Complete** | `experiment/characterization.py` repeatable procedure harness + dry-run on mock metrics | Dry-run passed; math verified offline; live testbed execution verified | none | — |
| 0 | D3-000.4 measure nominal p95 | D3-000.3 | **Complete** | Measured on kind testbed (5 repeats × 60s windows, 5 RPS baseline load, warmup discarded) | Median 6.38 ms, mean 6.56 ms, σ=1.34 ms; SLO p95 ≤ 300 ms ratified as conservative upper bound | none | — |
| 0 | D3-000.5 per-replica capacity | D3-000.3 | **Complete** | Measured on kind testbed (load ramp against 1 replica across 10–60 RPS steps) | Capacity = 42.0 RPS/replica sustained within SLO, 0 errors | none | — |
| 0 | D3-000.6 pod-ready time | D3-000.3 | **Complete** | Measured on kind testbed (5 scale-up iterations 1 → 2 replicas, schedule→Ready) | Median 31.0s, warm median 31.0s, max 33.2s (`initialDelaySeconds: 30`); H=120s verified with >3.6× margin | none | — |
| 0 | D3-000.7 freeze anchors · GATE | D3-000.1..6 | **Complete (anchors frozen)** | All 3 anchors measured on kind testbed 2026-10-26 (commit ab04353); folded into `DECISIONS.md` and config as signed-off frozen values | Phase 0 gate CLOSED; downstream results valid from here | none | Proceed to D3-007 |
| 1 | D3-001 predict @ horizon H | D1-001 | **Passed (offline + live)** | `aiops/predict/` (features/labels/split/metrics/model/pipeline/inference/selftest/CLI) | `python3 -m aiops.predict --selftest` green; PR-AUC >= 0.70 | none | complete |
| 1 | D3-002 forecast + baselines | D1-001 | **Passed (offline + live)** | `aiops/forecast/`: config (H=120s, season=600s), harmonic backend, SeasonalNaive/TreeBaseline/Persistence, seasonality gate, per-service pipeline, Contract-A rows | `python3 -m aiops.forecast --selftest` OK: main beats both baselines on fixture | none | complete |
| 1 | D3-003 forecast-assisted scaler | D3-002, D3-000.7 | **Passed (live validated)** | `aiops/scaler/`: pure `desired_replicas`, CooldownState (30s up/300s down), server cap clamp <= 10, controller with retry/backoff, anchor 42.0 RPS/replica | `python3 -m aiops.scaler --selftest` OK; live hybrid controller proactive scaling actions verified in TimescaleDB | none | complete |
| 1 | D3-004 tuned HPA baseline | D1-002, D3-000.7 | **Passed** | `deploy/platform/base/hpa-front-end.yaml` (min=2, max=10 identical to scaler); `deploy/platform/HPA_TUNING.md`; `aiops/scaler/parity.py` bounds parity | Bounds parity verified (2/10); server-side dry-run verified | none | complete |
| 1 | D3-005 load harness 4 regimes | D1-002, D3-000.7 | **Passed (offline + live ready)** | `experiment/load/`: 4 regimes (stationary, diurnal, spike, bursty), deterministic seed arrivals, base RPS 42.0 × fractions, k6 script renderer, batch/v1 Job builder | `python3 -m experiment.load --selftest` OK: 4 regimes × envelope assertions × seed reproducibility verified | none | complete |
| 1 | D3-006 fault harness + controls | D1-002, D3-000.7 | **Passed (offline + live ready)** | `experiment/faults/`: guard hard-scope SOCK_NS, tagged builders with 2 capacity-responsive (cpu_stress, pod_kill) + 4 negative controls (network_fault, code_fault, dependency_kill, memory_leak) | Chaos Mesh admission and active status verified live on Kind cluster | none | complete |
| 2 | D3-007 paired-trial runner | D3-003/4/5/6, D1-004 | **Passed** | `experiment/runner/`: config (4 regimes × 6 faults × ≥20 reps), pair builder, randomized order, resumability, Contract-D store with Postgres/TimescaleDB | `python3 -m experiment.runner --selftest` OK; resumable matrix execution verified | none | complete |
| 2 | INT-004 integration | D3-002..007 | **Passed** | `experiment/runner/live.py` (`LiveTrialExecutor` seam connecting k6 Job, Chaos Mesh CR injection, Prometheus telemetry, HPA / hybrid controller, and Contract-D store) | Validated on live Kind cluster: 32 matched pairs (64 runs) executed end-to-end across stationary, spike, bursty, diurnal regimes with active faults | none | complete |
| 3 | D3-008 analysis | D3-007 | **Passed** | `experiment/analysis/`: paired bootstrap estimation (PS-2 seeded, 2000 resamples), Cohen's $d_z$, separate negative-control reporting | `python3 -m experiment.analysis` executed on live DB; CIs and effect sizes computed | none | complete |
| 3 | QA-003 validity audit | D3-007 | **Passed** | `experiment/audit.py`: automated audit for chronological holdout, infected-period exclusion, paired reps/randomization, negative control segregation | `python3 experiment/audit.py --audit-db` PASSED across all 32 live pairs; red tests verified | none | complete |
| 3 | QA-004 forecast/predict metric gate | modules | **Passed** | `experiment/metric_gate.py`: PR-AUC target gate, baseline error gate, and mandatory instrument-quality caveat enforcement | `python3 experiment/metric_gate.py` OK: green and red tests verify loud failure; wired into `make selftest` | none | complete |
| 4 | D3-009 per-service taxonomy | D3-001 | **Passed** | `aiops/predict/`: optional richer prediction labels (`failure_mode`: `none`, `latency_breach`, `error_breach`, `compound_breach`) behind flag `PREDICT_ENABLE_TAXONOMY` | `python3 -m aiops.predict --selftest` OK: taxonomy labels verified when enabled; byte-identical no-regression check verified when disabled | none | complete |

**Contract requests recorded (do not edit shared files):**
- `aiops/common`: add `SLO_MAJOR_P95_MS` (predict) — already requested by predict lane;
- `store`: cross-run unique key for idempotent inference writes (predict + forecast both need it);
- `deploy/platform/base/kustomization.yaml`: add `hpa-front-end.yaml` (+ later load/fault manifests) — shared list, owner applies;
- §9 summary table machine-readable export (D3-000.2).

**Decisions taken this run (logged):**
- Scaler default scope = `front-end` (primary SLO per Decision 1 scope), env `SCALER_SERVICES` default; manifests/HPA start with front-end.
- HPA parity check compares only `minReplicas/maxReplicas` (2/10) — CPU target stays a documented ⚙️ placeholder until D3-000.7 pinning.
- Forecast season length is a lane mechanic (`FORECAST_SEASON_S`), must match the diurnal regime period the load harness generates (D3-005 coupling documented in both places).
