"""Shared config, env-driven. In-cluster defaults point at the service DNS names
the bootstrap installs; override via env for local/offline runs."""
import os

# Prometheus (raw metrics source of truth)
PROM_URL = os.environ.get("PROM_URL", "http://monitoring-kube-prometheus-prometheus.monitoring:9090")

# TimescaleDB (inference results)
TIMESCALE_DSN = os.environ.get(
    "TIMESCALE_DSN",
    "postgresql://aiops:aiops@timescaledb.aiops:5432/aiops",
)

# Services under test and the metric window defaults
SOCK_NS = os.environ.get("SOCK_NS", "sock-shop")
WINDOW_MIN = int(os.environ.get("WINDOW_MIN", "15"))   # ingest lookback per pull (minutes)
STEP_S = int(os.environ.get("STEP_S", "15"))            # sample step (seconds)
# NOTE: WINDOW_MIN is the ingest history window, NOT the SLO evaluation window.
# DECISIONS.md proposes a 60 s rolling SLO window — a separate §9 constant, still owed
# and not yet wired (the experiment harness reads it); do not conflate the two.

# §9-OWED PLACEHOLDERS — experiment/DECISIONS.md first-pass, NOT signed off. A human +
# advisor must predeclare and freeze these before any trial; do not treat as final.
# Values below are synced to that first-pass proposal so code compiles and self-tests run.
SLO_P95_MS = float(os.environ.get("SLO_P95_MS", "300"))      # ⚙️ calibrate from baseline run
SLO_ERROR_RATE = float(os.environ.get("SLO_ERROR_RATE", "0.01"))
HORIZON_S = int(os.environ.get("HORIZON_S", "120"))          # ⚙️ must exceed pod-ready time
