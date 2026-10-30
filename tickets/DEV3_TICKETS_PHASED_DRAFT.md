# Sanmith (Dev 3) — Phased Ticket Breakdown · **DRAFT (v2 — production detail)**

> **Draft only.** Expands `DEV3_TICKETS.md` into individually-closeable sub-tickets with
> production-level implementation + testing detail. Does **not** replace `DEV3_TICKETS.md`.
> **No §9 value is invented here** — every constant (SLO p95, horizon H, severity cuts,
> load-regime RPS, fault schedule, scaler map, ⚙️ anchors) is read from
> `experiment/DECISIONS.md`/config as the signed-off value. Specifying *how* to build/test
> a ticket never includes *picking* a decision value; those stay human-ratified.

**Mission (unchanged):** Forecast near-term load/breach, drive the hybrid scaler, run the
matched experiment that is the project's sole scientific contribution. Guard the
methodology like it's the thesis — because it is.

**Prepend to every AI prompt:** You are in the `aiops-platform` monorepo. Read
`ARCHITECTURE.md`, `TECHNICAL_ARCHITECTURE.md`, `PARALLEL_DEV_PLAN.md`, and
`experiment/DECISIONS.md` first. Reuse `aiops/common/{prom,store,config}.py` (import, never
re-implement); read config from env only; every module ships an offline
`python -m aiops.<module> --selftest`; edit only owned directories; never surface the
retired claims; keep it minimal — detail ≠ speculative abstraction.

**Files owned:** `aiops/predict/*`, `aiops/forecast/*`, `aiops/scaler/*`,
`experiment/{load,faults,runner,analysis}/*`, `deploy/platform/base/hpa-*.yaml`.

**Phase gate (hard):** No result is valid as a headline until **Phase 0** is signed off and
the ⚙️ anchors are frozen. Modules may be *built & unit-tested* against provisional defaults
in Phase 1; their *scored output* is not valid until the gate clears.

---

## Cross-cutting production standards  *(every ticket inherits these — "PS-n")*

- **PS-1 Config from env, single source.** All §9 constants via `aiops.common.config`
  (env-backed). No literals in module code. Missing/invalid env → fail fast at startup with
  a named error, never a silent default of a §9 value.
- **PS-2 Determinism.** Every stochastic step (model init, k6 arrival process, fault
  timing, bootstrap) takes an explicit seed logged into output `meta`/run row. Same seed ⇒
  byte-identical result. No wall-clock or un-seeded RNG in a scored path.
- **PS-3 Fail-closed safety.** Scaler, faults, and k8s calls refuse rather than guess:
  bad target → clamp + log; wrong namespace → raise; missing model → exit non-zero. Never
  take a destructive or cluster-mutating action on malformed input.
- **PS-4 Idempotency & restart-safety.** Re-running a step with the same inputs must not
  double-write or corrupt results (store writes keyed by (ts,module,service,kind); runner
  reps resumable by run-id). Partial failure leaves a recoverable state.
- **PS-5 Observability.** Structured logs (level, module, service, action, seed) to stderr;
  one-line human summary to stdout. No secrets in logs. Metrics/latency of the module's own
  work surfaced where it aids debugging.
- **PS-6 Data hygiene.** NaN gaps preserved end-to-end (never zero-filled); timestamps UTC
  epoch seconds; feature frames sorted (ts, service); no lookahead past `t` in any feature.
- **PS-7 Secrets/boundaries.** TimescaleDB creds from env (local-testbed `aiops/aiops` only);
  read-API/dashboard stay unauthenticated + localhost-only (deliberate v1, documented).
  Remediation/scaling actions are the only cluster-mutating paths and are capped server-side.
- **PS-8 Resource caps.** Max-replica cap enforced server-side (denial-of-wallet guard);
  load/fault jobs bounded in duration and blast radius (`SOCK_NS` only).

## Testing standards  *(every ticket inherits these — "TS-n")*

- **TS-1 Offline selftest is the floor.** `python -m aiops.<module> --selftest`: assert-based,
  no framework, no cluster, no network. Runs in CI (`make selftest`) and is the merge gate.
- **TS-2 Four tiers.** (a) *unit* assertions inside selftest; (b) *property/invariant* tests
  (leakage, monotonic bounds, idempotency); (c) *integration* on mock k8s / mock store /
  mocked run; (d) *live* smoke on the testbed (manual, gated behind `make up`), documented
  but never in the CI gate.
- **TS-3 Negative tests mandatory.** Each guard ships the test that *fails* it: wrong
  namespace is refused, future-row perturbation doesn't change past features, cap can't be
  exceeded, threshold never read from holdout. A guard without its red test is unfinished.
- **TS-4 Edge coverage.** Empty frame, single row, all-NaN column, single-class labels,
  missing service, duplicate timestamps, cold start (insufficient history) — each handled
  explicitly and asserted (raise-with-message or defined fallback, never crash with a bare
  KeyError).
- **TS-5 Reproducibility test.** Re-run with fixed seed ⇒ identical artifact/metrics (PS-2).
- **TS-6 Fixture discipline.** `sample_frame()` is a SHAPE fixture; modules synthesize a
  larger seeded series in-selftest for anything needing training volume. Synthetic data is
  labeled as mechanics-only; no synthetic result is ever presented as a §9 measurement.
- **TS-7 Validity audit (QA-003) is CI-loud.** Any methodology violation (leakage, missing
  embargo, <20 reps, un-randomized order, controls not segregated) fails the build visibly.

## Phase 0 — §9 Freeze & Baseline Characterization  *(was D3-000)*
**Not a coding phase for the values.** The three ⚙️ anchors are **measured on the testbed**,
never chosen by an AI agent. Needs Dev 1's testbed (`make up`) + advisor sign-off.
**Exit:** six decisions signed off + three anchors measured, recorded with provenance, frozen & dated.

### D3-000.1 — Justify the six §9 decisions · Must · deps: none
- **Deliverable:** one justification block per decision in `DECISIONS.md`.
- **Content/edge:** each cites specific survey findings in `LITERATURE_SURVEY_DECISION_REPORT.md`;
  record the alternatives considered + why rejected; mark anything unsupported by literature as
  "operator judgement" so reviewers see it.
- **Tests:** doc-review checklist (all six present, each with ≥1 citation + rejected-alternative).
- **Done:** advisor can trace every decision to a source or an explicit judgement call.

### D3-000.2 — Pre-register the predeclared constants table · Must · deps: D3-000.1
- **Deliverable:** frozen-format table (SLO p95/error-rate, horizon H, severity cuts, 4 load
  regimes, fault schedule, scaler map) with proposed values + units + rationale.
- **Edge:** every row flagged *provisional — pending anchors*; a machine-readable mirror lives
  in config/env so code reads values, never the prose table (PS-1).
- **Tests:** a check that each config key referenced by Phase-1 code exists in the table and vice
  versa (no orphan constant, no undocumented knob).
- **Done:** table + config in sync; pre-registration timestamped before any trial.

### D3-000.3 — Characterization run procedure + harness readiness · Must · deps: D1 testbed
- **Deliverable:** a documented, repeatable measurement procedure + the tooling to execute it
  (collection scripts/queries only — **this ticket does not pick values**).
- **Procedure spec:** warmup window discarded; fixed measurement duration; N repeats; percentile
  math defined (p95 over the SLO window); provenance captured (image digests, node, k6 seed,
  commit, timestamp). Methodology is production-grade; the *outputs* are human-ratified.
- **Tests:** dry-run on mock metrics asserts the procedure computes p95/capacity/ready-time from
  a known series correctly (math verified offline); checks testbed reachable before a live run.
- **Done:** procedure reviewed; `make up` confirmed; one dry-run green.

### D3-000.4 — Measure nominal p95 · Must · deps: D3-000.3 · ⚠️ measurement, not a coding decision
- **Run:** baseline (no fault, nominal regime), warmup discarded, N repeats, record p95 + spread.
- **Edge:** reject the run if testbed is unhealthy (API flaps — see testbed-bringup notes) or
  variance exceeds a documented tolerance; re-run rather than report a noisy anchor.
- **Done:** value + full provenance recorded; shared with advisor; **no AI-chosen number**.

### D3-000.5 — Measure per-replica capacity · Must · deps: D3-000.3 · ⚠️ measurement
- **Run:** ramp load against a single replica; capacity = max sustained RPS within SLO.
- **Edge:** confirm the knee is load-bound, not dependency-bound (watch downstream saturation);
  document the saturation signal used.
- **Done:** value + method + provenance recorded.

### D3-000.6 — Measure pod-ready time · Must · deps: D3-000.3 · ⚠️ measurement
- **Run:** measure schedule→Ready latency across N scale-ups; report median + tail.
- **Edge:** cold image pull vs warm cache distinguished (report the regime the experiment will
  actually hit); exclude failed schedules with reason logged.
- **Done:** value(s) + method + provenance recorded.

### D3-000.7 — Freeze anchors + advisor sign-off · Must · deps: D3-000.1..6 · 🔒 GATE
- **Deliverable:** measured anchors folded into `DECISIONS.md`/config as signed-off values;
  advisor sign-off on all six decisions.
- **Edge:** once frozen, any later change requires a new sign-off + a note invalidating prior
  trials that used the old value (no silent re-tuning mid-experiment).
- **Tests:** config now exposes final anchors; a guard flips results from "provisional" to
  "valid" only when the signed-off flag/date is present.
- **Done:** values frozen + dated; **downstream results become valid from here**.

## Phase 1 — Module & Harness Builds
Built + unit-tested against Phase-0 provisional defaults; scored output not valid until D3-000.7.
All tickets inherit PS-1..8 and TS-1..7. **Exit:** predict/forecast/scaler/HPA/load/faults `--selftest` green.

### D3-001 — Failure prediction at horizon H  *(deps: D1-001 fixture; scoring needs D3-000.7)*

#### D3-001.1 — Leakage-safe features · Must
- **Implements:** `features.build_features(frame) -> (df, feature_cols)`; per-service lags,
  rolling mean/std, slope using only rows ≤ t; grouped by service, no cross-service bleed.
- **Edge:** early rows get NaN (left for the imputer, PS-6); single-row service → all-NaN
  derived feats, no crash; duplicate ts raises (TS-4).
- **Tests:** TS-3 leakage probe — spiking a future row must not change any earlier row's
  features (`np.allclose`, equal_nan); feature set stable/ordered; empty frame → empty, typed.

#### D3-001.2 — Forward §9 breach label at H · Must · deps: D3-001.1
- **Implements:** `label_frame(frame)` → `y_major` (any MAJOR in (t, t+H]) + `dur_est_s`
  (clipped [0,H]); severity from signed-off cuts via config (450ms cut via `SLO_MAJOR_P95_MS`
  until Dev 1 folds it into config — flag kept).
- **Edge:** label strictly forward (own window excluded — prediction not detection); NaN metric
  grades `none`, never fabricated into a breach.
- **Tests:** both classes present on the seeded fixture; label window never includes t; a known
  hand-built series yields the hand-computed labels.

#### D3-001.3 — Chronological holdout + embargo + infected exclusion · Must · deps: D3-001.2
- **Implements:** `chrono_split(df, train_frac=2/3)` with an H-second embargo; `exclude_infected`.
- **Edge:** if a side ends up single-class, raise with a clear message (don't fit a degenerate
  model); embargo removes any train row whose label window reaches ≥ cut.
- **Tests:** `train.ts.max()+H <= test.ts.min()`; zero infected rows in train; no shuffle
  (order preserved); boundary case where cut lands on a shared timestamp.

#### D3-001.4 — Classifier + duration regressor · Must · deps: D3-001.3
- **Implements:** scikit-learn pipelines (impute→scale→LogisticRegression, class_weight
  balanced; impute→GradientBoostingRegressor) behind `BreachPredictor`; sklearn lazy-imported
  so the module/metrics import on numpy+pandas alone; joblib persistence (`save`/`load`).
- **Edge:** duration clipped to [0, H]; `fit` asserts two classes present; model artifact
  versioned with feature list + seed in `meta` (PS-2) so stale features fail loudly on load.
- **Tests:** integration test monkeypatches `_build` with a fake estimator (same
  fit/predict_proba/predict interface) to exercise fit→predict→save→load with no sklearn;
  real fit runs in the live/`--selftest` tier on a machine with sklearn installed.

#### D3-001.5 — Threshold selection + PR-AUC · Must · deps: D3-001.4
- **Implements:** numpy `pr_auc`, `precision_recall_at`, `select_threshold` (smallest threshold
  meeting the ≥70% precision target while maximising recall; fallback = max-precision with
  `target_met=False`). Threshold chosen on TRAIN scores only.
- **Edge:** no positives → PR-AUC NaN handled; target unreachable → reported, not silently
  met; ties broken deterministically.
- **Tests:** TS-3 — assert threshold derivation never reads holdout; PR-AUC == 1.0 on perfectly
  separable toy data, == prevalence-ish on random; reproducible under fixed seed.

#### D3-001.6 — Contract-A rows + store write + offline selftest · Must · deps: D3-001.5
- **Implements:** `inference_rows(predictor, frame, ts=None)` → `breach_prob` +
  `breach_duration_est` rows (meta: horizon_s, threshold), on `_KINDS["predict"]`; `store.write`.
- **Edge:** 2 rows per input row; rows survive `store.normalize`; idempotent re-write (PS-4).
- **Tests:** full offline `--selftest` chains all of 001.1–001.6 on a seeded synthetic series;
  asserts vocabulary == `_KINDS["predict"]`; scoring labelled provisional until D3-000.7.

### D3-002 — Capacity forecasting + baselines  *(deps: D1-001)*

#### D3-002.1 — Main forecast · Must
- **Implements:** `aiops/forecast/` Prophet/seasonal forecast of per-service p95/load → `forecast_p95`;
  uncomment the prophet extra in `requirements.txt`; Prophet lazy-imported (heavy dep).
- **Edge:** cold start / < one season of history → documented fallback (no crash, TS-4);
  non-finite inputs dropped with a logged count.
- **Tests:** forecast produced on fixture; horizon + cadence match config; reproducible (PS-2).

#### D3-002.2 — Seasonal-naive baseline · Must · deps: D3-002.1
- **Implements:** `forecast_p95_snaive` (last-season carry-forward).
- **Tests:** exact hand-check on a periodic toy series; written alongside main forecast.

#### D3-002.3 — Tree baseline · Must · deps: D3-002.1
- **Implements:** `forecast_p95_tree` (lagged-feature regressor), seeded.
- **Tests:** deterministic under seed; writes the baseline kind.

#### D3-002.4 — Seasonality gate · Must · deps: D3-002.1
- **Implements:** detect weak/absent seasonality → fall back (e.g. to snaive) rather than emit a
  spurious seasonal fit.
- **Tests:** flat/noise series trips the gate; strongly periodic series does not.

#### D3-002.5 — Comparison + selftest · Must · deps: D3-002.2, D3-002.3
- **Implements:** error metric (per config) comparing main vs both baselines on the fixture.
- **Edge:** metric computed on the same horizon/alignment for all three (apples-to-apples).
- **Tests:** `--selftest` asserts main beats BOTH baselines on the fixture; result labelled
  instrument-quality (not reliability proof); fails loud if a baseline is missing.

### D3-003 — Forecast-assisted hybrid scaler  *(deps: D3-002, D3-000.7)*

#### D3-003.1 — Forecast→replicas map · Must
- **Implements:** `aiops/scaler/` pure function `desired_replicas(forecast, capacity) -> int`
  using the **predeclared** map + per-replica capacity anchor (signed-off, from config — not
  AI-picked).
- **Edge:** forecast NaN/negative → hold last-known-good + log reason; capacity anchor absent
  (pre-D3-000.7) → refuse to emit a scored target.
- **Tests:** table-driven unit cases map forecast → expected replicas; pure + deterministic.

#### D3-003.2 — Cooldown + bounds · Must · deps: D3-003.1
- **Implements:** min/max bounds + scale-up/down cooldown (per config).
- **Edge:** flapping suppressed by cooldown; bounds clamp before any API call (PS-3).
- **Tests:** rapid oscillating forecast yields cooldown-respecting, bounded targets.

#### D3-003.3 — k8s scale client · Must · deps: D3-003.1
- **Implements:** `apps/v1` scale via the k8s API behind a thin client interface (mockable).
- **Edge:** API error/conflict → retry-with-backoff then give up logging state (PS-4/PS-5);
  never partial-apply across services.
- **Tests:** integration against a mock k8s client asserts the correct scale call; failure
  injection asserts no crash + no half-applied state.

#### D3-003.4 — Server-side max-replica cap · Must · deps: D3-003.3
- **Implements:** cap enforced at the apply boundary (denial-of-wallet guard, PS-8), independent
  of the computed target.
- **Tests:** TS-3 — a target above the cap is clamped at the server boundary; assert it is
  impossible to exceed even with a malicious/buggy upstream target.

#### D3-003.5 — `replicas_target` write + mock-k8s selftest · Must · deps: D3-003.2, D3-003.4
- **Implements:** write `replicas_target` with `meta={current,reason,cooldown_s,bounds,seed}`.
- **Tests:** `--selftest` (mock k8s) asserts bounded + cooldown-respecting targets, cap honored,
  rows on `_KINDS["scaler"]`, idempotent re-write.

### D3-004 — Tuned HPA baseline  *(deps: D1-002, D3-000.7)*

#### D3-004.1 — HPA v2 manifests · Must
- **Implements:** `deploy/platform/base/hpa-*.yaml` (autoscaling/v2).
- **Edge:** target metrics + behavior fields set explicitly (no cluster defaults silently in play).
- **Tests:** `kubectl apply --dry-run=server` + schema lint in CI; live apply on testbed.

#### D3-004.2 — Tuning procedure doc · Must · deps: D3-004.1
- **Implements:** the predeclared, reproducible tuning procedure (genuinely tuned = fair comparator).
- **Edge:** procedure fixed BEFORE trials; any retune invalidates affected runs (ties to D3-000.7 rule).
- **Tests:** a second person can reproduce the tuned config from the doc alone (review check).

#### D3-004.3 — Resource-bound parity · Must · deps: D3-004.1
- **Implements:** requests/limits + min/max replicas identical to the scaler's.
- **Tests:** automated diff asserts HPA bounds == scaler bounds (fairness guard) — fails loud if not.

### D3-005 — Load harness / 4 regimes  *(deps: D1-002, D3-000.7)*

#### D3-005.1 — k6 Job scaffold + seed/param plumbing · Must
- **Implements:** `experiment/load/` base k6 Job, parametrized by regime name, seed-driven arrivals (PS-2).
- **Edge:** blast radius bounded to `SOCK_NS` services; duration capped; invalid regime name rejected.
- **Tests:** dry-run renders a valid k6 script per regime.

#### D3-005.2 — Stationary regime · Must · deps: D3-005.1
#### D3-005.3 — Diurnal regime · Must · deps: D3-005.1
#### D3-005.4 — Spike regime · Must · deps: D3-005.1
#### D3-005.5 — Bursty regime · Must · deps: D3-005.1
> Each regime's RPS magnitudes/shape come from the signed-off regime definition (§9 — not
> AI-picked). Each ships a shape assertion (mean/peak/variance envelope) + seed-reproducibility test.

#### D3-005.6 — Dry-run/selftest · Must · deps: D3-005.2..5
- **Tests:** `--selftest`/dry-run asserts each regime matches its shape envelope and is identical
  across two runs with the same seed; distinct seeds differ.

### D3-006 — Fault harness + negative controls  *(deps: D1-002, D3-000.7)*

#### D3-006.1 — Namespace hard guard · Must
- **Implements:** `experiment/faults/` guard — resolve target namespace, raise/refuse unless `SOCK_NS`.
- **Edge:** guard runs BEFORE any schedule is created; empty/unset namespace → refuse (fail-closed, PS-3).
- **Tests:** TS-3 — passing any non-`SOCK_NS` target raises; `SOCK_NS` passes.

#### D3-006.2 — Capacity-responsive faults · Must · deps: D3-006.1
- **Implements:** Chaos Mesh schedules for CPU stress + pod-kill, each tagged + seed/timed (PS-2).
- **Tests:** schedule objects validate; tags present; reproducible from seed.

#### D3-006.3 — Negative-control faults · Must · deps: D3-006.1
- **Implements:** network, code/5xx, dependency-kill, memory-leak, each tagged `is_negative_control`.
- **Rationale:** a null effect here is the *correct* result (guards against false attribution).
- **Tests:** each control tagged + reproducible; distinct from capacity-responsive set.

#### D3-006.4 — Tagging + reproducibility selftest · Must · deps: D3-006.2, D3-006.3
- **Tests:** `--selftest` asserts the namespace guard, control tagging, and that every fault is
  labelled + reproducible; refuses to emit an untagged fault.

## Phase 2 — Paired Runner & Integration
**Exit:** one full paired trial runs end-to-end; results tables populate; QA-003 passes on the run.

### D3-007 — Paired-trial runner  *(deps: D3-003/4/5/6, D1-004)*

#### D3-007.1 — Matched-pair construction · Must
- **Implements:** `experiment/runner/` builds, per regime × fault, a pair identical in
  seed/regime/fault/duration — policy (HPA vs scaler) the only difference.
- **Edge:** a pair where one side fails to start is discarded as a pair (never a half-pair in metrics).
- **Tests:** mocked run asserts both members share seed/regime/fault and differ only in policy.

#### D3-007.2 — Randomized policy order · Must · deps: D3-007.1
- **Implements:** seeded randomization of which policy runs first within each pair (removes
  order/warmup bias).
- **Tests:** TS-3/TS-5 — order varies across pairs, is reproducible under the master seed, and
  is logged per pair.

#### D3-007.3 — ≥20 reps orchestration · Must · deps: D3-007.1
- **Implements:** drive ≥20 paired reps per regime × fault cell; resumable by run-id (PS-4).
- **Edge:** crash mid-matrix resumes without duplicating completed reps.
- **Tests:** mocked run asserts rep count ≥20 per cell and resume skips completed reps.

#### D3-007.4 — Results writes · Must · deps: D3-007.1
- **Implements:** write `experiment_run`/`experiment_result` to Dev 1's tables (consume schema,
  don't define it); full provenance (seeds, image digests, policy, regime, fault) per row.
- **Tests:** rows written per rep; idempotent under re-run; schema-conformant insert on mock store.

#### D3-007.5 — Infected exclusion + selftest · Must · deps: D3-007.2..4
- **Implements:** exclude infected-period samples from the metric windows (not from raw storage).
- **Tests:** `--selftest` (mocked run) asserts pairing, randomization, rep count, infected
  exclusion, and provenance completeness — the runner's own validity contract.

### INT-004 — Experiment integration  *(deps: D3-002..007, D1-004)*

#### INT-004.1 — Wire the pipeline · Must
- **Implements:** connect scaler ↔ forecast ↔ HPA ↔ load ↔ faults ↔ runner ↔ results tables on
  the testbed; config-driven, no hard-coded endpoints.
- **Edge:** every cross-module contract (Contract-A kinds, Contract-C frame, results schema)
  asserted at the seam so a mismatch fails at wiring time, not mid-trial.
- **Tests:** live smoke (gated behind `make up`): each hop produces the expected rows.

#### INT-004.2 — One full paired trial · Must · deps: INT-004.1
- **Done:** a single full paired trial completes end-to-end, populates `experiment_run`/`result`,
  and passes QA-003 — the integration proof before scaling to the full matrix.

---

## Phase 3 — Analysis & Validity Audits
**Exit:** CI'd primaries + separate negative-control section; validity + metric gates green.

### D3-008 — Analysis  *(deps: D3-007)*

#### D3-008.1 — Primary metrics + CIs · Must
- **Implements:** `experiment/analysis/` SLO-breach duration + breaching-request count with 95%
  bootstrap CIs + paired effect sizes; bootstrap seeded (PS-2).
- **Edge:** paired analysis respects pairing (bootstrap over pairs, not pooled samples);
  insufficient reps → report wide CI, never fabricate precision.
- **Tests:** CIs reproducible under seed; on a synthetic known-effect dataset the CI covers the
  planted effect; empty/degenerate input handled (TS-4).

#### D3-008.2 — Secondary metrics · Must · deps: D3-008.1
- **Implements:** cost (replica-seconds) + churn (scaling actions) secondaries.
- **Tests:** hand-check on a toy run; reported alongside primaries, clearly secondary.

#### D3-008.3 — Negative-control section · Must · deps: D3-008.1
- **Implements:** separate section; null results printed as-is (never buried or reframed).
- **Tests:** a planted-null control dataset renders a null in its own section, not mixed into primaries.

#### D3-008.4 — Reproducibility + selftest · Must · deps: D3-008.1..3
- **Tests:** `--selftest` asserts CIs produced, controls segregated, and the full analysis
  reproduces byte-identical from the results tables under a fixed seed.

### QA-003 — Experiment validity audit  *(deps: D3-007)* — **loud failure = results invalid (TS-7)**

#### QA-003.1 — Assert chronological holdout (no leakage) · Must
#### QA-003.2 — Assert infected-period exclusion · Must
#### QA-003.3 — Assert ≥20 paired reps + randomized order · Must
#### QA-003.4 — Assert negative controls present + reported separately · Must
> Implemented as an automated audit over the results tables + run provenance; wired into
> `make selftest` so any violation fails the build visibly. Each sub-check ships its own red test
> (a deliberately invalid fixture that must trip it).

### QA-004 — Forecast/predict metric gate  *(instrument-quality, not reliability proof)*

#### QA-004.1 — PR-AUC ≥ target for predict · Must
#### QA-004.2 — Forecast error < snaive + tree baselines · Must
#### QA-004.3 — Label all outputs as instrument-quality metrics (not a reliability proof) · Must
> Gate reads scored outputs only after D3-000.7; prints the "instrument-quality" caveat with
> every reported number so no metric is mistaken for a reliability claim.

---

## Phase 4 — Nice-to-have

### D3-009 — Per-service failure-mode taxonomy  *(deps: D3-001)*

#### D3-009.1 — Richer per-service labels · Nice
- **Implements:** optional richer prediction labels in `aiops/predict/`, behind a flag (off by default).
- **Edge:** must not alter the primary label path or metrics when disabled.

#### D3-009.2 — Selftest + no-regression · Nice · deps: D3-009.1
- **Tests:** `--selftest` green; a regression test asserts primary metrics are byte-identical
  with the taxonomy flag off.

---

**Definition of done (Sanmith):** scaler + HPA run head-to-head under all regimes × faults;
results tables populate; analysis emits CI'd primaries + a separate negative-control section;
every §9 constant used is the signed-off value; `make selftest` (incl. QA-003/004) is green.
**No result is presented until Phase 0 (D3-000.7) is signed off.**




