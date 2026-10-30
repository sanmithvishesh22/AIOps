"""CLI: ``python -m experiment.load [--selftest]``.

Offline gate: ``--selftest``. ``--render <regime>`` prints the deterministic
k6 script for that regime; ``--job <regime>`` prints the Job manifest YAML.
Both are render-only: creating k8s objects requires the testbed (make up) and
belongs to the runner (D3-007).
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .regimes import build_profile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiment.load",
        description="D3-005: predeclared k6 load harness for the four §9 regimes.",
    )
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--render", metavar="REGIME",
        help=f"render the k6 script for a regime ({', '.join(config.REGIMES)})",
    )
    parser.add_argument(
        "--job", metavar="REGIME",
        help="render the k6 Job manifest YAML for a regime",
    )
    parser.add_argument("--seed", type=int, default=config.SEED)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.selftest:
        from .selftest import run_selftest

        run_selftest()
        return 0
    prof = build_profile(args.render or args.job, seed=args.seed)
    if args.render:
        from .k6script import render_script

        print(render_script(prof), end="")
    else:
        import json

        from .job import build_job

        print(json.dumps(build_job(prof), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
