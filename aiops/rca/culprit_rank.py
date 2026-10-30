from __future__ import annotations

import sys

from ..common import store
from .dependency_graph import build_graph


def rank_culprits(anomaly_scores, graph_edges, incident_id="inc-1"):
    """
    Rank likely culprits using anomaly scores and graph propagation.

    This is a ranking, not causal proof.
    """
    graph = build_graph(graph_edges)

    scores = {
        str(service): float(score)
        for service, score in anomaly_scores.items()
    }

    propagated = dict(scores)

    for source, target in graph:
        target_score = scores.get(target, 0.0)
        propagated[source] = (
            propagated.get(source, 0.0) + 0.5 * target_score
        )

    ranked = sorted(
        propagated.items(),
        key=lambda item: (-item[1], item[0]),
    )

    rows = []

    for rank, (service, score) in enumerate(ranked, start=1):
        rows.append(
            {
                "ts": 1000.0,
                "module": "rca",
                "service": service,
                "kind": "culprit_rank",
                "value": rank,
                "meta": {
                    "score": float(score),
                    "incident_id": incident_id,
                    "graph_edges": [list(edge) for edge in graph],
                },
            }
        )

    return rows


def _selftest():
    graph_edges = [
        ("front-end", "orders"),
    ]

    # Inject an anomaly into orders.
    # The injected culprit should rank first.
    anomaly_scores = {
        "front-end": 0.20,
        "orders": 0.90,
    }

    rows = rank_culprits(
        anomaly_scores,
        graph_edges,
        incident_id="inc-selftest",
    )

    assert rows
    assert rows[0]["service"] == "orders"
    assert rows[0]["value"] == 1
    assert rows[0]["kind"] == "culprit_rank"
    assert rows[0]["meta"]["incident_id"] == "inc-selftest"
    assert rows[0]["meta"]["graph_edges"] == [
        ["front-end", "orders"],
    ]

    store.normalize(rows)

    print("culprit_rank selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    rows = rank_culprits(
        {"front-end": 0.20, "orders": 0.90},
        [("front-end", "orders")],
    )

    store.write(rows)
    print(f"wrote {len(rows)} culprit ranking rows")


if __name__ == "__main__":
    main()