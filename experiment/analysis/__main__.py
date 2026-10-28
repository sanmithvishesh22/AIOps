"""CLI entry point for experiment.analysis (D3-008)."""
import argparse
import sys

from .loader import load_pairs_from_db
from .report import ExperimentAnalyzer
from .selftest import run_selftest


def main():
    parser = argparse.ArgumentParser(description="Statistical analysis for matched pairs (D3-008)")
    parser.add_argument("--selftest", action="store_true", help="Run analysis test suite")
    parser.add_argument("--dsn", default="postgresql://aiops:aiops@localhost:5432/aiops", help="TimescaleDB DSN")
    parser.add_argument("--seed", type=int, default=42, help="Master RNG seed")
    parser.add_argument("--resamples", type=int, default=2000, help="Number of bootstrap resamples")
    args = parser.parse_args()

    if args.selftest:
        success = run_selftest()
        sys.exit(0 if success else 1)

    # Load from DB and analyze
    try:
        import psycopg2

        conn = psycopg2.connect(args.dsn)
        pairs = load_pairs_from_db(conn)
        print(f"Loaded {len(pairs)} completed matched pairs from database.")
        analyzer = ExperimentAnalyzer(pairs, n_resamples=args.resamples, seed=args.seed)
        print(analyzer.render_text())
    except Exception as e:
        print(f"Error loading or analyzing results: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
