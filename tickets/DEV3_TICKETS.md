# Sanmith — Tickets
## Prediction, Forecasting & the Contribution (Scaler + Experiment)

**Mission:** Forecast near-term load/breach, drive the hybrid scaler, and run the matched experiment that is the project's sole scientific contribution. Guard the methodology like it's the thesis — because it is.

**How to use this file (prepend to every AI prompt below):**
> You are in the `aiops-platform` monorepo. Read `ARCHITECTURE.md`, `TECHNICAL_ARCHITECTURE.md`, `PARALLEL_DEV_PLAN.md`, and `experiment/DECISIONS.md` first. Rules: reuse `aiops/common/{prom,store,config}.py` (import, never re-implement); read config from env vars only; every module ships an offline `python -m aiops.<module> --selftest` (assert-based, no framework, no cluster) as its only test; edit only files inside your owned directories; never surface the retired claims ("first integrated platform", "integration is novel", "forecast accuracy proves reliability", "RCA proves causality", "human approval makes remediation safe", "Sock Shop generalizes to production"); keep it minimal — no speculative abstractions.

**Files you own:** `aiops/predict/*`, `aiops/forecast/*`, `aiops/scaler/*`, `experiment/{load,faults,runner,analysis}/*`, `deploy/platform/base/hpa-*.yaml` (deps live in the base `requirements.txt` — uncomment the prophet extra for forecast).

**Files to avoid:** `aiops/common/*` (import only), `experiment/schema.sql` (Dev 1 owns the DDL — you consume it), the dashboard/eval rendering (Dev 4).

**Contracts you must honor:** write `breach_prob`/`breach_duration_est` (predict), `forecast_p95`/`forecast_p95_snaive`/`forecast_p95_tree` (forecast), `replicas_target` (scaler) via `store.py`; write `experiment_run`/`experiment_result` rows to the tables Dev 1 defined; consume Contract-C feature frames. **Every §9 constant you use must be the signed-off value from `experiment/DECISIONS.md`** — until D3-000 is signed off you build against its defaults, but no result is valid.

**Guardrails that live in your stream:** negative-control faults are mandatory and reported separately (a null result there is correct); chronological holdout + infected-period exclusion + ≥20 paired reps + randomized order; the tuned-HPA baseline must be genuinely tuned (fair comparison); max-replica cap enforced server-side.

---

### D3-000 — Author §9 decision proposals · **Must** · deps: none · Phase 0 · ⚠️ needs advisor sign-off, NOT a coding task
**Build:** first-pass defensible defaults for the six predeclared decisions. *(Already drafted at `experiment/DECISIONS.md` — this ticket is getting it reviewed, calibrated, and signed off.)*
**Done when:** each of the six has a signed-off value; the ⚙️ calibration run (nominal p95, per-replica capacity, pod-ready time) is done; values frozen before any trial.
**Prompt:**
> Review `experiment/DECISIONS.md`. Run the baseline characterization on the testbed to fill the ⚙️ values (nominal p95, per-replica capacity, pod-ready time). Justify each of the six against `LITERATURE_SURVEY_DECISION_REPORT.md`. Get advisor sign-off. Nothing here is a coding decision — do not let an AI agent pick these.

### D3-001 — Failure prediction at horizon H · **Must** · deps: D1-001 (fixture); scoring needs D3-000 · Phase 1
**Build:** predict near-term SLO breach at H; writes `breach_prob`, `breach_duration_est`.
**Done when:** chronological 2/3–1/3 holdout (no leakage), infected-period exclusion, PR-AUC reported (≥70% precision target); `--selftest` green.
**Prompt:**
> In `aiops/predict/`, predict near-term SLO breach at horizon H from feature frames; write `breach_prob`, `breach_duration_est`. Use a strictly CHRONOLOGICAL 2/3–1/3 holdout (no shuffling → no leakage), exclude infected periods from training, report PR-AUC (target ≥70% precision). `--selftest` asserts the split is chronological and PR-AUC is computed.

### D3-002 — Capacity forecasting + baselines · **Must** · deps: D1-001 · Phase 1
**Build:** Prophet/seasonal forecast feeding the scaler; must beat seasonal-naive + tree baselines.
**Done when:** main forecast error < both baselines on the fixture; baselines logged alongside; `--selftest` green.
**Prompt:**
> In `aiops/forecast/`, Prophet/seasonal forecast of per-service p95/load feeding the scaler; write `forecast_p95` AND the two baselines `forecast_p95_snaive`, `forecast_p95_tree`. Add a seasonality gate. `--selftest` asserts the main forecast beats both baselines on the fixture. Uncomment the prophet extra in `requirements.txt`.

### D3-003 — Forecast-assisted hybrid scaler (the contribution) · **Must** · deps: D3-002, D3-000 · Phase 1
**Build:** forecast → desired replicas with predeclared map, cooldown, bounds; writes `replicas_target`; scales via k8s API.
**Done when:** emits a bounded, cooldown-respecting target; max-replica cap enforced server-side; `--selftest` (mock k8s) green.
**Prompt:**
> In `aiops/scaler/`, map forecast → desired replicas with the predeclared forecast→replica map, cooldown, and min/max bounds; write `replicas_target` with `meta={current,reason,cooldown_s,bounds}`; scale via the k8s API (`apps/v1` scale). Enforce the max-replica cap SERVER-SIDE (denial-of-wallet guard). `--selftest` (mock k8s) asserts bounded, cooldown-respecting targets.

### D3-004 — Tuned HPA baseline + procedure · **Must** · deps: D1-002, D3-000 · Phase 1
**Build:** native HPA v2 manifests + the predeclared tuning procedure (the fair reactive comparator).
**Done when:** manifests apply; tuning procedure documented + reproducible; resource bounds match the scaler.
**Prompt:**
> Author native HPA v2 manifests (`deploy/platform/base/hpa-*.yaml`) + document the predeclared tuning procedure; ensure resource bounds match the scaler for a fair comparison. Verify manifests apply on the testbed.

### D3-005 — Load harness / 4 regimes · **Must** · deps: D1-002, D3-000 · Phase 1
**Build:** k6 Jobs for stationary/diurnal/spike/bursty, each seeded and parametrized.
**Done when:** each regime reproducible from a seed; runs as a k6 Job; parametrized by regime.
**Prompt:**
> In `experiment/load/`, k6 Jobs for the four regimes, each reproducible from a seed and parametrized by regime name. `--selftest`/dry-run asserts each regime's shape.

### D3-006 — Fault harness + negative controls · **Must** · deps: D1-002, D3-000 · Phase 1
**Build:** Chaos Mesh schedules for capacity-responsive faults AND mandatory negative controls, each tagged.
**Done when:** each fault reproducible + labeled; controls separated; **hard guard that faults target only `SOCK_NS`**; `--selftest` asserts the guard + tagging.
**Prompt:**
> In `experiment/faults/`, Chaos Mesh schedules for capacity-responsive faults (CPU stress, pod-kill) AND mandatory negative controls (network, code/5xx, dependency-kill, memory-leak), each tagged `is_negative_control`. HARD guard: faults may target ONLY the local testbed namespace (`SOCK_NS`) — assert this and refuse otherwise. `--selftest` asserts the namespace guard and control tagging.

### D3-007 — Paired-trial runner · **Must** · deps: D3-003/4/5/6, D1-004 · Phase 2
**Build:** run HPA and scaler under identical conditions per regime × fault; write results tables.
**Done when:** matched pairs share seed/regime/fault; policy order randomized; ≥20 reps; infected-period rows excluded from metrics.
**Prompt:**
> In `experiment/runner/`, for each regime × fault run HPA and scaler under identical conditions; ≥20 paired reps, randomized policy order, same seed per pair; write `experiment_run`/`experiment_result`; exclude infected-period samples from metrics. `--selftest` asserts pairing, randomization, and rep count on a mocked run.

### D3-008 — Analysis · **Must** · deps: D3-007 · Phase 3
**Build:** primary metrics with 95% bootstrap CIs + effect sizes; controls reported separately.
**Done when:** CI'd primaries + a separate negative-control section; null results shown as-is; reproducible from the results tables.
**Prompt:**
> In `experiment/analysis/`, compute primary metrics (SLO-breach duration, breaching requests) with 95% bootstrap CIs + effect sizes; secondary cost/churn; report negative controls in a SEPARATE section and print a null result as-is (never bury). `--selftest` asserts CIs are produced and controls are segregated.

### D3-009 — Per-service failure-mode taxonomy · **Nice** · deps: D3-001 · Phase 4
**Build:** richer per-service prediction labels.
**Done when:** optional label set; `--selftest` green; no impact on primary metrics.
**Prompt:**
> Add richer per-service prediction labels in `aiops/predict/`. `--selftest` green; must not change primary metrics.

---

## Integration / QA you own

### INT-004 — Experiment integration · **Must** · deps: D3-002..007, D1-004 · Phase 2
**Prompt:** > Wire scaler ↔ forecast ↔ HPA ↔ load ↔ faults ↔ runner ↔ results tables; run one full paired trial end-to-end on the testbed.

### QA-003 — Experiment validity audit · **Must** · deps: D3-007 · Phase 3
Automated audit asserting chronological holdout (no leakage), infected-period exclusion, ≥20 paired reps, randomized policy order, and negative controls present + reported separately. **A failure invalidates results — make it loud.**

### QA-004 (forecast/predict half) · **Must** · Phase 3
PR-AUC ≥ target for predict; forecast error < seasonal-naive + tree baselines. **Instrument-quality metrics, not reliability proof** — label as such.

---

**Definition of done (Sanmith):** scaler + HPA run head-to-head under all regimes × faults; results tables populate; analysis emits CI'd primaries + a separate negative-control section; every §9 constant used is the signed-off value. **No result is presented until D3-000 is signed off.**
