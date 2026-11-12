#!/usr/bin/env python3
"""Backward-compatibility shim. Migrated to aiops.forecasting.__main__.

Entry point: `python -m aiops.forecast --selftest` now delegates to aiops.forecasting.
"""
from aiops.forecasting.__main__ import main
import sys

if __name__ == "__main__":
    raise SystemExit(main())