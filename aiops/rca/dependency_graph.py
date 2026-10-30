from __future__ import annotations

import sys


def build_graph(edges):
    """Build a deterministic directed service dependency graph."""
    normalized = set()

    for edge in edges:
        if len(edge) != 2:
            raise ValueError("each dependency edge must contain two services")

        source, target = edge

        if not source or not target:
            raise ValueError("service names must be non-empty")

        normalized.add((str(source), str(target)))

    return sorted(normalized)


def graph_from_trace_rows(trace_rows):
    """Extract directed service edges from trace-shaped fixture rows."""
    edges = []

    for row in trace_rows:
        source = row.get("source")
        target = row.get("target")

        if source is not None and target is not None:
            edges.append((source, target))

    return build_graph(edges)


def _selftest():
    trace_fixture = [
        {"source": "front-end", "target": "orders"},
        {"source": "front-end", "target": "orders"},
    ]

    graph = graph_from_trace_rows(trace_fixture)

    assert graph == [
        ("front-end", "orders"),
    ]

    print("dependency_graph selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    print(build_graph([
        ("front-end", "orders"),
    ]))


if __name__ == "__main__":
    main()