"""Analysis module for matched-pair experiments (D3-008)."""
from .loader import load_pairs_from_db
from .paired import BootstrapResult, PairedComparison, paired_bootstrap
from .report import ExperimentAnalyzer, MatchedPairOutcome
from .selftest import run_selftest

__all__ = [
    "BootstrapResult",
    "PairedComparison",
    "paired_bootstrap",
    "MatchedPairOutcome",
    "ExperimentAnalyzer",
    "load_pairs_from_db",
    "run_selftest",
]
