"""Injectable Kubernetes control for remediation (ticket D4-001).

The workflow (`aiops.remediate`) never talks to the k8s API directly — it calls
this small interface only, so the offline `--selftest` runs against `FakeK8s`
with no cluster, and INT-005 swaps in `RealK8s` on the live testbed. Verification
reads (`get_rollout`) go through the same interface: 'applied' is only ever
recorded after the change is confirmed here.

v1 executes the two actions the lane actually wires — `scale` and `restart`
(flow doc: "approval -> k8s scale/restart -> audit row"). The schema's wider
`action_type` vocabulary ('rollout' | 'traffic_shift') fails loudly at
propose() time until it is implemented.

Import discipline: `kubernetes` and `aiops.common.config` are imported lazily
inside `RealK8s`, so importing this module (and the offline selftest) needs
stdlib only — same convention as store.py's lazy psycopg2.
"""
from __future__ import annotations

import uuid

# Annotation used to trigger a rolling restart — the same trick `kubectl rollout
# restart` uses, so the marker is visible on the Deployment's pod template.
RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"


class RealK8s:
    """Live adapter — official `kubernetes` client (already a base dependency:
    "scaler + remediation talk to the k8s API").

    Auth uses the standard kube config chain: the in-cluster ServiceAccount in the
    pod, kubeconfig for a local run. `request_timeout_s` bounds every API call —
    a hung call must fail, not stall the approval loop (timeout != success).
    """

    def __init__(self, namespace: str | None = None, request_timeout_s: float = 30.0):
        if namespace is None:
            from ..common import config  # lazy: env-var config only (Contract G)
            namespace = config.SOCK_NS   # the only namespace faults/remediation target
        self.namespace = namespace
        self.request_timeout_s = float(request_timeout_s)
        self._client = None

    def _api(self):
        if self._client is None:
            from kubernetes import client, config as kubeconfig  # lazy: offline runs never import it
            try:
                kubeconfig.load_incluster_config()
            except Exception:
                kubeconfig.load_kube_config()
            self._client = client.AppsV1Api()
        return self._client

    def get_rollout(self, service: str) -> dict:
        """Observed Deployment state: desired spec replicas, current/ready pods, and
        the restart marker currently on the pod template."""
        d = self._api().read_namespaced_deployment(
            service, self.namespace, _request_timeout=self.request_timeout_s)
        annotations = (d.spec.template.metadata.annotations or {})
        return {
            "desired": d.spec.replicas,
            "replicas": d.status.replicas or 0,
            "ready": d.status.ready_replicas or 0,
            "marker": annotations.get(RESTART_ANNOTATION),
        }

    def scale(self, service: str, replicas: int) -> None:
        """Set spec.replicas on the Deployment's scale subresource."""
        self._api().patch_namespaced_deployment_scale(
            service, self.namespace, {"spec": {"replicas": int(replicas)}},
            _request_timeout=self.request_timeout_s)

    def restart(self, service: str) -> str:
        """Trigger a rolling restart; returns the marker token that must appear on
        the pod template before the restart counts as confirmed."""
        token = uuid.uuid4().hex
        self._api().patch_namespaced_deployment(
            service, self.namespace,
            {"spec": {"template": {"metadata": {
                "annotations": {RESTART_ANNOTATION: token}}}}},
            _request_timeout=self.request_timeout_s)
        return token


class FakeK8s:
    """Offline double: in-memory Deployments + a call log, with knobs for the
    failure modes the selftest asserts.

    `converge=False` models a change the cluster never confirms — the case that
    must end 'failed', never 'applied'. `fail={"scale"}` models an API call that
    errors. Both are the timeout/failure paths a timeout != success rule needs.
    """

    def __init__(self, deployments: dict | None = None, converge: bool = True,
                 fail: set | None = None):
        self._deployments = {k: dict(v) for k, v in (deployments or {}).items()}
        self.converge = converge
        self.fail = set(fail or ())
        self.calls: list = []   # [("scale", svc, 5), ("get_rollout", svc), ...] — for assertions

    def _state(self, service: str) -> dict:
        return self._deployments.setdefault(
            service, {"desired": 1, "replicas": 1, "ready": 1, "marker": None})

    def get_rollout(self, service: str) -> dict:
        self.calls.append(("get_rollout", service))
        return dict(self._state(service))

    def scale(self, service: str, replicas: int) -> None:
        self.calls.append(("scale", service, int(replicas)))
        if "scale" in self.fail:
            raise RuntimeError("fake k8s: scale failed")
        state = self._state(service)
        state["desired"] = int(replicas)            # spec accepts immediately...
        if self.converge:                           # ...status only converges if the fake says so
            state["replicas"] = state["ready"] = int(replicas)

    def restart(self, service: str) -> str:
        self.calls.append(("restart", service))
        if "restart" in self.fail:
            raise RuntimeError("fake k8s: restart failed")
        n = sum(1 for c in self.calls if c[0] == "restart")
        token = f"fake-restart-{n}"
        if self.converge:
            self._state(service)["marker"] = token
        return token
