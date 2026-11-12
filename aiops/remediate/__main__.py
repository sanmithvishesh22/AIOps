#!/usr/bin/env python3
"""Backward-compatibility shim. Migrated to aiops.remediation.__main__.

Entry point: `python -m aiops.remediate --selftest` now delegates to aiops.remediation.
"""
from aiops.remediation.__main__ import main
import sys

if __name__ == "__main__":
    raise SystemExit(main())