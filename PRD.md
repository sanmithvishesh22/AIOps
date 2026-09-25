# Product Requirements Document
## AIOps Platform — AI-Driven Anomaly Detection & Predictive Maintenance for IT Infrastructure

**Prepared for:** Capstone team, Dept. of Information Technology
**Status:** Final — v1.0 (conforms to the settled research baseline; experiment parameters in §9 pending predeclaration)
**Owner:** Sanmith
**Last updated:** 2026-09-24
**Governing research doc:** `LITERATURE_SURVEY_DECISION_REPORT.md` — if this PRD and the survey ever disagree on a claim, the survey wins.

---

## 1. Overview

The AIOps Platform is an AI-driven operations layer for containerized microservices infrastructure. It watches live telemetry (logs, metrics, traces), detects anomalies before they become outages, explains *why* something is going wrong and *where* in the service graph the fault originates, predicts failures and capacity shortfalls ahead of time, and — with a human in the loop — triggers remediation. It is built and evaluated against a Kubernetes-based microservices testbed (Sock Shop) using Chaos Mesh fault injection, so every claim it makes can be tested under controlled, repeatable failure conditions rather than asserted from forecasting accuracy alone.

The platform is the **instrument**; the single scientific contribution is a controlled, **conditional** experiment:

> Under predeclared nonstationary workloads and capacity-responsive injected faults in Sock Shop, does a **forecast-assisted hybrid** Kubernetes scaling policy reduce **SLO-breach duration** and **SLO-breaching requests** relative to a **tuned reactive HPA**, without unacceptable resource cost or scaling churn — and under which fault classes does it fail?

The binary question "can proactive/forecasted scaling help at all" is already settled in the literature (e.g. FLAS, Fazio et al. 2021), so it is **not** our contribution. What we contribute is evidence about *conditions, trade-offs, and failure cases* in this testbed — negative controls included. Building the seven-module platform is credible engineering; it is not, by itself, a novel system concept.

### Positioning guardrails (do not violate — from the survey, §11)

These statements were refuted or ruled unusable by our own literature survey and must **never** appear in the report, dashboard, viva, or code comments:

- ❌ "the first integrated AIOps platform" / "7-module integration is novel"
- ❌ "no prior autoscaling work measures SLA violations" / "this gap is unclosed"
- ❌ "forecast accuracy proves reliability improvement"
- ❌ "root-cause ranking proves causality"
- ❌ "human approval makes remediation safe"
- ❌ "Sock Shop results generalize to production"

**Safe positioning (verbatim intent from §11):** "We build an integrated AIOps prototype and empirically evaluate a forecast-assisted scaling policy under a controlled microservice fault-and-load matrix. Our contribution is evidence about conditions, trade-offs and failure cases in this testbed."

---

## 2. Who It's For

| Persona | Role | What they need from the platform |
|---|---|---|
| **Primary — SRE / DevOps engineer** | Operates the microservices cluster day to day | Early warning before SLO breach, root cause in seconds not hours, a remediation action they can approve with confidence |
| **Secondary — IT Ops / Engineering manager** | Owns SLO outcomes and infra spend | Evidence that the forecast-assisted policy reduces SLO-breach duration vs. a *tuned* reactive baseline **and at what resource/churn cost**; auditable metrics |
| **Tertiary — Platform/ML evaluator (capstone reviewers)** | Assesses methodological rigor | Traceable, temporally valid metrics (PR-AUC, MTTD, FP rate, breach duration) reported as **ranges/CIs across repeated paired trials**, not single-run numbers |

The product is designed around the SRE as the day-to-day user; the manager and evaluator personas consume the same evidence at a higher level of aggregation.

---

## 3. Problem It Solves

Most operations teams today are reactive: alerts fire only after a threshold is already breached, and root-causing a failure in a microservices graph means manually correlating logs, metrics, and traces across dozens of services under time pressure. Two concrete operator pain points motivate the platform:

- **Reactive-only scaling leaves a damage window.** Native HPA adds capacity only after utilization/latency has already crossed a threshold, so the SLO is already breaching by the time replicas arrive. Forecasting papers report strong prediction accuracy (R², MSE), but forecast accuracy is **not** the same claim as *fewer/shorter SLO breaches under live faults* — a distinction the survey is emphatic about.
- **Localization is slow.** When p95 latency spikes across a service mesh, the most expensive minutes go to finding *which* service is the origin rather than the symptom.

**What the literature already settles (so we don't re-claim it):** the *binary* question — can forecast-assisted/hybrid scaling improve SLO outcomes at all — is closed (FLAS). Failure prediction *and* localization in autoscaling Kubernetes apps already exists (Preface, Denaro et al. 2024), so "no precedent for occurrence+severity prediction" is not usable as a novelty claim. The **defensible, open question is conditional**: *under which workload/fault conditions* does the hybrid policy help, where does it fail, and at what resource and churn cost. The platform exists to answer that rigorously — with honest negative controls — not to plant a flag.

---

## 4. Core Features

Features are grouped by the platform's seven modules, each tagged **Must-have** (required to run the conditional experiment and ship a working capstone MVP) or **Nice-to-have** (strengthens the product but is not required to validate the core result).

### 4.1 Unified Data Ingestion — **Must-have**
- Ingest logs, metrics, and traces from the testbed via OpenTelemetry.
- Normalize and timestamp-align multi-source telemetry; raw metrics live in Prometheus (source of truth), derived **inference results** are written to TimescaleDB.
- *Nice-to-have:* pluggable connectors for non-OpenTelemetry sources; historical bulk-import UI.

### 4.2 Unsupervised Anomaly Detection — **Must-have**
- Isolation Forest for point/statistical anomalies, with a severity gate (robust baseline: median + K·MAD) so healthy series report ~0.
- LSTM Autoencoder for sequence/temporal anomalies.
- Infected-period exclusion enforced in all training windows (non-negotiable per project methodology — prevents label leakage; the survey lists "train only on the pre-fault period" as a required audit).
- *Nice-to-have:* ensembling/voting across detectors with confidence scoring exposed in the UI.

### 4.3 Graph-Based Root Cause Localization — **Must-have**
- Service dependency graph built from trace data.
- Anomaly propagation/localization to the originating service, not just the symptomatic one — a **ranking**, not causal proof.
- *Nice-to-have:* interactive graph exploration UI with time-scrubbing.

### 4.4 Severity-Aware Failure Prediction — **Must-have**
- Log-driven LSTM (Zhang et al. template) and/or CEP+HMM (Baldoni et al. template) as validated methodological baselines.
- Output operationalized as **probability of SLO breach + expected breach duration** at horizon *H*, evaluated with chronological 2/3–1/3 holdout; **PR-AUC ≥ 70% precision** as the acceptance threshold.
- Time-to-prediction vs. time-to-failure dual-metric reporting.
- *Nice-to-have:* per-service failure-mode taxonomy beyond tiered severity.

### 4.5 Capacity Forecasting — **Must-have**
- Prophet-based forecasting, gated by a mandatory **seasonality diagnostic** before use (Prophet must not be applied to non-seasonal telemetry without this check).
- Seasonal-naive and tree-based baselines run alongside Prophet for comparison, not as an afterthought (the survey requires seasonal-naive as the reference).
- *Nice-to-have:* multi-horizon forecast comparison view (1h / 24h / 7d).

### 4.6 Human-in-the-Loop Remediation — **Must-have**
- Proposes a remediation action (scale-out, restart, traffic shift) with the supporting evidence bundle.
- Operator approves/rejects before execution — no fully autonomous action in v1. (Human approval is a **safety property**, not proof of autonomy — see guardrails.)
- *Nice-to-have:* autonomous remediation for a pre-approved low-risk allow-list; rollback automation.

### 4.7 Explainability — **Must-have**
- SHAP/LIME output attached to every anomaly and failure prediction shown to the user — no black-box scores.
- *Nice-to-have:* natural-language explanation summaries generated from SHAP/LIME output.

### 4.8 Supporting platform features
- **Must-have:** React dashboard — live anomaly feed, RCA graph view, failure-prediction alerts, forecast view, remediation approval queue. *(The dashboard + read-API are **unauthenticated**, bound to localhost via NodePort — acceptable only for a single-user local research cluster. Do not expose the NodePort beyond localhost; auth is a prerequisite for any shared deployment.)*
- **Must-have:** Evaluation/reporting layer outputting MTTD, false-positive rate, root-cause accuracy, remediation success rate, **and the primary operations metrics (SLO-breach duration, breaching-request count, pod-minutes/churn)** as ranges/95% CIs across **≥20 repeated paired fault-injection trials** (or fewer with the constraint reported — never overclaimed).
- **Nice-to-have:** Role-based access control, multi-user auth, historical incident timeline/postmortem export.

---

## 5. User Flow (End to End)

1. **Ingest** — Telemetry streams continuously from the Sock Shop testbed through OpenTelemetry; raw metrics land in Prometheus, ML services read recent windows and write inference results to TimescaleDB.
2. **Detect** — Isolation Forest and the LSTM Autoencoder flag anomalies in near-real-time (severity-gated); flagged events appear in the SRE's live dashboard feed.
3. **Localize** — The operator opens an anomaly; the graph-based RCA view shows the propagation path and highlights the likely originating service (ranking).
4. **Predict** — In parallel, the failure-prediction module estimates SLO-breach probability and expected breach duration for services on the propagation path, with a PR-AUC-backed score and a time-to-failure estimate.
5. **Forecast** — If the anomaly correlates with a capacity trend, the forecasting module surfaces a short-horizon load projection (post seasonality check) so the operator can tell a spike from a sustained trend. This same forecast is what the hybrid scaler acts on.
6. **Explain** — Every score the operator sees (anomaly, failure prediction, forecast) is backed by a SHAP/LIME panel — which features drove it.
7. **Act** — The system proposes a remediation action with its evidence bundle. The operator approves, edits, or rejects it. Approved actions execute against the testbed via the k8s API and are logged.
8. **Evaluate** — Every incident (real or Chaos Mesh-injected) is logged with MTTD, false-positive status, root-cause accuracy, breach duration, and remediation outcome, feeding the evaluation layer used for reporting.

---

## 6. MVP Definition

The MVP is the smallest system that can produce a **defensible, repeatable answer to the conditional research question** on the Sock Shop testbed:

- Modules 1–4 and 7 fully functional (ingestion → anomaly detection → RCA → failure prediction → explainability), using the validated Zhang et al. / Baldoni et al. methodological templates.
- Module 5 (capacity forecasting) with the mandatory seasonality diagnostic and seasonal-naive/tree baselines — not a bare Prophet call.
- Module 6 (remediation) human-in-the-loop only; no autonomous execution.
- **The scaling comparison wired up:** a **tuned reactive HPA** baseline and the **forecast-assisted hybrid** policy (with cooldown + min/max-replica guardrails), plus the Chaos Mesh fault-injection + k6 load harness driving matched paired trials (**≥20 reps** per scenario, or the constraint reported).
- Evaluation layer producing MTTD, FP rate, root-cause accuracy, remediation success rate, and the **SLO-breach-duration / breaching-request / cost / churn comparison of hybrid vs tuned HPA** — reported as ranges/CIs, **with capacity-responsive faults and negative controls reported separately.**
- Dashboard covering the full user flow above, even if visually minimal.

The full seven-module platform is the committed capstone deliverable; anything beyond the above (see §8) is explicitly deferred.

---

## 7. Success Metrics

Metrics are layered as the survey (§10) requires. The **primary** layer is the operations comparison; the model/detection layers describe instrument quality and do **not**, by themselves, prove reliability improvement.

| Layer | Metric | Definition | Target / standard |
|---|---|---|---|
| **Operations (primary)** | **SLO-breach-duration reduction** | Paired breach duration under forecast-assisted hybrid vs. **tuned** HPA, same fault/load scenario | Statistically meaningful reduction for **capacity-responsive** faults (H1), with 95% bootstrap CIs + effect size |
| **Operations (primary)** | **SLO-breaching requests** | Count/proportion of requests served in breach | Reported alongside duration, same paired design |
| **Operations (primary)** | **Resource cost & churn** | pod-minutes / CPU-seconds, scaling actions, oscillations | Hybrid must not win on breaches by paying an unacceptable cost/churn price (H2) |
| **Operations** | **Negative-control integrity** | Hybrid vs HPA on network/code/dependency/memory-leak faults | **No significant improvement expected** — a null result here is the *correct* result and is reported, not buried |
| Detection/RCL | MTTD | Mean time to detect from fault onset | Range across ≥20 trials |
| Detection/RCL | False-positive rate | Flagged anomalies that are not real faults; false alerts per fault-free hour | Range across ≥20 trials; ~0 on healthy services (severity gate) |
| Detection/RCL | Root-cause accuracy | Incidents where RCA localizes the originating service | Top-1 / top-3 range across ≥20 trials |
| Prediction | PR-AUC | Precision-recall AUC on chronological holdout | **≥ 70% precision** threshold |
| Remediation | Remediation success rate | Approved remediations that resolve the incident without a follow-on failure | Range across ≥20 trials |

All metrics follow the project's validity discipline: **infected-period exclusion** from training, **chronological holdout** (not random split), paired tests with randomized policy order, and **range/CI reporting across ≥20 repeated trials** (report the constraint if fewer) rather than single-run figures.

---

## 8. Explicitly NOT Building in v1

- **Retired novelty/gap claims.** v1 does not assert GAP-1/GAP-2 as open, nor any of the §1 guardrail statements. The contribution is the *conditional* result, not a first.
- **Multi-cluster / multi-cloud support.** Single local Kubernetes (kind) + Sock Shop testbed only — no production multi-cloud.
- **Fully autonomous remediation.** Every action requires human approval in v1; unattended auto-remediation is out of scope.
- **Multi-tenant SaaS features.** No billing, org-level RBAC, or tenant isolation — single-team research platform.
- **Auth / hardening on the dashboard.** The dashboard + API are unauthenticated and localhost-only (see §4.8); adding auth is out of scope for v1 but required before any shared deployment.
- **Custom connectors for proprietary observability tools.** OpenTelemetry ingestion only; no Datadog/New Relic/Splunk connectors.
- **Mobile app / mobile alerting.** Desktop-web dashboard only. No Slack/PagerDuty/email integrations in v1.
- **Legacy/non-containerized infrastructure.** Assumes a containerized Kubernetes environment; no bare-metal/VM-only estates.
- **Production-scale throughput.** Built and evaluated at testbed scale, not billions-of-events-per-day ingestion — and results are **not** claimed to generalize to production.
- **Natural-language explanation generation.** SHAP/LIME raw output is v1; NL summarization is deferred.

---

## 9. Open Decisions (block the experiment, not the modules)

The survey (§1) notes the project has not yet defined several parameters. Modules 1–7 can be built without them, but the scaling comparison (§6) cannot be run credibly until these are predeclared:

1. **SLO** — p95 latency + error-rate thresholds + evaluation window.
2. **Prediction horizon *H***.
3. **Workload generator** + the four traffic regimes (stationary, diurnal/periodic, abrupt spike, bursty).
4. **Scaling-policy parameters** — forecast→replica mapping, cooldown, min/max replica bounds, and the predeclared HPA **tuning procedure**.
5. **Fault taxonomy** — capacity-responsive faults vs. negative controls.
6. **Severity** — operationalized as breach duration or affected-request count.

---

*This PRD reflects the platform as scoped for the current capstone cycle. The settled research positioning (conditional experiment, tuned-HPA baseline, mandatory negative controls) and the Chaos Mesh evaluation methodology are treated as binding constraints on what v1 must demonstrate, per `LITERATURE_SURVEY_DECISION_REPORT.md` — not aspirational goals.*