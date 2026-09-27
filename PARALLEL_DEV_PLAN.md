# 4-Developer Parallel Development Plan
## AIOps Platform — how four developers build this at once

**What this file is:** the high-level plan — how the system is split, the contracts that keep the streams independent, the dependency graph, the critical path, and the execution phases. **Per-developer tickets (full acceptance criteria + copy-paste AI prompts) live in `tickets/DEV1..4_TICKETS.md`.** This file does not repeat them.

**Inputs (repo is the source of truth):** `PRD.md`, `TECHNICAL_ARCHITECTURE.md`, `ARCHITECTURE.md`, `FEATURE_TICKETS.md`, `SECURITY_AND_ACCESS.md`, `experiment/DECISIONS.md`, governed by `LITERATURE_SURVEY_DECISION_REPORT.md`.

**Guardrails carried into every ticket (from the survey — never violate):** RCA is a *ranking, not causal proof*; remediation is *human-approved, never autonomous* (approval = accountability, not safety); *negative-control faults are mandatory and reported separately*; the dashboard/read-API is *unauthenticated, localhost-only*; demo DB creds are *local-testbed-only*; the retired novelty claims must never reappear. The **sole scientific contribution** is the conditional scaling experiment (Sanmith).

**Status of the two open decisions:**
- **Dev split — decided:** subsystem split along the data flow (Sanmith owns the whole contribution). Chosen for *seamless* development (disjoint directories, only frozen contracts shared); even-hours rebalancing rejected because it would fracture the coupled experiment chain across people.
- **§9 research decisions — first-pass drafted** in `experiment/DECISIONS.md`; still need advisor sign-off + a calibration run (ticket D3-000). They gate the experiment *result*, not the *code*.

---

## Contents

**Part A — The plan**
1. System understanding
2. How we split it: domains → four workstreams
3. Ownership boundaries & merge-conflict rules
4. Shared contracts (freeze in Phase 0)
5. Dependency graph
6. Critical path
7. Parallel execution plan (phases)

**Part B — Workstreams** (summaries only; full tickets + prompts in `tickets/`)
8. Developer 1–4 summaries

**Part C — Cross-cutting & reference**
9. Integration, testing & security
10. Master ticket table (index)
11. Final launch dependency checklist

---

# Part A — The plan

## 1. System understanding

A local-Kubernetes AIOps platform (seven modules + a scaler + an experiment harness) running against Sock Shop. **Prometheus is the raw-metrics source of truth**; **TimescaleDB stores inference results**. It exists to run one controlled experiment: *when does forecast-assisted hybrid scaling beat a tuned reactive HPA on SLO-breach duration, and under which fault classes does it fail?*

**Data flow:** Sock Shop → Prometheus → ingestion bridge (feature windows) → ML modules (detect/rca/predict/forecast) write to the `inference` hypertable → scaler turns forecasts into replica counts (k8s API) / remediation proposes human-approved actions / dashboard reads `inference` + experiment tables. The harness drives k6 load and Chaos Mesh faults, runs matched HPA-vs-scaler trials, and logs to the relational experiment tables.

**v1 access model:** no auth, single operator, localhost-only. The only human-in-the-loop action is approving a remediation. (The multi-role RBAC/RLS model in `SECURITY_AND_ACCESS.md` is forward-looking, out of v1.)

**Storage:** two planes — Prometheus (raw time series) and TimescaleDB (one high-volume `inference(ts,module,service,kind,value,meta)` hypertable + three low-volume relational tables `experiment_run`/`experiment_result`/`remediation_action`). Hybrid schema per `TECHNICAL_ARCHITECTURE.md` §3–4.

**Deployment:** kind (1 cp + 2 workers); kube-prometheus-stack, Sock Shop, Chaos Mesh installed by `cluster/bootstrap.sh`; our components as kustomize bases + a `local` overlay; `Makefile` one-liners. No cloud, no CI/CD in scope.

**Highest-risk areas (tightest contracts, senior attention):** the `inference` write/read contract shared by all modules; the ingestion feature-frame shape shared by all ML modules; and the experiment harness + scaler + analysis — because that is the scientific result and any methodology slip (leakage, buried controls, unpaired trials) invalidates the contribution.

**Explicitly absent (do not invent):** alerting integrations (Nice only), external integrations beyond OTel/Prometheus/k8s, multi-tenancy, billing, job queues, and any autonomous remediation.

## 2. How we split it: domains → four workstreams

The system decomposes into ~13 domains — foundation/contracts, ingestion, detection, RCA, prediction, forecasting, scaler, experiment harness, remediation, explainability, dashboard, evaluation, and (deferred) security. Grouped by **subsystem along the data flow** — not frontend/backend — into four coherent workstreams with the fewest cross-stream hard dependencies:

| Dev | Workstream | Owns (directories) | Why grouped this way |
|---|---|---|---|
| **1** | **Foundation & data plane** | `cluster/`, `deploy/`, `aiops/common/`, `experiment/schema.sql`, `aiops/ingest/`, `Makefile` | The base everyone builds on. One owner for the shared contract code removes the biggest merge-conflict source. Ingestion belongs here — its feature-frame shape *is* a contract. Critical-path root. |
| **2** | **Diagnosis** (detect · rca · explain) | `aiops/{detect,rca,explain}/` | A cohesive "diagnose" slice; all write to `inference`, none touches infra control, so it's fully offline-testable and never blocks the contribution. |
| **3** | **Prediction, forecast & the contribution** | `aiops/{predict,forecast,scaler}/`, `experiment/{load,faults,runner,analysis}/`, HPA manifests | predict+forecast feed the scaler; scaler+harness+analysis are the scientific contribution and must stay under one owner for methodological coherence. Heaviest by design — it *is* the project. |
| **4** | **Act, surface & measure** | `aiops/{remediate,dashboard}/`, eval layer, deferred `aiops/auth/` | The two human-facing surfaces + evaluation; all pure *consumers* of module outputs via the read contract, so they parallelize perfectly against mocks. |

**Load is intentionally uneven** (Sanmith > Dev 1 > Dev 4 > Dev 2). Padding the diagnosis stream to match would invent work; Dev 2 instead absorbs the Should-tier ensemble/NL work without touching anyone else's files.

## 3. Ownership boundaries & merge-conflict rules

```
 DEV 1 foundation ──► cluster/ deploy/ aiops/common/ experiment/schema.sql aiops/ingest/
        │ feature frames + inference schema + prom/store clients + config
   ┌────┴─────────────────────────┬──────────────────────────────┐
   ▼                              ▼                               ▼
 DEV 2 diagnose            SANMITH predict + contribution     DEV 4 act + surface + measure
 detect rca explain        predict forecast scaler          remediate dashboard eval
        └──── writes ──►  TimescaleDB `inference` (shared contract, owned by DEV 1) ◄── reads ────┘
                          experiment_run/result/remediation_action (owned by DEV 1)
```

**The four rules that keep boundaries clean:**

1. **Edit only files inside the directories you own.** Need a change across the line? Open a contract request — don't edit another stream's files.
2. **`aiops/common/*` is edited only by Dev 1.** Everyone else imports read-only; new shared helpers are added by Dev 1 (Phase-0 fast path) or live inside the requesting module.
3. **The top-level kustomization and base `requirements.txt` are edited only by Dev 1.** Each module ships its *own* manifest file — nobody edits a shared list. Dependencies all live in the single base `requirements.txt` (uncomment each module's extra); the per-module `requirements-<module>.txt` split was dropped 2026-09-27 (solo ownership removes the merge rationale).
4. **Cross-stream data passes only through the frozen contracts** (§4) — never through direct imports of another module's internals.

**Merge-conflict hotspots and their mitigations:**

| File / area | Risk | Mitigation |
|---|---|---|
| `aiops/common/*` (prom, store, config) | High | Single owner: Dev 1. Others import read-only. |
| Top-level `kustomization.yaml` | High (list-merge) | Each module = one self-contained manifest file (Dev 1 owns the top-level list). |
| `requirements.txt` | Low (solo) | Single base file; per-module extras commented, no split. |
| `experiment/schema.sql` | Low | Dev 1 owns the DDL; Sanmith/4 only read/write rows. |
| `inference` `kind` vocabulary | Medium (semantic) | Frozen in Contract A; adding a `kind` is a reviewed contract change, not a silent edit. |
| `Makefile`, `README.md`, `docs/` | Low | Dev 1 curates; per-module notes live in each module's own README. |

**Net effect:** the only genuinely shared artifacts are the contracts, frozen up front. Day-to-day, four people push to four disjoint directory sets → near-zero textual merge conflicts.

## 4. Shared contracts (freeze in Phase 0, before anyone writes module logic)

Dev 1 authors and owns these; Dev 2/3/4 review and sign off in a ~1-hour kickoff. Once frozen, they change only by explicit agreement. Freezing these first is what lets four people build against **mocks** instead of waiting on each other.

**A — `inference` write/read contract (the linchpin).** One row per derived signal: `inference(ts, module, service, kind, value, meta JSONB)`. `normalize()` in `store.py` fails loudly on missing fields. The `kind` vocabulary is fixed so modules and the dashboard agree without coupling:

| Writer | `module` | `kind` values | `value` | key `meta` |
|---|---|---|---|---|
| Detect (Dev 2) | `detect` | `anomaly_score`, `anomaly_score_seq`, `anomaly_flag` | score∈[0,1] / flag | `detector`, `threshold`, `features` |
| RCA (Dev 2) | `rca` | `culprit_rank` | rank (1=top) | `score`, `incident_id`, `graph_edges` |
| Explain (Dev 2) | `explain` | `attribution` | top weight | `target_module`, `shap` |
| Predict (Sanmith) | `predict` | `breach_prob`, `breach_duration_est` | prob / seconds | `horizon_s`, `threshold` |
| Forecast (Sanmith) | `forecast` | `forecast_p95`, `forecast_p95_snaive`, `forecast_p95_tree` | predicted p95 ms | `horizon_s`, `model` |
| Scaler (Sanmith) | `scaler` | `replicas_target` | desired replicas | `current`, `reason`, `cooldown_s`, `bounds` |

Remediation and experiment records do **not** go in `inference` — they use the relational tables (Contract D).

**B — Prometheus read helpers (`aiops/common/prom.py`).** Fixed signatures: `q_latency_p95(window)`, `q_error_rate(window)`, `q_replicas(window)` — each executes the query and returns **all** Sock Shop services in one call (list of `(labels, ts, vals)`, grouped by the `name` label; filter by that label for a single service); plus `range_query(promql, start, end, step)`. Env `PROM_URL`. Consumers call these — never hand-roll PromQL.

**C — feature-window frame (`aiops/ingest` output).** Columns `[ts, service, p95_ms, error_rate, cpu, mem, replicas, rps]`, window `WINDOW_MIN`, step `STEP_S`, documented NaN policy, sorted by `ts`. Dev 1 ships `sample_frame()` so Dev 2/3 build against real-shaped data on day one.

**D — experiment relational schema (`experiment/schema.sql`).** `experiment_run` (pair_id, policy∈{hpa_tuned,forecast_hybrid}, workload_regime, fault_class, is_negative_control, seed, SLO/horizon stamps), `experiment_result` (1:1), `remediation_action` (append-only audit; proposed→approved→applied/failed; nullable run_id FK). DDL lives here, not in `store.py`'s hot path.

**E — dashboard read-API shapes (`aiops/dashboard` Express).** Dev 4 owns; pinned in Phase 0: `GET /api/{anomalies,rca,predictions,forecasts,remediations,experiments}`, each a documented JSON array over `inference`/experiment rows. Read-only, localhost-only, no auth (deliberate v1 constraint).

**F — remediation evidence bundle.** The JSON a proposed action carries into `remediation_action.evidence` (which anomaly/rca/prediction rows justify it). Dev 4 owns; reads the Contract-A vocabulary.

**G — config / env vars (`aiops/common/config.py`).** `PROM_URL`, `TIMESCALE_DSN`, `SOCK_NS`, `WINDOW_MIN`, `STEP_S`, `SLO_P95_MS`, `SLO_ERROR_RATE`. Single source; every module reads config from here.

**§9 research constants are a contract too** (SLO, H, regimes, scaling params, fault taxonomy, severity) — but decided by the team (D3-000, see `experiment/DECISIONS.md`), not a developer. Until frozen they are clearly-marked defaults so code compiles and self-tests run, but **no experiment result is valid until they are predeclared and signed off.**

## 5. Dependency graph

**Legend:** **hard** = cannot build without it; **soft** = build against a mock/fixture, integrate later.

```
                    D3-000 §9 decisions (team sign-off)
                          │ (gates experiment RUNS + analysis validity — not code)
                          ▼
D1-001 Contracts freeze ──┬── hard ──► everyone (Phase 0 gate)
        ├─ D1-002 testbed ─┼─ hard(runtime) ─► live deploy + experiment
        ├─ D1-003 store   ─┤
        ├─ D1-004 exp schema ─ hard ─► D3 runner, D4 remediation/eval
        └─ D1-005 ingestion frame ── soft(fixture) ──► D2 detect, D3 predict/forecast

D2:  detect ── soft ──► rca        detect+predict ── soft ──► explain
D3:  forecast ── hard(internal) ──► scaler ── hard ──► runner ── hard ──► analysis
     load + faults + HPA ── hard(internal) ──► runner
D4:  all inference rows ── soft(mock read-API) ──► dashboard, eval
     detect/rca/predict/forecast rows ── soft(fixture) ──► remediation propose
```

- **Only two true chokepoints.** (1) Contract freeze (D1-001) — a ~1-day kickoff, not a long pole. (2) Live testbed (D1-002/003) — a hard gate only for runtime integration and experiment execution, not for writing module logic (that's what `--selftest` is for).
- **Every cross-stream edge except the contract freeze is soft** — satisfiable with Phase-0 fixtures. After day 1, all four proceed in parallel with zero waiting.
- **§9 gates the experiment's *validity*, not the code.** Sanmith builds against default constants; results publish only once D3-000 is signed off.
- **No circular dependencies.** The only cycle risk (forecast↔scaler↔runner) is entirely inside Sanmith — coordination-free.

## 6. Critical path

Two finish lines — be explicit about which you mean.

**A) To the scientific result (what the capstone is graded on):**
```
D3-000 §9 sign-off ─┐
D1-001 contracts ───┼─► D1-002/003 testbed+store ─► D3-002 forecast ─► D3-003 scaler ─► D3-004 HPA
                    └────────────────► D3-005 load + D3-006 faults ──┘
                                              └─► D3-007 runner ─► D3-008 analysis ─► QA-003 ─► RESULT
```
This runs through **Dev 1 (foundation) then Sanmith (contribution)**, gated by the team's §9 sign-off. It is the longest pole — protect Sanmith's time.

**B) To the full 7-module demo:** add Dev 2 (diagnosis) and Dev 4 (surfaces) — both run fully in parallel off the same foundation, **not** on path A. They converge at QA-002 (E2E flow).

**Single most important scheduling action:** get the six §9 decisions signed off in week 1. They block nothing in the code but everything in the result, and they need humans (you + advisor), so they have the longest lead time.

## 7. Parallel execution plan (phases)

Durations are relative phases, not calendar promises.

**Phase 0 — Kickoff & contract freeze (short, together).** Dev 1 freezes Contracts A–G and publishes `sample_frame()` + inference fixtures; Dev 2/3/4 sign off. In parallel, the team + advisor start §9 (D3-000) — the longest human lead time. *Exit gate: contracts signed off; fixtures importable.* Nobody writes module logic before this; everybody is unblocked after it.

**Phase 1 — Parallel build against fixtures (the long stretch; zero cross-blocking).**

| Dev 1 | Dev 2 | Sanmith | Dev 4 |
|---|---|---|---|
| testbed, store, exp schema, ingestion, deploy skeleton | IF, LSTM-AE, graph, ranking, SHAP | predict, forecast, scaler, HPA, load, faults | remediation, read-API, dashboard (all vs mocks) |

Every stream passes `--selftest`. Dev 1 finishes the live testbed first so others swap mocks for the real cluster as it lands.

**Phase 2 — Integration (owned, not ambient).** INT-002 cluster assembly (Dev 1) → INT-003 live data-flow (Dev 4) + INT-004 experiment integration (Sanmith) + INT-005 remediation integration (Dev 4).

**Phase 3 — Experiment execution & QA (§9 signed off by now).** Sanmith runs ≥20 paired trials across regimes × faults, then D3-008 analysis. QA-002 (E2E), QA-003 (validity audit), QA-004 (quality gates), SEC-001 (guardrails) run in parallel. *Exit gate: CI'd primaries + separate negative-control section + all guardrail checks green.*

**Phase 4 — Should/Nice polish (only if time).** Ensemble/NL, failure modes, dashboard extras, auto-remediation. All non-blocking; drop first under time pressure.

# Part B — Workstreams

Summaries only. **Full tickets (acceptance criteria + copy-paste AI prompts) live in `tickets/DEVn_TICKETS.md`.** Each stream ships every module with an offline `--selftest` and edits only its own directories.

## 8. Developer 1–4 summaries

**Developer 1 — Foundation & data plane** → [`tickets/DEV1_TICKETS.md`](tickets/DEV1_TICKETS.md)
Critical-path root and contract authority. Owns `cluster/`, `deploy/{timescaledb,monitoring,platform}`, `aiops/common/*`, `aiops/ingest/*`, `experiment/schema.sql`, `Makefile`, base `requirements.txt`. Freezes Contracts A–G and publishes `sample_frame()` + inference fixtures in Phase 0, then stands up the kind testbed, the `inference` store, the experiment schema, the ingestion bridge, and the deploy skeleton. Tickets D1-001…D1-007 (+ INT-001/002, QA-001, SEC-001 infra half). *Definition of done: `make up && make deploy && make selftest` green on a fresh machine; contracts signed off; ingestion feeding live frames.*

**Developer 2 — Diagnosis (detect · rca · explain)** → [`tickets/DEV2_TICKETS.md`](tickets/DEV2_TICKETS.md)
Says what's wrong, ranks why, explains the flag — fully offline-testable, never touches infra control, never blocks the contribution. Owns `aiops/{detect,rca,explain}/*`. Writes only the documented `kind` rows via `store.py`; consumes the Contract-C frame via `sample_frame()` until the live bridge lands. Tickets D2-001…D2-007 (+ QA-004 detect half). **Stream guardrail: RCA output is a ranking, not causal proof — in every output and comment (D2-004).**

**Sanmith — Prediction, forecast & the contribution** → [`tickets/DEV3_TICKETS.md`](tickets/DEV3_TICKETS.md)
The project's sole scientific contribution, kept under one owner for methodological coherence. Owns `aiops/{predict,forecast,scaler}/*`, `experiment/{load,faults,runner,analysis}/*`, `deploy/platform/base/hpa-*.yaml`. Builds the forecast-assisted hybrid scaler, the tuned-HPA comparator, the load/fault harness, the paired-trial runner, and the analysis. Tickets D3-000…D3-009 (+ INT-004, QA-003 validity audit, QA-004 forecast/predict half). **Stream guardrails: negative controls mandatory + reported separately; chronological holdout + infected-period exclusion + ≥20 randomized paired reps; genuinely tuned HPA; server-side max-replica cap. D3-000 §9 constants need advisor sign-off — no result is valid until then.**

**Developer 4 — Act, surface & measure** → [`tickets/DEV4_TICKETS.md`](tickets/DEV4_TICKETS.md)
The two human-facing surfaces + evaluation, all pure consumers of module outputs, so they parallelize against mocks. Owns `aiops/{remediate,dashboard}/*`, the eval/reporting layer, deferred `aiops/auth/*`. Owns Contract-E (read-API shapes) and Contract-F (evidence bundle). Tickets D4-001…D4-009 (+ INT-003/005, QA-002 E2E, SEC-001 app half). **Stream guardrails: remediation is human-approved, never autonomous (approval = accountability, not safety); execute idempotent, timeout ≠ success; dashboard/read-API unauthenticated + localhost-only by deliberate v1 design; eval views are instrument metrics, not reliability proof.**

# Part C — Cross-cutting & reference

## 9. Integration, testing & security

**Integration (owned, not ambient — each has one accountable dev):**

| Ticket | Owner | What it proves |
|---|---|---|
| INT-001 | Dev 1 | Contracts A–G frozen, fixtures published, kickoff sign-off recorded |
| INT-002 | Dev 1 | `make up && make deploy` brings every module Ready on the testbed |
| INT-003 | Dev 4 | One real signal traverses frames → detect/rca/predict/forecast → `inference` → read-API → dashboard |
| INT-004 | Sanmith | One full paired trial runs end-to-end (scaler↔forecast↔HPA↔load↔faults↔runner↔results) |
| INT-005 | Dev 4 | Evidence bundle → approval → k8s scale/restart → audit row, on the live cluster |

**Testing — the one non-negotiable gate.** Every module ships an offline assert-based `python -m aiops.<module> --selftest` (no framework, no cluster). **QA-001: `make selftest` must be green before any merge to main** — the single merge gate. Then quality gates: QA-002 (E2E fault→…→dashboard), QA-003 (**experiment validity audit** — chronological holdout, infected-period exclusion, ≥20 randomized paired reps, negative controls present + segregated; a failure invalidates results, make it loud), QA-004 (PR-AUC ≥ target; forecast beats both baselines; detector FPR bounded — all labeled *instrument-quality metric, not reliability proof*).

**Security — SEC-001, launch-blocking, split across two owners.** Dev 1 (infra half): scaler/remediation k8s ServiceAccounts least-privilege (scale/restart only, no secret read); **Chaos Mesh cannot target any namespace but `SOCK_NS`** (highest-stakes check). Dev 4 (app half): dashboard/read-API reachable only on localhost with no auth surface; no secrets/creds in logs. The unauthenticated, localhost-only posture and the local-testbed-only demo DB creds are *deliberate v1 constraints*, documented as such (see `SECURITY_AND_ACCESS.md` for the forward-looking RBAC/RLS model that is out of v1).

## 10. Master ticket table (index)

Full acceptance criteria + prompts in the per-dev files. Must = ship for v1; Should/Nice = drop first under time pressure.

| Dev | Must | Should / Nice | Integration · QA · Security |
|---|---|---|---|
| **1** → [DEV1](tickets/DEV1_TICKETS.md) | D1-001 contracts · D1-002 testbed · D1-003 store · D1-004 exp schema · D1-005 ingestion · D1-006 deploy skeleton | D1-007 bulk connectors *(Nice)* | INT-001 · INT-002 · QA-001 · SEC-001 (infra) |
| **2** → [DEV2](tickets/DEV2_TICKETS.md) | D2-001 IF+gate · D2-002 LSTM-AE · D2-003 dep graph · D2-004 culprit rank · D2-005 SHAP | D2-006 ensemble *(Should)* · D2-007 NL summary *(Nice)* | QA-004 (detect half) |
| **3** → [DEV3](tickets/DEV3_TICKETS.md) | D3-000 §9 sign-off · D3-001 predict · D3-002 forecast · D3-003 scaler · D3-004 tuned HPA · D3-005 load · D3-006 faults · D3-007 runner · D3-008 analysis | D3-009 failure-mode taxonomy *(Nice)* | INT-004 · QA-003 · QA-004 (forecast half) |
| **4** → [DEV4](tickets/DEV4_TICKETS.md) | D4-001 remediation · D4-002 read-API · D4-003 dashboard UI · D4-006 eval layer | D4-004/005/007/008 dashboard+auto *(Nice)* · D4-009 auth *(out of v1)* | INT-003 · INT-005 · QA-002 · SEC-001 (app) |

## 11. Final launch dependency checklist

Ship v1 only when all of these are true:

- [ ] Contracts A–G frozen and signed off; fixtures importable (INT-001)
- [ ] `make up && make deploy && make selftest` green on a fresh machine (D1 DoD)
- [ ] Every module writes only its documented `kind`/table rows; `normalize()` fails loud on malformed rows
- [ ] **§9 constants (D3-000) advisor-signed-off and frozen before any trial** — no result is valid otherwise
- [ ] ≥20 randomized paired reps per regime × fault; chronological holdout + infected-period exclusion enforced (QA-003 green)
- [ ] Analysis emits CI'd primaries **and a separate negative-control section**; null controls shown as-is
- [ ] Remediation never executes without explicit approval; execute idempotent; timeout marked failed; audit append-only
- [ ] Dashboard/read-API localhost-only, no auth surface, no secrets in logs (SEC-001 app half)
- [ ] Chaos Mesh scoped hard to `SOCK_NS`; k8s ServiceAccounts least-privilege (SEC-001 infra half — launch-blocking)
- [ ] None of the retired novelty claims appear anywhere in code, docs, dashboard, or report
