"""Offline selftest for D3-007 paired runner (python -m experiment.runner --selftest).

Assert-based, no cluster, no network (TS-1/TS-2).
Validates:
  * D3-007.1: Matched-pair construction (seed/regime/fault identical, policy differs, atomicity)
  * D3-007.2: Seeded policy order randomization (balanced, reproducible, recorded)
  * D3-007.3: >=20 reps matrix orchestration + resumability (skips completed)
  * D3-007.4: Schema-conformant results persistence + provenance
  * D3-007.5: Infected-period exclusion + red tests (TS-3)
"""
from __future__ import annotations

import collections
import dataclasses

from . import config
from .metrics import (
    Scorecard,
    TelemetryPoint,
    compute_scorecard,
    exclude_infected,
    tag_infected_samples,
)
from .pair import MatchedPair, build_matrix, derive_pair_seed
from .runner import MockTrialExecutor, PairedRunner
from .store import MockResultsStore


def test_matched_pair_construction() -> None:
    """D3-007.1: Both members share seed/regime/fault/duration and differ ONLY in policy."""
    pairs = build_matrix(reps=1, regimes=["stationary"], faults=["cpu_stress"])
    assert len(pairs) == 1
    p = pairs[0]
    t1, t2 = p.trials()

    assert t1.pair_id == t2.pair_id == p.pair_id
    assert t1.workload_regime == t2.workload_regime == "stationary"
    assert t1.fault_class == t2.fault_class == "cpu_stress"
    assert t1.seed == t2.seed == p.seed
    assert t1.duration_s == t2.duration_s == config.TRIAL_DURATION_S
    assert {t1.policy, t2.policy} == {"hpa_tuned", "forecast_hybrid"}
    assert t1.policy != t2.policy, "Members must differ in policy"


def test_pair_atomicity_on_failure() -> None:
    """D3-007.1 edge: A pair where one trial fails is discarded as a pair (no half-pairs)."""
    store = MockResultsStore()
    # Inject failure only when policy is forecast_hybrid
    executor = MockTrialExecutor(failure_filter=lambda s: s.policy == "forecast_hybrid")
    runner = PairedRunner(store, executor, reps_per_cell=2, regimes=["stationary"], faults=["cpu_stress"])

    stats = runner.run_matrix()
    assert stats["completed"] == 0, "No pair should be completed when half fails"
    assert stats["discarded"] == 2, "Both attempted pairs must be discarded"
    assert len(store.runs) == 0, "No orphaned half-pair runs may be recorded in the store"
    assert len(store.results) == 0, "No orphaned results"
    assert len(store.get_completed_pair_ids()) == 0


def test_randomized_policy_order() -> None:
    """D3-007.2: Seeded policy order randomization varies across pairs and is reproducible."""
    pairs1 = build_matrix(reps=20, master_seed=42)
    pairs2 = build_matrix(reps=20, master_seed=42)
    pairs_other_seed = build_matrix(reps=20, master_seed=999)

    # Identical seed => byte-identical pair orderings (PS-2 / TS-5)
    for p1, p2 in zip(pairs1, pairs2):
        assert p1.ordered_policies == p2.ordered_policies
        assert p1.pair_id == p2.pair_id

    # Order varies across pairs (not static)
    order_counts = collections.Counter(p.ordered_policies for p in pairs1)
    assert order_counts[("hpa_tuned", "forecast_hybrid")] > 0
    assert order_counts[("forecast_hybrid", "hpa_tuned")] > 0
    # Both orderings reasonably balanced (within 40%-60% of total)
    ratio = order_counts[("hpa_tuned", "forecast_hybrid")] / len(pairs1)
    assert 0.35 <= ratio <= 0.65, f"Policy order unbalanced: ratio={ratio:.2f}"

    # Different master seed produces different orderings
    assert any(
        p1.ordered_policies != p3.ordered_policies
        for p1, p3 in zip(pairs1, pairs_other_seed)
    ), "Different master seeds must yield distinct orderings"


def test_reps_orchestration_and_resumability() -> None:
    """D3-007.3: >=20 reps matrix orchestration + resumability on restart (PS-4)."""
    store = MockResultsStore()
    executor = MockTrialExecutor()

    # Full matrix: 4 regimes × 6 faults = 24 cells; 20 reps = 480 pairs
    matrix = build_matrix(reps=20)
    assert len(matrix) == 4 * 6 * 20 == 480

    # Test small submatrix orchestration with resumability
    runner = PairedRunner(store, executor, reps_per_cell=3, regimes=["stationary", "diurnal"], faults=["cpu_stress"])
    stats1 = runner.run_matrix(limit_pairs=3)
    assert stats1["completed"] == 3
    assert stats1["skipped"] == 0
    assert len(store.get_completed_pair_ids()) == 3

    # Re-run: must skip the 3 already completed pairs and execute the remaining 3 (total 6)
    stats2 = runner.run_matrix()
    assert stats2["skipped"] == 3, "Resumed runner must skip already completed pairs"
    assert stats2["completed"] == 3, "Resumed runner must finish the remaining pairs"
    assert len(store.get_completed_pair_ids()) == 6


def test_results_persistence_and_provenance() -> None:
    """D3-007.4: Schema-conformant results insertion with full provenance."""
    store = MockResultsStore()
    executor = MockTrialExecutor()
    runner = PairedRunner(store, executor, reps_per_cell=1, regimes=["stationary"], faults=["cpu_stress"])

    stats = runner.run_matrix()
    assert stats["completed"] == 1
    completed_ids = list(store.get_completed_pair_ids())
    assert len(completed_ids) == 1
    pair_id = completed_ids[0]

    # Two runs recorded for the pair
    pair_runs = [r for r in store.runs.values() if r.pair_id == pair_id]
    assert len(pair_runs) == 2
    for r in pair_runs:
        res = store.get_result(r.run_id)
        assert res is not None
        assert res.run_id == r.run_id
        assert res.slo_breach_duration_s >= 0.0
        assert res.pod_minutes >= 0.0
        assert res.scaling_actions >= 0
        assert 0.0 <= res.breaching_request_ratio <= 1.0
        assert r.slo_p95_ms == config.SLO_P95_MS
        assert r.horizon_s == config.HORIZON_S
        assert "matched_pair" in (r.notes or "")


def test_infected_period_exclusion() -> None:
    """D3-007.5: Infected period exclusion separates fault samples from clean samples."""
    # Create 20 points, 15s step
    raw_points = [
        TelemetryPoint(ts=1000.0 + i * 15.0, p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=2)
        for i in range(20)
    ]
    # Fault fires at onset 90s (step 6, ts 1090) for 60s (ends ts 1150)
    tagged = tag_infected_samples(raw_points, fault_onset_s=90.0, fault_duration_s=60.0, trial_start_s=1000.0)
    infected_count = sum(1 for p in tagged if p.is_infected)
    assert infected_count > 0, "Active fault window must tag points as infected"

    clean = exclude_infected(tagged)
    assert len(clean) == len(raw_points) - infected_count
    assert all(not p.is_infected for p in clean)

    # Scorecard without exclusion vs with exclusion
    # Inject breach during infected period
    breached_points = [
        dataclasses.replace(p, p95_ms=500.0 if p.is_infected else 20.0)
        for p in tagged
    ]
    sc_all = compute_scorecard(breached_points, exclude_infected_period=False)
    sc_clean = compute_scorecard(breached_points, exclude_infected_period=True)

    assert sc_all.slo_breach_duration_s > 0.0, "All points include the breach"
    assert sc_clean.slo_breach_duration_s == 0.0, "Clean points exclude the infected breach"


def test_scorecard_finite_breach_and_no_breach() -> None:
    """Regression test: finite breach duration vs clean no-breach calculation."""
    # 1. No breach
    clean_points = [
        TelemetryPoint(ts=1000.0 + i * 15.0, p95_ms=25.0, error_rate=0.001, rps=40.0, replicas=2)
        for i in range(10)
    ]
    sc_clean = compute_scorecard(clean_points, step_s=15, slo_p95_ms=300.0, slo_error_rate=0.01)
    assert sc_clean.slo_breach_duration_s == 0.0
    assert sc_clean.breaching_requests == 0
    assert sc_clean.breaching_request_ratio == 0.0
    assert sc_clean.pod_minutes == round(10 * 15 * 2 / 60.0, 2)

    # 2. Finite breach: steps 2 and 3 breach p95 (400ms > 300ms)
    breached_points = list(clean_points)
    breached_points[2] = dataclasses.replace(clean_points[2], p95_ms=450.0)
    breached_points[3] = dataclasses.replace(clean_points[3], p95_ms=500.0)
    sc_breach = compute_scorecard(breached_points, step_s=15, slo_p95_ms=300.0, slo_error_rate=0.01)
    assert sc_breach.slo_breach_duration_s == 30.0  # 2 steps * 15s
    assert sc_breach.breaching_requests == 2 * int(round(40.0 * 15))
    assert abs(sc_breach.breaching_request_ratio - 0.20) < 1e-4


def test_scorecard_breach_crossing_adjacent_windows() -> None:
    """Regression test: contiguous breach spanning multiple consecutive windows."""
    points = [
        TelemetryPoint(ts=1000.0 + i * 15.0, p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=2)
        for i in range(10)
    ]
    # Breaches across steps 3, 4, 5, 6 (4 consecutive steps = 60s)
    for idx in (3, 4, 5, 6):
        points[idx] = dataclasses.replace(points[idx], error_rate=0.05)  # 5% > 1%

    sc = compute_scorecard(points, step_s=15, slo_p95_ms=300.0, slo_error_rate=0.01)
    assert sc.slo_breach_duration_s == 60.0
    assert sc.breaching_requests == 4 * int(round(30.0 * 15))


def test_scorecard_missing_telemetry_and_nans() -> None:
    """Regression test: empty points and NaN metrics grade as non-breach."""
    # Empty
    sc_empty = compute_scorecard([])
    assert sc_empty.slo_breach_duration_s == 0.0
    assert sc_empty.breaching_requests == 0
    assert sc_empty.pod_minutes == 0.0

    # NaNs in metrics
    points = [
        TelemetryPoint(ts=1000.0 + i * 15.0, p95_ms=float("nan"), error_rate=float("nan"), rps=30.0, replicas=2)
        for i in range(5)
    ]
    sc_nan = compute_scorecard(points, step_s=15)
    assert sc_nan.slo_breach_duration_s == 0.0
    assert sc_nan.breaching_requests == 0


def test_scorecard_invalid_or_reversed_timestamps() -> None:
    """Regression test: non-chronological or invalid timestamps must raise ValueError."""
    # Reversed timestamps
    reversed_points = [
        TelemetryPoint(ts=1030.0, p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=2),
        TelemetryPoint(ts=1015.0, p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=2),
    ]
    try:
        compute_scorecard(reversed_points, step_s=15)
        raise AssertionError("Expected ValueError on reversed timestamps")
    except ValueError as exc:
        assert "reversed or non-chronological" in str(exc)

    # Non-finite timestamp
    nan_ts_points = [
        TelemetryPoint(ts=float("nan"), p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=2),
    ]
    try:
        compute_scorecard(nan_ts_points, step_s=15)
        raise AssertionError("Expected ValueError on non-finite timestamp")
    except ValueError as exc:
        assert "non-finite timestamp" in str(exc)


def test_scorecard_exact_duration_and_step_accounting() -> None:
    """Regression test: verify exact 1:1 duration and step accounting without inflation."""
    for duration_s in (60, 300, 1200):
        step_s = 15
        n_steps = duration_s // step_s
        replicas = 2
        pts = [
            TelemetryPoint(ts=1000.0 + i * step_s, p95_ms=20.0, error_rate=0.0, rps=30.0, replicas=replicas)
            for i in range(n_steps)
        ]
        sc = compute_scorecard(pts, step_s=step_s)
        expected_pod_minutes = round(duration_s * replicas / 60.0, 2)
        assert sc.pod_minutes == expected_pod_minutes, f"Expected {expected_pod_minutes}, got {sc.pod_minutes}"
        assert sc.slo_breach_duration_s == 0.0


def test_scorecard_epoch_duration_confusion_guard() -> None:
    """Regression test: Unix timestamp like 1938300118 passed as duration raises ValueError."""
    try:
        Scorecard(
            slo_breach_duration_s=1938300118.0,  # epoch timestamp accidentally passed
            breaching_requests=0,
            breaching_request_ratio=0.0,
            pod_minutes=2.0,
            scaling_actions=0,
            oscillations=0,
        )
        raise AssertionError("Expected ValueError when Unix timestamp is passed as breach duration")
    except ValueError as exc:
        assert "exceeds 86400s" in str(exc) or "epoch timestamp" in str(exc)


def selftest() -> None:
    test_matched_pair_construction()
    test_pair_atomicity_on_failure()
    test_randomized_policy_order()
    test_reps_orchestration_and_resumability()
    test_results_persistence_and_provenance()
    test_infected_period_exclusion()
    test_scorecard_finite_breach_and_no_breach()
    test_scorecard_breach_crossing_adjacent_windows()
    test_scorecard_missing_telemetry_and_nans()
    test_scorecard_invalid_or_reversed_timestamps()
    test_scorecard_epoch_duration_confusion_guard()
    test_scorecard_exact_duration_and_step_accounting()
    print("runner selftest OK — matched pairs, randomized order, >=20 reps resumability, Contract-D writes, infected exclusion, duration regression checks")


if __name__ == "__main__":
    selftest()
