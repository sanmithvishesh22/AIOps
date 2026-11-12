"""Backward-compatibility shim. Migrated to aiops.explainability.

All public names are re-exported from aiops.explainability for backward
compatibility. New code should import directly from aiops.explainability.
"""
from aiops.explainability import (  # noqa: F401
    FEATURES,
    build_attribution,
    explain_score,
    build_summary,
)

__all__ = [
    "FEATURES",
    "build_attribution",
    "explain_score",
    "build_summary",
]