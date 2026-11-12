#!/usr/bin/env python3
"""Backward-compatibility shim. Migrated to aiops.scaling.__main__.

Entry point: `python -m aiops.scaler --selftest` now delegates to aiops.scaling.
"""
from aiops.scaling.__main__ import main
import sys

if __name__ == "__main__":
    raise SystemExit(main())