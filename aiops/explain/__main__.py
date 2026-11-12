#!/usr/bin/env python3
"""Backward-compatibility shim. Migrated to aiops.explainability.__main__.

Entry point: `python -m aiops.explain --selftest` now delegates to aiops.explainability.
"""
from aiops.explainability.__main__ import main
import sys

if __name__ == "__main__":
    raise SystemExit(main())