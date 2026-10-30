# Chaos Mesh namespace scope (SEC-001, Dev 1 infra half)

This directory pins Chaos Mesh to the released chart **2.8.7** and runs it in
namespace-scoped mode with `sock-shop` (`SOCK_NS`) as the only target namespace.
It is the infrastructure half of SEC-001. The creator-side half — refusing
Chaos custom resources created by an unauthorized identity or aimed at another
namespace — is **not implemented on this branch**; see
[Remaining gap](#remaining-gap-creator-side-authorization).

> Status: static configuration verified against the exact released chart.
> No live cluster validation was performed (Helm, kubectl, kind and Docker are
> not available in the development environment).

## Pinned chart and evidence

| Item | Value |
|---|---|
| Chart | `chaos-mesh/chaos-mesh` |
| Version | `2.8.7` |
| Source | <https://charts.chaos-mesh.org/chaos-mesh-2.8.7.tgz> |
| SHA-256 | `c963e0f4ed2e30c1c7e236477f1c31fcf988b171991801bbe392546948436d38` |
| `Chart.yaml` | `version: 2.8.7`, `appVersion: 2.8.7`, no `kubeVersion` constraint |
| Verified | 2026-10-30 |

The digest above matches the `digest` field of the 2.8.7 entry in the official
Helm index (`https://charts.chaos-mesh.org/index.yaml`) and the SHA-256 of the
downloaded `.tgz`. Values and templates cited below come from that extracted
release artifact, not from the project's `master` branch.

**This digest is evidence from the inspected artifact, not runtime digest
enforcement.** `cluster/bootstrap.sh` pins `--version 2.8.7` but does not verify
the chart digest at install time, and `helm repo add ... || true` can keep an
existing repository entry. If provenance matters on a given machine, run
`helm repo list`, `helm pull chaos-mesh/chaos-mesh --version 2.8.7`, and compare
the tarball SHA-256 before installing.

### Kubernetes compatibility

The repository does not pin a Kubernetes version: `cluster/kind-config.yaml`
sets no `kindest/node` image, so `kind create cluster` uses the locally
installed kind default. Chart 2.8.7 declares no `kubeVersion` constraint. Its
CRDs use `apiextensions.k8s.io/v1` (Kubernetes >= 1.16). Because neither side
pins a version, compatibility can only be confirmed by rendering/installing on
the actual testbed; that was not possible here.

## Values applied

`cluster/bootstrap.sh` installs the chart with
`--values cluster/chaos-mesh-values.yaml` and keeps the existing release name
(`chaos-mesh`), release namespace (`chaos-mesh`), containerd runtime and
containerd socket path. No Prometheus-related values were added or changed.

| Value | Set to | Verified semantics in 2.8.7 |
|---|---|---|
| `clusterScoped` | `false` | Namespaced mode. The controller and dashboard "target namespace" roles are bound with `RoleBinding`s in `controllerManager.targetNamespace` instead of `ClusterRoleBinding`s (`templates/controller-manager-rbac.yaml:161-181`, `templates/chaos-dashboard-rbac.yaml:106-126`). |
| `controllerManager.targetNamespace` | `sock-shop` | The chart documents that this "only works with clusterScoped is false (namespace scoped mode)". It selects the namespace of the target `RoleBinding` (`controller-manager-rbac.yaml:169`) and is exported to the controller and dashboard as `TARGET_NAMESPACE`. |
| `controllerManager.serviceAccountCreate` | `true` | The chart creates the controller ServiceAccount (`controller-manager-rbac.yaml:15-21`). Setting it false would make the deployment use a pre-existing account with unknown permissions. |
| `rbac.create` | `true` | The controller/dashboard RBAC templates are gated by this value (`controller-manager-rbac.yaml:15`, `chaos-dashboard-rbac.yaml:15`). Setting it false would skip the target-namespace `RoleBinding`s. |
| `dnsServer.create` | `false` | All four DNS templates (`dns-configmap.yaml`, `dns-deployment.yaml`, `dns-rbac.yaml`, `dns-service.yaml`) are gated by this value. Disabling it removes the DNS server Deployment, Service, ConfigMap, ServiceAccount and RBAC. |
| `controllerManager.enableFilterNamespace` | chart default `false` | If enabled, only pods in namespaces annotated `chaos-mesh.org/inject: enabled` are eligible for injection. This is a pod-injection filter, **not** a namespace allowlist, and it is not a substitute for scoping. |

### Why DNSChaos is disabled

The ratified experiment taxonomy (`experiment/DECISIONS.md`, Decision 5) does
not include `DNSChaos`, and a repository-wide search found no `DNSChaos`
resources, creation code, supported-experiment references, or DNS-specific
assumptions. Enabling the chart's DNS server therefore adds permissions and a
Deployment that no supported workflow uses. In 2.8.7 the DNS RBAC includes an
unconditional cluster-level read of namespaces, services, endpoints and pods
(`templates/dns-rbac.yaml:47-61`), so disabling the component removes that
surface entirely.

If DNSChaos is ever added to the taxonomy, re-enable it with
`dnsServer.create: true` and set `dnsServer.targetNamespace: sock-shop`. That
key is read by `templates/dns-rbac.yaml:123` but is absent from the chart's
`values.yaml`/`values.schema.json`; it works only because the schema does not
set `additionalProperties: false`. Treat it as an undocumented compatibility
shim and re-verify it on every chart upgrade. The supported `create` switch is
declared in `values.yaml:436` and in the schema's `dnsServer.create` boolean.

## Offline guard: what it does and does not prove

`make security-test` (or `python cluster/chaos_scope_offline_test.py`) runs a
**strict offline configuration regression guard**. It is not a Helm renderer, a
YAML implementation, or a live security proof. It accepts only the explicitly
approved bootstrap invocation and the exact approved values-file structure;
ambiguous or unsupported syntax fails closed.

It accepts the current canonical command plus safe equivalent flag forms such as
`--version=2.8.7`, `--namespace=chaos-mesh`, `--values=...`, `-f ...`,
`-f=...`, `-f<path>`, combined `--set a=b,c=d`, and `--flag=true` for the
approved boolean flags. It rejects:

- extra `--values`/`-f` files, duplicate values files, and a values path other
  than `cluster/chaos-mesh-values.yaml`;
- `--set-json`, `--set-file`, `--set-literal`, `--set-string`,
  `--post-renderer`, `--post-renderer-args`, `--reuse-values`,
  `--reset-values`, unknown flags, and `--set` assignments other than the two
  approved runtime/socket settings;
- a second `helm upgrade`/`install`/`uninstall`/`delete` targeting the
  `chaos-mesh` release or namespace, and a wrapped (`eval`/`bash -c`-style)
  `helm upgrade`;
- quoted/duplicate keys, flow mappings/sequences, anchors, aliases, tags, block
  scalars, tabs, inline comments, odd indentation, deeper nesting, and unknown
  keys in the values file;
- `clusterScoped` not boolean false, `controllerManager.targetNamespace` not
  equal to the project `SOCK_NS`, `controllerManager.serviceAccountCreate` not
  true, `rbac.create` not true, or `dnsServer.create` not false;
- `SOCK_NS` disagreement between `docs/CONTRACTS.md` (Contract G),
  `aiops/common/config.py`, `Makefile`, and the values file.

The test asserts its own case counts so cases cannot silently disappear:
**1 positive, 12 safe variants, and 100 negative cases** (91 values/bootstrap
mutations plus 9 namespace-source mutations). Each negative case must fail for
the expected reason, not merely fail somewhere.

**What it cannot prove:** Helm's actual merge/render semantics, the chart
digest, what a live cluster runs, whether an operator bypasses the script, or
whether a sourced/wrapped script runs another Helm command. It is a repository
regression gate, not a security boundary by itself.

## What this configuration enforces

- Chaos Mesh CRDs are `scope: Namespaced` (`crds/chaos-mesh.org_*.yaml`), so
  Chaos custom resources are namespace objects.
- The controller's and dashboard's target-namespace permissions are bound in
  `sock-shop`, not cluster-wide. Chaos resources in other namespaces are not
  reconciled by the controller.
- The DNS server and its target/cluster-level RBAC are not rendered because
  `dnsServer.create` is false.
- The release name, release namespace, containerd runtime/socket and bootstrap
  idempotency (`helm upgrade --install`) are unchanged.
- The offline guard rejects the canonical bypasses above and namespace drift.

## What this configuration does **not** enforce

### Remaining gap: creator-side authorization

The experiment harness/runner that creates Chaos custom resources is **not in
this branch** (only `experiment/schema*` exists), so its ServiceAccount and
permissions cannot be inspected or constrained here. Consequently:

- An identity with cluster-wide permission to create `chaos-mesh.org` resources
  (for example a cluster-admin running `kubectl apply -f fault.yaml`) can still
  create a Chaos resource in any namespace. Namespaced mode means the
  controller will not act on it, but it is **not refused at admission**.
- The SEC-001 invariant "experiments targeting any other namespace must be
  refused" therefore needs a second layer: least-privilege creator RBAC plus an
  admission restriction (for example a `ValidatingAdmissionPolicy` or a
  validating webhook) tied to the actual harness identity. That layer is
  deliberately not invented here; it belongs with the harness owner (Sanmith) and must be
  added once the harness lands. Dev 4 owns least-privilege ServiceAccounts for the scaler
  and remediation components; creator-side admission enforcement must not be assigned to Dev 4.
  Do not treat this chart configuration as complete isolation.

### Residual cluster-wide surface in chart 2.8.7

Namespaced mode does not make every Chaos Mesh component namespaced:

- The controller keeps a cluster-level `ClusterRole`/`ClusterRoleBinding` that
  can `get/list/watch` nodes, persistent volumes and persistent volume claims,
  and `create` `subjectaccessreviews` (`templates/controller-manager-rbac.yaml`).
  Its control-plane `Role` in the `chaos-mesh` namespace can also read
  services/secrets and create `pods/exec`.
- The dashboard keeps a cluster-level `ClusterRole`/`ClusterRoleBinding` for
  namespace reads and `subjectaccessreviews`, plus a target-namespace
  `RoleBinding` in `sock-shop` (`templates/chaos-dashboard-rbac.yaml`). The
  dashboard is a second creator identity; it cannot target other namespaces.
- The validating/mutating webhook configurations are cluster-wide objects and
  have no `namespaceSelector`; they validate Chaos resources but do not restrict
  which namespace a resource may target.
- `chaos-daemon` is a privileged `DaemonSet` on every node with `hostPID`,
  privileged containers, and `hostPath` mounts including the container runtime
  socket (`/run/containerd/containerd.sock`), `/sys` and `/lib/modules`
  (`templates/chaos-daemon-daemonset.yaml`). It is a node-level agent by design;
  namespace scoping limits what the controller tells it to act on, not the
  agent's host access.
- CRDs and webhook configurations are necessarily cluster-scoped installation
  objects.
- The DNS server's cluster-level read is not present because the component is
  disabled; re-enabling it adds that surface back.

These are properties of the upstream chart, not of our values file. They are
documented so the remaining risk is not mistaken for a complete boundary.

## Optional hardening (not enabled)

- `controllerManager.enableFilterNamespace: true` plus the namespace annotation
  `chaos-mesh.org/inject: enabled` on `sock-shop` would restrict which pods may
  be injected. It is opt-in per namespace and does not replace target-namespace
  scoping or creator-side admission, so it is left off to avoid changing
  namespace manifests in this change.
- Creator RBAC and admission enforcement are the missing half described above.
- If the dashboard is not needed for the experiment workflow, disabling it would
  remove a second creator identity and its cluster-level reads. That is a
  product decision, not made here.

## Upgrade procedure

1. Read the new chart entry from `https://charts.chaos-mesh.org/index.yaml` and
   record its `version` and `digest`.
2. Download the exact `.tgz`, verify its SHA-256 against the index digest, and
   extract it. Do not use `master` values as evidence.
3. Diff `values.yaml`, `values.schema.json`, the CRD scopes, and the
   controller/dashboard/DNS RBAC templates against 2.8.7.
4. Update `--version` in `cluster/bootstrap.sh`, this file, and the constants in
   `cluster/chaos_scope_offline_test.py`.
5. Run `make security-test` (or `python cluster/chaos_scope_offline_test.py`).
6. When Helm is available, render and inspect before deploying:

   ```bash
   helm template chaos-mesh chaos-mesh/chaos-mesh --version <new-version> \
     --namespace chaos-mesh --values cluster/chaos-mesh-values.yaml \
     --set chaosDaemon.runtime=containerd \
     --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
     > /tmp/chaos-mesh-rendered.yaml
   ```

   Confirm `RoleBinding` (not `ClusterRoleBinding`) for
   `chaos-controller-manager-target-namespace` and
   `chaos-dashboard-target-namespace`, both in `sock-shop`; confirm no
   `chaos-dns-server-*` objects are rendered.
7. Install/upgrade on the testbed, then perform these manual post-upgrade
   checks:

   ```bash
   # Old cluster-wide target bindings must not remain.
   kubectl get clusterrolebinding | grep chaos-mesh
   kubectl get rolebinding -n sock-shop | grep chaos-mesh

   # DNS objects should be absent while dnsServer.create is false.
   kubectl get deployment,service,configmap,serviceaccount -n chaos-mesh | grep dns

   # Effective permissions of the two creator identities.
   kubectl auth can-i --list --as=system:serviceaccount:chaos-mesh:chaos-controller-manager
   kubectl auth can-i --list --as=system:serviceaccount:chaos-mesh:chaos-dashboard
   kubectl auth can-i create chaosengines.chaos-mesh.org -n default \
     --as=system:serviceaccount:chaos-mesh:chaos-controller-manager
   ```

   The last command should be denied for a non-`sock-shop` namespace. If old
   `chaos-controller-manager-target-namespace`,
   `chaos-dashboard-target-namespace` or `chaos-dns-server-*`
   `ClusterRoleBinding`s remain from a previous `clusterScoped: true` install,
   inspect them and remove only after confirming they are stale.
8. CRD caveat: Helm does not upgrade CRDs under `crds/` on `helm upgrade`; it
   only installs them on first install. Apply the new chart's CRDs manually (or
   reinstall) and verify with `kubectl get crd | grep chaos-mesh.org`.
9. `--atomic` is not used; a failed upgrade can leave a partially applied
   release. Re-run `helm status chaos-mesh -n chaos-mesh` and the checks above
   before trusting the result.

## Validation performed

- `python cluster/chaos_scope_offline_test.py` — **passed** on 2026-10-30:
  1 positive case, 12 safe flag variants, and 100 negative cases (91
  values/bootstrap mutations plus 9 namespace-source mutations). The guard
  checks the pinned chart version, the exact values file and its single use,
  `clusterScoped: false`, `SOCK_NS` agreement across Contract G/config/Makefile/
  values, `rbac.create: true`, `controllerManager.serviceAccountCreate: true`,
  `dnsServer.create: false`, preserved runtime/socket/release namespace, and
  rejects the extra-values/`--set-*`/`--post-renderer`/`--reuse-values` and
  duplicate/flow/anchor/tag YAML bypasses. It is a static repository guard, not
  a cluster test.
- `python experiment/schema_offline_test.py` — **passed**.
- `git diff --check` — **clean**.
- `helm lint` / `helm template` / rendered-RBAC inspection — **not run**
  (Helm is not installed).
- Live cluster scenarios (authorized `sock-shop` experiment accepted,
  other-namespace experiment rejected, unauthorized identity blocked, cleanup
  works) — **not executed** (no cluster, kubectl, kind or Docker).
