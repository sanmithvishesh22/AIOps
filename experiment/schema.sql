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
    policy              TEXT        NOT NULL,   -- 'hpa_tuned' | 'forecast_hybrid'
    workload_regime     TEXT        NOT NULL,   -- 'stationary' | 'diurnal' | 'spike' | 'bursty'
    fault_class         TEXT        NOT NULL,   -- e.g. 'cpu_stress','pod_kill','network_delay','mem_leak'
    is_negative_control BOOLEAN     NOT NULL,   -- TRUE where scaling cannot help (reported, never buried)
    seed                INTEGER,                -- RNG seed for reproducibility
    slo_p95_ms          DOUBLE PRECISION NOT NULL,  -- SLO in force for this run (predeclared)
    slo_error_rate      DOUBLE PRECISION NOT NULL,
    horizon_s           INTEGER,                -- prediction/forecast horizon H used
    notes               TEXT                    -- policy config (target_util, cooldown, bounds, HPA manifest ref)
);
CREATE INDEX IF NOT EXISTS run_pair ON experiment_run (pair_id);

-- 4.3 experiment_result — one scorecard per run (1:1 to experiment_run).
CREATE TABLE IF NOT EXISTS experiment_result (
    run_id                  BIGINT PRIMARY KEY REFERENCES experiment_run(run_id) ON DELETE CASCADE,
    slo_breach_duration_s   DOUBLE PRECISION,  -- PRIMARY outcome
    breaching_requests      BIGINT,            -- PRIMARY outcome
    breaching_request_ratio DOUBLE PRECISION,
    pod_minutes             DOUBLE PRECISION,  -- resource cost
    scaling_actions         INTEGER,           -- churn
    oscillations            INTEGER,           -- churn (up-down flips)
    mttd_s                  DOUBLE PRECISION,  -- detection quality (secondary)
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
    status        TEXT        NOT NULL DEFAULT 'proposed',  -- proposed|approved|rejected|applied|failed
    decided_by    TEXT,                   -- who approved/rejected
    decided_at    TIMESTAMPTZ,
    applied_at    TIMESTAMPTZ,
    outcome       TEXT,                   -- 'resolved' | 'no_effect' | 'regressed' | free text
    run_id        BIGINT REFERENCES experiment_run(run_id) ON DELETE SET NULL  -- run it happened during, if any
);
CREATE INDEX IF NOT EXISTS remediation_status ON remediation_action (status, proposed_at DESC);
