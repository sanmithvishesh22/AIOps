"""Paired trial matrix runner (D3-007)."""
from .live import LiveTrialExecutor
from .pair import MatchedPair, TrialSpec, build_matrix
from .runner import PairedRunner
from .store import MockResultsStore, PostgresResultsStore

__all__ = [
    "MatchedPair",
    "TrialSpec",
    "build_matrix",
    "PairedRunner",
    "MockResultsStore",
    "PostgresResultsStore",
    "LiveTrialExecutor",
]
