"""Entry point: ``python -m aiops.explain --selftest``.

Runs both offline checks (attribution + operator summary). No cluster, no DB.
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        from .attribution import _selftest as attribution_selftest
        from .summary import _selftest as summary_selftest

        attribution_selftest()
        summary_selftest()
        print("explain selftest OK")
        return 0
    print(__doc__)
    print("usage: python -m aiops.explain --selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
