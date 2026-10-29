#!/usr/bin/env bash
# Build the shared Python image and load it into the existing kind cluster.
# Single source of truth for both `make platform-image` and bootstrap.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER="${CLUSTER:-aiops}"

docker build -t aiops:dev .
kind load docker-image aiops:dev --name "$CLUSTER"
