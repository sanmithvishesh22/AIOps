#!/usr/bin/env bash
# Bring up the whole local testbed on kind. Idempotent-ish: safe to re-run.
# Requires: docker, kind, kubectl, helm. Runs on your Mac (not in the assistant).
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=aiops

echo "==> [1/6] kind cluster"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --config cluster/kind-config.yaml
kubectl cluster-info --context "kind-$CLUSTER" >/dev/null

echo "==> [2/6] helm repos"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
helm repo update >/dev/null

echo "==> [3/6] kube-prometheus-stack (Prometheus + Grafana)"
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --values deploy/monitoring/kps-values.yaml --wait --timeout 10m

echo "==> [4/6] Sock Shop"
kubectl apply -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml
# carts-db/orders-db ship as unpinned `mongo`; modern mongo refuses to start on the
# Docker-Desktop VM kernel (>=6.19, MongoDB SERVER-121912). Pin to 4.4 — pre-guard,
# arm64-native, and this test data is ephemeral so mongo durability is irrelevant.
kubectl -n sock-shop set image deploy/carts-db  "*=mongo:4.4"
kubectl -n sock-shop set image deploy/orders-db "*=mongo:4.4"
# catalogue-db (seeded MySQL) and the rabbitmq container ship with memory limits too
# low for this setup — both OOMKill (exit 137) in a restart loop. 512Mi wasn't enough
# for either; give them 1Gi. These are ops knobs, not §9 research constants.
kubectl -n sock-shop set resources deploy/catalogue-db --limits=memory=1Gi --requests=memory=512Mi
kubectl -n sock-shop set resources deploy/rabbitmq -c rabbitmq --limits=memory=1Gi --requests=memory=512Mi
# rabbitmq 3.6.8's Erlang VM spawns one scheduler per visible CPU (10 here) and
# preallocates a big heap at startup — OOMs even at 1Gi. Cap schedulers to shrink its
# footprint directly; more effective (and lighter on the node) than raising the limit.
kubectl -n sock-shop set env deploy/rabbitmq -c rabbitmq RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS="+S 2:2"
kubectl -n sock-shop rollout status deploy/front-end --timeout=5m || true

echo "==> [5/6] Chaos Mesh"
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock --wait --timeout 10m

echo "==> [6/6] our components (TimescaleDB + platform)"
kubectl apply -k deploy/timescaledb
kubectl apply -k deploy/monitoring        # ServiceMonitors for Sock Shop
# platform overlay is empty until modules land — apply only if it renders objects
# (kubectl treats an empty `apply -k` as an error, not a no-op)
manifest="$(kubectl kustomize deploy/platform/overlays/local)"
if [ -n "$manifest" ]; then echo "$manifest" | kubectl apply -f -
else echo "   (no platform module manifests yet — skipping)"; fi

cat <<'EOF'

Testbed up. Reach it at:
  Dashboard   http://localhost:8080
  Grafana     http://localhost:3300   (admin / prom-operator)
  Prometheus  http://localhost:9090

Next:  make load      # generate traffic
       make chaos     # list/apply chaos experiments
EOF
