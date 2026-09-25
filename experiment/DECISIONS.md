# §9 Predeclared Decisions — First-Pass Proposals
## AIOps Platform experiment (ticket D3-000)

**Status:** FIRST-PASS PROPOSAL — **not yet signed off.** These are defensible starting values for you + your advisor to approve or edit. They must be **predeclared and frozen before any trial is run**, because choosing them after seeing results is p-hacking and invalidates the contribution.

**Governing baseline:** `LITERATURE_SURVEY_DECISION_REPORT.md`. The experiment being parameterized: *under predeclared nonstationary workloads and capacity-responsive faults in Sock Shop, does forecast-assisted hybrid scaling reduce SLO-breach duration + breaching requests vs a tuned reactive HPA — and where does it fail?*

**Config bindings:** each fixed constant below maps to an env var in `aiops/common/config.py` / an `experiment_run` column, so freezing this doc = filling in those defaults.

---

## Precondition — a baseline characterization run (do this first)

Several numbers below are marked ⚙️ **calibrate**: they cannot be picked honestly from a desk — they depend on your actual kind cluster. Before freezing this doc, run one short characterization on the testbed and record:

1. **Nominal p95 latency** of `front-end` at low, steady load → anchors the SLO threshold.
2. **Per-replica capacity** — ramp RPS until p95 crosses a candidate SLO; RPS-at-breach ÷ replicas = sustainable RPS per pod → anchors the forecast→replica map and regime RPS levels.
3. **Pod-ready time** — time from `scale` call to a new replica serving traffic (schedule + pull + readiness) → anchors the horizon *H* and the scale-up cooldown.

Everything else is a defensible default that does not need the cluster.

---

## Decision 1 — SLO definition

**Proposal.** Target the user-facing edge, the `front-end` service, measured per request.

- **Latency SLO:** p95 request latency **≤ 300 ms** ⚙️ *calibrate*, evaluated over a **60-second rolling window**.
- **Error SLO:** HTTP-5xx rate **≤ 1%** over the same 60 s window.
- **Breach:** any 60 s window where p95 > 300 ms **OR** error rate > 1%.
- **Primary metrics derived from this:** *SLO-breach duration* = summed length of breaching windows in a trial; *breaching requests* = requests served during breaching windows.

**Rationale.** Latency is the dimension scaling can actually move; the error-rate guard catches saturation collapse that latency alone misses. p95 (not mean) is the standard user-experience SLI. The 300 ms figure is a placeholder — set it from the characterization run so nominal load comfortably passes and stress reliably breaches (a rule of thumb: SLO ≈ nominal p95 × 1.3–1.5, rounded).

**Knobs for the advisor:** the ms threshold (calibration-dependent), the window length (60 s balances noise vs responsiveness), whether to add backend services (catalogue/carts/orders) as secondary SLOs.

**Config:** `SLO_P95_MS=300`, `SLO_ERROR_RATE=0.01`, window = `WINDOW_MIN=1`.

**Sign-off:** ☐ advisor ☐ you

## Decision 2 — Prediction / forecast horizon *H*

**Proposal.** Primary **H = 120 s (2 min)**. ⚙️ *calibrate against pod-ready time.*

**Rationale.** The whole point of proactive scaling is that added capacity is live *before* the load arrives. So *H* must exceed pod-ready time (schedule + image + readiness — tens of seconds on kind) plus a safety margin. 120 s gives ~2–4× headroom over a typical ~30–60 s pod-ready time. If your characterization shows slower pod-ready, raise *H*; if much faster, 90 s is acceptable.

**Anti-fishing rule:** predeclare **one** primary horizon (120 s). Report H ∈ {60, 300} only as clearly-labeled secondary/exploratory, never as the headline.

**Knobs:** primary *H* value; whether prediction and forecast share *H* (proposed: yes, so the two modules are comparable).

**Config:** `horizon_s=120` (stamped on every `experiment_run`).

**Sign-off:** ☐ advisor ☐ you

## Decision 3 — Workload generator + four traffic regimes

**Generator:** k6 Jobs, one per regime, each reproducible from a fixed `seed`, base RPS pinned to a fraction of measured per-replica capacity ⚙️. Trial length **20 min** each (long enough for diurnal shape + ≥15 evaluation windows).

| Regime | Shape | Base level | What it probes |
|---|---|---|---|
| **Stationary** | Constant RPS | ~60% capacity | Control — scaling should barely act; catches false scaling/oscillation. |
| **Diurnal** | Slow sinusoid up→down | 30%↔90% capacity | **Predictable seasonality — where forecasting should win.** |
| **Spike** | Step to 2.5× held ~3 min, then drop | 40% → 100%+ | Reactive lag vs proactive lead — the core comparison. |
| **Bursty** | Poisson bursts on a low baseline | 20% + random bursts | **Low predictability — where hybrid may NOT beat HPA (report honestly).** |

**Rationale.** The regimes deliberately span the predictability axis. Diurnal is where a forecaster earns its keep; bursty is where it likely can't — and reporting a *non-win* there is exactly the "and where does it fail" half of the contribution. This directly serves the conditional framing and guards against overclaiming.

**Knobs:** the RPS levels (calibration), trial length, spike magnitude/timing, burst intensity.

**Config:** `workload_regime` ∈ {stationary, diurnal, spike, bursty} + `seed` on each `experiment_run`.

**Sign-off:** ☐ advisor ☐ you

## Decision 4 — Scaling-policy parameters + HPA tuning procedure

**Forecast → replica map (the hybrid scaler):**
`desired = clip( ceil( forecast_RPS / (target_util × per_replica_capacity) ), min, max )`
with **target_util = 0.7**, **per_replica_capacity** ⚙️ from characterization.

**Cooldown:** scale-up **30 s**, scale-down **300 s** (asymmetric — react up fast, shrink down slowly to avoid flapping).

**Bounds:** **min = 2** (basic availability), **max = 10** (hard denial-of-wallet cap, enforced server-side, never trusted from any input).

**Tuned-HPA baseline procedure (this is what makes the comparison fair — do not skip):**
1. Under a slow ramp, find the CPU utilization at which p95 first crosses the SLO.
2. Set the HPA **CPU target 10–15% below** that point.
3. Set HPA **min/max identical to the scaler's** (2 / 10).
4. Use documented, default stabilization windows; record the exact HPA manifest.

**Rationale.** The survey retired the claim that prior autoscaling ignores SLA violations — so the baseline must be a *genuinely tuned* HPA, not the Kubernetes default, or any "win" is an artifact of a strawman. Identical min/max bounds isolate the only intended difference: proactive (forecast) vs reactive (CPU threshold). The max cap is a safety guardrail (denial-of-wallet).

**Knobs:** target_util, cooldown values, min/max, the "10–15% below" margin.

**Config:** stored with each run's policy config (`meta`/notes on `experiment_run`).

**Sign-off:** ☐ advisor ☐ you

## Decision 5 — Fault taxonomy (capacity-responsive vs negative controls)

All faults injected via Chaos Mesh, **scoped hard to `SOCK_NS` only** (a fault that could touch anything else must refuse to run).

**Capacity-responsive (scaling *can* help — the method should show benefit):**

- **CPU stress** (`StressChaos` CPU) on a service → latency rises, more replicas relieve it.
- **Pod-kill under load** (`PodChaos`) → capacity drops, scaler/HPA should recover it.

**Negative controls (scaling *cannot* help — a null result here is the CORRECT result):**

- **Network latency/loss** (`NetworkChaos`) — delay is on the wire, not from capacity.
- **Code / error fault** (HTTP 5xx injection) — errors are independent of replica count.
- **Dependency failure** (kill a downstream, e.g. the DB) — front-end replicas can't fix a dead dependency.
- **Memory leak** (progressive `StressChaos` memory → OOM) — replicas delay, don't cure.

Every fault row is tagged **`is_negative_control`** (true/false).

**Rationale.** Negative controls are mandatory per the survey. They prove the method isn't spuriously "winning everywhere" (which would signal a measurement artifact) and they draw the boundary of *where* forecast-assisted scaling applies. Reporting no-improvement on the four controls is a feature, not a failure — it must appear in its own results section, never buried.

**Knobs:** fault intensities/durations; whether to add a combined fault+regime matrix or keep faults and regimes as separate axes (proposed: full regime × fault matrix, controls included).

**Config:** `fault_class` (string) + `is_negative_control` (bool) on each `experiment_run`.

**Sign-off:** ☐ advisor ☐ you

## Decision 6 — Severity definition

**Proposal.** Grade each breaching window by margin over the SLO:

- **None:** p95 ≤ 300 ms and error ≤ 1%.
- **Minor:** p95 ∈ (300, 450] ms and error ≤ 1%.
- **Major:** p95 > 450 ms **or** error > 1%.

**Prediction target (module 4):** binary "**a *major* breach window occurs within horizon *H***", plus `breach_duration_est` (seconds) as a severity proxy.

**Rationale.** A fixed graded definition removes ambiguity from the prediction label (avoids arbitrary post-hoc thresholds and label leakage) and lets breaches be weighted — a 10 ms overshoot is not a 2× overshoot. Anchoring "major" to the SLO threshold keeps severity, SLO, and the prediction target mutually consistent rather than three independent knobs.

**Knobs:** the minor/major cut (450 ms), whether to weight breaching-request counts by severity.

**Sign-off:** ☐ advisor ☐ you

---

## Summary — the frozen constants (once signed off)

| Symbol | Value (first-pass) | Calibrate? | Binds to |
|---|---|---|---|
| SLO p95 | 300 ms / 60 s window | ⚙️ yes | `SLO_P95_MS`, `WINDOW_MIN` |
| SLO error | ≤ 1% / 60 s | no | `SLO_ERROR_RATE` |
| Horizon *H* | 120 s | ⚙️ yes | `horizon_s` |
| Regimes | stationary/diurnal/spike/bursty, 20 min, seeded | ⚙️ RPS levels | `workload_regime`, `seed` |
| target_util | 0.70 | no | scaler config |
| per_replica_capacity | — | ⚙️ yes | scaler config |
| Cooldown | up 30 s / down 300 s | no | scaler config |
| Bounds | min 2 / max 10 | no | scaler + HPA |
| Fault classes | 2 capacity-responsive + 4 negative controls | no | `fault_class`, `is_negative_control` |
| Severity | none/minor(≤450)/major(>450 or err) | no | analysis |

## Already-fixed methodology (not re-litigated here — inherited from the survey)

Chronological 2/3–1/3 holdout (no shuffling), infected-period exclusion, **≥20 paired reps** with randomized policy order per pair, PR-AUC with **≥70% precision** target for prediction, forecast must beat seasonal-naive **and** tree baselines, **95% bootstrap CIs + effect sizes** on primaries, negative controls reported separately.

---

*First-pass proposal for ticket D3-000. Values marked ⚙️ require a baseline characterization run on the testbed. Nothing here is valid as a result parameter until predeclared, signed off, and frozen. Conforms to `LITERATURE_SURVEY_DECISION_REPORT.md`; these controls account for and bound risk — they do not make any result "proven safe."*
