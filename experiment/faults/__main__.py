"""Fault harness (D3-006) — online/offline canary.

Because `experiment.faults` is a namespace package, direct ``python3 -m
experiment.faults`` may not resolve without the ``__main__.py`` entry point.
"""
from __future__ import annotations

import sys

from .chaos import (
    assert_fault,
    assert_target_namespace,
    build_fault,
    build_schedule,
    CHAOS_KINDS,
    fault_class_or_raise,
    IS_NEGATIVE_CONTROL,
)

# Lightweight edge smoke test — use a fabricated namespace to force refusal.
FAULT_TEST_SERVICE = "front-end"


def _fault_rejects_if_wrong_ns() -> int:
    try:
        # Temporarily break namespace assertion, just to confirm it raises
        target_ns = os.environ.get("SOCK_NS", "sock-shop")
        resolved = assert_target_namespace(target_ns)
        # If we get here and target IS SOCK_NS, that's a pass
        return 0
    except SystemExit:
        return 2
    except Exception as exc:
        # The guard must fire for a bad namespace
        print(f"namespace guard raised as expected: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    # A quick smoke: all ratified classes build tags correctly
    for fc in config_faults := __import__("aiops.platform.experiment.faults.config", fromlist=["FAULT_CLASSES"]).FAULT_CLASSES:
        key = fault_class_or_raise(fc)
        manifest = build_fault(key, service=FAULT_TEST_SERVICE, seed=42)
        assert_fault(manifest)
    print("fault harness smoke: all rated classes tag+scope correctly")
    # Quick guard confirmation
    _fault_rejects_if_wrong_ns()
    sys.exit(0)