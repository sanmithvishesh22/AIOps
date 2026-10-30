"""CLI: ``python -m aiops.predict [--selftest]``.

The live path (no ``--selftest``) pulls a Contract-C window from Prometheus,
runs the chronological evaluation, and optionally writes the latest per-service
predictions.  It needs ``make up`` (Prometheus + TimescaleDB); the offline gate
never touches the network or a database.
"""
from __future__ import annotations

import argparse
import sys

from . import config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiops.predict",
        description="D3-001: predict major SLO breach within horizon H.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the offline assert-based check (no cluster, no DB)",
    )
    parser.add_argument(
        "--train-frac",
        type=float,
        default=config.TRAIN_FRAC,
        help="chronological training fraction (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=config.SEED,
        help="deterministic model seed (default: %(default)s)",
    )
    parser.add_argument(
        "--target-precision",
        type=float,
        default=config.TARGET_PRECISION,
        help="train-only precision target (default: %(default)s)",
    )
    parser.add_argument(
        "--save-model",
        metavar="PATH",
        help="persist the production-fitted predictor (joblib artifact)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write Contract-A rows for the latest per-service timestamp",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        from .selftest import run_selftest

        run_selftest()
        return 0

    args = _parser().parse_args(argv)
    from ..ingest import fetch

    from .pipeline import fit_production_predictor, run_pipeline

    frame = fetch()
    result = run_pipeline(
        frame,
        train_frac=args.train_frac,
        seed=args.seed,
        target_precision=args.target_precision,
    )
    m = result.metrics
    print(
        "predict: "
        f"pr_auc={m['pr_auc']:.4f} "
        f"holdout_precision={m['holdout_precision']:.4f} "
        f"holdout_recall={m['holdout_recall']:.4f} "
        f"threshold={m['threshold']:.4f} "
        f"target_met={m['threshold_target_met']} "
        f"train={m['train_rows']} test={m['test_rows']} "
        f"provisional={m['provisional']}"
    )
    print(
        "note: mechanics-only until D3-000.7 freezes the ⚙️ anchors; "
        "this is not a validity claim",
        file=sys.stderr,
    )

    production = fit_production_predictor(
        frame,
        seed=args.seed,
        target_precision=args.target_precision,
    )
    if args.save_model:
        production.save(args.save_model)
        print(f"saved model: {args.save_model}")

    if args.write:
        from .features import build_features
        from .inference import write_inference

        # Features need the trailing window, so build them on the whole frame
        # and then emit rows only for each service's newest timestamp.
        features, _ = build_features(frame, production.feature_cols)
        latest_keys = (
            frame.sort_values(["service", "ts"], kind="mergesort")
            .groupby("service", as_index=False)
            .tail(1)[["ts", "service"]]
        )
        latest = features.merge(
            latest_keys, on=["ts", "service"], how="inner", validate="one_to_one"
        )
        count = write_inference(production, latest)
        print(f"wrote {count} inference rows for {len(latest)} service(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
