"""Selftest for D3-008 statistical analysis module.

Tests:
  1. Deterministic seeded reproducibility (PS-2)
  2. Planted-effect coverage (synthetic dataset with true delta)
  3. Planted-null control handling (segregated and non-significant)
  4. Degenerate input handling (empty, zero variance, insufficient reps)
  5. Full report rendering and byte-identical reproducibility
"""
from __future__ import annotations

import json
import numpy as np

from . import config
from .paired import paired_bootstrap
from .report import ExperimentAnalyzer, MatchedPairOutcome


def test_deterministic_bootstrap():
    """Verify bootstrap produces identical numbers under fixed seed (PS-2)."""
    deltas = [-12.5, -10.0, -15.2, -8.3, -11.0, -9.5, -14.1, -12.0, -10.5, -13.2] * 3
    res1 = paired_bootstrap(deltas, metric_name="test", seed=42)
    res2 = paired_bootstrap(deltas, metric_name="test", seed=42)

    assert res1.to_dict() == res2.to_dict(), "Bootstrap must be byte-identical under fixed seed"
    assert res1.is_statistically_significant is True
    assert res1.ci_lower < res1.mean_delta < res1.ci_upper


def test_planted_effect_coverage():
    """Verify 95% bootstrap CI covers the true planted mean delta."""
    rng = np.random.default_rng(123)
    true_delta = -15.0
    # Generate 50 pairs with true delta + noise
    samples = rng.normal(loc=true_delta, scale=3.0, size=50)

    res = paired_bootstrap(samples, metric_name="planted_effect", seed=999)
    assert res.ci_lower <= true_delta <= res.ci_upper, (
        f"CI [{res.ci_lower}, {res.ci_upper}] failed to cover true delta {true_delta}"
    )
    assert res.is_statistically_significant is True
    assert res.warning is None


def test_planted_null_control():
    """Verify planted null control covers 0 and is not significant."""
    rng = np.random.default_rng(456)
    true_delta = 0.0
    samples = rng.normal(loc=true_delta, scale=2.0, size=40)

    res = paired_bootstrap(samples, metric_name="null_control", seed=888)
    assert res.ci_lower <= 0.0 <= res.ci_upper, "Null control CI must cover 0"
    assert res.is_statistically_significant is False


def test_degenerate_inputs():
    """Verify edge cases: empty list, zero variance, and insufficient sample size."""
    # Empty
    empty_res = paired_bootstrap([], metric_name="empty")
    assert empty_res.n_pairs == 0
    assert empty_res.warning == "no_pairs_provided"

    # Zero variance
    zero_res = paired_bootstrap([0.0] * 25, metric_name="zero")
    assert zero_res.mean_delta == 0.0
    assert zero_res.ci_lower == 0.0
    assert zero_res.ci_upper == 0.0

    # Insufficient reps (< 20)
    small_res = paired_bootstrap([-5.0, -4.0, -6.0], metric_name="small")
    assert small_res.warning is not None
    assert "insufficient_reps" in small_res.warning


def test_negative_control_segregation_in_report():
    """Verify negative controls are strictly separated from capacity-responsive trials."""
    pairs = [
        # Capacity-responsive pairs (planted positive effect)
        MatchedPairOutcome(
            pair_id=f"pair-resp-{i}",
            workload_regime="burst",
            fault_class="pod_kill",
            is_negative_control=False,
            hpa_breach_duration_s=25.0,
            hybrid_breach_duration_s=10.0,
            hpa_breaching_requests=100,
            hybrid_breaching_requests=40,
            hpa_pod_minutes=5.0,
            hybrid_pod_minutes=5.5,
            hpa_scaling_actions=2,
            hybrid_scaling_actions=4,
            hpa_oscillations=0,
            hybrid_oscillations=0,
        )
        for i in range(25)
    ] + [
        # Negative control pairs (planted null effect)
        MatchedPairOutcome(
            pair_id=f"pair-ctrl-{i}",
            workload_regime="stationary",
            fault_class="dns_failure",
            is_negative_control=True,
            hpa_breach_duration_s=30.0,
            hybrid_breach_duration_s=30.0,
            hpa_breaching_requests=200,
            hybrid_breaching_requests=200,
            hpa_pod_minutes=4.0,
            hybrid_pod_minutes=4.0,
            hpa_scaling_actions=1,
            hybrid_scaling_actions=1,
            hpa_oscillations=0,
            hybrid_oscillations=0,
        )
        for i in range(25)
    ]

    analyzer = ExperimentAnalyzer(pairs, n_resamples=1000, seed=42)
    rep = analyzer.generate_report()

    assert rep["capacity_responsive"]["n_pairs"] == 25
    assert rep["negative_controls"]["n_pairs"] == 25

    # Check capacity-responsive metrics
    res_dur = rep["capacity_responsive"]["primaries"]["slo_breach_duration_s"]
    assert res_dur["mean_delta"] == -15.0
    assert res_dur["significant"] is True

    # Check negative control metrics (must be null!)
    ctrl_dur = rep["negative_controls"]["primaries"]["slo_breach_duration_s"]
    assert ctrl_dur["mean_delta"] == 0.0
    assert ctrl_dur["significant"] is False

    text = analyzer.render_text()
    assert "### SECTION 1: CAPACITY-RESPONSIVE FAULTS" in text
    assert "### SECTION 2: NEGATIVE CONTROLS (SEPARATE REPORTING)" in text
    assert "CONFIRMED NULL" in text


def run_selftest() -> bool:
    """Run all selftest assertions."""
    print("Running experiment.analysis selftest...")
    test_deterministic_bootstrap()
    print("  ✓ Deterministic seeded bootstrap passed")
    test_planted_effect_coverage()
    print("  ✓ Planted-effect coverage passed")
    test_planted_null_control()
    print("  ✓ Planted-null control passed")
    test_degenerate_inputs()
    print("  ✓ Degenerate inputs & warnings passed")
    test_negative_control_segregation_in_report()
    print("  ✓ Negative-control segregation passed")
    print("All experiment.analysis tests green.")
    return True


if __name__ == "__main__":
    run_selftest()
