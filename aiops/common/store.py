"""TimescaleDB client for ML *inference results* (not raw metrics — those stay in
Prometheus). One generic hypertable keeps every module's output queryable and
joinable for the dashboard and the experiment analysis.

Schema:
  inference(ts, module, service, kind, value, meta jsonb)
    module  = detect|rca|explain|predict|forecast|scaler  (remediation uses the
              relational tables in experiment/schema.sql, not inference)
    kind    = e.g. anomaly_score, culprit_rank, breach_prob, forecast_p95, replicas_target
    value   = the number; meta = anything structured (feature attributions, etc.)
"""
from __future__ import annotations
import json
from . import config

DDL = """
CREATE TABLE IF NOT EXISTS inference (
    ts      TIMESTAMPTZ  NOT NULL,
    module  TEXT         NOT NULL,
    service TEXT         NOT NULL,
    kind    TEXT         NOT NULL,
    value   DOUBLE PRECISION,
    meta    JSONB
);
CREATE INDEX IF NOT EXISTS inference_lookup ON inference (module, service, kind, ts DESC);
"""
HYPERTABLE = "SELECT create_hypertable('inference','ts',if_not_exists=>TRUE);"

INSERT = ("INSERT INTO inference(ts, module, service, kind, value, meta) "
          "VALUES (to_timestamp(%s), %s, %s, %s, %s, %s)")


def _connect():
    import psycopg2  # lazy so offline selftest needs no driver
    return psycopg2.connect(config.TIMESCALE_DSN)


def init():
    with _connect() as c, c.cursor() as cur:
        cur.execute(DDL)
        try:
            cur.execute(HYPERTABLE)
        except Exception:
            pass  # plain Postgres without the Timescale ext still works


def normalize(rows):
    """rows: iterable of dicts with ts, module, service, kind, value, meta?.
    Returns tuples ready for executemany, meta json-encoded. Raises on missing keys
    so a malformed writer fails loudly instead of inserting nulls."""
    out = []
    for r in rows:
        out.append((
            float(r["ts"]), r["module"], r["service"], r["kind"],
            None if r.get("value") is None else float(r["value"]),
            json.dumps(r["meta"]) if r.get("meta") is not None else None,
        ))
    return out


def write(rows):
    tuples = normalize(rows)
    if not tuples:
        return 0
    with _connect() as c, c.cursor() as cur:
        cur.executemany(INSERT, tuples)
    return len(tuples)


def _recent_sql(module, kind, service, since):
    """Build the parameterized recent() query. Split out so the branch (service
    filter present or absent) is checkable offline without a database."""
    where = ["module = %s", "kind = %s", "ts >= to_timestamp(%s)"]
    params = [module, kind, float(since)]
    if service is not None:                      # service=None -> every service
        where.insert(2, "service = %s")
        params.insert(2, service)
    sql = ("SELECT extract(epoch from ts) AS ts, module, service, kind, value, meta "
           "FROM inference WHERE " + " AND ".join(where) + " ORDER BY ts DESC")
    return sql, tuple(params)


def recent(module, kind, service=None, since=0.0):
    """Read inference rows for a (module, kind[, service]) at/after `since` (unix
    seconds), newest first. service=None returns all services (what the dashboard
    read-API needs). Returns a list of column-keyed dicts, ts as unix seconds.
    Uses the (module, service, kind, ts DESC) index."""
    sql, params = _recent_sql(module, kind, service, since)
    with _connect() as c, c.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _selftest():
    rows = [
        {"ts": 1000.0, "module": "detect", "service": "orders", "kind": "anomaly_score",
         "value": -0.73, "meta": {"model": "iforest"}},
        {"ts": 1000, "module": "forecast", "service": "orders", "kind": "forecast_p95",
         "value": 612},
    ]
    t = normalize(rows)
    assert t[0][0] == 1000.0 and t[0][4] == -0.73
    assert json.loads(t[0][5])["model"] == "iforest"
    assert t[1][5] is None, "missing meta -> NULL"
    try:
        normalize([{"ts": 1, "module": "x"}])  # missing service/kind
        raise AssertionError("missing keys should raise")
    except KeyError:
        pass
    # recent(): service filter is optional and every %s placeholder is bound in order
    sql_all, p_all = _recent_sql("detect", "anomaly_score", None, 1000.0)
    assert "service = %s" not in sql_all and p_all == ("detect", "anomaly_score", 1000.0)
    sql_one, p_one = _recent_sql("detect", "anomaly_score", "orders", 1000.0)
    assert "service = %s" in sql_one and p_one == ("detect", "anomaly_score", "orders", 1000.0)
    assert sql_all.count("%s") == len(p_all) and sql_one.count("%s") == len(p_one)
    # insert+read round-trip with psycopg2 mocked (no driver needed) — proves write()
    # normalizes+INSERTs and recent() maps SELECT rows to column-keyed dicts.
    import sys, types
    seen = []
    class _Cur:
        description = [(c,) for c in ("ts", "module", "service", "kind", "value", "meta")]
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): seen.append(sql)
        def executemany(self, sql, rows): seen.append(sql); self._n = len(list(rows))
        def fetchall(self): return [(1000.0, "detect", "orders", "anomaly_score", -0.73,
                                     {"model": "iforest"})]
    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()
    fake = types.ModuleType("psycopg2"); fake.connect = lambda dsn: _Conn()
    saved = sys.modules.get("psycopg2")
    sys.modules["psycopg2"] = fake
    try:
        assert write(rows) == 2, "write() should report rows inserted"
        got = recent("detect", "anomaly_score", "orders", 0.0)
    finally:
        sys.modules.pop("psycopg2", None)
        if saved is not None:
            sys.modules["psycopg2"] = saved
    assert any("INSERT INTO inference" in s for s in seen), "write() must issue the INSERT"
    assert got[0]["module"] == "detect" and got[0]["ts"] == 1000.0, "recent() maps columns"
    assert got[0]["meta"] == {"model": "iforest"}, "recent() returns meta as-is"
    print("store selftest OK")


if __name__ == "__main__":
    _selftest()
