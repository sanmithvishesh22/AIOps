"""Module 6 — human-approved remediation (ticket D4-001).

One human gate, no autonomy, four stages:

    propose()  -> INSERT a 'proposed' row carrying the Contract-F evidence bundle
    approve()  -> the ONLY path to 'approved' (explicit human, decided_by named)
    reject()   -> terminal 'rejected'; can never execute afterwards
    execute()  -> ONLY from 'approved': apply via the injected k8s interface,
                  then verify through that same interface before 'applied' is written

Guardrails (do not weaken):
  - human-approved, never autonomous: nothing executes without an explicit
    approve() naming the accountable person. Approval is ACCOUNTABILITY, not
    safety — it does not make the action correct, harmless, or "proven safe".
  - exactly-once: duplicate or concurrent approvals execute once — the store's
    run_execution holds a row lock and refuses any action that is not 'approved'.
  - timeout != success: if the change is not CONFIRMED in-cluster inside the
    bounded window, the action is recorded 'failed' and applied_at stays NULL.
  - append-only audit: the lifecycle only moves forward (proposed -> approved |
    rejected -> applied | failed) through the remediation_action store; there is
    no delete or rewrite path (experiment/schema.sql enforces this in the DB too).

Contract F — evidence bundle, smallest pinned shape (proposed clarification,
also written up in aiops/remediate/README.md): the raw Contract-A inference rows
that justify the action, one per slot —

    {"service": <target>, "as_of": <newest row ts>,
     "anomaly": <detect row>, "rca": <rca row>, "prediction": <predict row>,
     "forecast": <forecast row>}        # forecast is optional

`build_evidence(service, rows)` assembles it from Contract-A rows (store.recent()
shape); `validate_evidence()` fails loudly on a malformed bundle at propose()
time. Reads use only the frozen Contract-A vocabulary. The bundle documents the
reasoning for the operator; it does not make the action autonomous.

Offline check: `python -m aiops.remediate --selftest` — stdlib only (no cluster,
no DB, no third-party imports): mock k8s (FakeK8s) + in-memory append-only store
(InMemoryAudit). Proves: no approval -> no execution; duplicate approval ->
exactly one execution (incl. a concurrent attempt); timeout -> failed, never
applied; applied only after verification; audit appended/forward-only, never
overwritten.
"""
from __future__ import annotations

import time

from .errors import InvalidInput, RemediateError, StateError  # noqa: F401  (re-export)
from .audit import InMemoryAudit, PgAudit  # noqa: F401  (re-export)
from .k8s import FakeK8s, RealK8s  # noqa: F401  (re-export)

# v1 executes exactly these; the schema's wider vocabulary ('rollout',
# 'traffic_shift') fails loudly at propose() time until it is implemented.
ACTIONS = ("scale", "restart")

DEFAULT_EXECUTE_TIMEOUT_S = 30.0   # bounded confirmation window; timeout != success
DEFAULT_POLL_S = 0.5

# Contract-A slots the Contract-F bundle may carry: slot -> (module, accepted kinds).
# `_PREFERRED` picks the most actionable kind when several rows exist (newest wins
# within a kind). Vocabulary mirrors Contract A / aiops.common.fixtures._KINDS.
_SLOTS = {
    "anomaly":    ("detect",   ("anomaly_flag", "anomaly_score", "anomaly_score_seq")),
    "rca":        ("rca",      ("culprit_rank",)),
    "prediction": ("predict",  ("breach_prob", "breach_duration_est")),
    "forecast":   ("forecast", ("forecast_p95", "forecast_p95_snaive", "forecast_p95_tree")),
}
_PREFERRED = {"anomaly": ("anomaly_flag",), "prediction": ("breach_prob",),
              "forecast": ("forecast_p95",)}
_REQUIRED_SLOTS = ("anomaly", "rca", "prediction")   # Contract F: anomaly + culprit + prediction


def _evidence_row(row: dict) -> dict:
    """Normalize to the exact Contract-A row shape (the columns store.recent returns)."""
    return {"ts": row["ts"], "module": row["module"], "service": row["service"],
            "kind": row["kind"], "value": row.get("value"), "meta": row.get("meta")}


def build_evidence(service: str, rows) -> dict:
    """Assemble the Contract-F bundle from Contract-A inference rows for `service`
    (rows in store.recent() shape). Picks the preferred kind when present, else the
    newest row of an accepted kind. Raises InvalidInput when a required slot
    (anomaly, rca, prediction) has no row — an action is never proposed on half an
    argument. For a cross-service bundle (e.g. the culprit is another service),
    pass a ready bundle to propose(evidence=...)."""
    picked = {}
    for slot, (module, kinds) in _SLOTS.items():
        candidates = [r for r in rows
                      if r.get("service") == service and r.get("module") == module
                      and r.get("kind") in kinds]
        if not candidates:
            picked[slot] = None
            continue
        for kind in _PREFERRED.get(slot, ()):       # most actionable kind wins
            preferred = [r for r in candidates if r["kind"] == kind]
            if preferred:
                candidates = preferred
                break
        picked[slot] = max(candidates, key=lambda r: float(r["ts"]))
    missing = [s for s in _REQUIRED_SLOTS if picked[s] is None]
    if missing:
        raise InvalidInput(f"evidence incomplete for {service!r}: missing "
                           f"{'/'.join(missing)} row(s) in the supplied inference rows")
    bundle = {"service": service,
              "as_of": max(float(r["ts"]) for r in picked.values() if r is not None)}
    for slot in _SLOTS:                              # forecast only when present
        if picked[slot] is not None:
            bundle[slot] = _evidence_row(picked[slot])
    return bundle


def validate_evidence(evidence) -> None:
    """Loud check of the Contract-F bundle before it reaches the audit row — a
    malformed bundle must fail at propose(), not sit wrong in the log."""
    if not isinstance(evidence, dict):
        raise InvalidInput("evidence must be a dict (Contract-F bundle)")
    if not isinstance(evidence.get("service"), str) or not evidence["service"]:
        raise InvalidInput("evidence must name the service it is about")
    if not isinstance(evidence.get("as_of"), (int, float)):
        raise InvalidInput("evidence needs a numeric as_of (unix seconds)")
    for slot in _SLOTS:
        row = evidence.get(slot)
        if row is None:
            if slot in _REQUIRED_SLOTS:
                module, kinds = _SLOTS[slot]
                raise InvalidInput(f"evidence has no {slot!r} row — expected a Contract-A "
                                   f"{module} row with kind in {kinds}")
            continue
        module, kinds = _SLOTS[slot]
        if not isinstance(row, dict) or row.get("module") != module or row.get("kind") not in kinds:
            raise InvalidInput(f"evidence {slot!r} must be a Contract-A {module} row with "
                               f"kind in {kinds}, got module={row.get('module') if isinstance(row, dict) else row!r}")
        if not isinstance(row.get("ts"), (int, float)):
            raise InvalidInput(f"evidence {slot!r} needs a numeric ts")


def _validate_params(action_type: str, params) -> dict:
    """Server-side validation before anything is stored — the approval UI is never
    trusted with what reaches the cluster (SEC-001: reject invalid settings early)."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise InvalidInput("params must be a dict")
    if action_type == "scale":
        if set(params) != {"replicas"}:
            raise InvalidInput("scale params must be exactly {'replicas': <int >= 0>}")
        replicas = params["replicas"]
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 0:
            raise InvalidInput("scale params['replicas'] must be an int >= 0")
        return {"replicas": replicas}
    if params:
        raise InvalidInput(f"{action_type} takes no params in v1, got {sorted(params)}")
    return {}


def propose(store, service: str, action_type: str, params=None, *,
            evidence: dict | None = None, rows=None, run_id: int | None = None) -> int:
    """Stage 1 — record a 'proposed' action and its evidence bundle. Nothing here
    touches the cluster. Pass `rows` (Contract-A inference rows around the
    incident) to assemble the bundle, or a ready `evidence` bundle — not both.
    Returns the new action_id."""
    if not isinstance(service, str) or not service.strip():
        raise InvalidInput("service must be a non-empty string")
    if action_type not in ACTIONS:
        raise InvalidInput(f"action_type must be one of {ACTIONS} in v1 (the schema "
                           f"vocabulary 'rollout'|'traffic_shift' is not implemented yet), "
                           f"got {action_type!r}")
    params = _validate_params(action_type, params)
    if evidence is not None and rows is not None:
        raise InvalidInput("pass evidence= or rows=, not both")
    if evidence is None:
        if rows is None:
            raise InvalidInput("propose needs evidence= (Contract-F bundle) or rows= (Contract-A rows)")
        evidence = build_evidence(service, rows)
    validate_evidence(evidence)
    return store.propose(service, action_type, params, evidence, run_id=run_id)


def _decide(store, action_id: int, status: str, decided_by: str) -> dict:
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise InvalidInput("decided_by must name the accountable human — "
                           "approval is accountability, not safety")
    if not store.decide(action_id, status, decided_by):
        row = store.get(action_id)
        state = row["status"] if row is not None else "unknown"
        raise StateError(f"action {action_id} is {state!r}; only 'proposed' actions can be "
                         f"{status} (already handled?)")
    return store.get(action_id)


def approve(store, action_id: int, decided_by: str) -> dict:
    """Stage 2 — the human gate. The ONLY path from 'proposed' to 'approved'.
    `decided_by` names the accountable person; approval is ACCOUNTABILITY, not
    safety — it does not make the action correct or harmless. Duplicate/concurrent
    approvals are refused (the conditional store update decides the race)."""
    return _decide(store, action_id, "approved", decided_by)


def reject(store, action_id: int, decided_by: str) -> dict:
    """Terminal 'rejected' — a rejected action can never execute afterwards."""
    return _decide(store, action_id, "rejected", decided_by)


def _apply_scale(k8s, service: str, replicas: int, timeout_s: float, poll_s: float):
    """Scale, then confirm spec AND status agree on the target before 'applied'.
    Unconfirmed change inside the window = ('failed', reason) — a timeout is not
    success. (Scale itself is naturally idempotent: setting replicas=N twice is
    the same cluster state.)"""
    k8s.scale(service, replicas)
    deadline = time.monotonic() + timeout_s
    while True:
        state = k8s.get_rollout(service)
        if state["desired"] == replicas and state["replicas"] == replicas:
            return ("applied", None)
        if time.monotonic() >= deadline:
            return ("failed", f"timeout: replicas did not converge to {replicas} "
                              f"(desired={state['desired']}, replicas={state['replicas']})")
        time.sleep(poll_s)


def _apply_restart(k8s, service: str, timeout_s: float, poll_s: float):
    """Rolling-restart, then confirm the marker landed AND the rollout converged
    (all pods ready) before 'applied'."""
    token = k8s.restart(service)
    deadline = time.monotonic() + timeout_s
    while True:
        state = k8s.get_rollout(service)
        if state["marker"] == token and state["replicas"] > 0 and state["ready"] == state["replicas"]:
            return ("applied", None)
        if time.monotonic() >= deadline:
            return ("failed", f"timeout: restart not confirmed (marker "
                              f"{'set' if state['marker'] == token else 'missing'}, "
                              f"ready {state['ready']}/{state['replicas']})")
        time.sleep(poll_s)


def execute(store, k8s, action_id: int, *, timeout_s: float = DEFAULT_EXECUTE_TIMEOUT_S,
            poll_s: float = DEFAULT_POLL_S) -> dict:
    """Stage 3 — execute an APPROVED action through the k8s interface, then verify
    the change through the same interface before recording 'applied'.

    The store holds the row lock across this whole attempt, so duplicate or
    concurrent approvals execute exactly once; any other state raises StateError
    without ever touching the cluster. A failed call or an unconfirmed change is
    recorded 'failed' (applied_at NULL): timeout != success. Returns the final
    audit row."""
    if timeout_s <= 0 or poll_s <= 0:
        raise InvalidInput("timeout_s and poll_s must be positive")

    def effect(row):
        service, action_type = row["service"], row["action_type"]
        if action_type == "scale":
            replicas = int((row["params"] or {})["replicas"])
            try:
                return _apply_scale(k8s, service, replicas, timeout_s, poll_s)
            except Exception as e:     # a failed/hung k8s call is a recorded failure
                return ("failed", f"{type(e).__name__}: {e}")
        if action_type == "restart":
            try:
                return _apply_restart(k8s, service, timeout_s, poll_s)
            except Exception as e:
                return ("failed", f"{type(e).__name__}: {e}")
        return ("failed", f"unsupported action_type {action_type!r} "
                          f"(v1 executes: {'/'.join(ACTIONS)})")

    return store.run_execution(action_id, effect)


# --------------------------------------------------------------------------- #
# Offline selftest — no cluster, no DB, stdlib only.
# --------------------------------------------------------------------------- #

def _fixture_rows(service: str = "orders", ts: float = 1000.0):
    """Contract-A inference rows mirroring aiops.common.fixtures.sample_inference_rows()
    (inlined so the offline check needs stdlib only; the shared fixture is used by
    the live INT-005 wiring)."""
    return [
        {"ts": ts, "module": "detect", "service": service, "kind": "anomaly_flag",
         "value": 1.0, "meta": {"detector": "iforest", "threshold": 0.8}},
        {"ts": ts - 15, "module": "detect", "service": service, "kind": "anomaly_score",
         "value": 0.92, "meta": {"detector": "iforest", "features": ["p95_ms"]}},
        {"ts": ts, "module": "rca", "service": service, "kind": "culprit_rank",
         "value": 1.0, "meta": {"score": 0.71, "incident_id": "inc-1"}},
        {"ts": ts, "module": "predict", "service": service, "kind": "breach_prob",
         "value": 0.63, "meta": {"horizon_s": 120, "threshold": 0.5}},
        {"ts": ts, "module": "forecast", "service": service, "kind": "forecast_p95",
         "value": 420.0, "meta": {"horizon_s": 120, "model": "prophet"}},
    ]


def _selftest():
    import json
    import threading

    importable = ("action_id", "proposed_at", "service", "action_type", "params", "evidence",
                  "status", "decided_by", "decided_at", "applied_at", "outcome", "run_id")
    immutable = ("action_id", "proposed_at", "service", "action_type", "params", "evidence", "run_id")

    # --- evidence builder: Contract-F shape, kind preference, loud gaps --------
    bundle = build_evidence("orders", _fixture_rows())
    assert bundle["service"] == "orders" and bundle["as_of"] == 1000.0
    assert set(bundle) == {"service", "as_of", "anomaly", "rca", "prediction", "forecast"}
    assert bundle["anomaly"]["kind"] == "anomaly_flag", "preferred kind wins over older rows"
    assert set(bundle["anomaly"]) == {"ts", "module", "service", "kind", "value", "meta"}, \
        "evidence rows carry the exact Contract-A shape"
    no_flag = [r for r in _fixture_rows() if r["kind"] != "anomaly_flag"]
    assert build_evidence("orders", no_flag)["anomaly"]["kind"] == "anomaly_score", "fallback kind"
    no_predict = [r for r in _fixture_rows() if r["kind"] != "breach_prob"]
    for bad_rows, target in ((no_predict, "orders"), (_fixture_rows(), "catalogue")):
        try:
            build_evidence(target, bad_rows)
            raise AssertionError(f"incomplete evidence for {target!r} must raise")
        except InvalidInput:
            pass

    # --- propose() input validation: fail loudly, store nothing ---------------
    guard_store = InMemoryAudit()
    bad_calls = (
        lambda: propose(guard_store, "orders", "rollout", {}, rows=_fixture_rows()),
        lambda: propose(guard_store, "orders", "scale", {"replicas": -1}, rows=_fixture_rows()),
        lambda: propose(guard_store, "orders", "scale", {"replicas": True}, rows=_fixture_rows()),
        lambda: propose(guard_store, "orders", "scale", {"replicas": 3, "extra": 1}, rows=_fixture_rows()),
        lambda: propose(guard_store, "orders", "scale", {"replicas": 3}),
        lambda: propose(guard_store, "orders", "scale", {"replicas": 3},
                        evidence=bundle, rows=_fixture_rows()),
    )
    for call in bad_calls:
        try:
            call()
            raise AssertionError("invalid propose() input must raise InvalidInput")
        except InvalidInput:
            pass
    bad = build_evidence("orders", _fixture_rows())
    bad["prediction"] = bad["forecast"]           # forecast row in the prediction slot
    try:
        propose(guard_store, "orders", "scale", {"replicas": 3}, evidence=bad)
        raise AssertionError("off-vocabulary evidence must raise")
    except InvalidInput:
        pass
    assert guard_store.get(1) is None, "rejected proposals must not reach the store"

    # --- no approval -> no execution ------------------------------------------
    store, k8s = InMemoryAudit(), FakeK8s()
    aid = propose(store, "orders", "scale", {"replicas": 3}, rows=_fixture_rows(), run_id=7)
    before = json.dumps({k: store.get(aid)[k] for k in immutable}, sort_keys=True)
    assert store.get(aid)["run_id"] == 7
    assert set(store.get(aid)) == set(importable), "audit row shape == documented table columns"
    try:
        execute(store, k8s, aid, timeout_s=0.05, poll_s=0.01)
        raise AssertionError("unapproved action must not execute")
    except StateError:
        pass
    assert k8s.calls == [], "no-approval -> no k8s call"
    assert store.get(aid)["status"] == "proposed", "no-approval leaves it 'proposed'"
    try:
        approve(store, aid, "   ")
        raise AssertionError("anonymous approval must be refused")
    except InvalidInput:
        pass
    assert store.get(aid)["status"] == "proposed", "anonymous approval must not decide"

    # --- duplicate approval -> exactly one execution --------------------------
    row = approve(store, aid, "aryan")
    assert row["status"] == "approved" and row["decided_by"] == "aryan" and row["decided_at"]
    for call, why in ((lambda: approve(store, aid, "aryan"), "double approval"),
                      (lambda: reject(store, aid, "aryan"), "approve then reject"),
                      (lambda: execute(store, k8s, 999, timeout_s=0.05, poll_s=0.01), "unknown action")):
        try:
            call()
            raise AssertionError(f"must raise StateError ({why})")
        except StateError:
            pass
    final = execute(store, k8s, aid, timeout_s=1.0, poll_s=0.01)
    assert final["status"] == "applied" and final["applied_at"] and final["outcome"] is None
    assert [c[0] for c in k8s.calls] == ["scale", "get_rollout"], \
        "verified: the change was confirmed through the k8s interface before 'applied'"
    assert k8s.calls[0] == ("scale", "orders", 3)
    for call, why in ((lambda: execute(store, k8s, aid, timeout_s=0.05, poll_s=0.01), "double execute"),
                      (lambda: approve(store, aid, "aryan"), "approve after execute"),
                      (lambda: reject(store, aid, "aryan"), "reject after execute")):
        try:
            call()
            raise AssertionError(f"{why} must raise StateError")
        except StateError:
            pass
    assert sum(1 for c in k8s.calls if c[0] == "scale") == 1, \
        "duplicate approval/execute -> exactly one k8s execution"

    # --- audit is appended, forward-only, never overwritten -------------------
    after = store.get(aid)
    assert json.dumps({k: after[k] for k in immutable}, sort_keys=True) == before, \
        "immutable fields (what/where/evidence) must never be rewritten"
    assert [after["status"], after["action_id"]] == ["applied", aid], \
        "the same audit row moved forward; no replacement row"
    aid2 = propose(store, "orders", "restart", {}, rows=_fixture_rows())
    assert aid2 > aid and store.get(aid)["service"] == "orders", \
        "a second proposal is appended; the first row is untouched"
    assert store.get(aid)["status"] == "applied" and store.get(aid2)["status"] == "proposed"
    assert not any(hasattr(store, m) for m in ("delete", "remove")), \
        "the audit store has no delete path (append-only by construction)"

    # --- reject is terminal: never executes -----------------------------------
    reject(store, aid2, "aryan")
    try:
        execute(store, k8s, aid2, timeout_s=0.05, poll_s=0.01)
        raise AssertionError("rejected action must not execute")
    except StateError:
        pass
    assert store.get(aid2)["status"] == "rejected"

    # --- timeout -> failed, never applied -------------------------------------
    tstore, tk8s = InMemoryAudit(), FakeK8s(converge=False)   # change never confirmed
    tid = propose(tstore, "orders", "scale", {"replicas": 5}, rows=_fixture_rows())
    approve(tstore, tid, "aryan")
    trow = execute(tstore, tk8s, tid, timeout_s=0.05, poll_s=0.01)
    assert trow["status"] == "failed", "unconfirmed change must be 'failed'"
    assert trow["applied_at"] is None, "timeout != success: applied_at stays NULL"
    assert "timeout" in (trow["outcome"] or ""), f"outcome explains the timeout: {trow['outcome']!r}"
    assert sum(1 for c in tk8s.calls if c[0] == "scale") == 1, "the attempt was made"

    # --- a failing k8s call -> failed, never applied --------------------------
    estore, ek8s = InMemoryAudit(), FakeK8s(fail={"scale"})
    eid = propose(estore, "orders", "scale", {"replicas": 5}, rows=_fixture_rows())
    approve(estore, eid, "aryan")
    erow = execute(estore, ek8s, eid, timeout_s=0.05, poll_s=0.01)
    assert erow["status"] == "failed" and erow["applied_at"] is None
    assert "RuntimeError" in (erow["outcome"] or ""), "the API error is recorded in the outcome"

    # --- restart: applied only after the marker is confirmed ------------------
    rstore, rk8s = InMemoryAudit(), FakeK8s()
    rid = propose(rstore, "orders", "restart", {}, rows=_fixture_rows())
    approve(rstore, rid, "aryan")
    rrow = execute(rstore, rk8s, rid, timeout_s=1.0, poll_s=0.01)
    assert rrow["status"] == "applied" and [c[0] for c in rk8s.calls] == ["restart", "get_rollout"]
    rstore2, rk8s2 = InMemoryAudit(), FakeK8s(converge=False)
    rid2 = propose(rstore2, "orders", "restart", {}, rows=_fixture_rows())
    approve(rstore2, rid2, "aryan")
    assert execute(rstore2, rk8s2, rid2, timeout_s=0.05, poll_s=0.01)["status"] == "failed"

    # --- concurrent duplicate: exactly one execution (store lock = DB row lock)
    class _SlowScaleK8s(FakeK8s):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def scale(self, service, replicas):
            self.entered.set()
            self.release.wait(5)
            super().scale(service, replicas)

    cstore, ck8s = InMemoryAudit(), _SlowScaleK8s()
    cid = propose(cstore, "orders", "scale", {"replicas": 4}, rows=_fixture_rows())
    approve(cstore, cid, "aryan")
    first, second = {}, {}
    t1 = threading.Thread(target=_exec_capture, args=(cstore, ck8s, cid, first))
    t1.start()
    assert ck8s.entered.wait(5), "first execute must reach the k8s call"
    t2 = threading.Thread(target=_exec_capture, args=(cstore, ck8s, cid, second))
    t2.start()
    t2.join(0.3)
    assert t2.is_alive(), "second execute must wait behind the first (serialized)"
    ck8s.release.set()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive(), "both executes must finish"
    assert "error" not in first, f"first execute failed: {first.get('error')!r}"
    assert first["row"]["status"] == "applied"
    assert isinstance(second.get("error"), StateError), f"the loser is refused: {second!r}"
    assert "row" not in second, "the loser must not execute"
    assert sum(1 for c in ck8s.calls if c[0] == "scale") == 1, "concurrent duplicate -> one execution"
    assert cstore.get(cid)["status"] == "applied"

    # --- live PgAudit issues the documented, append-only statements ------------
    # (psycopg2 mocked, same trick as aiops.common.store's selftest: no driver, no DB)
    import sys
    import types

    cols = importable
    state = {"status": "approved", "applied_at": None, "outcome": None}
    row_tuple = lambda: (11, 1000.0, "orders", "scale", {"replicas": 3}, {"service": "orders"},
                         state["status"], "aryan", 1001.0, state["applied_at"],
                         state["outcome"], 7)
    statements = []

    class _Cur:
        def __init__(self):
            self.rowcount = 0
            self.description = None
            self._next = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            statements.append((sql, params))
            if "RETURNING action_id" in sql:
                self.description = [("action_id",)]
                self._next = (11,)
            elif sql.lstrip().startswith("SELECT"):
                self.description = [(c,) for c in cols]
                self._next = row_tuple()
            elif sql.lstrip().startswith("UPDATE"):
                self.rowcount = 1
                self.description = None
                if "SET status = 'applied'" in sql:
                    state.update(status="applied", applied_at=1002.0)

        def fetchone(self):
            return self._next

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    fake = types.ModuleType("psycopg2")
    fake.connect = lambda dsn: _Conn()
    saved = sys.modules.get("psycopg2")
    sys.modules["psycopg2"] = fake
    try:
        pg = PgAudit(dsn="postgresql://fake")   # dsn given -> no aiops.common import
        assert pg.propose("orders", "scale", {"replicas": 3}, bundle, run_id=7) == 11
        assert pg.decide(11, "approved", "aryan") is True
        got = pg.get(11)
        assert got["status"] == "approved" and got["params"] == {"replicas": 3}, \
            "PgAudit.get maps the documented columns"
        final = pg.run_execution(11, lambda row: ("applied", None))
        assert final["status"] == "applied" and final["applied_at"] == 1002.0
    finally:
        sys.modules.pop("psycopg2", None)
        if saved is not None:
            sys.modules["psycopg2"] = saved
    sqls = [s for s, _ in statements]
    assert any("INSERT INTO remediation_action" in s for s in sqls), "propose INSERTs the audit row"
    assert any("FOR UPDATE" in s for s in sqls), "execute takes the row lock (exactly-once gate)"
    assert any("AND status = 'proposed'" in s for s in sqls), \
        "decide is race-gated on the current status (duplicate decisions lose)"
    assert not any(s.lstrip().upper().startswith("DELETE") for s in sqls), \
        "no DELETE path, ever — the live store only ever appends or moves forward"

    print("remediate selftest OK — proposed->approved->applied verified; "
          "timeout->failed; duplicate/concurrent approvals execute exactly once; audit append-only")


def _exec_capture(store, k8s, action_id: int, out: dict) -> None:
    """Thread body for the concurrency check: capture row or exception in `out`
    (the second caller must be refused with StateError and never execute)."""
    try:
        out["row"] = execute(store, k8s, action_id, timeout_s=5.0, poll_s=0.01)
    except Exception as e:   # capture for the asserting thread, don't die silently
        out["error"] = e


if __name__ == "__main__":
    _selftest()
