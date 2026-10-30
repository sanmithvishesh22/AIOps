# Tuned HPA baseline — predeclared tuning procedure (D3-004.2)

**Why this document exists.** The experiment compares a *genuinely tuned*
reactive HPA against the forecast-assisted hybrid scaler
(`experiment/DECISIONS.md`, Decision 4). A default HPA would be a strawman;
the tuning is fixed here, BEFORE trials, and any retune invalidates affected
runs (same rule as the ⚙️ §9 anchors, D3-000.7).

**Status: procedure predeclared; the CPU result is ⚙️ pending the
characterization run.** `hpa-front-end.yaml` currently carries a placeholder
target that the automated parity check deliberately skips until it is replaced
by the measured output of this procedure.

## The predeclared procedure

Inputs: the kind testbed running (`make up`), the k6 stationary regime at a
slow ramp, Prometheus scrape of `front-end` p95 + CPU, candidate SLO
(SLO_P95_MS, currently ⚙️ 300 ms).

1. **Find the crossover.** Run the slow CPU/load ramp (stationary regime,
   stepped RPS). Record, per 15 s sample: `front-end` p95 request latency
   (Prometheus: `request_duration_seconds_{bucket/count}` per
   `deploy/monitoring/servicemonitor-sockshop.yaml`) and the deployment's
   average CPU utilization (%) vs its container request.
2. **Crossover** := the CPU utilization % of the sample window where p95
   first exceeds the candidate SLO (with a 60 s confirmation window so a
   transient spike is not mistaken for the crossover). Take the median of the
   3 samples around the crossing.
3. **Set the HPA CPU target** to crossover − **12%** (midpoint of the
   ratified 10–15 % safety margin; predeclared here, not picked later).
   Round to the nearest integer %.
4. **Bounds identical to the scaler:** min 2 / max 10 (§9 Decision 4).
   These are asserted automatically (`aiops/scaler/parity.py`).
5. **Stabilization windows:** the documented k8s v2 defaults, written
   explicitly in the manifest — scale-up 0 s, scale-down 300 s calm window.
6. **Record:** the final `averageUtilization`, the ramp inputs, the
   measurement commit hash, and the date in a worklog note appended to this
   file. The exact manifest applied during trials must be reproducible
   byte-for-byte from this document alone.

## Reproducibility checklist (review gate)

- [ ] SLO candidate stated (⚙️ number, from `SLO_P95_MS`).
- [ ] Crossover samples recorded (RPS, CPU %, p95 ms per sample).
- [ ] Target = crossover − 12 %, rounded, recorded.
- [ ] Manifest `averageUtilization` updated + provenance comment date-stamped.
- [ ] Parity check re-run: `python3 -m aiops.scaler.parity` (must stay green).
- [ ] Any trial that ran against an older manifest is marked invalid.

## Live gate

`kubectl apply --dry-run=server` + schema lint are CI/live checks and cannot
pass until the testbed is up (`make up`; currently blocked — Docker daemon
unavailable). Offline parity + YAML structure checks are in
`aiops/scaler/parity.py` and run inside `python3 -m aiops.scaler --selftest`.
