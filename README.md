# AIOps Platform

AI-driven anomaly detection and predictive maintenance for microservices, built
as the **instrument** for one controlled experiment: *does forecast-assisted
hybrid Kubernetes scaling reduce SLO-breach duration versus a tuned reactive
HPA, and where does it fail?*

Read [ARCHITECTURE.md](ARCHITECTURE.md) first — it explains the seven modules,
the stack choices, and the positioning guardrails.

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
