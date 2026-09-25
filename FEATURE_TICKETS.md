# Feature Ticket List
## AIOps Platform — buildable tickets derived from `PRD.md`

**Owner:** Sanmith
**Source of truth:** `PRD.md` (features), `ARCHITECTURE.md` (build order + repo layout), `TECHNICAL_ARCHITECTURE.md` (interfaces/schema). Governing baseline: `LITERATURE_SURVEY_DECISION_REPORT.md`.
**Status:** v1.0 ticket set for the fresh `aiops-platform/` build.

---

## How to use these tickets

Each ticket is written so you can paste its **Description** and **Acceptance criteria** straight into an AI coding tool as a prompt. Every ticket names its **build target** (the path to work in) and the **real interfaces** it should reuse, so the coder builds *into* the existing scaffold rather than reinventing it:

- Read raw metrics from Prometheus via `aiops/common/prom.py` (`range_query`, and the `q_latency_p95` / `q_error_rate` / `q_replicas` executors — each takes `(window)` and returns all Sock Shop services). **Never** copy raw metrics into the database.
- Write derived results to TimescaleDB via `aiops/common/store.py` → the single `inference(ts, module, service, kind, value, meta)` hypertable. Use `normalize()` (it fails loudly on missing fields — keep that).
- Read config from `aiops/common/config.py` env vars (`PROM_URL`, `TIMESCALE_DSN`, `SOCK_NS`, `WINDOW_MIN`, `STEP_S`, `SLO_P95_MS`, `SLO_ERROR_RATE`).
- **Every module ships an offline `python -m aiops.<module> --selftest`** that exercises its core logic with synthetic data and no cluster. This is a hard acceptance criterion on every code ticket.

**Guardrails (from `PRD.md` §1) that belong in code comments and UI copy, never violated:** RCA output is a *ranking*, not causal proof; failure prediction is a *probability*, not certainty; remediation is *human-approved*, which gives accountability — it does **not** make an action "safe"; results are testbed-only and are **not** claimed to generalize to production; negative-control results are reported, never buried.

## How priorities were assigned

The PRD marks each module **Must-have** with **Nice-to-have** extensions. I mapped those to your three tiers using the PRD's own MVP definition (§6) as the cut line:

- **Must-have for launch** — required to run the conditional experiment and ship the committed seven-module capstone deliverable (everything in §6).
- **Should-have** — a PRD nice-to-have that materially strengthens the *result or its credibility* (better detectors, richer analysis views) but isn't required to answer the research question.
- **Nice-to-have** — polish or productization that can slip without affecting the capstone (NL summaries, auth/RBAC, postmortem export).

If you'd rather I treat, say, the LSTM autoencoder or ensemble voting as Should instead of Must, tell me and I'll re-tier — this mapping is a judgment call, flagged as such.

## Dependency overview (build order)

```
Epic A Foundation ─► Epic B Ingestion ─┬─► Epic C Detect ─► Epic H Explain
                                       ├─► Epic D RCA
                                       ├─► Epic E Predict ─► Epic H Explain
                                       └─► Epic F Forecast ─► Epic I Scaler/Experiment
Epic C/D/E/F ─► Epic G Remediation
Epic C…G ─► Epic J Dashboard + Evaluation
Epic I (Scaler + harness) ⛔ BLOCKED on the six predeclared decisions (PRD §9)
```

> **⛔ Standing blocker:** every ticket in **Epic I** is *buildable as code* but **cannot be run for a credible result** until the six decisions in `PRD.md` §9 are predeclared (SLO, horizon *H*, workload regimes, scaling-policy params + HPA tuning procedure, fault taxonomy, severity definition). Each affected ticket repeats this.

---

## Epic A — Foundation & Testbed

### A1 · Local testbed bring-up (kind + Sock Shop + Prometheus + Chaos Mesh)
- **Priority:** Must-have · **Depends on:** none · **Build target:** `cluster/`, `deploy/monitoring/`
- **Description (prompt):** Finish and verify `cluster/bootstrap.sh` so `make up` creates the kind cluster from `cluster/kind-config.yaml` (1 control-plane + 2 workers, NodePorts 30080/30300/30090), installs kube-prometheus-stack into `monitoring`, Sock Shop (upstream `complete-demo.yaml`) into `sock-shop`, Chaos Mesh into `chaos-mesh`, and applies our kustomize. Add a `deploy/monitoring` ServiceMonitor so Prometheus scrapes every Sock Shop service.
- **Acceptance criteria:** `make up` completes on a clean machine; `make ps` shows all pods Ready; Prometheus (`:9090`) returns non-empty results for `q_latency_p95()` and `q_error_rate()` against Sock Shop; Grafana reachable at `:3300`; `make down` fully removes the cluster.

### A2 · Inference results store (TimescaleDB + `inference` hypertable)
- **Priority:** Must-have · **Depends on:** A1 · **Build target:** `deploy/timescaledb/`, `aiops/common/store.py` *(scaffolded — verify + harden)*
- **Description (prompt):** Confirm the TimescaleDB StatefulSet deploys and `store.py` creates the `inference` hypertable + `inference_lookup` index on first write. Add a thin read helper (`latest(module, service, kind, n)` and `range(module, service, kind, since)`) the dashboard/eval layers will reuse.
- **Acceptance criteria:** `--selftest` for `store` validates `normalize()` (raises on a missing key, round-trips a good row) with no DB driver installed; against a live DB, an insert then read returns the same row; hypertable + index exist.

### A3 · Experiment relational schema (`experiment/schema.sql`)
- **Priority:** Must-have · **Depends on:** A2 · **Build target:** `experiment/schema.sql`
- **Description (prompt):** Create the three relational tables from `TECHNICAL_ARCHITECTURE.md` §4.2–4.4: `experiment_run`, `experiment_result` (1:1), `remediation_action` (append-only audit). Provide an idempotent apply script invoked once at harness init — keep this DDL out of the hot write path in `store.py`.
- **Acceptance criteria:** Applying the script twice is a no-op; foreign keys and the `pair_id` index exist; a smoke test inserts a paired run + result and reads them back with a join.

---

## Epic B — Data Ingestion (PRD 4.1)

### B1 · Feature-window ingestion bridge
- **Priority:** Must-have · **Depends on:** A1, A2 · **Build target:** `aiops/ingest/`
- **Description (prompt):** Build a bridge that, every `STEP_S`, pulls the last `WINDOW_MIN` minutes of per-service features from Prometheus via `prom.py` — p95 latency, error rate, CPU, memory, replica count, RPS — aligns them onto a common timestamp grid (preserving gaps as NaN, never fabricating values), and exposes them as a tidy per-service feature frame the ML modules import. Include the OpenTelemetry Collector config for Sock Shop.
- **Acceptance criteria:** `python -m aiops.ingest --selftest` builds a correct feature frame from a synthetic Prometheus payload (including a gap) with no cluster; against the live testbed it returns aligned windows for every Sock Shop service; missing series surface as NaN, not zeros.

### B2 · Pluggable non-OTel connectors & historical bulk import *(deferred)*
- **Priority:** Nice-to-have · **Depends on:** B1 · **Build target:** `aiops/ingest/`
- **Description (prompt):** Add a connector interface for non-OpenTelemetry sources and a one-shot historical bulk-import path. Out of scope for the experiment; build only if a second data source is needed.
- **Acceptance criteria:** A sample CSV/backfill import lands rows the modules can read; existing OTel path unchanged.

---

## Epic C — Anomaly Detection (PRD 4.2)

### C1 · Isolation Forest detector + severity gate
- **Priority:** Must-have · **Depends on:** B1 · **Build target:** `aiops/detect/`
- **Description (prompt):** Build a per-service Isolation Forest (scikit-learn) over the ingestion feature windows for point/statistical anomalies. Apply a robust severity gate (median + K·MAD) so healthy series score ~0. Write results to `inference` with `module='detect'`, `kind='anomaly_score'` (and a gated `kind='anomaly_flag'`), putting the driving features in `meta`. **Enforce infected-period exclusion:** training windows must exclude injected-fault periods.
- **Acceptance criteria:** `python -m aiops.detect --selftest` flags an injected synthetic spike and scores a clean series ~0, offline; the severity gate keeps false positives near zero on fault-free windows; every written row carries feature context in `meta`; training never includes a fault window.

### C2 · LSTM autoencoder (temporal anomalies)
- **Priority:** Must-have · **Depends on:** B1 · **Build target:** `aiops/detect/`
- **Description (prompt):** Add a PyTorch LSTM autoencoder over per-service sequences; flag windows with high reconstruction error as temporal anomalies. Share the `detect` write path; distinguish with `kind='anomaly_score_seq'`. Keep `torch` an optional install (guard the import). Same infected-period exclusion rule.
- **Acceptance criteria:** `--selftest` trains briefly on a synthetic periodic signal and flags an injected sequence anomaly, offline (CPU-only, tiny epochs); reconstruction-error threshold is documented and configurable.

### C3 · Ensemble voting + confidence scoring
- **Priority:** Should-have · **Depends on:** C1, C2 · **Build target:** `aiops/detect/`
- **Description (prompt):** Combine the IF and LSTM-AE signals into a single per-service anomaly verdict with a confidence value, and expose the per-detector contributions for the dashboard. Strengthens detection quality; not required to answer the research question.
- **Acceptance criteria:** `--selftest` shows the ensemble agreeing on clear cases and expressing low confidence on disagreement; confidence is written to `meta`.

---

## Epic D — Root-Cause Localization (PRD 4.3)

### D1 · Service dependency graph from traces
- **Priority:** Must-have · **Depends on:** B1 · **Build target:** `aiops/rca/`
- **Description (prompt):** Build the Sock Shop service dependency graph from trace data (fall back to a static topology if traces are unavailable). Represent it as a directed graph the localizer can traverse.
- **Acceptance criteria:** `python -m aiops.rca --selftest` reconstructs a known graph from a synthetic trace sample; the graph matches Sock Shop's real call structure against the live testbed.

### D2 · Anomaly propagation & culprit ranking
- **Priority:** Must-have · **Depends on:** C1, D1 · **Build target:** `aiops/rca/`
- **Description (prompt):** When anomalies fire, rank services by likelihood of being the *origin* (not the symptom) using severity + graph propagation. Write `module='rca'`, `kind='culprit_rank'`, value = rank/score, `meta` = evidence. **UI/comment copy must state this is a ranking, not causal proof.**
- **Acceptance criteria:** `--selftest` puts an injected root-cause service at top-1 on a synthetic propagation scenario; output exposes top-1 and top-3; no language anywhere claims proven causality.

### D3 · Interactive graph explorer with time-scrubbing
- **Priority:** Nice-to-have · **Depends on:** D2, J1 · **Build target:** `aiops/dashboard/`
- **Description (prompt):** Add an interactive RCA graph view with a time slider to replay propagation. Visualization polish on top of D2.
- **Acceptance criteria:** Operator can scrub a past incident and see the ranking evolve; no new backend claims.

---

## Epic E — Failure Prediction (PRD 4.4)

### E1 · Severity-aware SLO-breach prediction at horizon *H*
- **Priority:** Must-have · **Depends on:** B1 · **Build target:** `aiops/predict/`
- **Description (prompt):** Build failure prediction on the validated template (log-driven LSTM per Zhang et al., and/or CEP+HMM per Baldoni et al.). Output **probability of SLO breach + expected breach duration at horizon *H***, using the `SLO_*` config for the breach definition. Evaluate on a **chronological 2/3–1/3 holdout** (never a random split). Write `module='predict'`, `kind='breach_prob'` and `kind='breach_duration_est'`. Also emit the time-to-prediction vs time-to-failure pair.
- **Acceptance criteria:** `python -m aiops.predict --selftest` trains on the chronological front of a synthetic series and predicts a held-out injected breach, offline; reports **PR-AUC at the ≥70% precision** operating point; refuses to run on a random (non-chronological) split; horizon *H* and SLO come from config, not hard-coded. **⛔ Real scoring needs §9 SLO + *H*.**

### E2 · Per-service failure-mode taxonomy
- **Priority:** Nice-to-have · **Depends on:** E1 · **Build target:** `aiops/predict/`
- **Description (prompt):** Extend the tiered-severity output with a per-service failure-mode label beyond breach/no-breach. Enrichment only.
- **Acceptance criteria:** `--selftest` assigns distinct modes to distinct synthetic fault signatures.

---

## Epic F — Capacity Forecasting (PRD 4.5)

### F1 · Prophet forecast, gated by a seasonality diagnostic, with baselines
- **Priority:** Must-have · **Depends on:** B1 · **Build target:** `aiops/forecast/`
- **Description (prompt):** Forecast per-service load/latency. **Run a seasonality diagnostic first; only apply Prophet if the series is actually seasonal** — otherwise fall through to the baselines. Run a **seasonal-naive baseline** (required reference) and a tree-based baseline *alongside* Prophet, not as an afterthought. Write `module='forecast'`, `kind='forecast_p95'` (+ baseline kinds), horizon from config. This forecast is what the scaler (I1) consumes.
- **Acceptance criteria:** `python -m aiops.forecast --selftest` (a) detects seasonality on a synthetic seasonal series and non-seasonality on a random-walk and skips Prophet on the latter, (b) always produces the seasonal-naive baseline, (c) reports error metrics for all methods side by side; `prophet` import is optional/guarded.

### F2 · Multi-horizon comparison view (1h / 24h / 7d)
- **Priority:** Nice-to-have · **Depends on:** F1, J1 · **Build target:** `aiops/dashboard/`
- **Description (prompt):** Add a dashboard view comparing forecasts across horizons. Presentation only.
- **Acceptance criteria:** Three horizons render for a chosen service with their baselines.

---

## Epic G — Human-in-the-Loop Remediation (PRD 4.6)

### G1 · Remediation proposal, approval, execution & audit
- **Priority:** Must-have · **Depends on:** C1, D2, E1, F1, A3 · **Build target:** `aiops/remediate/`
- **Description (prompt):** Propose a remediation action (scale-out, restart, traffic shift) with a supporting **evidence bundle** (anomaly, culprit rank, prediction, forecast). Require explicit operator approve/reject **before** any execution — **no autonomous action in v1**. On approval, apply via the Kubernetes API (`apps/v1` Deployment scale) and record the full lifecycle in `remediation_action` (proposed → approved/rejected → applied → outcome). Enforce server-side replica bounds. **Comment/UI copy: approval provides accountability, it does not make the action "safe".**
- **Acceptance criteria:** `python -m aiops.remediate --selftest` runs the full proposal→approval→apply→log flow against a mocked k8s client offline; a rejected action never executes; an action is applied **exactly once** (idempotent, safe under double-approval); an apply failure is logged as `failed` and never marked `applied`; the audit row is append-only.

### G2 · Autonomous low-risk allow-list + rollback automation
- **Priority:** Nice-to-have · **Depends on:** G1 · **Build target:** `aiops/remediate/`
- **Description (prompt):** Optional auto-execution for a pre-approved low-risk allow-list, plus automatic rollback on regression. Explicitly out of scope for v1; keep behind a default-off flag.
- **Acceptance criteria:** With the flag off, behavior is identical to G1; with it on, only allow-listed actions auto-run and roll back on a detected regression in `--selftest`.

---

## Epic H — Explainability (PRD 4.7)

### H1 · SHAP/LIME attributions on every anomaly & prediction
- **Priority:** Must-have · **Depends on:** C1, E1 · **Build target:** `aiops/explain/`
- **Description (prompt):** Attach SHAP/LIME feature attributions to every anomaly score and failure prediction the operator sees — no black-box numbers. Store attributions in the originating row's `meta` (or a linked `module='explain'` row). Keep `shap` an optional/guarded import.
- **Acceptance criteria:** `python -m aiops.explain --selftest` produces per-feature attributions for a synthetic detector/predictor output offline; the dashboard can render the top drivers for any score; no score is shown without an attribution available.

### H2 · Natural-language explanation summaries
- **Priority:** Nice-to-have · **Depends on:** H1 · **Build target:** `aiops/explain/`
- **Description (prompt):** Generate a short plain-English summary from the SHAP/LIME output. Deferred per PRD §8.
- **Acceptance criteria:** `--selftest` turns a sample attribution into a faithful one-sentence summary (no invented features).

---

## Epic I — Scaling Experiment (the contribution) ⛔ blocked on PRD §9

> Every ticket here is buildable as code now, but **cannot produce a credible result** until the six §9 decisions are predeclared. Build the code; gate the *runs* on the decisions.

### I1 · Forecast-assisted hybrid scaler
- **Priority:** Must-have · **Depends on:** F1 · **Build target:** `aiops/scaler/`
- **Description (prompt):** Build the controller that maps the F1 forecast → desired replicas and applies it via the k8s scale API, with a **cooldown** and **min/max replica bounds**. This is the experiment's treatment arm. Write decisions to `inference` (`module='scaler'`, `kind='replicas_target'`).
- **Acceptance criteria:** `python -m aiops.scaler --selftest` maps a synthetic forecast to bounded replica targets, honors cooldown (no thrashing), and clamps to min/max, offline. **⛔ Forecast→replica mapping, cooldown, and bounds must come from the §9 decision, not hard-coded.**

### I2 · Tuned reactive HPA baseline
- **Priority:** Must-have · **Depends on:** A1 · **Build target:** `deploy/platform/`, `experiment/`
- **Description (prompt):** Configure native Kubernetes HPA v2 as the control arm, applying a **predeclared tuning procedure** (not defaults) so the baseline is honest, not a strawman. Capture the procedure as code/manifest + notes.
- **Acceptance criteria:** HPA manifests apply and scale Sock Shop under load; the tuning procedure is documented and reproducible. **⛔ Tuning procedure from §9.**

### I3 · Load harness — four traffic regimes (k6)
- **Priority:** Must-have · **Depends on:** A1 · **Build target:** `experiment/load/`
- **Description (prompt):** Build the k6 Job driven by `REGIME` to generate the four predeclared regimes (stationary, diurnal/periodic, abrupt spike, bursty). `make load REGIME=…` runs each.
- **Acceptance criteria:** Each regime produces its characteristic traffic shape against Sock Shop; profiles are reproducible from a seed. **⛔ Regime definitions from §9; real workload traces (e.g. a cluster trace) may inform them.**

### I4 · Fault harness — capacity-responsive + negative controls (Chaos Mesh)
- **Priority:** Must-have · **Depends on:** A1 · **Build target:** `experiment/faults/`
- **Description (prompt):** Author Chaos Mesh manifests for the fault taxonomy: capacity-responsive faults (where scaling *can* help) and **negative controls** (network/code/dependency/memory-leak, where scaling cannot). Tag each with `is_negative_control`.
- **Acceptance criteria:** `make chaos` lists/applies each fault; faults are schedulable and repeatable with recorded start/stop windows (for infected-period exclusion). **⛔ Taxonomy from §9. Negative controls are mandatory.**

### I5 · Paired-trial runner
- **Priority:** Must-have · **Depends on:** I1, I2, I3, I4, A3 · **Build target:** `experiment/`
- **Description (prompt):** Orchestrate matched trials: for each regime × fault, run once under tuned HPA and once under the hybrid scaler with the **same** fault/seed, **randomizing policy order**, **≥20 repetitions** per scenario. Record every run + result to `experiment_run`/`experiment_result` with the SLO/horizon stamped and fault windows captured.
- **Acceptance criteria:** A dry run (mocked cluster) writes correctly paired rows with randomized order and matching `pair_id`; repetition count and any shortfall are recorded, never overclaimed. **⛔ Needs §9 SLO, horizon, regimes, faults, severity.**

### I6 · Analysis & operations metrics
- **Priority:** Must-have · **Depends on:** I5 · **Build target:** `experiment/analysis/`
- **Description (prompt):** Compute the **primary** outcomes — SLO-breach duration, SLO-breaching requests, and resource cost/churn (pod-minutes, scaling actions, oscillations) — as **paired** hybrid-vs-HPA comparisons with **95% bootstrap CIs and effect sizes**. Report **capacity-responsive faults and negative controls separately**; a null result on negative controls is the correct result and is shown, not buried.
- **Acceptance criteria:** On synthetic paired data, produces per-scenario CIs + effect sizes; separates H1 (capacity-responsive) from negative controls; output is reproducible and states the repetition count.

---

## Epic J — Dashboard & Evaluation (PRD 4.8)

### J1 · Operator dashboard + read-API
- **Priority:** Must-have · **Depends on:** C1, D2, E1, F1, G1 · **Build target:** `aiops/dashboard/`
- **Description (prompt):** Build the React (Vite) dashboard covering the full user flow — live anomaly feed, RCA graph view, failure-prediction alerts, forecast view, remediation approval queue — over a thin Express read-API that reads TimescaleDB (browser never touches Postgres). **Security note in code + README: the dashboard/API are unauthenticated and bound to localhost via NodePort; do not expose beyond localhost.**
- **Acceptance criteria:** Every module's output is visible and the remediation approve/reject flow works end to end against the testbed; the read-API only reads; the localhost-only + no-auth constraint is documented in the repo.

### J2 · Evaluation & reporting layer
- **Priority:** Must-have · **Depends on:** C1, D2, E1, G1 · **Build target:** `aiops/` (eval module) / `experiment/analysis/`
- **Description (prompt):** Compute and report the detection/RCA/remediation metrics — MTTD, false-positive rate (incl. per fault-free hour), root-cause top-1/top-3 accuracy, remediation success rate — as **ranges / 95% CIs across ≥20 trials** (report the constraint if fewer). These are *instrument-quality* metrics and must **not** be presented as proof of reliability improvement (that's Epic I).
- **Acceptance criteria:** Produces each metric with a range/CI from logged incidents on synthetic data; FP rate ~0 on healthy services; output clearly separates instrument metrics from the Epic I operations result.

### J3 · Historical incident timeline / postmortem export
- **Priority:** Nice-to-have · **Depends on:** J1 · **Build target:** `aiops/dashboard/`
- **Description (prompt):** A browsable incident history with postmortem export. Convenience feature.
- **Acceptance criteria:** Past incidents list and export to a file with their evidence bundles.

---

## Epic K — Deferred / future (Nice-to-have)

### K1 · Authentication, RBAC & multi-user access
- **Priority:** Nice-to-have (out of scope for v1 per PRD §8) · **Depends on:** J1 · **Build target:** `aiops/dashboard/`, API
- **Description (prompt):** Implement the access model in `SECURITY_AND_ACCESS.md` (SSO/OIDC, roles, row-level tenant isolation) — **required before any shared/non-localhost deployment**, deferred while the platform is a single-user local instrument.
- **Acceptance criteria:** Login + role enforcement + tenant RLS per that document; localhost single-user behavior unchanged when disabled.

---

*This ticket list is derived from `PRD.md` and conforms to `LITERATURE_SURVEY_DECISION_REPORT.md`. Priorities trace to the PRD's §4 classifications and §6 MVP definition; the Should-have tier reflects senior-lead judgment (flagged as such). Epic I is code-ready but run-blocked on the six §9 decisions.*
