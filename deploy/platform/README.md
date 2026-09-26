# `deploy/platform` — manifest convention

Kustomize tree for our own components (everything the bootstrap installs *after*
Prometheus, Sock Shop, and Chaos Mesh). Two layers:

- `base/` — one self-contained manifest **file per module**, listed in `base/kustomization.yaml`.
- `overlays/local/` — the kind overlay; local-only tweaks (e.g. `imagePullPolicy: IfNotPresent`
  for images you `kind load`, small resource requests). `make deploy` applies this overlay.

## The rule: one module = one file, zero edits to shared lists by other devs

Each module owns exactly one manifest, named after the module, holding *all* of its
k8s objects (Deployment/CronJob + Service + ServiceAccount + RBAC, as needed):

```
base/
  kustomization.yaml     # Dev 1 owns this list
  ingest-cronjob.yaml    # Dev 1
  detect.yaml            # Dev 2
  rca.yaml               # Dev 2
  predict.yaml           # Dev 3
  forecast.yaml          # Dev 3
  scaler.yaml            # Dev 3
  hpa-*.yaml             # Dev 3 (tuned-HPA baseline)
  remediate.yaml         # Dev 4
  explain.yaml           # Dev 2
  dashboard.yaml         # Dev 4
```

Adding a module is: drop `base/<module>.yaml`, add that one line to `resources:` in
`base/kustomization.yaml`. Because every module is a distinct file, two devs adding
modules never touch the same lines — the only shared file is the `resources:` list, and
appending to it is conflict-free in practice.

`base/kustomization.yaml` sets `namespace: aiops`, so manifests don't repeat it.
Keep secrets out of these files (the local TimescaleDB creds live in
`deploy/timescaledb`); nothing here adds auth — the dashboard is localhost-only via
NodePort by design (see `SECURITY_AND_ACCESS.md`).
