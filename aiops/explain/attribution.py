from __future__ import annotations

import sys

import numpy as np

from ..common import store


FEATURES = [
    "p95_ms",
    "error_rate",
    "cpu",
    "mem",
    "replicas",
    "rps",
]


def explain_score(feature_values, baseline_values):
    """
    Estimate feature contributions to an anomaly score.

    This is an attribution, not causal proof.
    """
    contributions = {}

    for feature in FEATURES:
        value = float(feature_values.get(feature, 0.0))
        baseline = float(baseline_values.get(feature, 0.0))
        contributions[feature] = abs(value - baseline)

    return contributions


def build_attribution(
    service,
    feature_values,
    baseline_values,
    incident_id="inc-1",
):
    contributions = explain_score(
        feature_values,
        baseline_values,
    )

    total = sum(contributions.values())

    if total == 0.0:
        normalized = {
            feature: 0.0
            for feature in FEATURES
        }
    else:
        normalized = {
            feature: value / total
            for feature, value in contributions.items()
        }

    return {
        "ts": 1000.0,
        "module": "explain",
        "service": service,
        "kind": "attribution",
        "value": float(max(normalized.values())),
        "meta": {
            "incident_id": incident_id,
            "method": "feature_deviation",
            "attributions": normalized,
        },
    }


def _selftest():
    baseline = {
        "p95_ms": 100.0,
        "error_rate": 0.01,
        "cpu": 50.0,
        "mem": 50.0,
        "replicas": 3.0,
        "rps": 100.0,
    }

    anomalous = dict(baseline)
    anomalous["p95_ms"] = 500.0

    row = build_attribution(
        service="orders",
        feature_values=anomalous,
        baseline_values=baseline,
        incident_id="inc-selftest",
    )

    assert row["kind"] == "attribution"
    assert row["module"] == "explain"
    assert row["service"] == "orders"
    assert row["meta"]["incident_id"] == "inc-selftest"
    assert row["meta"]["attributions"]["p95_ms"] > 0.0
    assert np.isclose(
        sum(row["meta"]["attributions"].values()),
        1.0,
    )

    store.normalize([row])

    print("attribution selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    row = build_attribution(
        service="orders",
        feature_values={
            "p95_ms": 500.0,
            "error_rate": 0.01,
            "cpu": 50.0,
            "mem": 50.0,
            "replicas": 3.0,
            "rps": 100.0,
        },
        baseline_values={
            "p95_ms": 100.0,
            "error_rate": 0.01,
            "cpu": 50.0,
            "mem": 50.0,
            "replicas": 3.0,
            "rps": 100.0,
        },
    )

    store.write([row])
    print("wrote attribution row")


if __name__ == "__main__":
    main()