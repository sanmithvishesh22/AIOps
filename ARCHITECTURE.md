# AIOps Platform — Architecture

Fresh build. Local Kubernetes (kind), full seven-module platform, with the
platform treated as the **instrument** for one controlled experiment:

> When does forecast-assisted hybrid Kubernetes scaling beat a *tuned* reactive
> HPA on SLO-breach duration, and under which fault classes does it fail?

Everything below exists to make that experiment runnable and its result
credible. The platform is engineering; the experiment is the contribution.

## Positioning guardrails (do not violate)

These claims were refuted by our own literature survey and must never reappear
in code comments, dashboards, or docs:

- "first integrated AIOps platform" / "7-module integration is novel"
- "forecast accuracy proves reliability improvement"
- "root-cause ranking proves causality"
- "Sock Shop generalizes to production"

Negative-control faults (network, code, dependency, memory-leak — where scaling
*cannot* help) are mandatory and reported, never buried.

## Laziness principle (how we keep this small)

Reuse the platform and off-the-shelf charts; write custom code only for the ML
inference and the scaling controller.

| Need | Use (not build) |
|------|-----------------|
| App under test | Sock Shop upstream manifests |
| Metrics + TSDB | kube-prometheus-stack (Prometheus, Grafana, node/kube metrics) |
| Fault injection | Chaos Mesh |
| Reactive scaling baseline | Kubernetes **native HPA** (v2, tuned) |
| Load generation | k6 (or Locust) as a Job |
| Container-to-replica control | Kubernetes API (`apps/v1` Deployment scale) |

Custom code is only: the ingest bridge, the five ML modules, the
forecast-assisted scaler, the remediation approver, explainability, and the
dashboard.

## Stack decisions (defaults — say if you want them changed)

- **ML / services:** Python 3.11, FastAPI for anything with an endpoint,
  plain scripts/CronJobs for batch inference. scikit-learn, PyTorch (LSTM AE),
  Prophet, SHAP.
- **Analytics store:** Prometheus is the *live* metrics source of truth
  (k8s-native, already scraping Sock Shop). ML modules read recent windows from
  Prometheus via its HTTP API and write their **inference results**
  (anomaly flags, RCA ranks, forecasts, predictions) to **TimescaleDB** — one
  Postgres/Timescale StatefulSet — so results are queryable and joinable for the
  dashboard and the experiment analysis. Raw metrics stay in Prometheus; only
  derived signals land in Timescale. This keeps ingestion thin.
- **Dashboard:** React (Vite) + a small Express read-API over TimescaleDB.
- **Packaging:** each module is its own container + a kustomize base; overlays
  for `local` (kind) now, room for others later.
- **Repo:** monorepo, one directory per concern.

## Data flow

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

## Modules

1. **Ingestion / observability** (`aiops/ingest`) — OTel Collector config +
   a bridge that pulls per-service windows (p95 latency, error rate, CPU, mem,
   replica count, RPS) from Prometheus and shapes features for the ML modules.
2. **Anomaly detection** (`aiops/detect`) — Isolation Forest (fast,
   per-service baseline) + an LSTM autoencoder (temporal). Writes flags + scores.
3. **Root-cause localization** (`aiops/rca`) — ranks services by severity and
   a simple service-graph propagation. Names the likely culprit. (Ranking, not
   causal proof — see guardrails.)
4. **Failure prediction** (`aiops/predict`) — predicts near-term SLO breach
   (occurrence + a severity proxy) at horizon *H* from the feature windows.
5. **Capacity forecasting** (`aiops/forecast`) — Prophet/LSTM forecast of
   per-service load/latency; feeds the scaler.
6. **Human-approved remediation** (`aiops/remediate`) — proposes an action
   (scale, restart, rollout), waits for explicit approval, applies via k8s API,
   logs the decision.
7. **Explainability** (`aiops/explain`) — SHAP/LIME over the detector and
   predictor so a flag/prediction comes with feature attributions.

Plus the **scaler** (`aiops/scaler`, the contribution) and the
**experiment harness** (`experiment/`).

## How the experiment uses the platform

- The **forecast** (module 5) drives the **scaler**: forecast → desired
  replicas, with a predeclared cooldown and replica bounds.
- The **tuned HPA** is the baseline, configured by a predeclared procedure.
- The **experiment harness** runs matched trials: for each traffic regime ×
  fault class, run once under HPA and once under the forecast-assisted scaler,
  inject the same fault via Chaos Mesh, and log **SLO-breach duration** and
  affected-request count from Prometheus.
- **Six decisions still owed** before the scaler/harness are real (tracked as a
  blocker on that task): predeclared SLO, horizon *H*, workload generator + four
  traffic regimes, scaling-policy params (forecast→replica map, cooldown,
  bounds, HPA tuning procedure), fault taxonomy (capacity-responsive vs
  negative-control), and severity definition. Modules 1–7 do not need these and
  can be built first.

## Repo layout

```
aiops-platform/
  ARCHITECTURE.md          this file
  README.md                quickstart
  Makefile                 one-liners: up / down / deploy / load / chaos
  cluster/
    kind-config.yaml       local cluster (port maps for dashboard/grafana)
    bootstrap.sh           create cluster + install charts (Sock Shop, kps, Chaos Mesh)
  deploy/                  kustomize bases + local overlay for our components
    timescaledb/
    monitoring/            ServiceMonitors for Sock Shop
    platform/              our module Deployments/CronJobs
  aiops/                our code (one dir per module)
    common/                shared: prom client, timescale client, config
    ingest/ detect/ rca/ predict/ forecast/ scaler/ remediate/ explain/
    dashboard/             React + Express
  experiment/              harness: load regimes, fault schedules, analysis
  docs/
```

## Build order

1. Cluster bootstrap + testbed (kind, Sock Shop, Prometheus, Chaos Mesh) — task #10
2. TimescaleDB + `aiops/common` clients + Module 1 ingestion — task #11
3. Modules 2–5 (detect, rca, predict, forecast) — task #12
4. Scaler + experiment harness (after the six decisions) — task #13
5. Modules 6–7 + dashboard — task #14

## Constraint on this environment

This assistant session has **no shell** and cannot run kind/kubectl/docker. All
cluster/testbed steps run on your Mac. Every module ships a **self-check**
(`python -m module --selftest` or a `test_*.py`) that runs without a cluster, so
logic is verifiable offline; cluster wiring is verified by you via the Makefile.
