from __future__ import annotations

import sys


def build_summary(service, attributions):
    if not attributions:
        return f"{service}: anomaly detected."

    top_feature = max(
        attributions.items(),
        key=lambda item: float(item[1]),
    )[0]

    return (
        f"{service}: anomaly detected, mainly associated "
        f"with {top_feature}."
    )


def _selftest():
    summary = build_summary(
        "orders",
        {
            "p95_ms": 0.8,
            "error_rate": 0.1,
            "cpu": 0.05,
        },
    )

    assert isinstance(summary, str)
    assert summary.strip()
    assert "orders" in summary
    assert "p95_ms" in summary

    print("summary selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    summary = build_summary(
        "orders",
        {
            "p95_ms": 0.8,
            "error_rate": 0.1,
            "cpu": 0.05,
        },
    )

    print(summary)


if __name__ == "__main__":
    main()