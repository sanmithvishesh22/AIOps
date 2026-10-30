"""Offline selftest for D3-003 (python -m aiops.scaler --selftest).

Mock-k8s + assert-based, no cluster, no DB, no driver (TS-1/TS-2c). The selftest
injects a **clearly-provenanced TEST anchor** (``selftest_provisional``) — it is
NOT the ⚙️ ratified capacity and must never be treated as one; the fail-closed
provisional mode is itself tested (TS-3).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

from ..common import store
from ..common.fixtures import _KINDS
from . import config
from .cooldown import CooldownState, clamp_bounds, gate_scale, resolve_direction
from .controller import KIND, MODULE, ScalerController
from .k8s import MockScaleClient
from .k8s import server_clamp
from .policy import CapacityAnchor, PolicyRefusal, desired_replicas

# mechanics-only test anchor (TS-6): never a §9 value
TEST_ANCHOR = CapacityAnchor(rps_per_replica=120.0, provenance="selftest_provisional")

# red-test template (TS-3): bounds deliberately wrong => parity must fail loud
BAD_MANIFEST_TEMPLATE = """apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-bad
  namespace: sock-shop
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: front-end
  minReplicas: {lo}
  maxReplicas: {hi}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
    scaleDown:
      stabilizationWindowSeconds: 300
"""


def _anchor(rps: float = 120.0) -> CapacityAnchor:
    return CapacityAnchor(rps_per_replica=rps, provenance="selftest_provisional")


def _linear_rps_frame(
    services: dict[str, float],
    n: int = 60,
    end_ts: float = 5000.0,
) -> pd.DataFrame:
    """Frame whose `rps` is EXACTLY linear: the harmonic fit then extrapolates
    a known value at horizon H (slope 0.05 rps/step × 8 steps ≈ +0.4)."""
    from ..common import config as common

    cadence = int(common.STEP_S)
    rows = []
    for service, value_at_end in services.items():
        vals = value_at_end + 0.05 * (np.arange(n, dtype=float) - (n - 1))
        ts = end_ts - cadence * (n - 1) + cadence * np.arange(n, dtype=float)
        rows.append(pd.DataFrame({
            "ts": ts, "service": service, "rps": vals,
            "p95_ms": 100.0, "error_rate": 0.0, "cpu": 0.1, "mem": 0.1,
            "replicas": 2.0,
        }))
    return pd.concat(rows, ignore_index=True).sort_values(["ts", "service"])


# ---------------------------------------------------------------------------
def _check_policy_table() -> None:
    """TS-3 table-driven cases: forecast → expected replicas (pure, deterministic)."""
    cases = [
        # (forecast_rps, last_good, expected, held, clamped)
        (84.0, 3, 2, False, True),     # ceil(84/84)=1 -> min clamp 2
        (168.0, 3, 2, False, False),   # ceil(168/84)=2 exactly
        (840.0, 3, 10, False, False),  # ceil(10.0)=10 exactly at max (no clamp)
        (900.0, 3, 10, False, True),   # ceil(900/84)=11 -> hard max clamp
        (float("nan"), 3, 3, True, False),   # NaN -> hold last good
        (-5.0, 3, 3, True, False),           # negative -> hold last good
        (float("inf"), 3, 3, True, False),
        (0.0, 4, 4, True, False),            # zero -> hold
    ]
    for fc_rps, last_good, expect, held, clamped in cases:
        d = desired_replicas(fc_rps, TEST_ANCHOR, last_known_good=last_good)
        assert d.replicas == expect, (fc_rps, d)
        assert d.held is held and d.clamped is clamped, (fc_rps, d)

    # missing anchor -> loud refusal, never a scored target (pre-D3-000.7)
    try:
        desired_replicas(84.0, None, last_known_good=3)
        raise AssertionError("missing anchor must refuse")
    except PolicyRefusal as exc:
        assert "capacity anchor" in str(exc)

    # bad forecast AND nothing known-good -> refusal
    try:
        desired_replicas(float("nan"), TEST_ANCHOR, last_known_good=None)
        raise AssertionError("unholdable bad forecast must refuse")
    except PolicyRefusal as exc:
        assert "no last-known-good" in str(exc)

    # bounds parameterizable (still clamped); min>max is loud
    d = desired_replicas(500.0, TEST_ANCHOR, bounds=(1, 5))
    assert d.replicas == 5 and d.clamped
    try:
        desired_replicas(1.0, TEST_ANCHOR, bounds=(5, 1))
        raise AssertionError("min>max must raise")
    except ValueError:
        pass


def _check_cooldown_and_bounds() -> None:
    """TS-3: flapping forecasts are cooled; bounds clamp before any API call."""
    empty = CooldownState()
    after_up = CooldownState(last_scale_ts=1000.0, last_replicas=3, last_direction="up")

    allowed, why = gate_scale(4, empty, now_ts=1000.0)
    assert allowed and why.endswith("first_action")

    allowed, why = gate_scale(4, after_up, now_ts=1000.0 + 10)
    assert not allowed and "cooldown_blocked" in why, "must block within 30s up window"
    allowed, _ = gate_scale(4, after_up, now_ts=1000.0 + 30)
    assert allowed, "must allow after the 30 s up cooldown"

    down_state = CooldownState(
        last_scale_ts=1000.0, last_replicas=8, last_direction="down"
    )
    allowed, why = gate_scale(5, down_state, now_ts=1000.0 + 299)
    assert not allowed and why.startswith("down_cooldown_blocked")
    allowed, _ = gate_scale(5, down_state, now_ts=1000.0 + 300)
    assert allowed, "down cooldown is 300 s, not 30"

    allowed, why = gate_scale(3, after_up, now_ts=1000.0 + 1)
    assert allowed and why == "no_change", "no-op targets are never throttled"

    v, clamped = clamp_bounds(11)
    assert v == 10 and clamped
    v, clamped = clamp_bounds(0)
    assert v == 2 and clamped
    v, clamped = clamp_bounds(7)
    assert v == 7 and not clamped

    assert resolve_direction(5, CooldownState(last_replicas=3)) == "up"
    assert resolve_direction(2, CooldownState(last_replicas=3)) == "down"
    assert resolve_direction(3, CooldownState(last_replicas=3)) == "none"


def _check_server_cap() -> None:
    """TS-3 (D3-003.4): the boundary clamp is un-bypassable."""
    for malicious in (11, 999, 10 ** 6, -1, 0):
        applied = server_clamp(malicious)
        assert 2 <= applied <= config.SERVER_MAX_REPLICAS, (malicious, applied)
    mock = MockScaleClient(current={"front-end": 2})
    for malicious in (999, 10 ** 6, -1):
        ret = mock.scale("front-end", malicious)
        assert ret == min(max(malicious, 2), config.SERVER_MAX_REPLICAS)
        assert mock.calls[-1][2] == ret


def _check_controller_run() -> None:
    """Mock-k8s integration: bounded, cooldown-respecting, cap honored, rows."""
    frame = _linear_rps_frame({"front-end": 300.0})
    client = MockScaleClient(current={"front-end": 2})
    anchor = _anchor()
    controller = ScalerController(
        client,
        anchor_rps=anchor.rps_per_replica,
        anchor_provenance=anchor.provenance,
    )
    now = float(frame["ts"].max())
    run = controller.run(frame, now_ts=now)

    # scored targets are bounded and coherent
    assert not run.errors
    assert not run.refused, "test anchor injected -> scored mode"
    target = run.outcomes[0].target
    assert target is not None and 2 <= target <= config.MAX_REPLICAS, run.outcomes
    assert target >= 3, f"upward forecast must scale up: {target}"

    # scale call happened once, for front-end
    assert len(client.calls) == 1 and client.calls[0][0] == "front-end"

    # Contract-A row with the D3-003.5 meta shape
    store.normalize(run.rows)
    row = run.rows[-1]
    assert row["module"] == MODULE and row["kind"] == KIND
    assert row["kind"] in _KINDS["scaler"], "vocabulary respected"
    assert row["value"] == target
    meta = row["meta"]
    for key in ("current", "reason", "cooldown_s", "bounds", "seed"):
        assert key in meta, f"{key} missing from replicas_target meta"
    assert meta["bounds"] == [config.MIN_REPLICAS, config.MAX_REPLICAS]
    assert meta["current"] == 2
    assert meta["provisional"] is True and meta["instrument_quality"] is True
    assert meta["anchor_provenance"].endswith("selftest_provisional")

    before = [(r["ts"], r["service"], r["kind"], r["value"], str(r["meta"])) for r in run.rows]

    # PS-2 determinism: SAME inputs (fresh controller + fresh client state)
    # -> byte-identical rows
    client_fresh = MockScaleClient(current={"front-end": 2})
    controller_fresh = ScalerController(
        client_fresh,
        anchor_rps=anchor.rps_per_replica,
        anchor_provenance=anchor.provenance,
    )
    run_fresh = controller_fresh.run(frame, now_ts=now)
    after = [(r["ts"], r["service"], r["kind"], r["value"], str(r["meta"])) for r in run_fresh.rows]
    assert after == before, "same inputs must reproduce identical rows"

    # PS-4 settled replay on the SAME controller: target equals the applied
    # count, so the gate says no_change and NO new scale call happens
    run_settled = controller.run(frame, now_ts=now)
    assert len(client.calls) == 1, "no supplemental scale call on a settled target"
    assert all(o.target == run.outcomes[0].target for o in run_settled.outcomes
               if o.target is not None), "settled replay keeps the same target"

    # cooldown: a fresh spike inside the 30 s above window must hold, not flap
    state = controller._state["front-end"]
    allowed, why = gate_scale(6, state, now_ts=now + 15)
    assert not allowed and "cooldown_blocked" in why


def _check_failures_and_fail_closed() -> None:
    """TS-3: failure injection -> no crash/no half-apply; provisional mode fail-closed."""
    sleeps: list[float] = []
    now = 5000.0

    def build(svc_pair: tuple[str, str] = ("a-service", "front-end")) -> ScalerController:
        client = MockScaleClient(
            current={"a-service": 2, "front-end": 2},
        )
        return ScalerController(
            client,
            anchor_rps=_anchor().rps_per_replica,
            anchor_provenance=_anchor().provenance,
            services=svc_pair,
            sleep=sleeps.append,
        )

    frame = _linear_rps_frame({"a-service": 300.0, "front-end": 300.0})
    # a-service fails EVERY attempt -> batch aborts, front-end untouched
    controller = build()
    client = controller.client  # type: ignore[assignment]
    client.fail_burst("a-service", config.MAX_ATTEMPTS)
    run = controller.run(frame, now_ts=now + config.COOLDOWN_UP_S + 1)
    assert run.errors, "a-service must abort the batch"
    assert not any(s == "front-end" for s, _r, _a in client.calls), \
        "no scale call may hit later services after an abort (no half-apply)"
    assert len(sleeps) == config.MAX_ATTEMPTS - 1, f"backoff between retries: {sleeps}"

    # transient failure recovers on retry (backoff then success)
    client2 = MockScaleClient(current={"front-end": 2})
    client2.fail_burst("front-end", 1)
    c2 = ScalerController(
        client2,
        anchor_rps=_anchor().rps_per_replica,
        anchor_provenance=_anchor().provenance,
        sleep=sleeps.append,
    )
    run2 = c2.run(
        _linear_rps_frame({"front-end": 300.0}), now_ts=now + 10_000.0
    )
    assert not run2.errors and run2.applied == ["front-end"], \
        "retry after a transient failure must apply"

    # fail-closed provisional mode: NO anchor -> refusals, zero scored rows
    client3 = MockScaleClient(current={"front-end": 2})
    c3 = ScalerController(client3, anchor_rps=None)
    run3 = c3.run(
        _linear_rps_frame({"front-end": 300.0}), now_ts=now
    )
    assert run3.rows == [], "provisional mode must never write scored rows"
    assert all(o.target is None for o in run3.outcomes)
    assert any("capacity anchor" in (o.error or "") for o in run3.outcomes), \
        "refusal must name the missing ⚙️ anchor"

    # env default scope (Decision 1 primary SLO)
    assert config.SERVICES == ("front-end",)


def _check_hpa_parity() -> None:
    """D3-004.3: automated diff — HPA bounds == scaler bounds, offline,
    plus its TS-3 red test (a mismatching manifest must fail loud)."""
    import tempfile

    from .parity import check_hpa_parity

    infos = check_hpa_parity()
    assert infos, "at least one hpa-*.yaml must be parity-checked"
    for info in infos:
        assert info["bounds"] == (config.MIN_REPLICAS, config.MAX_REPLICAS)

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp) / "base"
        base.mkdir()
        bad = base / "hpa-front-end.yaml"
        bad.write_text(
            BAD_MANIFEST_TEMPLATE.format(lo=1, hi=config.MAX_REPLICAS)
        )
        try:
            check_hpa_parity(base)
            raise AssertionError("bounds mismatch must fail loudly (fairness guard)")
        except AssertionError:
            pass
        # red test #2: empty directory (no manifests) must fail loud
        try:
            check_hpa_parity(base.parent)
            raise AssertionError("missing manifests must fail loudly")
        except (AssertionError, OSError):
            pass


def run_selftest() -> None:
    _check_policy_table()
    _check_cooldown_and_bounds()
    _check_server_cap()
    _check_controller_run()
    _check_failures_and_fail_closed()
    _check_hpa_parity()
    print(
        "scaler selftest OK — mock-k8s bounded+cooled targets, server cap "
        f"={config.SERVER_MAX_REPLICAS}, fail-closed without ⚙️ anchor, "
        "rows on scaler/replicas_target, deterministic replays, "
        "HPA bounds parity (D3-004.3)"
    )


if __name__ == "__main__":
    run_selftest()
