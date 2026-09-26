-- Contract D — experiment relational schema (TimescaleDB / plain Postgres).
-- The low-volume, relational counterpart to the `inference` hypertable (that one
-- lives in aiops/common/store.py; do NOT duplicate it here). These three tables are
-- the paired-experiment ledger + the human-in-the-loop remediation audit log. They
-- are deliberately relational (not JSONB) because the statistical analysis joins on
-- them. Idempotent: safe to run on every deploy. Authoritative shape:
-- TECHNICAL_ARCHITECTURE.md §4.2–4.4.
--
-- SLO/horizon columns are stamped on every run so a result is never read without the
-- threshold it was judged against. Those values are §9-owed (experiment/DECISIONS.md,
-- NOT signed off) — this schema stores whatever is predeclared, it does not pick them.

-- 4.2 experiment_run — one row per matched trial (the paired-analysis backbone).
CREATE TABLE IF NOT EXISTS experiment_run (
    run_id              BIGSERIAL   PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at            TIMESTAMPTZ,
    pair_id             TEXT        NOT NULL,   -- groups the hpa_tuned + forecast_hybrid runs to compare
    policy              TEXT        NOT NULL CHECK (policy IN ('hpa_tuned','forecast_hybrid')),
    workload_regime     TEXT        NOT NULL,   -- 'stationary' | 'diurnal' | 'spike' | 'bursty'
    fault_class         TEXT        NOT NULL,   -- e.g. 'cpu_stress','pod_kill','network_delay','mem_leak'
    is_negative_control BOOLEAN     NOT NULL,   -- TRUE where scaling cannot help (reported, never buried)
    seed                INTEGER,                -- RNG seed for reproducibility
    slo_p95_ms          DOUBLE PRECISION NOT NULL CHECK (slo_p95_ms >= 0),      -- SLO in force (predeclared)
    slo_error_rate      DOUBLE PRECISION NOT NULL CHECK (slo_error_rate BETWEEN 0 AND 1),
    horizon_s           INTEGER          CHECK (horizon_s >= 0),                 -- prediction/forecast horizon H
    notes               TEXT                    -- policy config (target_util, cooldown, bounds, HPA manifest ref)
);
CREATE INDEX IF NOT EXISTS run_pair ON experiment_run (pair_id);

-- 4.3 experiment_result — one scorecard per run (1:1 to experiment_run).
CREATE TABLE IF NOT EXISTS experiment_result (
    run_id                  BIGINT PRIMARY KEY REFERENCES experiment_run(run_id) ON DELETE CASCADE,
    slo_breach_duration_s   DOUBLE PRECISION CHECK (slo_breach_duration_s >= 0),  -- PRIMARY outcome
    breaching_requests      BIGINT           CHECK (breaching_requests >= 0),     -- PRIMARY outcome
    breaching_request_ratio DOUBLE PRECISION CHECK (breaching_request_ratio BETWEEN 0 AND 1),
    pod_minutes             DOUBLE PRECISION CHECK (pod_minutes >= 0),   -- resource cost
    scaling_actions         INTEGER          CHECK (scaling_actions >= 0),-- churn
    oscillations            INTEGER          CHECK (oscillations >= 0),   -- churn (up-down flips)
    mttd_s                  DOUBLE PRECISION CHECK (mttd_s >= 0),         -- detection quality (secondary)
    rca_top1_correct        BOOLEAN,           -- localization quality (secondary)
    remediation_success     BOOLEAN,           -- remediation quality (secondary)
    extra                   JSONB              -- any additional per-run metrics
);

-- 4.4 remediation_action — human-in-the-loop audit log (append-only).
-- Records that a human approved; this is accountability, NOT proof remediation is safe.
CREATE TABLE IF NOT EXISTS remediation_action (
    action_id     BIGSERIAL   PRIMARY KEY,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    service       TEXT        NOT NULL,   -- target service
    action_type   TEXT        NOT NULL,   -- 'scale' | 'restart' | 'rollout' | 'traffic_shift'
    params        JSONB,                  -- e.g. {"replicas": 5}
    evidence      JSONB,                  -- Contract-F bundle shown to the operator (scores, SHAP, forecast)
    status        TEXT        NOT NULL DEFAULT 'proposed'
                  CHECK (status IN ('proposed','approved','rejected','applied','failed')),
    decided_by    TEXT,                   -- who approved/rejected
    decided_at    TIMESTAMPTZ,
    applied_at    TIMESTAMPTZ,
    outcome       TEXT,                   -- 'resolved' | 'no_effect' | 'regressed' | free text
    run_id        BIGINT REFERENCES experiment_run(run_id) ON DELETE SET NULL  -- run it happened during, if any
);
CREATE INDEX IF NOT EXISTS remediation_status ON remediation_action (status, proposed_at DESC);

-- Append-only + forward-only guard on the remediation audit log. The log must be
-- tamper-evident: no row may be DELETEd, immutable fields (what/where/evidence) may
-- never be rewritten, and status may only advance proposed -> approved|rejected ->
-- applied|failed (never backward, never across terminal states). Same-status updates
-- are allowed only to record the outcome/decision timestamps. This proves a human
-- approved — accountability — NOT that the action is "safe". Idempotent (CREATE OR
-- REPLACE + DROP TRIGGER IF EXISTS), so it re-applies cleanly on every deploy.
CREATE OR REPLACE FUNCTION remediation_audit_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'remediation_action is append-only: DELETE blocked (action_id=%)', OLD.action_id;
    END IF;
    IF NEW.action_id   IS DISTINCT FROM OLD.action_id
    OR NEW.proposed_at IS DISTINCT FROM OLD.proposed_at
    OR NEW.service     IS DISTINCT FROM OLD.service
    OR NEW.action_type IS DISTINCT FROM OLD.action_type
    OR NEW.params      IS DISTINCT FROM OLD.params
    OR NEW.evidence    IS DISTINCT FROM OLD.evidence
    OR NEW.run_id      IS DISTINCT FROM OLD.run_id THEN
        RAISE EXCEPTION 'remediation_action: immutable field rewrite blocked (action_id=%)', OLD.action_id;
    END IF;
    IF NEW.status <> OLD.status
       AND (OLD.status, NEW.status) NOT IN (
           ('proposed','approved'), ('proposed','rejected'),
           ('approved','applied'),  ('approved','failed')) THEN
        RAISE EXCEPTION 'remediation_action: illegal status transition % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS remediation_audit_guard_trg ON remediation_action;
CREATE TRIGGER remediation_audit_guard_trg
    BEFORE UPDATE OR DELETE ON remediation_action
    FOR EACH ROW EXECUTE FUNCTION remediation_audit_guard();
