"""D3-006.1 — namespace hard guard: the first line of every fault path.

Chaos against the wrong namespace would poison the platform itself, so the
guard resolves the target namespace and REFUSES unless it is exactly
``SOCK_NS`` (Contract G; §9 Decision 5 "a fault that could touch anything
else must refuse to run"). Empty/un/unset namespaces are refused too
(fail-closed, PS-3).

The guard runs BEFORE any schedule/chaos object is built (call
:meth:`resolve_namespace` first in every builder). It reads the live
``aiops.common.config.SOCK_NS`` attribute so the env default stays one knob.
"""
from __future__ import annotations

from aiops.common import config as common


class NamespaceRefusal(Exception):
    """The requested fault target is out of scope — refuse loudly (PS-3)."""


def resolve_namespace(namespace: str | None = None) -> str:
    """Resolve the target namespace; empty/unset → refuse."""
    candidate = common.SOCK_NS if namespace is None else namespace
    if candidate is None or not str(candidate).strip():
        raise NamespaceRefusal(
            "namespace guard: no target namespace resolved (empty/unset) — "
            "refusing to touch the cluster (fail-closed, PS-3)"
        )
    return str(candidate).strip()


def assert_target_namespace(namespace: str | None = None) -> str:
    """HARD scope check: the target must be exactly SOCK_NS."""
    resolved = resolve_namespace(namespace)
    allowed = common.SOCK_NS
    if not allowed:
        raise NamespaceRefusal(
            "namespace guard: SOCK_NS itself is unset/empty — no fault target "
            "can be authorized"
        )
    if resolved != allowed:
        raise NamespaceRefusal(
            f"namespace guard: target namespace {resolved!r} != SOCK_NS "
            f"{allowed!r} — refuse (rationale: §9 Decision 5 hard scoping)"
        )
    return resolved


__all__ = ["NamespaceRefusal", "resolve_namespace", "assert_target_namespace"]
