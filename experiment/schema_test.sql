-- Proof test for the D1-004 integrity guards on the experiment schema.
-- Proves: remediation_action is append-only (no DELETE), immutable fields cannot be
-- rewritten, status only advances legally, and the CHECK constraints fire.
--
-- Requires a running Postgres/TimescaleDB with schema.sql already applied. It CANNOT
-- run in an offline sandbox (there is no PL/pgSQL engine there). Run it via:
--     make schema-test
-- or directly (port-forward the DB first, e.g. kubectl -n aiops port-forward svc/timescaledb 5432:5432):
--     psql "$TIMESCALE_DSN" -v ON_ERROR_STOP=1 -f experiment/schema.sql -f experiment/schema_test.sql
--
-- Pattern: each negative case runs the illegal statement inside a DO block; if the
-- statement is (wrongly) allowed, we RAISE a 'FAIL:' sentinel which is re-raised and
-- aborts the run. If the guard fires as intended, the exception is swallowed = pass.
-- Everything runs in one transaction that is ROLLBACKed, so the test leaves no rows.

BEGIN;

-- A run to hang results/remediation off of (also exercises the happy-path CHECKs).
INSERT INTO experiment_run (pair_id, policy, workload_regime, fault_class, is_negative_control,
                            slo_p95_ms, slo_error_rate, horizon_s)
VALUES ('p-test', 'forecast_hybrid', 'spike', 'cpu_stress', false, 300, 0.01, 120);

-- POSITIVE: the full legal lifecycle must be permitted (any failure here aborts).
INSERT INTO remediation_action (service, action_type, params, evidence, status)
VALUES ('front-end', 'scale', '{"replicas":5}', '{"detect":0.9}', 'proposed');
UPDATE remediation_action SET status='approved', decided_by='alice', decided_at=now() WHERE service='front-end';
UPDATE remediation_action SET status='applied', applied_at=now()                       WHERE service='front-end';
UPDATE remediation_action SET outcome='resolved'                                       WHERE service='front-end';  -- same status: allowed

-- NEGATIVE 1: DELETE is blocked (append-only).
DO $$ BEGIN
    DELETE FROM remediation_action WHERE service='front-end';
    RAISE EXCEPTION 'FAIL: DELETE was allowed';
EXCEPTION WHEN sqlstate 'P0001' THEN IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF; END $$;

-- NEGATIVE 2: backward status transition (applied -> proposed) is blocked.
DO $$ BEGIN
    UPDATE remediation_action SET status='proposed' WHERE service='front-end';
    RAISE EXCEPTION 'FAIL: backward status transition allowed';
EXCEPTION WHEN sqlstate 'P0001' THEN IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF; END $$;

-- NEGATIVE 3: rewriting an immutable field (service) is blocked.
DO $$ BEGIN
    UPDATE remediation_action SET service='catalogue' WHERE service='front-end';
    RAISE EXCEPTION 'FAIL: immutable field rewrite allowed';
EXCEPTION WHEN sqlstate 'P0001' THEN IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF; END $$;

-- NEGATIVE 4: CHECK on policy enum rejects an unknown policy.
DO $$ BEGIN
    INSERT INTO experiment_run (pair_id, policy, workload_regime, fault_class, is_negative_control,
                                slo_p95_ms, slo_error_rate, horizon_s)
    VALUES ('p-bad','BOGUS','spike','cpu_stress',false,300,0.01,120);
    RAISE EXCEPTION 'FAIL: bad policy accepted';
EXCEPTION
    WHEN check_violation THEN NULL;                                   -- expected
    WHEN sqlstate 'P0001' THEN IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF; END $$;

-- NEGATIVE 5: CHECK rejects a negative primary duration.
DO $$
DECLARE r bigint;
BEGIN
    SELECT run_id INTO r FROM experiment_run WHERE pair_id='p-test';
    INSERT INTO experiment_result (run_id, slo_breach_duration_s) VALUES (r, -5);
    RAISE EXCEPTION 'FAIL: negative duration accepted';
EXCEPTION
    WHEN check_violation THEN NULL;                                   -- expected
    WHEN sqlstate 'P0001' THEN IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF; END $$;

DO $$ BEGIN RAISE NOTICE 'schema_test OK'; END $$;

ROLLBACK;
