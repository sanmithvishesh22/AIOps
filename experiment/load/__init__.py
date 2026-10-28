"""Load harness (D3-005) — k6 scaffold for the four §9 regimes.

Public surface:
    build_profile, Profile, assert_envelope, UnknownRegime, REGIMES
    render_script, render_configmap      (D3-005.1 deterministic k6 plumbing)
    build_job                            (batch/v1 Job objects for the runner)

Offline check: ``python -m experiment.load --selftest``.
"""
from __future__ import annotations

from . import config
from .job import build_job
from .k6script import render_configmap, render_script
from .regimes import (
    REGIMES,
    Profile,
    UnknownRegime,
    assert_envelope,
    build_profile,
    regime_or_raise,
)

__all__ = [
    "config",
    "build_job",
    "build_profile",
    "Profile",
    "REGIMES",
    "render_configmap",
    "render_script",
    "assert_envelope",
    "UnknownRegime",
    "regime_or_raise",
]
