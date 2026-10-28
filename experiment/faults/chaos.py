"""D3-006.2/003.4 — Chaos Mesh manifest builders for the §9 fault taxonomy.

Six ratified classes (experiment/DECISIONS.md, Decision 5):
  capacity-responsive (scaling CAN help):  ``cpu_stress``, ``pod_kill``
  negative controls  (scaling CANNOT help — a null result is CORRECT):
      ``network_fault``, ``code_fault``, ``dependency_kill``, ``memory_leak``

Every built manifest is:
  * tag-complete: `aiops.platform/fault-class` + `aiops.platform/is-negative-control`
    + `aiops.platform/run-seed` (D3-006.4 refuses to emit an untagged fault);
  * namespace-hard-scoped: built only for SOCK_NS, and the Chaos resource itself
    is created in SOCK_NS (metadata.namespace == selector namespaces == [SOCK_NS]);
  * deterministic (PS-2): timing enters as explicit parameters (the runner owns
    the seeded clock); builders hold zero randomness.

Mechanism honesty: `code_fault` maps to Chaos-Mesh HTTPChaos `abort`
(requests to the injected port fail) — true status-code 5xx replacement is a
LIVE validation item against the installed Chaos-Mesh version, recorded in the
execution ledger. `memory_leak` maps to a StressChaos memory pressure sized
below the container limit (pressure → OOM); "progressive growth" advance is a
live-tuning item. Both are labeled as approved-harness approximations pending
the testbed, never as verified §9 measurements.
"""
from __future__ import annotations

from typing import Any

from . import config
from .guard import NamespaceRefusal, assert_target_namespace


class UnknownFault(ValueError):
    """Fault class outside the ratified taxonomy — refuse to build (PS-3)."""


CHAOS_KINDS = {
    "cpu_stress": "StressChaos",
    "pod_kill": "PodChaos",
    "network_fault": "NetworkChaos",
    "code_fault": "HTTPChaos",
    "dependency_kill": "PodChaos",
    "memory_leak": "StressChaos",
}


def fault_class_or_raise(name: str) -> str:
    n = str(name).strip().lower()
    if n not in config.FAULT_CLASSES:
        raise UnknownFault(
            f"unknown fault {name!r}; ratified classes: "
            f"{', '.join(config.FAULT_CLASSES)}"
        )
    return n


def _labels(fault_class: str, seed: int) -> dict[str, str]:
    return {
        config.LABEL_PART_OF: "aiops-platform",
        config.LABEL_COMPONENT: "fault-harness",
        config.LABEL_FAULT: fault_class,
        config.LABEL_CONTROL: "true" if config.IS_NEGATIVE_CONTROL[fault_class] else "false",
        config.LABEL_SEED: str(seed),
    }


def _spec(fault_class: str, service: str, duration_s: int, seed: int) -> dict[str, Any]:
    """Chaos spec per ratified class; mode `one` limits blast radius (PS-8)."""
    selector = {"namespaces": [config.SOCK_NS], "labelSelectors": {"name": service}}
    if fault_class == "cpu_stress":
        return {
            "selector": selector,
            "mode": "one",
            "duration": f"{duration_s}s",
            "stressors": {
                "cpu": {
                    # placeholder shape — validated against the installed
                    # Chaos Mesh version in the live testbed (recorded gate)
                    "workers": int(config.CPU_WORKERS),
                    "load": int(config.CPU_LOAD_PCT),
                }
            },
        }
    if fault_class == "pod_kill":
        return {
            "selector": selector,
            "mode": "one",
            "action": "pod-kill",
            "gracePeriod": 0,
        }
    if fault_class == "network_fault":
        return {
            "selector": selector,
            "mode": "one",
            "action": "netem",
            "duration": f"{duration_s}s",
            "delay": {"latency": f"{config.NET_LATENCY_MS:.0f}ms"},
            "loss": {"loss": f"{config.NET_LOSS_PCT:.0f}", "correlation": "100"},
            "direction": "to",
        }
    if fault_class == "code_fault":
        return {
            "selector": selector,
            "mode": "one",
            "duration": f"{duration_s}s",
            "target": "Request",
            "port": 80,
            "abort": True,          # see the mechanism-honesty note in the docstring
        }
    if fault_class == "dependency_kill":
        dep = config.DEPENDENCY_TARGET
        return {
            "selector": {"namespaces": [config.SOCK_NS],
                         "labelSelectors": {"name": dep}},
            "mode": "one",
            "action": "pod-kill",
            "gracePeriod": 0,
        }
    if fault_class == "memory_leak":
        return {
            "selector": selector,
            "mode": "one",
            "duration": f"{duration_s}s",
            "stressors": {"memory": {"size": config.MEM_SIZE}},
        }
    raise UnknownFault(f"no chaos spec builder for {fault_class!r}")


def build_fault(
    fault_class: str,
    *,
    service: str,
    seed: int = 42,
    start_at_s: float | None = None,
    duration_s: int | None = None,
    run_id: str | None = None,
) -> dict:
    """Build ONE tagged Chaos-Mesh manifest (no application: offline builder).

    ``start_at_s`` is the predeclared onset inside the trial (the runner
    decides it from its seeded clock; the fault CR is created AT that tick).
    Building requires the namespace guard to pass first (D3-006.1).
    """
    key = fault_class_or_raise(fault_class)
    assert_target_namespace(config.SOCK_NS)      # guard BEFORE building (D3-006.1)
    if not service or not str(service).strip():
        raise ValueError(f"build_fault({key}): a target service is required")
    duration = int(config.FAULT_DURATION_S if duration_s is None else duration_s)
    if duration <= 0:
        raise ValueError(f"fault duration must be > 0, got {duration!r}")

    safe_key = key.replace("_", "-")
    safe_run_id = f"-{run_id.replace('_', '-').strip('-')}" if run_id else ""
    name = f"fault-{safe_key}-{seed}{safe_run_id}"
    manifest: dict[str, Any] = {
        "apiVersion": config.CHAOS_API,
        "kind": CHAOS_KINDS[key],
        "metadata": {
            "name": name,
            "namespace": config.SOCK_NS,          # chaos CR lives with its victims
            "labels": _labels(key, seed),
        },
        "spec": _spec(key, str(service).strip(), duration, seed),
    }
    apni = "aiops.platform"
    manifest["metadata"]["annotations"] = {
        f"{apni}/duration-s": str(duration),
        f"{apni}/onset-s": (
            "" if start_at_s is None else f"{float(start_at_s):.6f}"
        ),
        "aiops.platform/mechanism-note": (
            "code_fault=HTTPChaos abort; memory_leak=StressChaos memory pressure "
            "(live-validation items, see docstring)"
        ) if key in {"code_fault", "memory_leak"} else
        f"ratified class {key}; created at the runner's predeclared tick",
    }
    assert_fault(manifest)                        # never emit an untagged fault
    return manifest


def assert_fault(manifest: dict) -> None:
    """Validate tag completeness + namespace scoping (fail-closed, D3-006.4)."""
    kind = manifest.get("kind")
    if kind not in set(CHAOS_KINDS.values()):
        raise UnknownFault(f"refusing non-fault manifest kind {kind!r}")
    if manifest.get("apiVersion") != config.CHAOS_API:
        raise ValueError(f"apiVersion must be {config.CHAOS_API}")
    meta = manifest.get("metadata") or {}
    labels = meta.get("labels") or {}
    if config.LABEL_FAULT not in labels or config.LABEL_CONTROL not in labels \
            or config.LABEL_SEED not in labels:
        raise ValueError(
            f"refusing untagged fault manifest: labels must carry "
            f"{config.LABEL_FAULT}, {config.LABEL_CONTROL}, {config.LABEL_SEED} "
            "(D3-006.4)"
        )
    expected_tag = str(config.IS_NEGATIVE_CONTROL[labels[config.LABEL_FAULT]]).lower()
    if labels[config.LABEL_CONTROL] != expected_tag:
        raise ValueError(
            f"is-negative-control tag wrong for {labels[config.LABEL_FAULT]}: "
            f"{labels[config.LABEL_CONTROL]!r} != {expected_tag!r}"
        )
    ns = meta.get("namespace")
    if ns is not None and ns != config.SOCK_NS:
        raise NamespaceRefusal(
            f"chaos resource namespace {ns!r} != SOCK_NS — refuse (PS-3)"
        )
    spec = manifest.get("spec") or {}
    sel_ns = ((spec.get("selector") or {}).get("namespaces") or [])
    if sel_ns != [config.SOCK_NS]:
        raise NamespaceRefusal(
            f"chaos spec.selector.namespaces {sel_ns!r} != [\"{config.SOCK_NS}\"] "
            "— hard scope violation"
        )


def build_schedule(
    manifest: dict, *, start_iso: str, interval_s: int, seed: int = 42
) -> dict:
    """Wrap a fault manifest in a Chaos-Mesh Schedule CRD.

    ``schedule`` uses `@startingFrom <ISO> every <interval>s`; cron granularity
    caveats are a live-validation item — the runner normally creates the fault
    CR itself at the exact predeclared tick and uses schedules for KEEPALIVE
    (re-arm) semantics. Tags propagate so the run stays attributable.
    """
    assert_fault(manifest)
    spec = manifest["spec"]
    schedule = {
        "apiVersion": config.CHAOS_API,
        "kind": "Schedule",
        "metadata": {
            "name": f"schedule-{manifest['metadata']['name']}",
            "namespace": manifest["metadata"]["namespace"],
            "labels": dict(manifest["metadata"]["labels"]),
            "annotations": dict(manifest["metadata"]["annotations"]),
        },
        "spec": {
            "type": manifest["kind"],
            "schedule": f"@startingFrom {start_iso} every {int(interval_s)}s",
            "historyLimit": 1,
            "concurrencyPolicy": "Forbid",
            "scheduleSpec": {k: v for k, v in spec.items()},
        },
    }
    return schedule


__all__ = [
    "CHAOS_KINDS",
    "UnknownFault",
    "assert_fault",
    "build_fault",
    "build_schedule",
    "fault_class_or_raise",
]
