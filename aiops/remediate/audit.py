"""Append-only remediation audit store (`remediation_action`, experiment/schema.sql §4.4).

Lifecycle — the only legal forward moves (mirrored from the DB trigger
`remediation_audit_guard`, which enforces them even if a caller gets this wrong):

    proposed -> approved | rejected          (the human decision)
    approved -> applied | failed             (the execution outcome)

There is deliberately no delete path here and no code path that rewrites the
immutable fields (service, action_type, params, evidence, run_id, proposed_at).
The log records that a human approved — accountability — NOT proof the action is
"safe".

`PgAudit` is the live store (psycopg2 and config imported lazily, so the offline
selftest needs no driver, no DB, and no `aiops.common` import chain).
`InMemoryAudit` is the offline double with the same method surface, used by
--selftest (and by mock-driven development before a cluster exists).

Concurrency — exactly-once execution with the frozen schema: `run_execution`
holds a row lock (`SELECT ... FOR UPDATE`) across the whole execute attempt, so
duplicate or concurrent approvals serialize and only the first finds the action
'approved'. At single-operator testbed scale, holding the lock across the k8s
call is a deliberate, bounded trade-off (the call itself is timeout-bounded).
If remediation ever becomes a hot path, revisit with a claim column — that is a
schema/contract change, not a silent client-side hack.
"""
from __future__ import annotations

import copy
import json
import threading
import time

from .errors import StateError

# Mirror of experiment/schema.sql's guard: the only legal forward transitions.
_TRANSITIONS = {("proposed", "approved"), ("proposed", "rejected"),
                ("approved", "applied"), ("approved", "failed")}

_FIELDS = ("action_id, extract(epoch from proposed_at) AS proposed_at, service, "
           "action_type, params, evidence, status, decided_by, "
           "extract(epoch from decided_at) AS decided_at, "
           "extract(epoch from applied_at) AS applied_at, outcome, run_id")
_SELECT_ROW = f"SELECT {_FIELDS} FROM remediation_action WHERE action_id = %s"
_SELECT_ROW_FOR_UPDATE = _SELECT_ROW + " FOR UPDATE"


def _full(row: dict):
    """Column order shared by both stores, so selftest rows look like DB rows."""
    return {c: row.get(c) for c in
            ("action_id", "proposed_at", "service", "action_type", "params", "evidence",
             "status", "decided_by", "decided_at", "applied_at", "outcome", "run_id")}


class PgAudit:
    """Live store over TimescaleDB/Postgres. Commits per call (`with conn`), like
    aiops.common.store; nothing here ever DELETEs or rewrites immutable fields."""

    def __init__(self, dsn: str | None = None):
        if dsn is None:
            from ..common import config  # lazy: env-var config only (Contract G)
            dsn = config.TIMESCALE_DSN
        self._dsn = dsn

    def _connect(self):
        import psycopg2  # lazy: offline selftest needs no driver
        return psycopg2.connect(self._dsn)

    @staticmethod
    def _row(cur):
        if cur.description is None:
            return None
        cols = [d[0] for d in cur.description]
        r = cur.fetchone()
        return None if r is None else dict(zip(cols, r))

    def propose(self, service: str, action_type: str, params: dict, evidence: dict,
                run_id: int | None = None) -> int:
        with self._connect() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO remediation_action (service, action_type, params, evidence, run_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING action_id",
                (service, action_type, json.dumps(params), json.dumps(evidence), run_id))
            return cur.fetchone()[0]

    def get(self, action_id: int):
        with self._connect() as c, c.cursor() as cur:
            cur.execute(_SELECT_ROW, (action_id,))
            return self._row(cur)

    def decide(self, action_id: int, status: str, decided_by: str) -> bool:
        """Conditional proposed -> approved|rejected. The WHERE clause is the race
        gate: the second of two concurrent decisions gets rowcount 0."""
        if status not in ("approved", "rejected"):
            raise ValueError(f"decide status must be approved|rejected, got {status!r}")
        with self._connect() as c, c.cursor() as cur:
            cur.execute(
                "UPDATE remediation_action SET status = %s, decided_by = %s, decided_at = now() "
                "WHERE action_id = %s AND status = 'proposed'",
                (status, decided_by, action_id))
            return cur.rowcount == 1

    def run_execution(self, action_id: int, effect):
        """Hold the row lock for the whole attempt: check -> effect -> record the
        terminal status, in one transaction. `effect(row)` returns
        ('applied', outcome) or ('failed', reason); anything else is refused. An
        effect that raises rolls the transaction back (the action stays
        'approved' for an explicit retry) — but a *failed k8s call* is returned
        as ('failed', ...) by the caller's effect, not raised."""
        with self._connect() as c, c.cursor() as cur:
            cur.execute(_SELECT_ROW_FOR_UPDATE, (action_id,))
            row = self._row(cur)
            if row is None:
                raise StateError(f"unknown action_id {action_id}")
            if row["status"] != "approved":
                raise StateError(
                    f"action {action_id} is {row['status']!r}; only 'approved' actions execute")
            status, outcome = effect(dict(row))
            if (row["status"], status) not in _TRANSITIONS:
                raise StateError(f"illegal transition {row['status']!r} -> {status!r}")
            if status == "applied":
                cur.execute("UPDATE remediation_action SET status = 'applied', "
                            "applied_at = now(), outcome = %s WHERE action_id = %s",
                            (outcome, action_id))
            else:  # failed: applied_at stays NULL — a timeout is not success
                cur.execute("UPDATE remediation_action SET status = 'failed', "
                            "applied_at = NULL, outcome = %s WHERE action_id = %s",
                            (outcome, action_id))
            cur.execute(_SELECT_ROW, (action_id,))
            return self._row(cur)


class InMemoryAudit:
    """Offline double — same surface, same lifecycle rules, no DB.

    Models the three properties the selftest asserts: rows are append-only (no
    delete path exists), transitions are forward-only (same guard as the DB
    trigger), and `run_execution` holds a lock across the effect that stands in
    for the real store's `SELECT ... FOR UPDATE`."""

    def __init__(self):
        self._rows: dict = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def propose(self, service: str, action_type: str, params: dict, evidence: dict,
                run_id: int | None = None) -> int:
        with self._lock:
            action_id = self._next_id
            self._next_id += 1
            self._rows[action_id] = _full({
                "action_id": action_id, "proposed_at": time.time(), "service": service,
                "action_type": action_type, "params": copy.deepcopy(params or {}),
                "evidence": copy.deepcopy(evidence), "status": "proposed",
                "decided_by": None, "decided_at": None, "applied_at": None,
                "outcome": None, "run_id": run_id})
            return action_id

    def get(self, action_id: int):
        with self._lock:
            row = self._rows.get(action_id)
            return copy.deepcopy(row) if row is not None else None

    def decide(self, action_id: int, status: str, decided_by: str) -> bool:
        if status not in ("approved", "rejected"):
            raise ValueError(f"decide status must be approved|rejected, got {status!r}")
        with self._lock:
            row = self._rows.get(action_id)
            if row is None or row["status"] != "proposed":
                return False
            row.update(status=status, decided_by=decided_by, decided_at=time.time())
            return True

    def run_execution(self, action_id: int, effect):
        with self._lock:  # stands in for the real store's row lock
            row = self._rows.get(action_id)
            if row is None:
                raise StateError(f"unknown action_id {action_id}")
            if row["status"] != "approved":
                raise StateError(
                    f"action {action_id} is {row['status']!r}; only 'approved' actions execute")
            status, outcome = effect(copy.deepcopy(row))
            if (row["status"], status) not in _TRANSITIONS:
                raise StateError(f"illegal transition {row['status']!r} -> {status!r}")
            row["status"] = status
            row["applied_at"] = time.time() if status == "applied" else None
            row["outcome"] = outcome
            return copy.deepcopy(row)
