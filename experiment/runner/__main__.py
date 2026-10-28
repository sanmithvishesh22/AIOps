"""CLI entry point for experiment.runner (D3-007 / INT-004)."""
from __future__ import annotations

import argparse
import logging
import sys

from . import config
from .pair import build_matrix
from .runner import MockTrialExecutor, PairedRunner
from .selftest import selftest
from .store import PostgresResultsStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired trial runner (D3-007 / INT-004)")
    parser.add_argument("--selftest", action="store_true", help="Run offline selftest")
    parser.add_argument("--status", action="store_true", help="Report completed vs pending pairs in store")
    parser.add_argument("--run", action="store_true", help="Execute trial matrix batches")
    parser.add_argument("--live", action="store_true", help="Use live Kubernetes/Chaos/k6 executor (default is mock)")
    parser.add_argument("--batch-size", type=int, default=1, help="Max pairs to run in this batch")
    parser.add_argument("--duration-s", type=int, default=60, help="Duration per trial in seconds")
    parser.add_argument("--reps", type=int, default=config.MIN_REPS_PER_CELL, help="Reps per matrix cell")
    parser.add_argument("--seed", type=int, default=config.MASTER_SEED, help="Master RNG seed")
    parser.add_argument("--regimes", nargs="*", default=list(config.REGIMES), help="Regimes to include")
    parser.add_argument("--faults", nargs="*", default=list(config.FAULT_CLASSES), help="Faults to include")
    parser.add_argument("--dsn", default=config.TIMESCALE_DSN, help="TimescaleDB DSN")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.selftest:
        selftest()
        return

    store = PostgresResultsStore(args.dsn)

    if args.status:
        matrix = build_matrix(reps=args.reps, master_seed=args.seed, regimes=args.regimes, faults=args.faults)
        completed = store.get_completed_pair_ids()
        print(f"Total pairs in filtered matrix ({args.reps} reps/cell): {len(matrix)}")
        print(f"Completed pairs in DB: {len(completed)}")
        print(f"Remaining pairs: {len(matrix) - len(completed.intersection({p.pair_id for p in matrix}))}")
        return

    if args.run:
        if args.duration_s != config.TRIAL_DURATION_S:
            from experiment.load import config as load_config
            load_config.set_duration(args.duration_s)

        if args.live:
            from .live import LiveTrialExecutor
            executor = LiveTrialExecutor()
            print(f"Starting LIVE execution batch (size={args.batch_size}, duration={args.duration_s}s)...")
        else:
            executor = MockTrialExecutor()
            print(f"Starting MOCK execution batch (size={args.batch_size}, duration={args.duration_s}s)...")

        runner = PairedRunner(
            store=store,
            executor=executor,
            reps_per_cell=args.reps,
            master_seed=args.seed,
            regimes=args.regimes,
            faults=args.faults,
            duration_s=args.duration_s,
        )

        stats = runner.run_matrix(limit_pairs=args.batch_size)
        print("Batch execution finished:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
