"""DEV3 — Deadline-aware execution controller for paired trial matrix.

Orchestrates sequential execution of missing canonical matrix cells under:
- 48-hour hard deadline with 6-hour finalization reserve (42h execution budget).
- Sleep prevention via caffeinate.
- Atomic pair verification, Contract-D database audit, and cluster health checks.
- Fail-fast stop conditions on any failure, corruption, or anomaly.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Sequence

import psycopg2

from experiment.runner.pair import MatchedPair, build_matrix

logger = logging.getLogger("aiops.experiment.controller")

DEFAULT_DSN = "host=localhost port=5432 user=aiops dbname=aiops"
BASE_REPLICAS = 2
SOCK_NS = "sock-shop"
PLATFORM_NS = "aiops"
DEADLINE_HOURS = 48.0
RESERVE_HOURS = 6.0
EXEC_BUDGET_HOURS = DEADLINE_HOURS - RESERVE_HOURS
EST_PAIR_MINUTES = 41.5


def get_db_connection(dsn: str = DEFAULT_DSN):
    return psycopg2.connect(dsn)


def check_db_integrity(conn) -> tuple[bool, str, dict]:
    """Verify database integrity, run completeness, and scorecards."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM experiment_run;")
    run_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM experiment_result;")
    res_cnt = cur.fetchone()[0]

    if run_cnt != res_cnt:
        return False, f"Run count ({run_cnt}) != Result count ({res_cnt})", {}

    # Check for unmatched runs
    cur.execute("""
        SELECT r.run_id, res.run_id 
        FROM experiment_run r 
        FULL OUTER JOIN experiment_result res ON r.run_id = res.run_id
        WHERE r.run_id IS NULL OR res.run_id IS NULL;
    """)
    unmatched = cur.fetchall()
    if unmatched:
        return False, f"Found {len(unmatched)} unmatched runs/results", {}

    # Check completed pairs
    cur.execute("""
        SELECT pair_id, count(*), array_agg(policy ORDER BY policy), array_agg(run_id ORDER BY run_id)
        FROM experiment_run
        GROUP BY pair_id;
    """)
    pairs_rows = cur.fetchall()
    completed_pairs = {}
    invalid_pairs = []

    for pid, cnt, policies, run_ids in pairs_rows:
        if cnt != 2 or set(policies) != {"hpa_tuned", "forecast_hybrid"}:
            invalid_pairs.append((pid, cnt, policies, run_ids))
        else:
            completed_pairs[pid] = run_ids

    if invalid_pairs:
        return False, f"Found {len(invalid_pairs)} invalid/incomplete pairs: {invalid_pairs}", {}

    stats = {
        "total_runs": run_cnt,
        "total_results": res_cnt,
        "total_pairs": len(completed_pairs),
        "completed_pair_ids": set(completed_pairs.keys()),
    }
    return True, "DB integrity verified", stats


def check_cluster_health() -> tuple[bool, str]:
    """Verify cluster baseline: front-end at 2/2, no lingering jobs, HPAs, or faults."""
    # 1. Front-end deployment replicas
    res = subprocess.run(
        ["kubectl", "get", "deployment", "front-end", "-n", SOCK_NS, "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        return False, f"Failed to query front-end deployment: {res.stderr}"
    ready = res.stdout.strip()
    if ready != str(BASE_REPLICAS):
        return False, f"front-end readyReplicas={ready}, expected {BASE_REPLICAS}"

    # 2. Lingering loadgen Jobs
    res = subprocess.run(["kubectl", "get", "jobs", "-n", PLATFORM_NS], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        # Check if there are active jobs
        if "No resources" not in res.stderr and res.stdout.strip() != "":
            lines = [l for l in res.stdout.strip().split("\n") if not l.startswith("NAME")]
            if lines:
                return False, f"Lingering Jobs found in {PLATFORM_NS}: {lines}"

    # 3. Lingering HPAs
    res = subprocess.run(["kubectl", "get", "hpa", "-A"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        lines = [l for l in res.stdout.strip().split("\n") if not l.startswith("NAMESPACE")]
        if lines:
            return False, f"Lingering HPAs found: {lines}"

    # 4. Lingering Chaos Mesh
    for kind in ("stresschaos", "podchaos", "networkchaos", "httpchaos"):
        res = subprocess.run(["kubectl", "get", kind, "-n", SOCK_NS], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            lines = [l for l in res.stdout.strip().split("\n") if not l.startswith("NAME")]
            if lines:
                return False, f"Lingering Chaos Mesh {kind} objects: {lines}"

    # 5. Prometheus reachability
    try:
        url = "http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": 'up{job="front-end"}'})
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
            targets = len(data.get("data", {}).get("result", []))
            if targets != BASE_REPLICAS:
                return False, f"Prometheus reports {targets} targets for front-end, expected {BASE_REPLICAS}"
    except Exception as e:
        return False, f"Prometheus query failed: {e}"

    return True, "Cluster baseline healthy"


def get_matrix_coverage(db_completed_pairs: set[str], reps: int = 20, seed: int = 42) -> tuple[list[MatchedPair], list[MatchedPair], dict]:
    """Compute formal matrix coverage against canonical build_matrix."""
    canonical_matrix = build_matrix(reps=reps, master_seed=seed)
    completed_formal = [p for p in canonical_matrix if p.pair_id in db_completed_pairs]
    missing_formal = [p for p in canonical_matrix if p.pair_id not in db_completed_pairs]

    coverage_summary = {}
    for p in canonical_matrix:
        key = (p.regime, p.fault_class)
        if key not in coverage_summary:
            coverage_summary[key] = {"total": 0, "completed": 0, "reps": []}
        coverage_summary[key]["total"] += 1
        if p.pair_id in db_completed_pairs:
            coverage_summary[key]["completed"] += 1
            coverage_summary[key]["reps"].append(p.rep_index)

    return canonical_matrix, missing_formal, coverage_summary


def run_qa003_audit() -> tuple[bool, str]:
    """Execute live QA-003 audit script."""
    res = subprocess.run(
        [sys.executable, "experiment/audit.py", "--audit-db"],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        return False, f"QA-003 audit failed:\n{res.stderr}\n{res.stdout}"
    return True, res.stdout.strip()


def run_single_pair(pair: MatchedPair, dsn: str = DEFAULT_DSN) -> tuple[bool, str, str]:
    """Execute exactly one pair using the official runner wrapped in caffeinate."""
    log_file = f"live_batch_{pair.pair_id}.log"
    cmd = [
        "/usr/bin/caffeinate", "-dimsu",
        sys.executable, "-u", "-m", "experiment.runner",
        "--run", "--live",
        "--batch-size", "1",
        "--duration-s", str(pair.duration_s),
        "--seed", "42",
        "--reps", "20",
        "--dsn", dsn,
    ]

    t0 = time.time()
    logger.info("Executing pair %s -> log: %s", pair.pair_id, log_file)
    with open(log_file, "w") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)

    elapsed_s = time.time() - t0
    if proc.returncode != 0:
        return False, f"Runner failed with exit code {proc.returncode} after {elapsed_s:.1f}s", log_file

    return True, f"Completed in {elapsed_s:.1f}s", log_file


def run_controller_loop(
    max_pairs: int | None = None,
    deadline_hours: float = DEADLINE_HOURS,
    reserve_hours: float = RESERVE_HOURS,
    dsn: str = DEFAULT_DSN,
    dry_run: bool = False,
) -> int:
    """Run sequential execution loop with preflight, postflight, and stop conditions."""
    start_time = time.time()
    exec_budget_s = (deadline_hours - reserve_hours) * 3600.0

    print("==============================================================================")
    print("CAPSTONE AIOPS — DEADLINE-AWARE EXPERIMENT CONTROLLER")
    print(f"Total Deadline: {deadline_hours:.1f}h | Reserve: {reserve_hours:.1f}h | Execution Budget: {exec_budget_s/3600.0:.1f}h")
    print(f"Dry Run: {dry_run}")
    print("==============================================================================")

    pairs_executed = 0
    simulated_completed = None

    while True:
        loop_now = time.time()
        elapsed_s = loop_now - start_time
        remaining_budget_s = exec_budget_s - elapsed_s

        # Stop Condition 1: Check time budget
        if remaining_budget_s < (EST_PAIR_MINUTES * 60.0):
            print(f"\n[STOP CONDITION] Remaining execution budget ({remaining_budget_s/3600.0:.2f}h) is less than")
            print(f"one pair duration ({EST_PAIR_MINUTES:.1f}m). Halting execution to preserve final 6h reserve.")
            break

        # Stop Condition 2: Max pairs limit
        if max_pairs is not None and pairs_executed >= max_pairs:
            print(f"\n[TARGET REACHED] Reached requested max_pairs limit ({max_pairs}). Stopping.")
            break

        # Preflight 1: DB integrity
        conn = get_db_connection(dsn)
        ok, msg, db_stats = check_db_integrity(conn)
        if not ok:
            print(f"\n[STOP CONDITION: DB INTEGRITY] {msg}")
            return 1

        if simulated_completed is None:
            simulated_completed = set(db_stats["completed_pair_ids"])

        # Preflight 2: Matrix coverage & next cell
        matrix, missing, coverage = get_matrix_coverage(simulated_completed if dry_run else db_stats["completed_pair_ids"])
        if not missing:
            print("\n[ALL COMPLETE] All 480 formal matrix cells completed!")
            break

        next_pair = missing[0]

        # Preflight 3: Cluster health
        ok, msg = check_cluster_health()
        if not ok:
            print(f"\n[STOP CONDITION: CLUSTER HEALTH] {msg}")
            return 1

        # Preflight 4: QA-003 audit
        ok, msg = run_qa003_audit()
        if not ok:
            print(f"\n[STOP CONDITION: QA-003 AUDIT] {msg}")
            return 1

        print(f"\n--- [Pair {pairs_executed + 1}] Next Target: {next_pair.pair_id} ---")
        print(f"  Regime: {next_pair.regime} | Fault: {next_pair.fault_class} | Rep: {next_pair.rep_index}")
        print(f"  Seed: {next_pair.seed} | Order: {next_pair.ordered_policies} | Duration: {next_pair.duration_s}s")
        print(f"  Progress: {len(matrix) - len(missing)}/{len(matrix)} completed ({len(missing)} remaining)")
        print(f"  Execution Time Elapsed: {elapsed_s/3600.0:.2f}h | Remaining Budget: {remaining_budget_s/3600.0:.2f}h")

        if dry_run:
            print("  [DRY RUN] Invariants satisfied. Skipping physical execution.")
            simulated_completed.add(next_pair.pair_id)
            pairs_executed += 1
            if max_pairs is not None and pairs_executed >= max_pairs:
                break
            continue

        # Execute Pair
        pre_runs_cnt = db_stats["total_runs"]
        ok, msg, log_file = run_single_pair(next_pair, dsn=dsn)
        if not ok:
            print(f"\n[STOP CONDITION: EXECUTION FAILURE] {msg}")
            print(f"Preserved execution log: {log_file}")
            return 1

        # Postflight 1: Verify DB records
        ok, msg, new_db_stats = check_db_integrity(conn)
        if not ok:
            print(f"\n[STOP CONDITION: POST-EXEC DB CORRUPTION] {msg}")
            return 1

        if new_db_stats["total_runs"] != pre_runs_cnt + 2:
            print(f"\n[STOP CONDITION: RUN COUNT ANOMALY] Expected {pre_runs_cnt + 2} runs, found {new_db_stats['total_runs']}")
            return 1

        if next_pair.pair_id not in new_db_stats["completed_pair_ids"]:
            print(f"\n[STOP CONDITION: PAIR PERSISTENCE FAILURE] Pair {next_pair.pair_id} not found in completed pairs")
            return 1

        # Postflight 2: Cluster cleanup check
        ok, msg = check_cluster_health()
        if not ok:
            print(f"\n[STOP CONDITION: POST-EXEC CLUSTER DIRTY] {msg}")
            return 1

        # Postflight 3: QA-003 Audit
        ok, msg = run_qa003_audit()
        if not ok:
            print(f"\n[STOP CONDITION: POST-EXEC AUDIT FAILURE] {msg}")
            return 1

        pairs_executed += 1
        rate = pairs_executed / ((time.time() - start_time) / 3600.0)
        feasible_remaining = int(remaining_budget_s / (EST_PAIR_MINUTES * 60.0))
        print(f"✓ Pair {next_pair.pair_id} successfully verified. Rate: {rate:.2f} pairs/h. Est feasible remaining: ~{feasible_remaining} pairs.")

    print("\n==============================================================================")
    print(f"CONTROLLER RUN SUMMARY: Executed {pairs_executed} pairs.")
    print("==============================================================================")
    return 0


def main():
    parser = argparse.ArgumentParser(description="DEV3 Deadline-Aware Controller")
    parser.add_argument("--dry-run", action="store_true", help="Perform preflight checks without launching trials")
    parser.add_argument("--max-pairs", type=int, default=None, help="Maximum pairs to execute")
    parser.add_argument("--deadline-hours", type=float, default=DEADLINE_HOURS, help="Total deadline in hours")
    parser.add_argument("--reserve-hours", type=float, default=RESERVE_HOURS, help="Finalization reserve in hours")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="Postgres/TimescaleDB connection string")
    parser.add_argument("--status", action="store_true", help="Print matrix coverage and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.status:
        conn = get_db_connection(args.dsn)
        ok, msg, stats = check_db_integrity(conn)
        if not ok:
            print(f"DB Error: {msg}")
            sys.exit(1)
        matrix, missing, coverage = get_matrix_coverage(stats["completed_pair_ids"])
        print(f"Formal Matrix Cells: {len(matrix)} total, {len(matrix) - len(missing)} completed, {len(missing)} remaining.")
        print("\nCoverage Breakdown by Regime & Fault:")
        for (regime, fault), c in sorted(coverage.items()):
            reps_str = ", ".join(map(str, sorted(c["reps"]))) if c["reps"] else "None"
            print(f"  {regime:11s} × {fault:15s}: {c['completed']:2d}/{c['total']:2d} ({c['completed']/c['total']*100:5.1f}%) | Reps: {reps_str}")
        if missing:
            nxt = missing[0]
            print(f"\nNext Canonical Missing Cell: {nxt.pair_id} ({nxt.regime} × {nxt.fault_class}, rep {nxt.rep_index}, seed {nxt.seed})")
        sys.exit(0)

    code = run_controller_loop(
        max_pairs=args.max_pairs,
        deadline_hours=args.deadline_hours,
        reserve_hours=args.reserve_hours,
        dsn=args.dsn,
        dry_run=args.dry_run,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
