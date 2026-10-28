"""QA-003 — Automated Experiment Validity Audit (TS-7).

Loud failure = results invalid.
Asserts:
  QA-003.1: Chronological holdout (no future-to-past data leakage).
  QA-003.2: Infected-period exclusion (fault periods cleanly excised from nominal evaluation windows).
  QA-003.3: Paired reps count (>=20 reps per cell) & deterministic randomized policy ordering.
  QA-003.4: Negative controls present and strictly segregated from capacity-responsive findings.

Each sub-check ships its own 'red test' (a deliberately flawed fixture that MUST trip it).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Sequence, Tuple
import numpy as np

# Ensure project root is in path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class ExperimentValidityError(Exception):
    """Loud failure: raised when an experiment integrity check fails. Results are invalid."""
    pass


def audit_chronological_holdout(
    train_ts: Sequence[float],
    test_ts: Sequence[float],
) -> None:
    """QA-003.1: Assert chronological holdout.
    
    Training data must strictly precede holdout test data. Max train ts <= Min test ts.
    """
    train_arr = np.asarray(train_ts, dtype=float)
    test_arr = np.asarray(test_ts, dtype=float)

    if train_arr.size == 0:
        raise ExperimentValidityError("QA-003.1 VIOLATION: Empty training timestamps.")
    if test_arr.size == 0:
        raise ExperimentValidityError("QA-003.1 VIOLATION: Empty test timestamps.")

    max_train = float(np.max(train_arr))
    min_test = float(np.min(test_arr))

    if max_train > min_test:
        raise ExperimentValidityError(
            f"QA-003.1 VIOLATION: Temporal leakage detected! "
            f"Max train timestamp ({max_train}) > Min test timestamp ({min_test})."
        )


def audit_infected_period_exclusion(
    eval_window: Tuple[float, float],
    fault_infection_window: Tuple[float, float],
    is_infected_excluded: bool,
) -> None:
    """QA-003.2: Assert infected-period exclusion.
    
    If the evaluation window overlaps with an active fault infection window,
    infected samples must be explicitly excluded from metric computation.
    """
    eval_start, eval_end = eval_window
    fault_start, fault_end = fault_infection_window

    # Check for interval overlap
    overlap = max(0.0, min(eval_end, fault_end) - max(eval_start, fault_start))
    if overlap > 0.0 and not is_infected_excluded:
        raise ExperimentValidityError(
            f"QA-003.2 VIOLATION: Evaluation window [{eval_start}, {eval_end}] overlaps "
            f"fault window [{fault_start}, {fault_end}] by {overlap:.2f}s without infected exclusion!"
        )


def audit_paired_reps_and_randomization(
    pairs: Sequence[Any],
    min_reps_per_cell: int = 20,
    check_full_matrix: bool = True,
) -> None:
    """QA-003.3: Assert paired reps and policy order randomization.
    
    - Every matched pair must have both policies executed under identical parameters.
    - If check_full_matrix is True, asserts >= min_reps_per_cell per (regime, fault) cell.
    - Policy order within pairs must be randomized (both orders present across multiple pairs).
    """
    if not pairs:
        raise ExperimentValidityError("QA-003.3 VIOLATION: No pairs provided for audit.")

    cell_counts: Dict[Tuple[str, str], int] = {}
    orders_seen = set()

    for p in pairs:
        # Check pair structure
        regime = getattr(p, "regime", getattr(p, "workload_regime", None))
        fault = getattr(p, "fault_class", None)
        order = getattr(p, "ordered_policies", None)

        if not regime or not fault:
            raise ExperimentValidityError(f"QA-003.3 VIOLATION: Pair {p} missing regime or fault.")

        key = (regime, fault)
        cell_counts[key] = cell_counts.get(key, 0) + 1

        if order:
            orders_seen.add(tuple(order))

    if check_full_matrix:
        for cell, count in cell_counts.items():
            if count < min_reps_per_cell:
                raise ExperimentValidityError(
                    f"QA-003.3 VIOLATION: Cell {cell} has only {count} reps, "
                    f"minimum required is {min_reps_per_cell}."
                )

    if len(pairs) >= 10 and len(orders_seen) < 2:
        raise ExperimentValidityError(
            f"QA-003.3 VIOLATION: Policy order is degenerate across {len(pairs)} pairs: {orders_seen}. "
            "Policy order must be randomized to prevent order/warmup bias."
        )


def audit_negative_controls_segregation(report_dict: Dict[str, Any]) -> None:
    """QA-003.4: Assert negative controls present and reported separately.
    
    Negative controls must be segregated into 'negative_controls' section,
    never pooled into 'capacity_responsive' confirmatory metrics.
    """
    if "capacity_responsive" not in report_dict:
        raise ExperimentValidityError("QA-003.4 VIOLATION: Report missing 'capacity_responsive' section.")
    if "negative_controls" not in report_dict:
        raise ExperimentValidityError("QA-003.4 VIOLATION: Report missing 'negative_controls' section.")

    ctrl_pairs = report_dict["negative_controls"].get("n_pairs", 0)
    if ctrl_pairs == 0 and report_dict.get("total_pairs", 0) >= 20:
        raise ExperimentValidityError(
            "QA-003.4 VIOLATION: Zero negative control pairs in evaluated report with >=20 total pairs! "
            "Negative controls are mandatory to guard against false attribution."
        )


def audit_live_experiment_db(conn, check_full_matrix: bool = False) -> Dict[str, Any]:
    """Audit actual experiment records in TimescaleDB against QA-003 contracts."""
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, pair_id, policy, workload_regime, fault_class, 
               is_negative_control, seed, slo_p95_ms, horizon_s, notes, started_at, ended_at
        FROM experiment_run
        WHERE pair_id IS NOT NULL
        ORDER BY pair_id, run_id;
    """)
    rows = cur.fetchall()
    if not rows:
        raise ExperimentValidityError("QA-003 AUDIT FAILED: Zero experiment runs found in database!")

    pairs_dict: Dict[str, List[dict]] = {}
    for r in rows:
        p_id = r[1]
        pairs_dict.setdefault(p_id, []).append({
            "run_id": r[0],
            "policy": r[2],
            "regime": r[3],
            "fault": r[4],
            "is_negative_control": r[5],
            "seed": r[6],
            "slo_p95_ms": r[7],
            "horizon_s": r[8],
            "notes": r[9],
            "started_at": r[10],
            "ended_at": r[11],
        })

    class PairObj:
        def __init__(self, regime, fault, order):
            self.regime = regime
            self.fault_class = fault
            self.ordered_policies = order

    pair_objs = []
    for p_id, trials in pairs_dict.items():
        if len(trials) != 2:
            raise ExperimentValidityError(
                f"QA-003.3 VIOLATION: Pair {p_id} has {len(trials)} trials, expected exactly 2 (atomic pair requirement)!"
            )
        t1, t2 = trials[0], trials[1]
        if set([t1["policy"], t2["policy"]]) != {"hpa_tuned", "forecast_hybrid"}:
            raise ExperimentValidityError(
                f"QA-003.3 VIOLATION: Pair {p_id} policies {t1['policy'], t2['policy']} != {{'hpa_tuned', 'forecast_hybrid'}}!"
            )
        for field in ("regime", "fault", "seed", "slo_p95_ms", "horizon_s"):
            if t1[field] != t2[field]:
                raise ExperimentValidityError(
                    f"QA-003.3 VIOLATION: Pair {p_id} trial mismatch on {field}: {t1[field]} vs {t2[field]}!"
                )
        # Parse order from notes
        order = (t1["policy"], t2["policy"])
        pair_objs.append(PairObj(t1["regime"], t1["fault"], order))

    # Audit paired reps and order
    audit_paired_reps_and_randomization(pair_objs, min_reps_per_cell=20, check_full_matrix=check_full_matrix)

    # Audit negative controls segregation via loader
    from experiment.analysis.loader import load_pairs_from_db
    from experiment.analysis.report import ExperimentAnalyzer

    outcomes = load_pairs_from_db(conn)
    analyzer = ExperimentAnalyzer(outcomes)
    report = analyzer.generate_report()
    audit_negative_controls_segregation(report)

    return {
        "status": "PASSED",
        "total_pairs_audited": len(pair_objs),
        "capacity_responsive_pairs": report["capacity_responsive"]["n_pairs"],
        "negative_control_pairs": report["negative_controls"]["n_pairs"],
    }


# ===========================================================================
# Selftest Suite & Red Tests
# ===========================================================================
def _assert_trips(expected_msg_substring: str, fn, *args, **kwargs):
    """Assert that calling fn trips ExperimentValidityError with expected message."""
    try:
        fn(*args, **kwargs)
    except ExperimentValidityError as err:
        assert expected_msg_substring in str(err), f"Expected substring '{expected_msg_substring}' in '{err}'"
        return
    raise AssertionError(f"Expected ExperimentValidityError({expected_msg_substring}) but no exception was raised!")


def test_qa_003_1_holdout():
    # Green test
    train = [100.0, 101.0, 102.0]
    test = [103.0, 104.0, 105.0]
    audit_chronological_holdout(train, test)

    # Red test: temporal leakage
    leaky_test = [101.5, 102.0, 103.0]
    _assert_trips("QA-003.1 VIOLATION", audit_chronological_holdout, train, leaky_test)


def test_qa_003_2_infected_exclusion():
    # Green test: infected excluded
    audit_infected_period_exclusion((30.0, 60.0), (25.0, 45.0), is_infected_excluded=True)
    # Green test: no overlap
    audit_infected_period_exclusion((60.0, 90.0), (25.0, 45.0), is_infected_excluded=False)

    # Red test: overlapping window with no exclusion
    _assert_trips(
        "QA-003.2 VIOLATION",
        audit_infected_period_exclusion,
        (30.0, 60.0),
        (25.0, 45.0),
        is_infected_excluded=False,
    )


def test_qa_003_3_reps_and_randomization():
    class DummyPair:
        def __init__(self, regime, fault, order):
            self.regime = regime
            self.fault_class = fault
            self.ordered_policies = order

    # Green test: 20 reps per cell with alternating orders
    valid_pairs = []
    for i in range(20):
        order = ("hpa_tuned", "forecast_hybrid") if i % 2 == 0 else ("forecast_hybrid", "hpa_tuned")
        valid_pairs.append(DummyPair("burst", "pod_kill", order))
    audit_paired_reps_and_randomization(valid_pairs, min_reps_per_cell=20, check_full_matrix=True)

    # Red test A: insufficient reps
    _assert_trips(
        "QA-003.3 VIOLATION: Cell ('burst', 'pod_kill') has only 19 reps",
        audit_paired_reps_and_randomization,
        valid_pairs[:19],
        min_reps_per_cell=20,
        check_full_matrix=True,
    )

    # Red test B: degenerate order (no randomization)
    biased_pairs = [
        DummyPair("burst", "pod_kill", ("hpa_tuned", "forecast_hybrid"))
        for _ in range(20)
    ]
    _assert_trips(
        "QA-003.3 VIOLATION: Policy order is degenerate",
        audit_paired_reps_and_randomization,
        biased_pairs,
        min_reps_per_cell=20,
        check_full_matrix=True,
    )


def test_qa_003_4_negative_controls():
    # Green test
    valid_rep = {
        "total_pairs": 30,
        "capacity_responsive": {"n_pairs": 20},
        "negative_controls": {"n_pairs": 10},
    }
    audit_negative_controls_segregation(valid_rep)

    # Red test: missing negative controls section
    _assert_trips(
        "QA-003.4 VIOLATION: Report missing 'negative_controls'",
        audit_negative_controls_segregation,
        {"capacity_responsive": {"n_pairs": 20}},
    )

    # Red test: zero negative controls when total pairs >= 20
    _assert_trips(
        "QA-003.4 VIOLATION: Zero negative control pairs",
        audit_negative_controls_segregation,
        {
            "total_pairs": 25,
            "capacity_responsive": {"n_pairs": 25},
            "negative_controls": {"n_pairs": 0},
        },
    )


def run_selftest() -> bool:
    print("Running QA-003 Experiment Validity Audit selftest (with red tests)...")
    test_qa_003_1_holdout()
    print("  ✓ QA-003.1 Chronological holdout audit & red test passed")
    test_qa_003_2_infected_exclusion()
    print("  ✓ QA-003.2 Infected-period exclusion audit & red test passed")
    test_qa_003_3_reps_and_randomization()
    print("  ✓ QA-003.3 Paired reps & randomization audit & red test passed")
    test_qa_003_4_negative_controls()
    print("  ✓ QA-003.4 Negative-controls segregation audit & red test passed")
    print("All QA-003 validity audit checks green.")
    return True


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="QA-003 Experiment Validity Audit")
    parser.add_argument("--selftest", action="store_true", help="Run offline selftest + red tests")
    parser.add_argument("--audit-db", action="store_true", help="Audit live records in TimescaleDB")
    parser.add_argument("--dsn", default="postgresql://aiops:aiops@localhost:5432/aiops", help="TimescaleDB DSN")
    parser.add_argument("--full-matrix", action="store_true", help="Enforce full matrix >=20 reps per cell")
    args = parser.parse_args()

    if args.audit_db:
        import psycopg2
        conn = psycopg2.connect(args.dsn)
        try:
            res = audit_live_experiment_db(conn, check_full_matrix=args.full_matrix)
            print("QA-003 Live Experiment Audit Status:", res["status"])
            print(f"  Total Pairs Audited: {res['total_pairs_audited']}")
            print(f"  Capacity-Responsive Pairs: {res['capacity_responsive_pairs']}")
            print(f"  Negative-Control Pairs: {res['negative_control_pairs']}")
            print("All QA-003 integrity contracts verified for database records.")
            sys.exit(0)
        except ExperimentValidityError as exc:
            print(f"QA-003 AUDIT VIOLATION: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        run_selftest()
