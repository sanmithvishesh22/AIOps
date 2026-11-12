"""Entry point: `python -m aiops.remediate --selftest` (the Makefile `selftest`
target calls exactly this). The live propose/approve/execute API is imported as
`aiops.remediate`; wiring it to the cluster is INT-005, not this module's job."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        from . import _selftest
        _selftest()
        return 0
    print(__doc__)
    print("usage: python -m aiops.remediate --selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
