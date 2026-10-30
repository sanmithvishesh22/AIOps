"""Entry point: ``python -m aiops.ingest [--selftest]``.

Offline check (no cluster): ``--selftest`` assembles a frame from a synthetic
Prometheus payload (including a gap) and asserts the Contract-C shape + NaN
policy. The live path prints the frame pulled from Prometheus.
"""
from __future__ import annotations

import sys

from . import _selftest, fetch


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        _selftest()
        return 0
    print(fetch().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
