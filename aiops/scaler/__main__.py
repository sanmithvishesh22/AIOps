"""CLI: ``python -m aiops.scaler [--selftest]``.

Offline gate: ``--selftest`` (mock k8s). The live path pulls a Contract-C
window, computes per-service desired replicas from the forecast ⚙️ capacity
anchor (fail-closed when absent), applies them via apps/v1, and writes the
``scaler/replicas_target`` rows (needs the cluster + TimescaleDB; `make up`).
"""
from __future__ import annotations

import argparse
import sys

from . import config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiops.scaler",
        description="D3-003: forecast-assisted hybrid scaler (live needs a cluster).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the offline mock-k8s assert-based check (no cluster, no DB)",
    )
    parser.add_argument(
        "--services",
        default=",".join(config.SERVICES),
        help="comma-separated services to manage (default: %(default)s)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write replicas_target Contract-A rows (needs TimescaleDB)",
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

    from .controller import ScalerController
    from .k8s import K8sScaleClient

    frame = fetch()
    controller = ScalerController(
        K8sScaleClient(),
        anchor_rps=config.CAPACITY_RPS,
        anchor_provenance="env:SCALER_CAPACITY_RPS" if config.CAPACITY_RPS else None,
        services=tuple(s.strip() for s in args.services.split(",") if s.strip()),
    )
    run = controller.run(frame)
    for outcome in run.outcomes:
        line = (
            f"{outcome.service}: current={outcome.current} "
            f"target={outcome.target} reason={outcome.reason}"
        )
        print(line)
    for err in run.errors:
        print(f"error: {err}", file=sys.stderr)
    if config.CAPACITY_RPS is None:
        print(
            "note: ⚙️ per-replica capacity anchor absent (D3-000.5 pending) — "
            "fail-closed scored mode, no replica targets applied",
            file=sys.stderr,
        )
    note = (
        "scaler actions are mechanics-provisional until D3-000.7 freezes the "
        "anchors; this is not a validity claim"
    )
    print(f"note: {note}", file=sys.stderr)

    if args.write:
        count = controller.write_rows(run)
        print(f"wrote {count} replicas_target inference rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
