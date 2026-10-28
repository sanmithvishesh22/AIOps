"""D3-003.3/003.4 — thin, mockable apps/v1 scale client with a server-side cap.

The real client (``K8sScaleClient``) lazily imports the ``kubernetes``
package (heavy dep, only needed live) and PATCHes the ``apps/v1`` Scale
subresource once per call. Mock k8s (``MockScaleClient``) keeps the offline
selftest exhaustive (TS-2c). Retry-with-backoff lives in the CONTROLLER so
injected failures exercise the same path offline.

Boundary guarantees:
  * **Server-side cap (D3-003.4 / PS-8):** every apply clamps to
    [min, server_max] — ratified values — so no upstream policy, forecast,
    or API race can push past the hard denial-of-wallet cap.
  * **Idempotent apply:** a PATCH scale to the same number is a no-op, so a
    retry after a timeout can never double-apply (PS-4).
  * **No secrets in logs** (PS-7): only service/replicas bookkeeping.
"""
from __future__ import annotations

import logging

from . import config

logger = logging.getLogger("aiops.scaler")


class ScaleAPIError(Exception):
    """k8s scale call failed (live API error or mock-injected failure)."""


class ScaleClient:
    """Interface any scale backend must implement (mockable, per ticket)."""

    def current_replicas(self, service: str) -> int:
        raise NotImplementedError

    def scale(self, service: str, replicas: int) -> int:
        """Apply the scale; returns the replicas ACTUALLY requested (post-clamp)."""
        raise NotImplementedError


def server_clamp(replicas: int) -> int:
    """The apply-boundary cap (D3-003.4): independent of any computed target."""
    lo, hi = config.MIN_REPLICAS, config.SERVER_MAX_REPLICAS
    return int(min(max(int(replicas), lo), hi))


class K8sScaleClient(ScaleClient):
    """Live apps/v1 scale client. Needs the kubernetes package + a cluster."""

    def __init__(self, namespace: str | None = None) -> None:
        self.namespace = namespace or common_namespace()

    def _api(self):
        try:
            from kubernetes import client, config as kube_config
        except Exception as exc:
            raise RuntimeError(
                "kubernetes client not available; install requirements.txt "
                "deps and run on the testbed (make up) — offline runs use the "
                "mock client"
            ) from exc
        try:
            kube_config.load_incluster_config()
        except Exception:
            kube_config.load_kube_config()   # local dev against the kind context
        return client.AppsV1Api()

    def current_replicas(self, service: str) -> int:
        api = self._api()
        deployment = api.read_namespaced_deployment(service, self.namespace)
        return int(deployment.spec.replicas or 0)

    def scale(self, service: str, replicas: int) -> int:
        target = server_clamp(replicas)
        if target != int(replicas):
            logger.info("scaler cap clamp %s: %d -> %d", service, int(replicas), target)
        from kubernetes import client

        api = self._api()
        try:
            api.patch_namespaced_deployment_scale(
                service, self.namespace, {"spec": {"replicas": int(target)}}
            )
        except Exception as exc:
            raise ScaleAPIError(
                f"scale {service} -> {target} failed (namespace {self.namespace}): {exc}"
            ) from exc
        return target


def common_namespace() -> str:
    from ..common import config as common

    return common.SOCK_NS


class MockScaleClient(ScaleClient):
    """In-memory k8s stand-in: records every call, injectable failures.

    Enforces the SAME server-side clamp as the live client, so cap tests prove
    the boundary, not the backend. ``fail_bursts`` is a list of (service, n)
    making the next `n` scale calls for `service` raise ``ScaleAPIError``.
    """

    def __init__(
        self,
        current: dict[str, int] | None = None,
        namespace: str | None = None,
    ) -> None:
        self.namespace = namespace or common_namespace()
        self.current: dict[str, int] = dict(current or {})
        self.calls: list[tuple[str, int, int]] = []  # (service, requested, applied)
        self.fail_remaining: dict[str, int] = {}

    def fail_burst(self, service: str, count: int) -> "MockScaleClient":
        if count > 0:
            self.fail_remaining[service] = self.fail_remaining.get(service, 0) + count
        return self

    def _maybe_fail(self, service: str) -> None:
        left = self.fail_remaining.get(service, 0)
        if left > 0:
            self.fail_remaining[service] = left - 1
            raise ScaleAPIError(f"mock-injected failure for {service}")

    def current_replicas(self, service: str) -> int:
        return int(self.current.get(service, 0))

    def scale(self, service: str, replicas: int) -> int:
        target = server_clamp(replicas)
        if target != int(replicas):
            logger.info("mock cap clamp %s: %d -> %d", service, int(replicas), target)
        self._maybe_fail(service)
        self.calls.append((service, int(replicas), target))
        self.current[service] = target
        return target


__all__ = [
    "ScaleAPIError",
    "ScaleClient",
    "K8sScaleClient",
    "MockScaleClient",
    "server_clamp",
]
