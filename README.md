# AIOps Platform

AI-driven anomaly detection and predictive maintenance for microservices, built
as the **instrument** for one controlled experiment: *does forecast-assisted
hybrid Kubernetes scaling reduce SLO-breach duration versus a tuned reactive
HPA, and where does it fail?*

Read [ARCHITECTURE.md](ARCHITECTURE.md) first — it explains the seven modules,
the stack choices, and the positioning guardrails.

## Flows (parallel development)

Work runs on four parallel lanes, one Git branch each. Every lane builds on the
same frozen foundation (`aiops/common/*` + the Contracts) and integrates via PRs
into `main`, gated by `make selftest` (QA-001). Pick your lane, check out its
branch, and follow its onboarding doc — each lists only the docs that lane needs:

| Branch | Lane | Start here |
|--------|------|------------|
| `dev1-foundation` | contracts · testbed · ingestion | [flows/dev1-foundation.md](flows/dev1-foundation.md) |
| `dev2-diagnosis` | detect · rca · explain | [flows/dev2-diagnosis.md](flows/dev2-diagnosis.md) |
| `dev3-experiment` | predict · forecast · scaler + experiment (Sanmith) | [flows/dev3-experiment.md](flows/dev3-experiment.md) |
| `dev4-surface` | remediation · dashboard · evaluation | [flows/dev4-surface.md](flows/dev4-surface.md) |

```bash
git clone https://github.com/sanmithvishesh22/AIOps.git
cd AIOps
git checkout dev2-diagnosis        # your lane's branch, then open its flows/ doc
```

## Prerequisites (on your machine)

- Docker, [kind](https://kind.sigs.k8s.io/), `kubectl`, `helm`
- Python 3.11+ (`pip install -r requirements.txt`)
- Node 20+ (for the dashboard, later)

## Quickstart

```bash
make up        # create the kind cluster + install Sock Shop, Prometheus, Chaos Mesh, TimescaleDB
make ps        # see what's running
make load      # generate traffic (REGIME=steady|ramp|spike|soak)
make selftest  # run every module's offline logic check (no cluster needed)
make down      # tear the cluster down
```

Endpoints once `make up` finishes:

| Service | URL | Login |
|---------|-----|-------|
| Dashboard | http://localhost:8080 | — |
| Grafana | http://localhost:3300 | admin / prom-operator |
| Prometheus | http://localhost:9090 | — |

## Layout

See ARCHITECTURE.md → "Repo layout". In short: `cluster/` brings up the
testbed, `deploy/` holds the manifests, `aiops/` holds our module code
(`common/` is the shared Prometheus-read / TimescaleDB-write base), and
`experiment/` holds the load regimes, fault schedules, and analysis.

## Status

Foundation in place: cluster bootstrap, TimescaleDB, monitoring wiring, and
`aiops/common` (with offline self-checks). Modules are being built in the
order listed in ARCHITECTURE.md → "Build order".

> This repo is authored without a live cluster in the assistant environment, so
> every module carries an offline `--selftest`. Cluster wiring is verified by
> running `make up` on your machine.
