# Technical Architecture Document
## AIOps Platform — AI-Driven Anomaly Detection & Predictive Maintenance for Microservices

**Owner:** Sanmith
**Status:** v1.0 — matches the scaffolded repo as of 2026-09-24
**Audience:** Engineering / build team
**Relationship to other docs:**
- `ARCHITECTURE.md` is the concise map (modules, data flow, build order). This TAD expands it into the buildable detail: stack reasoning, folder structure, database schema, and configuration.
- `PRD.md` defines *what* and *why*. This defines *how it's built*.
- `LITERATURE_SURVEY_DECISION_REPORT.md` is the fixed research baseline. If this document and the survey ever disagree on a research claim, the survey wins.

> **Framing.** The platform is the **instrument** for one controlled experiment: *when does forecast-assisted hybrid Kubernetes scaling beat a tuned reactive HPA on SLO-breach duration, and under which fault classes does it fail?* Every technical choice below serves making that experiment runnable and its result credible — not building a production SaaS. "Future scaling" notes here mean "don't paint us into a corner," not "provision for production"; production scale is explicitly out of scope (PRD §8).

---

## 1. Architecture at a glance

```
Sock Shop pods ──(OTel/Prometheus scrape)──► Prometheus (raw metrics, TSDB)
                                                  │
                    ┌─────────────────────────────┤ read recent windows (HTTP API)
                    ▼                             ▼
              ingest bridge                 ML modules (batch/stream)
              (feature windows)      detect · rca · predict · forecast
                    │                             │
                    └──────────► TimescaleDB ◄─────┘  (inference results)
                                     │
                    ┌────────────────┼───────────────────┐
                    ▼                ▼                    ▼
              scaler controller   dashboard (React)   remediation approver
              forecast → replicas   + explain (SHAP)    human-in-the-loop
                    │                                     │
                    └──────────► Kubernetes API (scale Deployments) ◄┘

Chaos Mesh ──(inject faults on a schedule)──► Sock Shop   [experiment harness drives this]
k6 load Job ──(traffic regimes)────────────► Sock Shop
```

Two storage planes, on purpose: **Prometheus holds raw metrics** (the live source of truth, already scraping Sock Shop) and the modules read recent windows from it over HTTP; **TimescaleDB holds only derived inference results** so they're queryable and joinable for the dashboard and the experiment analysis. Ingestion stays thin — we never copy raw metrics into Postgres.

---

## 2. Recommended tech stack (with reasoning)

The guiding rule is the laziness principle from `ARCHITECTURE.md`: **reuse off-the-shelf charts and native Kubernetes features; write custom code only for the five ML modules, the scaling controller, remediation, explainability, and the dashboard.** Every "build" below is justified against a "why not just use X".

| Layer | Choice | Why this, not the alternative |
|---|---|---|
| **Cluster** | Kubernetes via **kind** (1 control-plane + 2 workers) | The experiment needs a *real* scheduler, HPA, and the k8s scale API — a single-node/minikube setup hides scheduling and multi-replica behavior. kind gives a throwaway, reproducible multi-node cluster on one laptop. Not a cloud cluster: cost, and reproducibility of paired trials matters more than realism at this stage. |
| **App under test** | **Sock Shop** upstream manifests | A well-known microservices benchmark with a real service graph — needed for RCA and for load/fault realism. Building our own demo app would be wasted effort and less comparable to prior work. |
| **Metrics + TSDB** | **kube-prometheus-stack** (Prometheus, Grafana, node/kube-state metrics) | Prometheus is the k8s-native metrics standard and already scrapes everything we need (latency, error rate, CPU/mem, replicas). Grafana comes free in the chart for ad-hoc inspection. Writing a custom collector would reinvent a solved problem. |
| **Inference store** | **TimescaleDB** (`timescale/timescaledb:2.17.2-pg16`) | Module outputs are append-heavy, time-ordered rows — exactly what a Timescale hypertable is for (automatic time-partitioning, compression, retention). It's still plain Postgres, so the dashboard's Express API and the experiment analysis use ordinary SQL/JOINs. Plain Postgres would work at testbed scale but gives up the partitioning/compression we'd want the moment trials pile up. |
| **ML / services** | **Python 3.11** + **FastAPI** (endpoints), plain scripts / k8s CronJobs (batch) | Python is where scikit-learn, PyTorch, Prophet, and SHAP live — no bridging cost. FastAPI only where a live endpoint is genuinely needed (scaler, remediation approver, dashboard read-API); batch inference runs as CronJobs, so we don't stand up servers we don't need. |
| **Anomaly detection** | **scikit-learn** Isolation Forest + **PyTorch** LSTM autoencoder | IF is a fast per-service point-anomaly baseline; the LSTM-AE catches temporal/sequence anomalies. Two complementary detectors, both standard — no custom model architecture invented. |
| **Forecasting** | **Prophet** (+ seasonal-naive baseline, mandatory) | Prophet handles trend/seasonality with little tuning, but the baseline requires it be gated by a seasonality diagnostic and compared against seasonal-naive (survey requirement) — Prophet is never applied blindly. |
| **Explainability** | **SHAP / LIME** | Standard, model-agnostic attribution attached to every score. Non-negotiable per PRD: no black-box numbers reach the operator. |
| **Reactive baseline** | Kubernetes **native HPA v2**, tuned | The HPA *is* the control arm of the experiment. Using native HPA (not a custom reactive scaler) keeps the baseline honest and un-strawmanned; we only tune it via a predeclared procedure. |
| **Scaling controller** | Custom Python controller → **k8s API** (`apps/v1` Deployment scale) | This is the contribution. Minimal custom code: forecast → desired replicas, with predeclared cooldown and min/max bounds. Talks to the cluster via the official `kubernetes` client. |
| **Fault injection** | **Chaos Mesh** | Declarative, schedulable, covers the fault taxonomy (network, pod-kill, stress, etc.) we need for capacity-responsive faults *and* negative controls. Writing fault scripts by hand would be fragile and unrepeatable. |
| **Load generation** | **k6** as a Kubernetes Job | Scriptable traffic regimes (steady/ramp/spike/soak) driven by an env var; runs in-cluster so it hits Sock Shop directly. |
| **Dashboard** | **React (Vite)** + small **Express** read-API | React for the live feed/graph/approval UI; a thin Express layer reads TimescaleDB so the browser never talks to Postgres directly. Vite for fast local dev. |
| **Packaging** | **kustomize** bases + `local` overlay | One base per component, environment overlays layered on top — no templating engine (Helm) for our own manifests, since we have exactly one environment today and kustomize is built into `kubectl`. |
| **Orchestration of ops** | **Makefile** | `up / down / deploy / load / chaos / selftest / ps` as one-liners. No task runner to learn. |

**Language/runtime versions:** Python **3.11+**, Node **20+**, Docker, `kubectl`, `helm`, `kind`. Pinned Python deps in `requirements.txt` (heavy per-module extras — `torch`, `prophet`, `shap` — are listed commented so you install only what a module needs).

---

## 3. Database design — recommendation for future scaling

You asked which schema shape scales best. Three options were on the table:

1. **Single generic table only** — everything (every module's output *and* experiment/remediation records) as rows in one `inference(ts, module, service, kind, value, meta)` hypertable. This is what the repo scaffolds today.
2. **Fully normalized** — a purpose-built table per module (`anomaly_scores`, `rca_ranks`, `breach_predictions`, `forecasts`, …) plus normalized experiment/remediation tables with foreign keys everywhere.
3. **Hybrid** — keep the single generic hypertable for the high-volume time-series firehose, and add a *small* number of proper relational tables only for the low-volume, relationship-rich, integrity-sensitive records.

**Recommendation: the Hybrid (option 3).** Reasoning, on the axis that actually has volume:

- The part of this system that *grows* is per-service, per-timestamp module output — anomaly scores, RCA ranks, breach probabilities, forecasts, replica targets, one row every scrape interval per service per module. That is textbook time-series: append-only, time-ordered, uniform shape. A **TimescaleDB hypertable** is exactly the right tool — it auto-partitions by time and gives you compression and retention for free later. **Full normalization here scales *worst*:** you'd get 5–7 near-identical tables, more schema surface to migrate, and every cross-module dashboard query (“show me everything about `carts` in this window”) becomes a multi-table UNION/JOIN for no benefit.
- The part that does **not** have volume but **does** have relationships and integrity requirements is the **experiment ledger** (which trial ran under which policy/fault, and what it measured) and the **remediation audit log** (what was proposed, who approved it, what happened). Cramming these into the generic `meta` JSONB — the single-table-only option — forces fragile JSONB querying for the exact analysis the whole project hinges on (paired statistical comparison of hybrid vs HPA), and gives you no foreign-key integrity on the audit trail. These deserve **real relational tables**.

So the hybrid keeps the firehose lean where it needs to scale, and adds relational structure only where correctness (not volume) demands it. This is a mild, additive extension of the current single-table scaffold — the `inference` hypertable in `aiops/common/store.py` is kept exactly as built.

**Honest caveat (per the research baseline):** at capstone/testbed scale, all three options work fine — none of this is a bottleneck for ≥20 paired trials on one laptop cluster. This is strictly a "don't box yourself in for future scaling" recommendation, and the platform explicitly does **not** target production scale (PRD §8). We are choosing the shape that stays cheap to grow, not provisioning for load we don't have.

---

## 4. Full database schema

All tables live in the `aiops` Postgres/TimescaleDB database (namespace `aiops` in the cluster). Raw metrics are **not** here — they stay in Prometheus. This database holds only derived inference results and the experiment/remediation records.

### 4.1 `inference` — the time-series firehose (already built)

The one hypertable every module writes to. Defined in `aiops/common/store.py`.

```sql
CREATE TABLE IF NOT EXISTS inference (
    ts      TIMESTAMPTZ  NOT NULL,   -- when this result is *about* (event time)
    module  TEXT         NOT NULL,   -- which module produced it
    service TEXT         NOT NULL,   -- which Sock Shop service it concerns
    value   DOUBLE PRECISION,        -- the numeric result (nullable)
    kind    TEXT         NOT NULL,   -- what 'value' means for this module
    meta    JSONB                    -- structured extras (feature attributions, etc.)
);
CREATE INDEX IF NOT EXISTS inference_lookup ON inference (module, service, kind, ts DESC);
SELECT create_hypertable('inference','ts', if_not_exists => TRUE);
```

In plain English — each row is **one thing one module concluded about one service at one point in time**:

- **`ts`** — the event time the result refers to (not wall-clock insert time). This is the hypertable partition key, so time-range queries are fast.
- **`module`** — the producer: one of `detect`, `rca`, `predict`, `forecast`, `scaler`, `remediate`, `explain`.
- **`service`** — the Sock Shop service the row is about (`carts`, `orders`, `catalogue`, …). Free text by design — no foreign key — so ingestion never blocks on a missing dimension row.
- **`value`** — the single number the row carries. Its meaning depends on `kind`.
- **`kind`** — the label that tells you how to read `value`. Examples: `anomaly_score`, `severity_rank`, `breach_prob`, `forecast_p95`, `replicas_target`.
- **`meta`** — a JSONB bag for anything structured that isn't a single number: SHAP feature attributions, model version, the input window hash, confidence bounds.

Why one table instead of one-per-module: every module emits the same shape (time, service, a number, some context). A shared table means the dashboard and analysis read *everything* about a service with a single `WHERE service = … AND ts BETWEEN …`, and Timescale handles the growth. The `(module, service, kind, ts DESC)` index serves the "latest N results of kind X for service Y" query the dashboard makes constantly.

### 4.2 `experiment_run` — the trial ledger (new, relational)

One row per matched trial: a single execution of one scenario under one scaling policy. This is the backbone of the paired statistical analysis, so it must be clean relational data, not JSONB.

```sql
CREATE TABLE IF NOT EXISTS experiment_run (
    run_id            BIGSERIAL PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at          TIMESTAMPTZ,
    pair_id           TEXT        NOT NULL,   -- groups the HPA run and the hybrid run that must be compared
    policy            TEXT        NOT NULL,   -- 'hpa_tuned' | 'forecast_hybrid'
    workload_regime   TEXT        NOT NULL,   -- 'steady' | 'ramp' | 'spike' | 'soak'
    fault_class       TEXT        NOT NULL,   -- e.g. 'cpu_stress', 'network_delay', 'pod_kill', 'mem_leak'
    is_negative_control BOOLEAN   NOT NULL,   -- TRUE where scaling cannot help (reported, never buried)
    seed              INTEGER,                -- RNG seed for reproducibility
    slo_p95_ms        DOUBLE PRECISION NOT NULL,  -- the SLO in force for this run (predeclared)
    slo_error_rate    DOUBLE PRECISION NOT NULL,
    horizon_s         INTEGER,                -- prediction/forecast horizon H used
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS run_pair ON experiment_run (pair_id);
```

In plain English — each row records **one run of the experiment and the exact conditions it ran under**. The `pair_id` is the important field: the two runs that share a `pair_id` (one `hpa_tuned`, one `forecast_hybrid`, same regime + fault + seed) are the matched pair the analysis compares. `is_negative_control` marks the fault classes where scaling *cannot* help — the null result there is the correct result and is queried out and reported separately, per the baseline. The SLO/horizon columns are stamped onto every run so a result is never read without the threshold it was judged against.

### 4.3 `experiment_result` — measured outcome per run (new, relational)

One row per run, holding what we measured. Split from `experiment_run` so "what we configured" stays separate from "what came out".

```sql
CREATE TABLE IF NOT EXISTS experiment_result (
    run_id                  BIGINT PRIMARY KEY REFERENCES experiment_run(run_id) ON DELETE CASCADE,
    slo_breach_duration_s   DOUBLE PRECISION,  -- PRIMARY outcome
    breaching_requests      BIGINT,            -- PRIMARY outcome
    breaching_request_ratio DOUBLE PRECISION,
    pod_minutes             DOUBLE PRECISION,  -- resource cost
    scaling_actions         INTEGER,           -- churn
    oscillations            INTEGER,           -- churn (up-down flips)
    mttd_s                  DOUBLE PRECISION,  -- detection quality
    rca_top1_correct        BOOLEAN,           -- localization quality
    remediation_success     BOOLEAN,           -- remediation quality
    extra                   JSONB              -- any additional per-run metrics
);
```

In plain English — each row is **the scorecard for one run**, keyed one-to-one to its `experiment_run` by `run_id`. `slo_breach_duration_s` and `breaching_requests` are the primary outcomes the whole experiment turns on; `pod_minutes`/`scaling_actions`/`oscillations` capture the cost-and-churn side so a policy can't "win" on breaches by paying an unacceptable resource price. The detection/RCA/remediation columns let the same ledger produce the secondary metrics tables. `ON DELETE CASCADE` means deleting a run cleans up its result automatically.

### 4.4 `remediation_action` — human-in-the-loop audit log (new, relational)

Every proposed remediation and its human decision. This is an audit trail, so it needs integrity and a clear status lifecycle — not a JSONB blob.

```sql
CREATE TABLE IF NOT EXISTS remediation_action (
    action_id     BIGSERIAL PRIMARY KEY,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    service       TEXT        NOT NULL,   -- target service
    action_type   TEXT        NOT NULL,   -- 'scale' | 'restart' | 'rollout' | 'traffic_shift'
    params        JSONB,                  -- e.g. {"replicas": 5}
    evidence      JSONB,                  -- the bundle shown to the operator (scores, SHAP, forecast)
    status        TEXT        NOT NULL DEFAULT 'proposed',  -- proposed|approved|rejected|applied|failed
    decided_by    TEXT,                   -- who approved/rejected
    decided_at    TIMESTAMPTZ,
    applied_at    TIMESTAMPTZ,
    outcome       TEXT,                   -- free-text / 'resolved' | 'no_effect' | 'regressed'
    run_id        BIGINT REFERENCES experiment_run(run_id) ON DELETE SET NULL  -- run it happened during, if any
);
CREATE INDEX IF NOT EXISTS remediation_status ON remediation_action (status, proposed_at DESC);
```

In plain English — each row is **one proposed action and the full story of what a human decided about it**: what was proposed and why (`params` + `evidence`), whether it was approved or rejected and by whom, whether it was applied, and how it turned out. `status` moves `proposed → approved/rejected → applied → (outcome)`. The optional `run_id` links an action to the experiment run it occurred during (or stays null for actions outside a formal trial). Note per the guardrails: this log documents that a human approved — it is **not** evidence that remediation is "safe". `ON DELETE SET NULL` keeps the audit record even if its run is deleted.

### 4.5 How the tables relate (plain English)

- **`inference` stands alone by design.** It is joined to the relational tables only loosely — by `service` name and by `ts` falling inside a run's `[started_at, ended_at]` window. There is deliberately **no foreign key** from `inference` to a service dimension: the firehose must never block on a missing parent row.
- **`experiment_run` 1 — 1 `experiment_result`.** Each run produces exactly one scorecard, sharing the `run_id`.
- **`experiment_run` 1 — many `remediation_action`.** A single run can involve several proposed actions; each action optionally points back to its run via `run_id`.
- **`pair_id` links runs to each other** (not via a foreign key but as a grouping key): the matched HPA-vs-hybrid pair the analysis compares share one `pair_id`.

```
          experiment_run ──1:1──► experiment_result
                │
                │ 1:many
                ▼
        remediation_action

  inference  (independent time-series; correlated by service + ts window)
```

**Deliberately not modeled (YAGNI):** a `service` dimension table and a `service_edge` dependency-graph table. The RCA module builds the service graph from trace data at runtime, and `inference.service` as free text is enough for every query we have. Add a `service`/`service_edge` pair only if the dashboard later needs a persisted, editable topology — not before.

### 4.6 Example queries the schema is shaped for

```sql
-- Dashboard: latest anomaly score per service
SELECT DISTINCT ON (service) service, value, ts
FROM inference
WHERE module = 'detect' AND kind = 'anomaly_score'
ORDER BY service, ts DESC;

-- Analysis: paired breach-duration, hybrid vs tuned HPA, capacity-responsive faults only
SELECT r_hpa.workload_regime, r_hpa.fault_class,
       res_hpa.slo_breach_duration_s   AS hpa_s,
       res_hyb.slo_breach_duration_s   AS hybrid_s
FROM experiment_run r_hpa
JOIN experiment_run r_hyb   ON r_hyb.pair_id = r_hpa.pair_id AND r_hyb.policy = 'forecast_hybrid'
JOIN experiment_result res_hpa ON res_hpa.run_id = r_hpa.run_id
JOIN experiment_result res_hyb ON res_hyb.run_id = r_hyb.run_id
WHERE r_hpa.policy = 'hpa_tuned' AND r_hpa.is_negative_control = FALSE;
```

---

## 5. Complete file & folder structure

Monorepo, one directory per concern. Folders marked *(scaffolded)* exist with working code today; *(to build)* are created as their module lands (build order in §8).

```
aiops-platform/
├── ARCHITECTURE.md              concise technical map (this doc expands it)
├── TECHNICAL_ARCHITECTURE.md    this document
├── PRD.md                       product requirements (what/why)
├── README.md                    prerequisites + quickstart
├── Makefile                     up / down / deploy / load / chaos / selftest / ps
├── requirements.txt             pinned base deps; heavy extras commented per-module
├── .gitignore
│
├── cluster/                     bring up the local testbed              (scaffolded)
│   ├── kind-config.yaml          1 control-plane + 2 workers; NodePort maps
│   └── bootstrap.sh              create cluster + install kps, Sock Shop, Chaos Mesh, our kustomize
│
├── deploy/                      kustomize manifests for our components
│   ├── timescaledb/              StatefulSet + Service + Secret            (scaffolded)
│   │   └── resources.yaml
│   ├── monitoring/               kps values + Sock Shop ServiceMonitor     (scaffolded)
│   │   ├── kps-values.yaml
│   │   └── ...
│   └── platform/                 our module Deployments/CronJobs
│       ├── base/                  shared kustomize base                   (to build as modules land)
│       └── overlays/local/        kind overlay                            (to build as modules land)
│
├── aiops/                    our code — one dir per module
│   ├── common/                   shared clients + config                 (scaffolded)
│   │   ├── __init__.py
│   │   ├── config.py              env-var config (PROM_URL, TIMESCALE_DSN, SLOs, windows)
│   │   ├── prom.py                Prometheus HTTP client + PromQL helpers
│   │   └── store.py               TimescaleDB write/read + DDL (add §4.2–4.4 tables here)
│   ├── ingest/                    Module 1: OTel config + feature-window bridge   (to build)
│   ├── detect/                    Module 2: Isolation Forest + LSTM autoencoder    (to build)
│   ├── rca/                       Module 3: service-graph localization (ranking)   (to build)
│   ├── predict/                   Module 4: SLO-breach prediction at horizon H     (to build)
│   ├── forecast/                  Module 5: Prophet + seasonal-naive baseline      (to build)
│   ├── scaler/                    the contribution: forecast → replicas controller (to build)
│   ├── remediate/                 Module 6: human-approved remediation + audit log (to build)
│   ├── explain/                   Module 7: SHAP/LIME attributions                 (to build)
│   └── dashboard/                 React (Vite) UI + Express read-API              (to build)
│
├── experiment/                  the harness (contribution)               (to build)
│   ├── load/                      k6 job + traffic regimes (steady/ramp/spike/soak)
│   ├── faults/                    Chaos Mesh manifests (capacity-responsive + negative controls)
│   ├── schema.sql                 DDL for the relational experiment tables (§4.2–4.4)
│   └── analysis/                  paired-trial stats: bootstrap CIs, effect sizes
│
└── docs/                        supporting notes
```

Convention: every Python module is runnable as `python -m aiops.<module> --selftest`, which exercises its core logic offline (no cluster). The Makefile `selftest` target loops this over all modules. This is why each module dir holds its logic in an importable package, not a loose script.

---

## 6. Environment variables & configuration

### 6.1 Application config (`aiops/common/config.py`)

Read from the environment with defaults, so nothing is required to run a selftest, but you override these in the cluster overlay.

| Variable | Default | Meaning |
|---|---|---|
| `PROM_URL` | `http://monitoring-kube-prometheus-prometheus.monitoring:9090` | In-cluster Prometheus endpoint the modules read windows from. |
| `TIMESCALE_DSN` | `postgresql://aiops:aiops@timescaledb.aiops:5432/aiops` | Where inference results and experiment tables are written. |
| `SOCK_NS` | `sock-shop` | Namespace of the app under test (used to scope PromQL and scale calls). |
| `WINDOW_MIN` | `15` | Minutes of history each module pulls per inference cycle. |
| `STEP_S` | `15` | Sample step (seconds) for range queries. |
| `SLO_P95_MS` | `500` | **Placeholder** — p95 latency SLO. One of six owed predeclared decisions (§7). |
| `SLO_ERROR_RATE` | `0.02` | **Placeholder** — error-rate SLO. Also owed. |

> **These two SLO values are placeholders, not decisions.** The experiment cannot be run credibly until the SLO (and the other five items in §7) is predeclared. They default to a plausible value only so modules run; do not treat `500ms / 2%` as the chosen SLO.

### 6.2 Database credentials (`deploy/timescaledb/resources.yaml`, Secret `timescaledb`)

| Key | Value | Note |
|---|---|---|
| `POSTGRES_USER` | `aiops` | **Demo credential — local kind testbed only, not production.** |
| `POSTGRES_PASSWORD` | `aiops` | Same. Rotate + move to a real secret store before any shared deployment. |
| `POSTGRES_DB` | `aiops` | Database name; matches the DSN default above. |

### 6.3 Operational / build-time config

| Where | Variable | Meaning |
|---|---|---|
| `Makefile` | `CLUSTER` = `aiops` | kind cluster name (`make down` deletes this cluster). |
| `Makefile` | `SOCK_NS` = `sock-shop` | Namespace for Sock Shop. |
| `make load` | `REGIME` = `steady\|ramp\|spike\|soak` | Traffic regime the k6 Job runs (via `envsubst` on the job manifest). |
| `cluster/kind-config.yaml` | NodePort maps | `30080→localhost:8080` dashboard, `30300→localhost:3300` Grafana, `30090→localhost:9090` Prometheus. |
| Grafana | login | `admin` / `prom-operator` (kube-prometheus-stack default). |

### 6.4 Configuration notes before you build

- **Where the schema DDL lives.** The `inference` hypertable DDL is in `aiops/common/store.py` (applied on first write). The three relational tables from §4.2–4.4 go in `experiment/schema.sql`, applied once when the harness initializes — keep experiment DDL out of the hot write path.
- **Prometheus is the source of truth for raw metrics.** Never write raw metrics into TimescaleDB; only derived results. If a module needs history, it re-queries Prometheus.
- **Infected-period exclusion is a hard rule.** Training windows must exclude injected-fault periods (the harness records fault windows via `experiment_run.started_at/ended_at`) — this is a required audit in the baseline, not an option.
- **`normalize()` in `store.py` fails loudly** (raises `KeyError` on a missing field) by design — a malformed inference row should error, not silently write nulls.
- **`psycopg2` is imported lazily** so offline selftests need no DB driver installed; only real writes require it (`psycopg2-binary` in `requirements.txt`).

---

## 7. Predeclared decisions the experiment is blocked on

Modules 1–7 can be built now. The **scaler + harness cannot produce a credible result** until these six are predeclared (mirrors PRD §9 / survey §10 — recorded here because they are configuration the build must eventually pin down):

1. **SLO** — p95 latency + error-rate thresholds + the evaluation window (fills `SLO_P95_MS`, `SLO_ERROR_RATE`).
2. **Prediction horizon *H*** — fills `experiment_run.horizon_s`.
3. **Workload generator + the four regimes** — steady / ramp / spike / soak (the `REGIME` values).
4. **Scaling-policy parameters** — forecast→replica mapping, cooldown, min/max replica bounds, and the predeclared **HPA tuning procedure** for the baseline.
5. **Fault taxonomy** — which faults are capacity-responsive vs negative controls (fills `fault_class`, `is_negative_control`).
6. **Severity** — breach duration vs affected-request count as the primary severity operationalization.

Until these are set, treat the SLO env defaults as placeholders and the scaler as un-runnable for scoring.

---

## 8. Deployment topology & how to run

Single local **kind** cluster, everything in-cluster. Bring-up sequence (`cluster/bootstrap.sh`, invoked by `make up`):

1. Create the kind cluster (1 control-plane + 2 workers) from `cluster/kind-config.yaml`.
2. Add helm repos (`prometheus-community`, `chaos-mesh`).
3. Install **kube-prometheus-stack** into namespace `monitoring` (values: `deploy/monitoring/kps-values.yaml`).
4. Install **Sock Shop** (upstream `complete-demo.yaml`) into namespace `sock-shop`.
5. Install **Chaos Mesh** into `chaos-mesh` (containerd runtime, socket `/run/containerd/containerd.sock`).
6. Apply our components: `kubectl apply -k` over `deploy/timescaledb`, `deploy/monitoring`, `deploy/platform/overlays/local`.

Namespaces: `monitoring` (Prometheus/Grafana), `sock-shop` (app), `chaos-mesh` (faults), `aiops` (TimescaleDB + our modules).

Day-to-day (`Makefile`):

```
make up        # create cluster + install everything above
make ps        # what's running
make load REGIME=spike   # drive traffic
make chaos     # list/apply fault manifests
make selftest  # offline logic check for every module (no cluster needed)
make down      # delete the kind cluster
```

Reach the UIs at `localhost:8080` (dashboard), `localhost:3300` (Grafana), `localhost:9090` (Prometheus).

**Build order** (from `ARCHITECTURE.md`): cluster/testbed → TimescaleDB + `common` + ingestion → detect/rca/predict/forecast → scaler + harness (after the six decisions) → remediation/explain + dashboard.

---

## 9. Scaling & future considerations (honest)

At today's scope (one laptop, one Sock Shop, ≥20 paired trials) nothing here is a bottleneck. If this were ever pushed further — explicitly **out of v1 scope**, noted only so the design doesn't block it:

- **Timescale compression + retention + continuous aggregates** on `inference` — turn on when trial history grows; the hypertable is already shaped for it. No schema change needed.
- **Connection pooling** (PgBouncer) in front of TimescaleDB once many modules write concurrently.
- **Split read/write** — the dashboard's Express API reads; heavy analysis could run off a replica.
- **Auth + ingress** — prerequisite for any shared/multi-user deployment (see §10).
- **A `service` / `service_edge` dimension** — only if a persisted, editable topology is ever needed (see §4.5).

None of these are built now, on purpose. The hybrid schema is chosen precisely so these are *additive* later, not rewrites.

---

## 10. Security notes (flagged, not fixed in v1)

- **The dashboard and read-API are unauthenticated and localhost-only** via NodePort (`30080→8080`). Acceptable for a single-user local research cluster; **do not expose the NodePort beyond localhost.** Auth is a prerequisite for any shared deployment (PRD §8).
- **TimescaleDB uses demo credentials** (`aiops`/`aiops`/`aiops`) in a plain Kubernetes Secret. Fine for a throwaway kind cluster; rotate and move to a real secret manager before anything shared.
- **The scaler and remediation approver hold cluster-scale permissions** (they call the k8s scale API). In v1 remediation is human-approved only — no autonomous action. The approval log (§4.4) records that a human approved; per the guardrails this documents the workflow, it does **not** prove remediation is "safe".

---

*This TAD describes the platform as scaffolded and as scoped for the current capstone cycle. It conforms to `LITERATURE_SURVEY_DECISION_REPORT.md`; where a research claim and this document ever conflict, the survey governs.*
