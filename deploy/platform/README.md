# `deploy/platform` — manifest convention

Kustomize tree for our own components (everything the bootstrap installs *after*
Prometheus, Sock Shop, and Chaos Mesh). Two layers:

- `base/` — one self-contained manifest **file per module**, registered in
  `base/kustomization.yaml`. The existing ingest manifest is `base/ingest-cronjob.yaml`;
  future modules use `base/<module>.yaml` by default.
- `overlays/local/` — the kind overlay for local-only patches (for example,
  `imagePullPolicy` or resource overrides). `make deploy` applies this overlay.

## The rule: one module = one file, and only Dev 1 edits the shared list

Each module owner creates exactly one self-contained file, named for the module
(for example, `base/ingest-cronjob.yaml`), holding *all* of that module's k8s objects
(Deployment/CronJob + Service + ServiceAccount + RBAC, as needed):

```
base/
  kustomization.yaml     # Dev 1 owns this list
  ingest-cronjob.yaml    # Dev 1
  detect.yaml            # Dev 2
  rca.yaml               # Dev 2
  predict.yaml           # Sanmith
  forecast.yaml          # Sanmith
  scaler.yaml            # Sanmith
  remediate.yaml         # Dev 4
  explain.yaml           # Dev 2
  dashboard.yaml         # Dev 4
```

Adding a module is: the module owner drops the module's single manifest (for example,
`base/<module>.yaml`); Dev 1 registers it by adding its resource entry to `resources:`
in `base/kustomization.yaml`. Module owners must not edit either shared Kustomization
file — `base/kustomization.yaml` or `overlays/local/kustomization.yaml`. Because every
module is a distinct file, module owners do not compete over shared manifest lines.

`base/kustomization.yaml` sets `namespace: aiops`, so manifests don't repeat it.
Its `resources:` list currently registers `base/ingest-cronjob.yaml`, the first real module
manifest. The current ingest manifest is local-testbed-only, so it sets
`imagePullPolicy: IfNotPresent` and its resource requests directly in base; if a
non-local overlay is added, those local-only settings should move to `overlays/local`.
Registration is not live validation: image build/load, scheduling, Prometheus
reachability, and downstream frame delivery remain unverified.

Keep secrets out of these files (the local TimescaleDB creds live in
`deploy/timescaledb`); nothing here adds auth — the dashboard is localhost-only via
NodePort by design (see `SECURITY_AND_ACCESS.md`).

## Local image workflow

The shared Python image is built from the root `Dockerfile` and loaded into the existing
kind cluster:

```bash
make platform-image
```

The target runs `cluster/platform-image.sh`, the single build/load workflow used by both
the Make target and `cluster/bootstrap.sh`:

```bash
docker build -t aiops:dev .
kind load docker-image aiops:dev --name aiops
```

`make deploy` applies manifests only; it does **not** build or load images. Run
`make platform-image` after code changes, or let `make up` build/load the image before it
applies the platform overlay. The CronJob uses `image: aiops:dev` and explicitly sets
`imagePullPolicy: IfNotPresent`. `.dockerignore` excludes `.venv`, `.git`, caches, and
`store_diff.txt` from the build context.

## Provisional ingest policy

`base/ingest-cronjob.yaml` runs `python -m aiops.ingest` every five minutes
(`*/5 * * * *`) with `concurrencyPolicy: Forbid` and `backoffLimit: 1`. These are
**provisional local-testbed defaults**, not production guarantees; re-evaluate them before
using the testbed for long-running experiments. The container requests `100m` CPU and
`256Mi` memory and sets no limit, matching the repository's requests-only local-testbed
convention (for example, Prometheus in `deploy/monitoring/kps-values.yaml`). The request
keeps scheduling light. No container memory limit is set, so Kubernetes will not
terminate the container for exceeding a limit; node-level OOM or eviction can still
occur.

The live ingestion path prints the Contract-C frame to stdout. There is no durable frame
store, queue, API, or verified downstream ML-consumer delivery in this ticket. CronJob
logs are the only current output surface. Downstream delivery remains unverified.

## Open question: `hpa-*.yaml`

The earlier tree example used `hpa-*.yaml` (tuned-HPA baseline) alongside the
one-file-per-module rule, which does not identify a single file for Dev 1 to register.
`PARALLEL_DEV_PLAN.md` assigns the tuned-HPA baseline to Sanmith (D3-004), so ownership
is unchanged; the file layout is the unresolved part. Whether the baseline is one file
or several, and the exact path(s) Dev 1 should register, must be clarified before it is
added to `resources:`.

## Status

The manifest convention is implemented. `base/ingest-cronjob.yaml` is registered, so the
base list is no longer empty. Registration is not live validation: image build/load,
CronJob scheduling, Prometheus reachability, and downstream frame delivery remain
unverified in this environment. No live result is claimed by this document.
