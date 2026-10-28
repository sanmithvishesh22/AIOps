"""Entry point: `python -m aiops.dashboard --selftest` — the dashboard's offline
check (the Python read bridge; the Node read-API has its own `npm test`). Reads
and prints nothing else: the bridge itself is `python -m aiops.dashboard.bridge`,
driven over stdin/stdout by the Express layer."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        from .bridge import _selftest
        _selftest()
        return 0
    print(__doc__)
    print("usage: python -m aiops.dashboard --selftest")
    print("       echo '{\"resource\":\"rca\"}' | python -m aiops.dashboard.bridge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
