"""CLI: ``python -m aiops.forecast [--selftest] [flags]``.

Offline gate: ``--selftest`` (no cluster, no DB). The live path pulls a
Contract-C window from Prometheus, forecasts per-service p95 at horizon H,
prints the instrument-quality comparison against both baselines, and
optionally writes the Contract-A rows (``--write``, needs TimescaleDB).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiops.forecast",
        description="D3-002: seasonal capacity forecast + baseline comparison.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the offline assert-based check (no cluster, no DB)",
    )
    parser.add_argument(
        "--column",
        default="p95_ms",
        help="Contract-C column to forecast (default: %(default)s; use 'rps' for load)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=None,
        help="ingest lookback minutes (default: WINDOW_MIN from Contract G)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write Contract-A rows for the newest per-service anchor",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the metrics dict as JSON (machine-readable)",
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

    from .pipeline import assert_main_beats_baselines, run_forecast

    from ..common import config as common_config

    frame = fetch(common_config.WINDOW_MIN if args.window is None else args.window)
    run = run_forecast(frame, column=args.column)
    metrics = run.metrics()
    if args.json:
        print(json.dumps(metrics, sort_keys=True))
    else:
        print(
            f"forecast: metric={metrics['metric']} "
            f"horizon_s={metrics['horizon_s']} cadence_s={metrics['cadence_s']} "
            f"season_s={metrics['season_s']} n_compared={metrics['n_compared']}"
        )
        for svc, info in metrics["services"].items():
            cmpn = info["comparison"]
            if cmpn is None:
                print(
                    f"  {svc}: model={info['model_main']} "
                    f"comparison=skipped(insufficient history) "
                    f"fallback={info['main_fallback'] or '-'}"
                )
            else:
                print(
                    f"  {svc}: model={info['model_main']} "
                    f"main={cmpn['main']:.3f} snaive={cmpn['snaive']:.3f} "
                    f"tree={cmpn['tree']:.3f} fallback={info['main_fallback'] or '-'}"
                )
    try:
        assert_main_beats_baselines(run.comparisons)
        verdict = (
            "main beats BOTH baselines on these anchors — instrument-quality; "
            "not a §9 measurement and not a reliability proof"
        )
    except (ValueError, AssertionError) as exc:
        verdict = f"comparison gate NOT met: {exc}"
    print(f"note: {verdict}", file=sys.stderr)
    print(
        "note: provisional until D3-000.7 freezes the ⚙️ anchors; "
        "this is not a validity claim",
        file=sys.stderr,
    )

    if args.write:
        from .inference import write_forecast

        count = write_forecast(run)
        print(f"wrote {count} inference rows for {len(run.per_service)} service(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
