"""Fault harness (D3-006) — Chaos Mesh harness CLI and offline selftest.

Offline gate: ``python -m experiment.faults --selftest``.
List faults: ``python -m experiment.faults --list`` (or default).
Render manifest: ``python -m experiment.faults --render <class> [--service <svc>] [--seed <seed>]``.
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .chaos import (
    assert_fault,
    build_fault,
    build_schedule,
    CHAOS_KINDS,
    fault_class_or_raise,
    UnknownFault,
)
from .config import FAULT_CLASSES, IS_NEGATIVE_CONTROL
from .guard import NamespaceRefusal, assert_target_namespace

FAULT_TEST_SERVICE = "front-end"


def run_selftest() -> None:
    """Offline selftest verifying all 6 ratified classes, tags, and namespace guards (PS-3)."""
    # 1. All ratified classes build and pass assert_fault
    for fc in FAULT_CLASSES:
        key = fault_class_or_raise(fc)
        svc = config.DEPENDENCY_TARGET if key == "dependency_kill" else FAULT_TEST_SERVICE
        manifest = build_fault(key, service=svc, seed=42)
        assert_fault(manifest)
        expected_ctrl = "true" if IS_NEGATIVE_CONTROL[key] else "false"
        assert manifest["metadata"]["labels"][config.LABEL_CONTROL] == expected_ctrl
        assert manifest["metadata"]["namespace"] == config.SOCK_NS

    # 2. Namespace hard guard: refusal on non-SOCK_NS
    for bad_ns in ("default", "aiops", "kube-system", "", " "):
        try:
            assert_target_namespace(bad_ns)
            raise AssertionError(f"assert_target_namespace({bad_ns!r}) must raise NamespaceRefusal")
        except NamespaceRefusal:
            pass

    # 3. assert_fault rejects tampered namespace
    m = build_fault("cpu_stress", service=FAULT_TEST_SERVICE, seed=42)
    bad_m = dict(m)
    bad_m["metadata"] = dict(m["metadata"], namespace="default")
    try:
        assert_fault(bad_m)
        raise AssertionError("assert_fault on foreign namespace must raise NamespaceRefusal")
    except NamespaceRefusal:
        pass

    # 4. Unknown fault class rejected
    for bad_fault in ("unknown", "disk_wipe", "cpu-stress"):
        try:
            fault_class_or_raise(bad_fault)
            raise AssertionError(f"fault_class_or_raise({bad_fault!r}) must raise UnknownFault")
        except UnknownFault:
            pass

    # 5. Schedule wrapper builds valid schedule
    m_pod = build_fault("pod_kill", service=FAULT_TEST_SERVICE, seed=42)
    sched = build_schedule(m_pod, start_iso="2026-10-30T12:00:00Z", interval_s=60, seed=42)
    assert sched["kind"] == "Schedule"
    assert sched["metadata"]["namespace"] == config.SOCK_NS
    assert sched["spec"]["scheduleSpec"]["action"] == "pod-kill"

    print("fault selftest OK — 6 ratified classes, tag completeness + namespace hard guard verified (PS-3)")


def list_faults() -> None:
    """Print the ratified fault taxonomy, control categories, and targets."""
    print("Ratified Chaos Mesh fault classes (§9 Decision 5):")
    for fc in FAULT_CLASSES:
        is_ctrl = IS_NEGATIVE_CONTROL[fc]
        cat = "negative control" if is_ctrl else "capacity-responsive"
        tgt = config.DEPENDENCY_TARGET if fc == "dependency_kill" else "front-end"
        print(f"  - {fc:<18} [{cat:<20}] target: {tgt:<10} duration: {config.FAULT_DURATION_S}s")
    print(f"All faults hard-scoped to namespace: {config.SOCK_NS} (PS-3)")
    print("Render a manifest: python3 -m experiment.faults --render <class> [--service <svc>] [--seed <seed>]")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiment.faults",
        description="D3-006: Chaos Mesh fault harness for the ratified §9 taxonomy.",
    )
    parser.add_argument("--selftest", action="store_true", help="run offline selftest + safety guard checks")
    parser.add_argument("--list", action="store_true", help="list ratified fault classes and control categories")
    parser.add_argument(
        "--render", metavar="CLASS",
        help=f"render Chaos Mesh manifest for a fault class ({', '.join(FAULT_CLASSES)})",
    )
    parser.add_argument("--service", default=None, help="target service name in sock-shop")
    parser.add_argument("--seed", type=int, default=42, help="run seed (default: 42)")
    parser.add_argument("--schedule", action="store_true", help="wrap manifest in Chaos Mesh Schedule")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.selftest:
        run_selftest()
        return 0

    if args.render:
        import yaml

        key = fault_class_or_raise(args.render)
        svc = args.service or (config.DEPENDENCY_TARGET if key == "dependency_kill" else FAULT_TEST_SERVICE)
        manifest = build_fault(key, service=svc, seed=args.seed)
        if args.schedule:
            manifest = build_schedule(manifest, start_iso="2026-10-30T12:00:00Z", interval_s=60, seed=args.seed)
        print(yaml.safe_dump(manifest, sort_keys=False), end="")
        return 0

    # Default or --list:
    list_faults()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
