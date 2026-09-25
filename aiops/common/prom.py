"""Thin Prometheus HTTP API client. Just enough to pull range windows and parse
them into per-series numpy arrays for the ML modules. No new deps beyond requests.

Contract B (frozen, option A): consumers call the q_* executors or range_query and
never hand-roll PromQL. Each q_* returns every Sock Shop service in one query,
every series carrying a `name` label = service; filter the returned list by that
label for one service. The six executors cover the Contract-C feature columns:
q_latency_p95, q_error_rate, q_rps (from the well-labeled request_* http metrics),
q_replicas (kube-state-metrics), q_cpu, q_mem (cAdvisor joined to pod labels).

ponytail: every executor assumes the Sock Shop request metrics carry a `name`
label (service) and that q_replicas/q_cpu/q_mem's kube-state-metrics/cAdvisor label
names + the kube_pod_labels join hold on this cluster. These vary by setup. Verify
the labels once against the live testbed (ticket A1) and adjust the PromQL if a
series comes back empty — the frame-assembly logic in ingest.py does not depend on
the labels being right, only on each series carrying a resolvable service name.
"""
from __future__ import annotations
import time
import requests
import numpy as np

from . import config


def range_query(promql: str, start: float, end: float, step: int, url: str | None = None):
    """Run a range query over [start, end] (unix seconds) at `step`-second resolution.
    Returns list of (labels:dict, ts:np.ndarray, vals:np.ndarray)."""
    url = url or config.PROM_URL
    r = requests.get(f"{url}/api/v1/query_range",
                     params={"query": promql, "start": start, "end": end, "step": step},
                     timeout=30)
    r.raise_for_status()
    return parse_range(r.json())


def parse_range(payload: dict):
    """Parse a Prometheus query_range JSON body. Split out for offline testing."""
    if payload.get("status") != "success":
        raise RuntimeError(f"prometheus error: {payload.get('error', payload)}")
    out = []
    for series in payload["data"]["result"]:
        pairs = series.get("values", [])
        ts = np.array([float(t) for t, _ in pairs])
        # Prometheus returns NaN/Inf as strings; coerce, keep NaN so gaps are visible
        vals = np.array([float(v) if v not in ("NaN", "+Inf", "-Inf") else np.nan
                         for _, v in pairs])
        out.append((series.get("metric", {}), ts, vals))
    return out


def _window(window_min: int | None):
    """(start, end, step) for the last `window_min` minutes on the config step grid."""
    minutes = window_min or config.WINDOW_MIN
    end = time.time()
    return end - minutes * 60, end, config.STEP_S


# Per-service PromQL for Sock Shop, grouped by the `name` label so each returned
# series is one service. Executors run the query for the last `window` minutes and
# return all services at once (Contract B, option A).
def q_latency_p95(window: int | None = None):
    """p95 latency in ms, per service, over the last `window` minutes (all services)."""
    start, end, step = _window(window)
    return range_query(
        'histogram_quantile(0.95, sum(rate(request_duration_seconds_bucket'
        '{job=~".*sock-shop.*"}[1m])) by (le, name)) * 1000',
        start, end, step)


def q_error_rate(window: int | None = None):
    """5xx error ratio, per service, over the last `window` minutes (all services)."""
    start, end, step = _window(window)
    return range_query(
        'sum(rate(request_duration_seconds_count{status_code=~"5..",'
        'job=~".*sock-shop.*"}[1m])) by (name) '
        '/ sum(rate(request_duration_seconds_count{job=~".*sock-shop.*"}[1m])) by (name)',
        start, end, step)


def q_replicas(window: int | None = None):
    """Deployment replica count in SOCK_NS, per service, over the last `window` minutes.
    Relabels `deployment` → `name` (Sock Shop deployment names == service names) so
    every helper is keyed by `name`."""
    start, end, step = _window(window)
    return range_query(
        f'label_replace(kube_deployment_status_replicas{{namespace="{config.SOCK_NS}"}},'
        f' "name", "$1", "deployment", "(.+)")',
        start, end, step)


# cAdvisor/kube-state-metrics have no `name` label, so join pod labels
# (Sock Shop pods carry label `name=<service>`, exposed as kube_pod_labels.label_name)
# and expose it as `name` to match the http-metric helpers above.
_POD_JOIN = (' * on(namespace,pod) group_left(name) label_replace('
             'kube_pod_labels{{namespace="{ns}"}}, "name", "$1", "label_name", "(.+)")')


def q_cpu(window: int | None = None):
    """CPU cores in use, per service, over the last `window` minutes (all services)."""
    start, end, step = _window(window)
    return range_query(
        ('sum by (name) (rate(container_cpu_usage_seconds_total'
         '{{namespace="{ns}", container!="", container!="POD"}}[1m])' + _POD_JOIN + ')'
         ).format(ns=config.SOCK_NS),
        start, end, step)


def q_mem(window: int | None = None):
    """Working-set memory in bytes, per service, over the last `window` minutes."""
    start, end, step = _window(window)
    return range_query(
        ('sum by (name) (container_memory_working_set_bytes'
         '{{namespace="{ns}", container!="", container!="POD"}}' + _POD_JOIN + ')'
         ).format(ns=config.SOCK_NS),
        start, end, step)


def q_rps(window: int | None = None):
    """Requests per second, per service, over the last `window` minutes (all services).
    Reuses the well-labeled request_duration_seconds_count — no label join needed."""
    start, end, step = _window(window)
    return range_query(
        'sum(rate(request_duration_seconds_count{job=~".*sock-shop.*"}[1m])) by (name)',
        start, end, step)



def _selftest():
    sample = {
        "status": "success",
        "data": {"result": [
            {"metric": {"name": "orders"}, "values": [[1000, "50"], [1015, "NaN"], [1030, "170"]]},
            {"metric": {"name": "catalogue"}, "values": [[1000, "40"], [1015, "41"]]},
        ]},
    }
    parsed = parse_range(sample)
    assert len(parsed) == 2, "two series expected"
    labels, ts, vals = parsed[0]
    assert labels["name"] == "orders"
    assert np.isnan(vals[1]), "NaN gap must survive parsing"
    assert vals[2] == 170.0 and ts[0] == 1000.0
    # error payloads must raise, not silently return empty
    try:
        parse_range({"status": "error", "error": "bad query"})
        raise AssertionError("error payload should raise")
    except RuntimeError:
        pass
    # window bounds: end after start, positive step
    start, end, step = _window(5)
    assert end > start and step > 0, "window must be a positive interval"
    print("prom selftest OK")


if __name__ == "__main__":
    _selftest()
