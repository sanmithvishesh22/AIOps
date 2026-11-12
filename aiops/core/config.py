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
# §9 CONSTANTS — owner-ratified 2026-09-25 + advisor-signed 2026-09-26 (Guide Dhirbitri
# Bora); see experiment/DECISIONS.md. Both sign-off gates are closed, but the baseline
# characterization run is still pending, so the ⚙️ values remain PROVISIONAL: do not treat
# as final until that run freezes them. SLO_WINDOW_S is the SLO evaluation window (60 s) —
# deliberately SEPARATE from WINDOW_MIN (the 15-min ingest lookback); the two are different
# knobs and must not be conflated.
SLO_P95_MS = float(os.environ.get("SLO_P95_MS", "300"))      # ⚙️ recalibrate: nominal_p95 × 1.3–1.5
SLO_ERROR_RATE = float(os.environ.get("SLO_ERROR_RATE", "0.01"))
SLO_WINDOW_S = int(os.environ.get("SLO_WINDOW_S", "60"))     # SLO eval window (NOT WINDOW_MIN)
HORIZON_S = int(os.environ.get("HORIZON_S", "120"))          # ⚙️ must exceed measured pod-ready time
