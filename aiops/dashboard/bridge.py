"""Contract-E read bridge (ticket D4-002) — the ONLY place the dashboard reads the
database.

Why a Python bridge instead of a Node PostgreSQL driver: the read paths the
dashboard needs already exist on the Python side and must not be duplicated.
Inference rows come from `aiops.common.store.recent(module, kind, service, since)`
(Contract A — the same frozen reader the ML modules use), and the DSN comes from
`aiops.common.config.TIMESCALE_DSN` (Contract G — the single config source). A
second SQL client in JavaScript would be a parallel, independently-maintained
database client, which D4-002 forbids. Node cannot import Python functions, so the
process boundary here is a single-shot subprocess: one JSON request on stdin, one
JSON response on stdout, no shell, nothing interpolated into a command line.

Protocol — request (JSON object on stdin):

    {"resource": "anomalies", "since": 0}      "since" optional, unix seconds,
                                               inclusive lower bound (default 0)

Response (JSON object on stdout, exit 0 on ok / 1 on error):

    {"ok": true,  "rows": [...]}
    {"ok": false, "error": "invalid_request" | "read_failed"}

`read_failed` is deliberately the only failure code: whether the database is
unreachable, a query fails, or a value cannot be serialized into strict JSON, the
client gets one sanitized error and nothing else — no exception text, no DSN, no
SQL, no traceback ever leaves this process (the HTTP layer maps the code to a
status). Diagnostics go to stderr as a class name only.

`resource` -> source mapping (Contract A vocabulary / Contract D tables):

    anomalies    -> inference: module 'detect',   kinds anomaly_score,
                    anomaly_score_seq, anomaly_flag
    rca          -> inference: module 'rca',      kind culprit_rank
    predictions  -> inference: module 'predict',  kinds breach_prob,
                    breach_duration_est
    forecasts    -> inference: module 'forecast', kinds forecast_p95,
                    forecast_p95_snaive, forecast_p95_tree
    remediations -> remediation_action (append-only audit log; READ only)
    experiments  -> experiment_run LEFT JOIN experiment_result on run_id

Multi-kind endpoints merge exactly one query per kind, then sort by ts descending
with a documented total order (see `_inference_rows`); the merge is stable, so the
same database state always serializes to the same array.

Offline check: `python -m aiops.dashboard --selftest` (or
`python -m aiops.dashboard.bridge --selftest`) — stdlib only, psycopg2 mocked,
no DB and no cluster required.
"""
from __future__ import annotations

import io
import json
import math
import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from ..common import store
# The audit row's column list is owned by D4-001 (`aiops.remediate.audit._FIELDS`);
# importing it keeps the dashboard read shape and the audit write shape identical
# instead of copying the list here and letting the two drift apart.
from ..remediate.audit import _FIELDS as _AUDIT_FIELDS

# --------------------------------------------------------------------------- #
# Frozen endpoint -> source mapping (Contract A / Contract D). The keys are also
# the Contract-E resource names and the six `/api/<resource>` routes.
# --------------------------------------------------------------------------- #
INFERENCE_RESOURCES = {
    "anomalies": ("detect", ("anomaly_score", "anomaly_score_seq", "anomaly_flag")),
    "rca": ("rca", ("culprit_rank",)),
    "predictions": ("predict", ("breach_prob", "breach_duration_est")),
    "forecasts": ("forecast", ("forecast_p95", "forecast_p95_snaive", "forecast_p95_tree")),
}
RELATIONAL_RESOURCES = ("remediations", "experiments")
RESOURCES = tuple(INFERENCE_RESOURCES) + RELATIONAL_RESOURCES

# Exactly the columns `store.recent()` returns — the dashboard never adds or
# renames an inference field (Contract A is frozen).
INFERENCE_FIELDS = ("ts", "module", "service", "kind", "value", "meta")

# Explicit columns, never SELECT *. `_AUDIT_FIELDS` is D4-001's list (same columns,
# epochs as unix seconds); the only thing the dashboard adds is the deterministic
# ORDER BY. `since=0` means "everything" (the epoch) — the same inclusive-lower-bound
# convention store.recent() uses.
_REMEDIATION_SQL = (
    "SELECT " + _AUDIT_FIELDS + " FROM remediation_action "
    "WHERE proposed_at >= to_timestamp(%s) "
    "ORDER BY proposed_at DESC, action_id DESC"
)

# Run metadata and measured results stay apart on purpose: the response is
# {"run": {...}, "result": {...}|null}, so a missing scorecard is a null rather
# than a bag of nulls, and the join cannot produce a duplicated key (run_id
# appears once, on the run).
_RUN_FIELDS = ("run_id", "started_at", "ended_at", "pair_id", "policy",
               "workload_regime", "fault_class", "is_negative_control", "seed",
               "slo_p95_ms", "slo_error_rate", "horizon_s", "notes")
_RESULT_FIELDS = ("slo_breach_duration_s", "breaching_requests",
                  "breaching_request_ratio", "pod_minutes", "scaling_actions",
                  "oscillations", "mttd_s", "rca_top1_correct",
                  "remediation_success", "extra")
_EXPERIMENTS_SQL = (
    "SELECT r.run_id, "
    "extract(epoch from r.started_at) AS started_at, "
    "extract(epoch from r.ended_at) AS ended_at, "
    "r.pair_id, r.policy, r.workload_regime, r.fault_class, r.is_negative_control, "
    "r.seed, r.slo_p95_ms, r.slo_error_rate, r.horizon_s, r.notes, "
    "(res.run_id IS NOT NULL) AS has_result, "
    "res.slo_breach_duration_s, res.breaching_requests, res.breaching_request_ratio, "
    "res.pod_minutes, res.scaling_actions, res.oscillations, res.mttd_s, "
    "res.rca_top1_correct, res.remediation_success, res.extra "
    "FROM experiment_run r "
    "LEFT JOIN experiment_result res ON res.run_id = r.run_id "
    "WHERE r.started_at >= to_timestamp(%s) "
    "ORDER BY r.started_at DESC, r.run_id DESC"
)

# Every statement this bridge may ever issue — asserted read-only in the selftest.
_WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER",
                   "TRUNCATE", "GRANT", "COPY")


class _BadRequest(Exception):
    """Malformed bridge request — the caller's fault, not the database's."""


# --------------------------------------------------------------------------- #
# JSON safety: explicit conversion of everything the database can hand back.
# --------------------------------------------------------------------------- #
def _jsonable(value):
    """Convert a database-returned value into a strict-JSON-native value.

    Explicit on purpose — nothing is guessed and nothing is fabricated:
      - str/int/bool/None pass through; int stays an int (BIGINT ids are exact).
      - Decimal (psycopg2's type for `extract(epoch ...)` and NUMERIC) -> float.
      - A float/Decimal that is not finite -> None (JSON has no NaN/Infinity; the
        client sees an explicit null, never a silent 0 or a literal NaN).
      - datetime -> unix seconds (naive values are read as UTC, matching the
        timestamptz columns these rows come from).
      - date/time -> ISO string, UUID -> str.
      - list/tuple -> list, dict -> dict (keys stringified), recursively.
      - anything else raises, so an unexpected type fails the read loudly instead
        of being stringified into plausible-looking JSON.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        as_float = float(value)
        return as_float if math.isfinite(as_float) else None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    raise TypeError(f"cannot serialize {type(value).__name__} into JSON")


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _fetch(sql, params):
    """Run one parameterized read query. Reuses store's lazy psycopg2 connection
    factory (`aiops.common.store._connect`) so the dashboard never grows a second
    database client; every value travels as a query parameter, never as SQL text."""
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _inference_rows(resource: str, since: float):
    """One `store.recent()` call per kind (no duplicate or repeated queries), then
    a documented total order.

    Merge order: the kinds are read in the order listed in INFERENCE_RESOURCES
    ('anomaly_score', 'anomaly_score_seq', 'anomaly_flag' for detect). Sort order:
    ts descending; ties break by that same documented kind order, then service,
    then value (NULLs last, NaN sorted with the NULLs so it cannot swallow the
    tiebreak), then the serialized meta — a total order, so a given database
    state always produces the same array.
    """
    module, kinds = INFERENCE_RESOURCES[resource]
    rank = {kind: position for position, kind in enumerate(kinds)}
    rows = []
    for kind in kinds:                                   # exactly one query per kind
        rows.extend(store.recent(module, kind, service=None, since=since))

    def sort_key(row):
        value = row.get("value")
        if value is None:
            value_key = math.inf
        else:
            value_key = float(value)
            if math.isnan(value_key):
                # NaN sorts with NULLs (last): NaN != NaN inside a tuple
                # comparison, which would otherwise leave equal rows ordered by
                # their input position instead of reaching the meta tiebreaker.
                value_key = math.inf
        return (
            -float(row["ts"]),
            rank[row["kind"]],
            str(row["service"]),
            value_key,
            json.dumps(row.get("meta"), sort_keys=True, default=str),
        )

    rows.sort(key=sort_key)
    return [_jsonable({field: row[field] for field in INFERENCE_FIELDS}) for row in rows]


def _remediation_rows(since: float):
    """The append-only audit log, read verbatim (all documented columns). The
    dashboard never writes, approves, executes, or reorders history — this is a
    SELECT and nothing else. Rows come back as stored, whatever their status;
    filtering by status here would be a lifecycle opinion, not a read."""
    return [_jsonable(row) for row in _fetch(_REMEDIATION_SQL, (since,))]


def _experiment_rows(since: float):
    """Experiment trials, run metadata and measured results kept distinct.
    `is_negative_control` runs are NOT filtered here — Contract D says the ANALYSIS
    layer queries them out and reports them separately; the dashboard exposes the
    flag so a view can separate them without hiding data."""
    rows = _fetch(_EXPERIMENTS_SQL, (since,))
    out = []
    for row in rows:
        has_result = bool(row.pop("has_result"))
        run = {field: row[field] for field in _RUN_FIELDS}
        result = {field: row[field] for field in _RESULT_FIELDS} if has_result else None
        out.append(_jsonable({"run": run, "result": result}))
    return out


def _rows_for(resource: str, since: float):
    if resource in INFERENCE_RESOURCES:
        return _inference_rows(resource, since)
    if resource == "remediations":
        return _remediation_rows(since)
    return _experiment_rows(since)


# --------------------------------------------------------------------------- #
# Request handling
# --------------------------------------------------------------------------- #
def _validate(request):
    """Strict request validation: exactly {resource, since?}, nothing else."""
    if not isinstance(request, dict):
        raise _BadRequest("request must be a JSON object")
    unknown = set(request) - {"resource", "since"}
    if unknown:
        raise _BadRequest(f"unknown request field(s): {sorted(unknown)}")
    resource = request.get("resource")
    if resource not in RESOURCES:
        raise _BadRequest(f"unknown resource {resource!r}")
    raw_since = request.get("since", 0)
    if isinstance(raw_since, bool) or not isinstance(raw_since, (int, float)):
        raise _BadRequest("since must be a number (unix seconds)")
    since = float(raw_since)
    if not math.isfinite(since) or since < 0:
        raise _BadRequest("since must be a finite, non-negative number")
    return resource, since


def handle_request(request) -> dict:
    """Execute one read request and return the response object. Never raises: an
    invalid request answers `invalid_request`; any read or serialization failure
    answers `read_failed` — sanitized, with no internals attached."""
    try:
        resource, since = _validate(request)
        return {"ok": True, "rows": _rows_for(resource, since)}
    except _BadRequest:
        return {"ok": False, "error": "invalid_request"}
    except Exception as exc:                              # DB, mapping, serialization
        _stderr(f"bridge: read failed ({type(exc).__name__})")
        return {"ok": False, "error": "read_failed"}


def _stderr(message: str) -> None:
    """One sanitized diagnostic line. Never a message, DSN, SQL text, or traceback."""
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _write_response(response: dict) -> None:
    """Strict JSON on stdout: `allow_nan=False` means a missed non-finite value
    fails loudly here instead of emitting invalid JSON to the client."""
    payload = json.dumps(response, allow_nan=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv=None) -> int:
    """stdin -> stdout one-shot entry point (`python -m aiops.dashboard.bridge`)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        _selftest()
        return 0
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    try:
        request = json.loads(raw.decode("utf-8")) if raw.strip() else None
    except Exception:
        request = None
    response = (handle_request(request) if isinstance(request, dict)
                else {"ok": False, "error": "invalid_request"})
    try:
        _write_response(response)
    except Exception:
        # Unserializable response: answer in the sanitized form instead of crashing
        # with a traceback the caller might be tempted to surface. The fallback IS
        # the answer, so the exit code is the error code even when `response` was ok.
        _stderr("bridge: response serialization failed")
        _write_response({"ok": False, "error": "read_failed"})
        return 1
    return 0 if response.get("ok") else 1


# --------------------------------------------------------------------------- #
# Offline selftest — no DB, no cluster, stdlib only (psycopg2 is mocked).
# --------------------------------------------------------------------------- #
_AUDIT_COLUMNS = ("action_id", "proposed_at", "service", "action_type", "params",
                  "evidence", "status", "decided_by", "decided_at", "applied_at",
                  "outcome", "run_id")
_EXPERIMENT_COLUMNS = _RUN_FIELDS + ("has_result",) + _RESULT_FIELDS

_AUDIT_ROW = (11, Decimal("1000.0"), "orders", "scale", {"replicas": 3},
              {"service": "orders"}, "applied", "aryan", Decimal("1001.0"),
              Decimal("1002.0"), None, 7)
_RUN_WITH_RESULT = (7, Decimal("900.0"), None, "p-1", "forecast_hybrid", "spike",
                    "cpu_stress", False, 42, 300.0, 0.01, 120, "target_util=0.6",
                    True, 12.5, 40, 0.25, 3.5, 2, 1, 4.0, True, True, {"note": "ok"})
_RUN_WITHOUT_RESULT = (8, Decimal("890.0"), None, "p-2", "hpa_tuned", "normal",
                       "pod_kill", True, 43, 300.0, 0.01, 120, None,
                       False, None, None, None, None, None, None, None, None, None, None)


def _canned_psycopg2(canned, statements, fail=None):
    """psycopg2 double: `canned(sql)` returns (column names, rows) and every
    executed statement/parameter pair is recorded for inspection. Same trick the
    `aiops.common.store` selftest uses — no driver, no database."""
    import types as _types

    class _Cur:
        def __init__(self):
            self.description = None
            self._rows = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            statements.append((sql, params))
            if fail is not None:
                raise fail
            cols, self._rows = canned(sql)
            self.description = [(name,) for name in cols]

        def fetchall(self):
            return self._rows

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return _Cur()

    fake = _types.ModuleType("psycopg2")
    fake.connect = lambda dsn: _Conn()
    return fake


def _with_fake_driver(fake, fn):
    """Install the fake driver for the duration of fn(), then restore whatever was
    importable before (a real psycopg2 may well be installed)."""
    saved = sys.modules.get("psycopg2")
    sys.modules["psycopg2"] = fake
    try:
        return fn()
    finally:
        if saved is not None:
            sys.modules["psycopg2"] = saved
        else:
            sys.modules.pop("psycopg2", None)


class _FakeStream:
    """Stands in for sys.stdin/sys.stdout in main()'s protocol check."""

    def __init__(self, data=b""):
        self.buffer = io.BytesIO(data)


class _FailFirstWriteBuffer(io.BytesIO):
    """First write raises (a broken pipe / unserializable payload), later writes
    land, so main()'s fallback body and exit code are both assertable."""

    def __init__(self):
        super().__init__()
        self.writes = 0

    def write(self, payload):
        self.writes += 1
        if self.writes == 1:
            raise OSError("simulated write failure")
        return super().write(payload)


class _FailFirstWriteStream:
    """sys.stdout stand-in whose first buffer write fails, then behaves normally."""

    def __init__(self):
        self.buffer = _FailFirstWriteBuffer()


def _selftest():  # noqa: C901 — a flat list of assertions is the point of a selftest
    # --- frozen mapping: exactly six resources, exact Contract-A vocabulary -----
    assert RESOURCES == ("anomalies", "rca", "predictions", "forecasts",
                         "remediations", "experiments")
    assert INFERENCE_RESOURCES["anomalies"] == (
        "detect", ("anomaly_score", "anomaly_score_seq", "anomaly_flag"))
    assert INFERENCE_RESOURCES["rca"] == ("rca", ("culprit_rank",))
    assert INFERENCE_RESOURCES["predictions"] == (
        "predict", ("breach_prob", "breach_duration_est"))
    assert INFERENCE_RESOURCES["forecasts"] == (
        "forecast", ("forecast_p95", "forecast_p95_snaive", "forecast_p95_tree"))
    assert INFERENCE_FIELDS == ("ts", "module", "service", "kind", "value", "meta")

    # --- inference reads go through store.recent(), one call per kind ----------
    fixture = {
        ("detect", "anomaly_score"): [
            {"ts": Decimal("1000.5"), "module": "detect", "service": "orders",
             "kind": "anomaly_score", "value": 0.9, "meta": {"detector": "iforest"}},
            {"ts": 999.0, "module": "detect", "service": "carts",
             "kind": "anomaly_score", "value": 0.4, "meta": None},
            {"ts": 998.0, "module": "detect", "service": "catalogue",
             "kind": "anomaly_score", "value": float("nan"), "meta": {"dropped": True}},
        ],
        ("detect", "anomaly_score_seq"): [
            {"ts": 1000.5, "module": "detect", "service": "orders",
             "kind": "anomaly_score_seq", "value": 0.8, "meta": {}},
        ],
        ("detect", "anomaly_flag"): [
            {"ts": 1000.5, "module": "detect", "service": "orders",
             "kind": "anomaly_flag", "value": 1.0, "meta": {"threshold": 0.8}},
        ],
    }
    real_recent = store.recent
    calls = []

    def recording_recent(module, kind, service=None, since=0.0):
        calls.append((module, kind, service, since))
        return fixture.get((module, kind), [])

    store.recent = recording_recent
    try:
        rows = _rows_for("anomalies", 123.0)
    finally:
        store.recent = real_recent
    assert calls == [("detect", "anomaly_score", None, 123.0),
                     ("detect", "anomaly_score_seq", None, 123.0),
                     ("detect", "anomaly_flag", None, 123.0)], \
        f"exactly one store.recent() per kind, all services, since forwarded: {calls}"
    assert len(rows) == 5, "every kind's rows are merged"
    assert all(sorted(row) == sorted(INFERENCE_FIELDS) for row in rows), \
        "rows carry exactly the store.recent() fields"
    assert [row["kind"] for row in rows] == [
        "anomaly_score", "anomaly_score_seq", "anomaly_flag", "anomaly_score",
        "anomaly_score"], "ts desc; ties in the documented kind order, then service"
    assert rows[2]["service"] == "orders" and rows[3]["service"] == "carts", \
        "equal (ts, kind) ties break by service"
    assert rows[0]["ts"] == 1000.5 and isinstance(rows[0]["ts"], float), \
        "Decimal ts from extract(epoch) serializes as a JSON number"
    assert rows[-1]["value"] is None, "non-finite value -> explicit null, not NaN"

    # --- deterministic merge: same state -> same array, every time -------------
    responses = []
    for _ in range(3):
        store.recent = recording_recent
        try:
            responses.append(json.dumps(handle_request({"resource": "anomalies"}),
                                        sort_keys=True))
        finally:
            store.recent = real_recent
    assert len(set(responses)) == 1, "the merge order is deterministic"

    # --- NaN sorts with NULLs, so tied NaN rows still reach the meta tiebreak ---
    # Two otherwise identical rows (same ts/kind/service, both NaN) with different
    # metadata. Without the NaN normalization the tuple comparison stops at the
    # NaN (NaN != NaN), the stable sort leaves those rows in input order, and
    # reversing the input flips the response. Regression: the meta tiebreak must
    # decide, so both input orders serialize to the same array.
    nan_rows = [
        {"ts": 1000.5, "module": "detect", "service": "orders",
         "kind": "anomaly_score", "value": float("nan"), "meta": {"n": "a"}},
        {"ts": 1000.5, "module": "detect", "service": "orders",
         "kind": "anomaly_score", "value": float("nan"), "meta": {"n": "b"}},
    ]

    def nan_read(indexes):
        ordered = [nan_rows[index] for index in indexes]

        def ordered_recent(module, kind, service=None, since=0.0):
            return ordered if (module, kind) == ("detect", "anomaly_score") else []

        store.recent = ordered_recent
        try:
            return _rows_for("anomalies", 0.0)
        finally:
            store.recent = real_recent

    forward, backward = nan_read((0, 1)), nan_read((1, 0))
    assert [(row["meta"]["n"], row["value"]) for row in forward] == [("a", None), ("b", None)], \
        "tied NaN rows break the tie by serialized meta and serialize NaN as null"
    assert [row["meta"]["n"] for row in backward] == [row["meta"]["n"] for row in forward], \
        "reversing the input rows must not change the final order"

    # --- request validation is strict and never touches the database -----------
    for bad in (None, [], "anomalies", {"resource": "nope"}, {"resource": "rca", "extra": 1},
                {"resource": "rca", "since": "10"}, {"resource": "rca", "since": -1},
                {"resource": "rca", "since": True}, {"resource": "rca", "since": float("nan")},
                {"resource": "rca", "since": float("inf")}):
        assert handle_request(bad) == {"ok": False, "error": "invalid_request"}, bad

    # --- JSON safety is explicit ----------------------------------------------
    from datetime import timedelta
    assert _jsonable(Decimal("1000.5")) == 1000.5
    assert _jsonable(Decimal("NaN")) is None and _jsonable(Decimal("Infinity")) is None
    assert _jsonable(float("inf")) is None and _jsonable(float("-inf")) is None
    assert _jsonable(0.25) == 0.25 and _jsonable(40) == 40 and _jsonable(True) is True
    assert _jsonable(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600.0
    assert _jsonable(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone(timedelta(hours=5)))) \
        == 1767207600.0, "aware datetimes convert through UTC"
    assert _jsonable(date(2026, 1, 1)) == "2026-01-01"
    assert _jsonable(time(12, 30)) == "12:30:00"
    assert _jsonable([Decimal("1"), {"a": Decimal("2")}, (3,)]) == [1.0, {"a": 2.0}, [3]]
    assert _jsonable({1: "x"}) == {"1": "x"}
    for unserializable in (object(), b"bytes", {1, 2}):
        try:
            _jsonable(unserializable)
            raise AssertionError(f"must refuse to serialize {type(unserializable).__name__}")
        except TypeError:
            pass

    # --- relational reads: parameterized, explicit columns, read-only ----------
    statements = []

    def canned(sql):
        if "FROM remediation_action" in sql:
            return _AUDIT_COLUMNS, [_AUDIT_ROW]
        return _EXPERIMENT_COLUMNS, [_RUN_WITH_RESULT, _RUN_WITHOUT_RESULT]

    fake = _canned_psycopg2(canned, statements)
    actions = _with_fake_driver(fake, lambda: _remediation_rows(250.0))
    assert actions[0]["action_id"] == 11 and actions[0]["service"] == "orders"
    assert actions[0]["params"] == {"replicas": 3}
    assert actions[0]["evidence"] == {"service": "orders"}
    assert actions[0]["proposed_at"] == 1000.0 and actions[0]["applied_at"] == 1002.0
    assert actions[0]["decided_at"] == 1001.0 and actions[0]["run_id"] == 7
    assert set(actions[0]) == set(_AUDIT_COLUMNS), "all documented audit columns, nothing else"
    sql, params = statements[-1]
    assert sql.lstrip().upper().startswith("SELECT") and "FROM remediation_action" in sql
    assert "proposed_at >= to_timestamp(%s)" in sql and params == (250.0,), \
        "the since bound travels as a query parameter"
    assert "ORDER BY proposed_at DESC, action_id DESC" in sql
    assert "*" not in sql, "explicit columns, never SELECT *"
    assert all(name in sql for name in _AUDIT_COLUMNS), "every documented column is selected"
    # the audit column list is D4-001's, so the read shape cannot drift from the
    # write shape (aliases included)
    aliases = tuple(part.split(" AS ")[-1].strip() for part in _AUDIT_FIELDS.split(","))
    assert aliases == _AUDIT_COLUMNS, f"audit column list drifted: {aliases}"

    trials = _with_fake_driver(fake, lambda: _experiment_rows(250.0))
    assert len(trials) == 2 and set(trials[0]) == {"run", "result"}
    assert set(trials[0]["run"]) == set(_RUN_FIELDS), "run metadata is its own object"
    assert set(trials[0]["result"]) == set(_RESULT_FIELDS), "measured results are separate"
    assert trials[0]["run"]["run_id"] == 7 and "has_result" not in trials[0]["run"]
    assert trials[0]["run"]["is_negative_control"] is False
    assert trials[0]["run"]["started_at"] == 900.0 and trials[0]["run"]["ended_at"] is None
    assert trials[0]["result"]["slo_breach_duration_s"] == 12.5
    assert trials[0]["result"]["extra"] == {"note": "ok"}
    assert trials[1]["result"] is None, "a run with no scorecard yet is result: null"
    assert trials[1]["run"]["is_negative_control"] is True, \
        "negative-control runs are returned with their flag, not silently dropped"
    sql, params = statements[-1]
    assert "FROM experiment_run r" in sql and "LEFT JOIN experiment_result res" in sql
    assert "res.run_id = r.run_id" in sql and "to_timestamp(%s)" in sql and params == (250.0,)
    assert "ORDER BY r.started_at DESC, r.run_id DESC" in sql, "deterministic order"
    assert "*" not in sql, "explicit columns, never SELECT *"
    assert all(name in sql for name in _EXPERIMENT_COLUMNS)

    # --- every statement this module can issue is read-only --------------------
    upper = [sql.upper() for sql, _ in statements]
    assert upper, "the relational reads ran"
    for sql in upper:
        assert sql.lstrip().startswith("SELECT")
        for keyword in _WRITE_KEYWORDS:
            assert keyword not in sql, f"{keyword} must never be issued by the read bridge"

    # --- failures are sanitized: no DSN, no SQL, no traceback ------------------
    # Deliberate failures; the bridge's own diagnostics are captured so the
    # sanitized log line is asserted too (not just the sanitized response).
    secret = "postgresql://aiops:aiops@timescaledb.aiops:5432/aiops"
    logged = io.StringIO()
    saved_stderr = sys.stderr
    sys.stderr = logged
    try:
        failing = _canned_psycopg2(canned, [], fail=RuntimeError(f"could not connect to {secret}"))
        response = _with_fake_driver(failing, lambda: handle_request({"resource": "remediations"}))
        assert response == {"ok": False, "error": "read_failed"}, response
        text = json.dumps(response)
        for leak in ("aiops:aiops", "postgresql", "timescaledb", "RuntimeError", "Traceback",
                     "SELECT", secret):
            assert leak not in text, f"{leak!r} must never leave the bridge"
        failing_report = _canned_psycopg2(canned, [], fail=Exception("SELECT * FROM secrets"))
        response = _with_fake_driver(failing_report,
                                     lambda: handle_request({"resource": "experiments"}))
        assert response == {"ok": False, "error": "read_failed"}
        assert "SELECT" not in json.dumps(response) and "secrets" not in json.dumps(response)

        def unserializable_recent(module, kind, service=None, since=0.0):
            return [{"ts": 1.0, "module": module, "service": "orders", "kind": kind,
                     "value": 0.1, "meta": {"bad": object()}}]

        store.recent = unserializable_recent
        try:
            response = handle_request({"resource": "rca"})
        finally:
            store.recent = real_recent
        assert response == {"ok": False, "error": "read_failed"}, \
            "an unserializable row is a sanitized read failure, never fabricated JSON"
    finally:
        sys.stderr = saved_stderr
    diagnostics = logged.getvalue()
    assert "read failed (RuntimeError)" in diagnostics and "READ FAILED (TYPEERROR)" in \
        diagnostics.upper(), f"the diagnostic names the failure class only: {diagnostics!r}"
    for leak in ("aiops:aiops", secret, "SELECT", "Traceback", "secrets"):
        assert leak not in diagnostics, f"{leak!r} must never be logged"

    # --- the stdin -> stdout protocol -----------------------------------------
    stdin, stdout = _FakeStream(b'{"resource": "remediations", "since": 42}'), _FakeStream()
    saved_in, saved_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = stdin, stdout
    try:
        code = _with_fake_driver(fake, lambda: main([]))
    finally:
        sys.stdin, sys.stdout = saved_in, saved_out
    payload = json.loads(stdout.buffer.getvalue().decode("utf-8"))
    assert code == 0 and payload["ok"] is True and payload["rows"][0]["action_id"] == 11
    assert statements[-1][1] == (42.0,), "since crossed the process boundary as a parameter"

    empty_stdin, empty_stdout = _FakeStream(b""), _FakeStream()
    sys.stdin, sys.stdout = empty_stdin, empty_stdout
    try:
        code = main([])
    finally:
        sys.stdin, sys.stdout = saved_in, saved_out
    assert code == 1
    assert json.loads(empty_stdout.buffer.getvalue().decode("utf-8")) == \
        {"ok": False, "error": "invalid_request"}, "garbage in -> sanitized out, exit 1"

    # a failed initial write still answers the sanitized fallback — and the exit
    # code follows the emitted body (read_failed), not the original ok response
    broken_stdout, broken_stderr = _FailFirstWriteStream(), io.StringIO()
    saved_err = sys.stderr
    sys.stdin, sys.stdout, sys.stderr = (
        _FakeStream(b'{"resource": "remediations", "since": 0}'), broken_stdout, broken_stderr)
    try:
        code = _with_fake_driver(fake, lambda: main([]))
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved_in, saved_out, saved_err
    assert code == 1, "a read_failed fallback body must exit 1"
    assert json.loads(broken_stdout.buffer.getvalue().decode("utf-8")) == \
        {"ok": False, "error": "read_failed"}, "the fallback is the only body emitted"
    assert broken_stdout.buffer.writes == 2, "one failed write, then the fallback"
    assert "response serialization failed" in broken_stderr.getvalue(), \
        "the write failure is reported as a class-level diagnostic only"

    print("dashboard bridge selftest OK - store.recent() reuse, deterministic merge, "
          "parameterized read-only SQL, strict JSON, sanitized failures")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
